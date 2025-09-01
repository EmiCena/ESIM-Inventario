# core/views.py
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.contrib.auth import login
from django.utils import timezone
from django.db.models import Sum, Avg, F
from django.utils.crypto import get_random_string
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

from rest_framework.views import APIView
from rest_framework.response import Response

from .forms import PrestamoRapidoForm, DevolucionForm, SignupForm
from .models import (
    Prestamo, Item, Turno, TipoItem, EstadoItem, Nivel,
    DiscordLinkToken, Profile, Reserva, CarreraSup, AnioSup
)
from .discord import send_discord

# ML runtime helpers
from core.ml_runtime import (
    get_demand_model, get_late_model,
    demand_feature_row, late_feature_row, lag7_avg_for
)

# Extras
import json, re, unicodedata
import datetime as dt
import pandas as pd


# =========================
# PÁGINAS
# =========================
class Home(View):
    def get(self, request):
        return render(request, "home.html")


class OperadorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    raise_exception = False
    def test_func(self):
        u = self.request.user
        return u.is_superuser or u.groups.filter(name__in=["OPERADOR", "STAFF"]).exists()
    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "No tenés permisos para esta sección.")
            return redirect("home")
        return super().handle_no_permission()


class PrestamoRapidoView(LoginRequiredMixin, View):
    def get(self, request):
        p, _ = Profile.objects.get_or_create(user=request.user)
        initial = {
            "solicitante": request.user.username,
            "nivel": p.nivel,
            "carrera": p.carrera or "",
            "anio": str(p.anio) if p.anio else "",
        }
        return render(request, "prestamo_rapido.html", {"form": PrestamoRapidoForm(initial=initial)})

    def post(self, request):
        form = PrestamoRapidoForm(request.POST)
        if form.is_valid():
            p_obj = form.save()
            if p_obj.solicitante != request.user.username:
                p_obj.solicitante = request.user.username
                p_obj.save(update_fields=["solicitante"])
            if p_obj.nivel == Nivel.SUPERIOR and p_obj.turno != Turno.NOCHE:
                p_obj.turno = Turno.NOCHE
                p_obj.save(update_fields=["turno"])
            send_discord(f"✅ {request.user.username} inició préstamo de {p_obj.item.code} ({p_obj.get_nivel_display()} - {p_obj.get_turno_display()}).")
            messages.success(request, "Préstamo registrado.")
            return redirect("prestamo_ok")
        messages.error(request, "No se pudo registrar el préstamo. Corregí los errores señalados.")
        return render(request, "prestamo_rapido.html", {"form": form})


class DevolucionView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "devolucion.html", {"form": DevolucionForm()})
    def post(self, request):
        form = DevolucionForm(request.POST)
        if form.is_valid():
            p = form.save()
            send_discord(f"📦 {request.user.username} entregó {p.item.code}. Duración: {p.duracion_horas} h")
            messages.success(request, f"Entrega registrada. Duración: {p.duracion_horas} h")
            return redirect("devolucion_ok")
        return render(request, "devolucion.html", {"form": form})


class PrestamosActivosView(OperadorRequiredMixin, View):
    def get(self, request):
        activos = (Prestamo.objects
                   .filter(fin_real__isnull=True)
                   .select_related("item")
                   .order_by("-inicio"))
        return render(request, "prestamos_activos.html", {"activos": activos})


# Reservas pendientes (mostrador)
class ReservasPendientesView(OperadorRequiredMixin, View):
    def get(self, request):
        pend = Reserva.objects.filter(estado="activa").select_related("item").order_by("expira","inicio")
        return render(request, "reservas_pendientes.html", {"pendientes": pend})


@login_required
@require_POST
def aprobar_reserva(request, rid):
    if not (request.user.is_superuser or request.user.groups.filter(name__in=["OPERADOR","STAFF"]).exists()):
        return redirect("home")
    try:
        r = Reserva.objects.select_related("item").get(pk=rid, estado="activa")
    except Reserva.DoesNotExist:
        messages.error(request, "Reserva no encontrada o ya no está activa.")
        return HttpResponseRedirect(reverse("reservas_pendientes"))
    p = r.aprobar_y_convertir(request.user)
    if p:
        send_discord(f"✅ {p.solicitante or 'Usuario'} retiró {p.item.code}. Préstamo iniciado.")
        messages.success(request, f"Reserva aprobada y préstamo creado ({p.item.code}).")
    else:
        messages.error(request, "No se pudo convertir la reserva.")
    return HttpResponseRedirect(reverse("reservas_pendientes"))


