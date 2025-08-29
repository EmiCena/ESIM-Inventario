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
from django.http import HttpResponseRedirect
from django.urls import reverse
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from .forms import PrestamoRapidoForm, DevolucionForm, SignupForm
from .models import (
    Prestamo, Item, Turno, TipoItem, EstadoItem, Nivel,
    DiscordLinkToken, Profile, Reserva
)
from .discord import send_discord

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

# API: items disponibles por tipo
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

# API: KPIs
class KPIs(APIView):
    def get(self, request):
        days = int(request.GET.get("days", 30))
        tipo = request.GET.get("tipo")
        nivel = request.GET.get("nivel")
        carrera = request.GET.get("carrera")
        anio = request.GET.get("anio")

        since = timezone.now() - timedelta(days=days)
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

# Auth
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