@login_required
@require_POST
def cancelar_reserva(request, rid):
    if not (request.user.is_superuser or request.user.groups.filter(name__in=["OPERADOR","STAFF"]).exists()):
        return redirect("home")
    try:
        r = Reserva.objects.select_related("item").get(pk=rid, estado="activa")
    except Reserva.DoesNotExist:
        messages.error(request, "Reserva no encontrada o ya no está activa.")
        return HttpResponseRedirect(reverse("reservas_pendientes"))
    r.cancelar(user=request.user, motivo="Cancelada en mostrador")
    send_discord(f"🚫 Reserva cancelada: {r.item.code if r.item else r.tipo} (por {request.user.username}).")
    messages.success(request, "Reserva cancelada.")
    return HttpResponseRedirect(reverse("reservas_pendientes"))


# =========================
# API AUXILIARES (REST)
# =========================
class ItemsDisponibles(APIView):
    def get(self, request):
        tipo = request.GET.get("tipo")
        valid = {k for k, _ in TipoItem.choices}
        if tipo not in valid:
            return Response([])
        items = (Item.objects
                 .filter(tipo=tipo, estado=EstadoItem.DISPONIBLE)
                 .order_by("code"))
        return Response([{"code": i.code, "id": i.id} for i in items])


class KPIs(APIView):
    def get(self, request):
        days = int(request.GET.get("days", 30))
        tipo = request.GET.get("tipo")
        nivel = request.GET.get("nivel")
        carrera = request.GET.get("carrera")
        anio = request.GET.get("anio")

        since = timezone.now() - dt.timedelta(days=days)
        qs = Prestamo.objects.filter(fin_real__isnull=False, fin_real__gte=since)

        if tipo in {k for k, _ in TipoItem.choices}:
            qs = qs.filter(item__tipo=tipo)
        if nivel in {k for k, _ in Nivel.choices}:
            qs = qs.filter(nivel=nivel)
            if nivel == "SUP":
                if carrera in {"TCD","PTEC"}: qs = qs.filter(carrera=carrera)
                if anio in {"1","2"}: qs = qs.filter(anio=int(anio))

        top = (qs.values("item__code", "item__tipo")
                 .annotate(horas=Sum("duracion_horas"))
                 .order_by("-horas")[:5])

        by_tipo = qs.values("item__tipo").annotate(h=Sum("duracion_horas"))
        horas_por_tipo = {r["item__tipo"]: float(r["h"] or 0) for r in by_tipo}

        uso_por_turno = {t[0]: float(qs.filter(turno=t[0]).aggregate(h=Sum("duracion_horas"))["h"] or 0) for t in Turno.choices}
        promedio_duracion = float(qs.aggregate(avg=Avg("duracion_horas"))["avg"] or 0)
        en_mantenimiento = Item.objects.filter(estado=EstadoItem.MANTENIMIENTO).count()
        devoluciones_tardias = Prestamo.objects.filter(fin_prevista__isnull=False, fin_real__gt=F("fin_prevista")).count()

        return Response({
            "top_items": list(top),
            "uso_por_turno": uso_por_turno,
            "horas_por_tipo": horas_por_tipo,
            "promedio_duracion": round(promedio_duracion, 2),
            "en_mantenimiento": en_mantenimiento,
            "devoluciones_tardias": devoluciones_tardias,
        })


# =========================
# AUTH
# =========================
class SignupView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("home")
        return render(request, "registration/signup.html", {"form": SignupForm()})
    def post(self, request):
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
        return render(request, "registration/signup.html", {"form": form})


class AuthLoginView(LoginView):
    template_name = "registration/login.html"


class AuthLogoutView(LogoutView):
    next_page = "/"


class DiscordLinkView(LoginRequiredMixin, View):
    def get(self, request):
        prof, _ = Profile.objects.get_or_create(user=request.user)
        return render(request, "registration/discord_link.html", {
            "token": None,
            "linked": bool(prof.discord_user_id)
        })
    def post(self, request):
        Profile.objects.get_or_create(user=request.user)
        code = get_random_string(6, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        DiscordLinkToken.objects.create(user=request.user, token=code)
        prof = request.user.profile
        return render(request, "registration/discord_link.html", {
            "token": code,
            "linked": bool(prof.discord_user_id)
        })


# =========================
# CHATBOT (solo logueados)
# =========================
def _now():
    return timezone.localtime()

def _expira_2300(dtref=None):
    dtref = dtref or _now()
    exp = dtref.replace(hour=23, minute=0, second=0, microsecond=0)
    if dtref > exp:
        exp = exp + dt.timedelta(days=1)
    return exp

def _infer_turno(dtref=None):
    dtref = dtref or _now()
    t = dtref.time()
    if dt.time(6,0) <= t <= dt.time(12,0):
        return Turno.MANANA
    if dt.time(13,0) <= t <= dt.time(17,0):
        return Turno.TARDE
    if dt.time(17,15) <= t <= dt.time(23,0):
        return Turno.NOCHE
    return Turno.NOCHE

def _norm(s):
    s = (s or '').lower().strip()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s

def _parse_nivel(s):
    s = _norm(s)
    if s.startswith('sup'): return Nivel.SUPERIOR
    if s.startswith('per') or 'docente' in s: return Nivel.PERSONAL
    return Nivel.SECUNDARIO

def _parse_turno(s):
    s = _norm(s)
    if s.startswith('man'): return Turno.MANANA
    if s.startswith('tar'): return Turno.TARDE
    if s.startswith('noc'): return Turno.NOCHE
    return None

def _parse_carrera(s):
    s = _norm(s)
    if s.startswith('tcd'): return CarreraSup.TCD
    if s.startswith('pte') or 'prof' in s: return CarreraSup.PTEC
    return None

def _parse_anio(s):
    s = _norm(s)
    if s.startswith('1'): return AnioSup.PRIMERO
    if s.startswith('2'): return AnioSup.SEGUNDO
    return None

def _suggestions(base=None):
    return base or ["Menú","Mis reservas","Mis préstamos","Reservar NB-01","Devolver NB-01","Cancelar reserva"]

def _menu_text():
    return (
        "Opciones rápidas:\n"
        "• Reservar NB-01 (o cualquier código)\n"
        "• Devolver NB-01\n"
        "• Mis reservas | Mis préstamos\n"
        "• Cancelar reserva\n"
        "También podés cambiar turno: “cambiar a noche”."
    )

def _get_state(request):
    st = request.session.get('chat_state') or {}
    request.session['chat_state'] = st
    return st

def _clear_pending(request):
    st = _get_state(request)
    st['pending'] = None
    request.session.modified = True


@login_required
@require_POST
def chat_api(request):
    data = json.loads(request.body or '{}')
    msg_raw = data.get('message') or ''
    msg = _norm(msg_raw)
    user = request.user
    username = user.username
    state = _get_state(request)

    # Menú
    if msg in ('menu', 'menú'):
        return JsonResponse({'reply': _menu_text(), 'suggestions': _suggestions()})

    # Mis reservas
    if 'mis reservas' in msg:
        rs = Reserva.objects.filter(solicitante=username, estado='activa').select_related('item').order_by('-inicio')
        if not rs:
            return JsonResponse({'reply': 'No tenés reservas activas.', 'suggestions': _suggestions()})
        lines = []
        for r in rs:
            it = r.item
            code = it.code if it else '(sin asignar)'
            lines.append(f'- {code} · {r.get_turno_display()} · expira {timezone.localtime(r.expira).strftime("%d/%m %H:%M")}')
        return JsonResponse({'reply': "Tus reservas activas:\n" + "\n".join(lines), 'suggestions': _suggestions(['Cancelar reserva'])})

    # Mis préstamos
    if 'mis prestamos' in msg or 'mis préstamos' in msg:
        ps = Prestamo.objects.filter(solicitante=username, fin_real__isnull=True).select_related('item').order_by('-inicio')
        if not ps:
            return JsonResponse({'reply': 'No tenés préstamos activos.', 'suggestions': _suggestions()})
        lines = [f'- {p.item.code} · {p.get_turno_display()} · desde {timezone.localtime(p.inicio).strftime("%d/%m %H:%M")}' for p in ps]
        return JsonResponse({'reply': "Tus préstamos activos:\n" + "\n".join(lines), 'suggestions': _suggestions(['Devolver ' + ps[0].item.code])})

    # Cancelar reserva (una por usuario)
    if 'cancelar reserva' in msg or msg == 'cancelar':
        r = Reserva.objects.filter(solicitante=username, estado='activa').first()
        if not r:
            return JsonResponse({'reply': 'No encontré reservas activas para cancelar.', 'suggestions': _suggestions()})
        r.cancelar(user=user, motivo='cancelada desde chatbot')
        return JsonResponse({'reply': f'Reserva cancelada ({r.item.code if r.item else r.tipo}).', 'suggestions': _suggestions()})

    # Cambiar turno explícito durante reserva
    if msg.startswith('cambiar a '):
        t = _parse_turno(msg.replace('cambiar a ', ''))
        pending = state.get('pending') or {}
        if pending and pending.get('flow') == 'reserve' and t:
            pending['turno'] = t
            state['pending'] = pending
            request.session.modified = True
            return JsonResponse({'reply': f'Turno actualizado a {dict(Turno.choices)[t]}. Decí "confirmo" para crear la reserva o "cancelar".', 'suggestions': ['confirmo','cancelar']})
        return JsonResponse({'reply': 'Podés decir: "cambiar a mañana/tarde/noche" cuando estés reservando.', 'suggestions': _suggestions()})

    # Devolver por código
    m_ret = re.search(r'(devolver|entregar)\s+([a-z0-9\-]+)', msg)
    if m_ret:
        code = m_ret.group(2).upper()
        try:
            it = Item.objects.get(code__iexact=code)
        except Item.DoesNotExist:
            return JsonResponse({'reply': f'No encontré el ítem {code}.', 'suggestions': _suggestions()})
        p = Prestamo.objects.filter(item=it, solicitante=username, fin_real__isnull=True).first()
        if not p:
            return JsonResponse({'reply': f'No tenés un préstamo activo de {code}.', 'suggestions': _suggestions(['Mis préstamos'])})
        state['pending'] = {'flow':'return','code':code,'prestamo_id':p.id}
        request.session.modified = True
        return JsonResponse({'reply': f'Voy a registrar la devolución de {code}. ¿Confirmás? (sí/no)', 'suggestions': ['sí','no']})

    # Reservar por código
    m_res = re.search(r'reserv(ar|a)\s+([a-z0-9\-]+)', msg)
    if m_res:
        code = m_res.group(2).upper()
        if Reserva.objects.filter(solicitante=username, estado='activa').exists():
            return JsonResponse({'reply': 'Ya tenés una reserva activa. Primero cancelala o esperá a que se convierta.', 'suggestions': ['Mis reservas','Cancelar reserva']})
        try:
            it = Item.objects.get(code__iexact=code)
        except Item.DoesNotExist:
            return JsonResponse({'reply': f'No encontré el ítem {code}.', 'suggestions': _suggestions()})
        if it.estado in (EstadoItem.EN_USO, EstadoItem.MANTENIMIENTO, EstadoItem.RESERVADO):
            return JsonResponse({'reply': f'El ítem {code} no está disponible para reservar (estado: {dict(EstadoItem.choices)[it.estado]}).', 'suggestions': _suggestions()})

        turno = _infer_turno()
        pending = {
            'flow':'reserve', 'code':code, 'item_id':it.id, 'tipo':it.tipo,
            'nivel': None, 'carrera': None, 'anio': None, 'turno': turno, 'aula': None
        }
        state['pending'] = pending
        request.session.modified = True
        return JsonResponse({
            'reply': f'Voy a reservar {code}. ¿Cuál es tu nivel? (Secundario / Superior / Personal)\nTurno sugerido: {dict(Turno.choices)[turno]} (podés decir "cambiar a mañana/tarde/noche").',
            'suggestions': ['Secundario','Superior','Personal','cambiar a noche','cancelar']
        })

    # Completar flujo de reserva
    pending = state.get('pending')
    if pending and pending.get('flow') == 'reserve':
        # Nivel
        if not pending.get('nivel'):
            if any(x in msg for x in ('sec', 'sup', 'per', 'docente', 'superior', 'secundario', 'personal')):
                nv = _parse_nivel(msg)
                pending['nivel'] = nv
                state['pending'] = pending
                request.session.modified = True
                if nv == Nivel.SUPERIOR:
                    return JsonResponse({'reply': 'Carrera (TCD / PTEC)?', 'suggestions': ['TCD','PTEC']})
                else:
                    return JsonResponse({'reply': '¿Aula? (o escribí "-" para dejar vacío)', 'suggestions': ['-']})
            else:
                return JsonResponse({'reply': 'Indicá tu nivel: Secundario / Superior / Personal', 'suggestions': ['Secundario','Superior','Personal']})

        # Carrera/Año si Superior
        if pending['nivel'] == Nivel.SUPERIOR and not pending.get('carrera'):
            car = _parse_carrera(msg)
            if not car:
                return JsonResponse({'reply': 'Carrera no válida. Opciones: TCD o PTEC.', 'suggestions': ['TCD','PTEC']})
            pending['carrera'] = car
            state['pending'] = pending
            request.session.modified = True
            return JsonResponse({'reply': '¿Año? (1 o 2)', 'suggestions': ['1','2']})

        if pending['nivel'] == Nivel.SUPERIOR and not pending.get('anio'):
            an = _parse_anio(msg)
            if not an:
                return JsonResponse({'reply': 'Año no válido. Indicá 1 o 2.', 'suggestions': ['1','2']})
            pending['anio'] = an
            state['pending'] = pending
            request.session.modified = True
            return JsonResponse({'reply': '¿Aula? (o escribí "-" para dejar vacío)', 'suggestions': ['-']})

        # Aula
        if pending.get('aula') is None:
            aula = msg_raw.strip()
            if aula == '-' or aula == '':
                aula = ''
            pending['aula'] = aula
            state['pending'] = pending
            request.session.modified = True
            resumen = [
                f'Ítem: {pending["code"]}',
                f'Nivel: {dict(Nivel.choices)[pending["nivel"]]}',
                f'Turno: {dict(Turno.choices)[pending["turno"]]}',
                f'Aula: {pending["aula"] or "—"}'
            ]
            if pending['nivel'] == Nivel.SUPERIOR:
                resumen.insert(2, f'Carrera/Año: {dict(CarreraSup.choices)[pending["carrera"]]} · {dict(AnioSup.choices)[pending["anio"]]}')
            return JsonResponse({
                'reply': "Confirmar reserva:\n" + "\n".join(resumen) + "\n¿Confirmás? (sí/no)",
                'suggestions': ['sí','no','cambiar a noche','cancelar']
            })

    # Confirmaciones
    if msg in ('si','sí','confirmo','ok'):
        pending = state.get('pending')
        if pending and pending.get('flow') == 'reserve':
            try:
                it = Item.objects.get(id=pending['item_id'])
            except Item.DoesNotExist:
                _clear_pending(request)
                return JsonResponse({'reply': 'El ítem ya no está disponible.', 'suggestions': _suggestions()})
            if it.estado != EstadoItem.DISPONIBLE:
                _clear_pending(request)
                return JsonResponse({'reply': f'El ítem cambió de estado a {dict(EstadoItem.choices)[it.estado]}.', 'suggestions': _suggestions()})
            if Reserva.objects.filter(solicitante=username, estado='activa').exists():
                _clear_pending(request)
                return JsonResponse({'reply': 'Ya tenés una reserva activa.', 'suggestions': ['Mis reservas']})

            expira = _expira_2300()
            Reserva.objects.create(
                item=it, tipo=it.tipo, nivel=pending['nivel'],
                turno=pending['turno'], aula=pending['aula'] or '',
                solicitante=username, expira=expira
            )
            it.estado = EstadoItem.RESERVADO
            it.save(update_fields=['estado'])

            _clear_pending(request)
            return JsonResponse({
                'reply': f'Listo. Reserva creada para {it.code}. Expira el {expira.strftime("%d/%m %H:%M")}.',
                'suggestions': _suggestions(['Mis reservas'])
            })

        if pending and pending.get('flow') == 'return':
            p = Prestamo.objects.filter(id=pending.get('prestamo_id'), solicitante=username, fin_real__isnull=True).first()
            if not p:
                _clear_pending(request)
                return JsonResponse({'reply': 'No encontré el préstamo a devolver.', 'suggestions': _suggestions()})
            p.cerrar()
            _clear_pending(request)
            return JsonResponse({'reply': f'Devolución registrada para {p.item.code}. ¡Gracias!', 'suggestions': _suggestions()})

    # Cancelar
    if msg in ('no','cancelar','cancel'):
        _clear_pending(request)
        return JsonResponse({'reply': 'Operación cancelada. ¿Algo más?', 'suggestions': _suggestions()})

    # Fallback
    return JsonResponse({'reply': 'Puedo reservar por código, devolver, y listar tus reservas/préstamos. Decí "Menú" para ver opciones.', 'suggestions': _suggestions()})


# =========================
# PREDICCIONES ML (serving)
# =========================
class PrediccionesML(APIView):
    """
    /api/predicciones_ml/?kind=demanda&h=7&mode=lag7|ml|ensemble&w=0.6
    /api/predicciones_ml/?kind=tardanza&tipo=NB&nivel=SEC&turno=M
      params opcionales: hour=18, dur=2.0, date=YYYY-MM-DD
    """
    def get(self, request):
        kind = (request.GET.get("kind") or "demanda").lower()
        if kind == "tardanza":
            return self.tardanza(request)
        return self.demanda(request)

    def demanda(self, request):
        mode = (request.GET.get("mode") or "lag7").lower()  # lag7 | ml | ensemble
        try:
            w = float(request.GET.get("w", 0.6))  # peso lag7 en ensemble
        except Exception:
            w = 0.6
        try:
            model = get_demand_model()
        except Exception:
            model = None

        try:
            h = max(1, min(30, int(request.GET.get("h", 7))))
        except Exception:
            h = 7

        today = timezone.localdate()
        out = []
        for i in range(1, h+1):
            d = today + dt.timedelta(days=i)
            for tipo, _ in TipoItem.choices:
                for turno, _ in Turno.choices:
                    lag7_val = lag7_avg_for(tipo, turno)
                    ml_pred = None
                    if model is not None:
                        row = demand_feature_row(d, tipo, turno)
                        X = pd.DataFrame([row])
                        ml_pred = max(0.0, float(model.predict(X)[0]))
                    if mode == "lag7" or ml_pred is None:
                        pred = lag7_val
                    elif mode == "ml":
                        pred = ml_pred
                    else:
                        pred = w * lag7_val + (1 - w) * ml_pred
                    out.append({
                        "date": d.strftime("%Y-%m-%d"),
                        "tipo": tipo,
                        "turno": turno,
                        "pred": int(round(pred)),
                        "components": {"lag7": float(lag7_val), "ml": float(ml_pred) if ml_pred is not None else None},
                        "mode": mode
                    })
        return Response({"horizon": h, "predicciones": out})

    def tardanza(self, request):
        TH_MED = float(request.GET.get("thr_med", 0.40))
        TH_HIGH = float(request.GET.get("thr_high", 0.65))

        try:
            model = get_late_model()
        except Exception:
            return Response({"error": "Modelo de tardanza no entrenado. Ejecutá: manage.py train_ml"}, status=503)

        tipo = request.GET.get("tipo")
        nivel = request.GET.get("nivel")
        turno = request.GET.get("turno")
        if not (tipo and nivel and turno):
            return Response({"error": "Faltan parámetros: tipo, nivel, turno"}, status=400)

        now_local = timezone.localtime()
        date_str = request.GET.get("date")
        hour_str = request.GET.get("hour")
        dur_str  = request.GET.get("dur")

        if date_str:
            try:
                y, m, d = map(int, date_str.split("-"))
                now_local = now_local.replace(year=y, month=m, day=d)
            except Exception:
                pass
        if hour_str:
            try:
                hh = int(hour_str)
                now_local = now_local.replace(hour=hh, minute=0)
            except Exception:
                pass
        dur = None
        if dur_str:
            try:
                dur = float(dur_str)
            except Exception:
                pass

        row = late_feature_row(now_local, tipo, nivel, turno, dur_prevista_h=dur)
        X = pd.DataFrame([row])
        score = float(model.predict_proba(X)[:, 1][0])

        tier = "bajo"
        if score >= TH_HIGH:
            tier = "alto"
        elif score >= TH_MED:
            tier = "medio"

        return Response({
            "prediccion": {
                "tipo": tipo, "nivel": nivel, "turno": turno,
                "score": round(score, 4),
                "tier": tier,
                "thresholds": {"medio": TH_MED, "alto": TH_HIGH},
                "experimental": True
            }
        })

class Predicciones(PrediccionesML):
    pass

# =========================
# EXPLICABILIDAD DE PREDICCIONES (ML)
# =========================
def _to_1d(x):
    try:
        return x.toarray().ravel()
    except Exception:
        return pd.np.asarray(x).ravel() if hasattr(pd, 'np') else __import__('numpy').asarray(x).ravel()

def _group_contrib(names, contrib):
    from collections import defaultdict
    groups = defaultdict(float)
    details = []
    for n, c in zip(names, contrib):
        if n.startswith('cat__'):
            base = n.split('__', 1)[1].split('_', 1)[0]  # tipo_NB -> tipo
        elif n.startswith('num__'):
            base = n.split('__', 1)[1]
        else:
            base = n
        val = float(c)
        groups[base] += val
        details.append({'feature': n, 'contrib': round(val, 6)})
    by_group = [{'feature': k, 'contrib': round(v, 6)} for k, v in groups.items()]
    by_group.sort(key=lambda x: abs(x['contrib']), reverse=True)
    details.sort(key=lambda x: abs(x['contrib']), reverse=True)
    return by_group, details

class PrediccionesMLExplain(APIView):
    """
    Demanda:
      /api/predicciones_ml/explain/?kind=demanda&date=YYYY-MM-DD&tipo=NB&turno=N&mode=ml&w=0.7
    Tardanza:
      /api/predicciones_ml/explain/?kind=tardanza&tipo=NB&nivel=SEC&turno=N&hour=18&dur=2.0&date=YYYY-MM-DD
    """
    def get(self, request):
        kind = (request.GET.get('kind') or 'demanda').lower()
        if kind == 'tardanza':
            return self.explain_tardanza(request)
        return self.explain_demanda(request)

    def explain_demanda(self, request):
        date_str = request.GET.get('date')
        d = timezone.localdate() + dt.timedelta(days=1)
        if date_str:
            try:
                y, m, dd = map(int, date_str.split('-'))
                d = dt.date(y, m, dd)
            except Exception:
                pass

        tipo = request.GET.get('tipo') or 'NB'
        turno = request.GET.get('turno') or 'N'
        mode = (request.GET.get('mode') or 'ml').lower()
        try:
            w = float(request.GET.get('w', 0.7))
        except Exception:
            w = 0.7

        try:
            pipe = get_demand_model()
        except Exception:
            pipe = None

        row = demand_feature_row(d, tipo, turno)
        df = pd.DataFrame([row])

        lag7_val = float(lag7_avg_for(tipo, turno))
        ml_pred = None
        expl = None
        if pipe is not None:
            try:
                pre = pipe.named_steps['pre']
                mdl = pipe.named_steps['model']
                names = pre.get_feature_names_out()
                Xt = pre.transform(df)
                x1 = _to_1d(Xt)
                coef = mdl.coef_.ravel()
                intercept = float(mdl.intercept_)
                contrib = x1 * coef
                by_group, details = _group_contrib(names, contrib)
                ml_pred = float(pipe.predict(df)[0])
                expl = {
                    'intercept_log': round(intercept, 6),
                    'linear_sum_log': round(intercept + float(__import__('numpy').sum(contrib)), 6),
                    'by_group': by_group[:12],
                    'details': details[:24],
                    'notes': 'Contribuciones en escala log (Poisson). pred = exp(intercept + Σ contrib).'
                }
            except Exception as e:
                expl = {'error': f'No se pudo explicar: {e}'}

        if mode == 'lag7' or ml_pred is None:
            selected = lag7_val
        elif mode == 'ml':
            selected = ml_pred
        else:
            selected = w * lag7_val + (1 - w) * ml_pred

        return Response({
            'input': {'date': d.strftime('%Y-%m-%d'), 'tipo': tipo, 'turno': turno},
            'pred': {
                'mode': mode, 'w': w,
                'lag7': round(lag7_val, 4),
                'ml': round(ml_pred, 4) if ml_pred is not None else None,
                'ensemble': round((w * lag7_val + (1 - w) * ml_pred), 4) if ml_pred is not None else None,
                'selected': round(selected, 4)
            },
            'explain_ml': expl
        })

    def explain_tardanza(self, request):
        tipo = request.GET.get('tipo') or 'NB'
        nivel = request.GET.get('nivel') or 'SEC'
        turno = request.GET.get('turno') or 'N'

        now_local = timezone.localtime()
        date_str = request.GET.get('date')
        hour_str = request.GET.get('hour')
        dur_str = request.GET.get('dur')

        if date_str:
            try:
                y, m, dd = map(int, date_str.split('-'))
                now_local = now_local.replace(year=y, month=m, day=dd)
            except Exception:
                pass
        if hour_str:
            try:
                hh = int(hour_str)
                now_local = now_local.replace(hour=hh, minute=0)
            except Exception:
                pass
        dur = None
        if dur_str:
            try:
                dur = float(dur_str)
            except Exception:
                pass

        try:
            pipe = get_late_model()
        except Exception:
            return Response({'error': 'Modelo no entrenado'}, status=503)

        row = late_feature_row(now_local, tipo, nivel, turno, dur_prevista_h=dur)
        df = pd.DataFrame([row])

        try:
            score = float(pipe.predict_proba(df)[:, 1][0])
        except Exception as e:
            return Response({'error': f'No se pudo predecir: {e}'}, status=500)

        expl = None
        try:
            pre = pipe.named_steps['pre']
            names = pre.get_feature_names_out()
            Xt = pre.transform(df)
            x1 = _to_1d(Xt)

            clf = pipe.named_steps['clf']
            base = None
            if hasattr(clf, 'calibrated_classifiers_') and clf.calibrated_classifiers_:
                base = clf.calibrated_classifiers_[0].estimator
            elif hasattr(clf, 'estimator'):
                base = clf.estimator

            if base is not None and hasattr(base, 'coef_'):
                coef = base.coef_.ravel()
                intercept = float(base.intercept_.ravel()[0])
                contrib = x1 * coef
                by_group, details = _group_contrib(names, contrib)
                import numpy as np
                logit_sum = intercept + float(np.sum(contrib))
                prob_uncal = float(1 / (1 + np.exp(-logit_sum)))
                expl = {
                    'intercept_logit': round(intercept, 6),
                    'linear_sum_logit': round(logit_sum, 6),
                    'prob_uncalibrated': round(prob_uncal, 6),
                    'by_group': by_group[:12],
                    'details': details[:24],
                    'notes': 'Contribuciones de la regresión logística (antes de calibración).'
                }
            else:
                expl = {'warning': 'No se pudieron obtener coeficientes del estimador base.'}
        except Exception as e:
            expl = {'error': f'No se pudo explicar: {e}'}

        return Response({
            'input': {
                'tipo': tipo, 'nivel': nivel, 'turno': turno,
                'datetime': now_local.strftime('%Y-%m-%d %H:%M'),
                'dur_prevista_h': row.get('dur_prevista_h')
            },
            'pred': {'prob_calibrated': round(score, 6)},
            'explain_base': expl
        })