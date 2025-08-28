from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.contrib.auth import login
from django.utils import timezone
from django.db.models import Sum, Avg, F
from django.utils.crypto import get_random_string
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response

from .forms import PrestamoRapidoForm, DevolucionForm, SignupForm
from .models import (
    Prestamo, Item, Turno, TipoItem, EstadoItem, Nivel,
    DiscordLinkToken
)

# Home
class Home(View):
    def get(self, request):
        return render(request, "home.html")

# Solo para vistas “de operador” (ej: En uso ahora)
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

# Préstamo: ahora alcanza con estar logueado
class PrestamoRapidoView(LoginRequiredMixin, View):
    def get(self, request):
        # Prefill desde el perfil (si existe)
        p = getattr(request.user, "profile", None)
        initial = {}
        if p:
            initial = {
                "nivel": p.nivel,
                "carrera": p.carrera or "",
                "anio": str(p.anio) if p.anio else "",
                "solicitante": (request.user.get_full_name() or request.user.username) if p.nivel == "SEC" else "",
            }
        return render(request, "prestamo_rapido.html", {"form": PrestamoRapidoForm(initial=initial)})

    def post(self, request):
        form = PrestamoRapidoForm(request.POST)
        if form.is_valid():
            form.save()  # si querés guardar quién lo hizo, avisame y agregamos el campo usuario al modelo
            messages.success(request, "Préstamo registrado.")
            return redirect("prestamo_ok")
        return render(request, "prestamo_rapido.html", {"form": form})

# Entrega: también con login alcanza
class DevolucionView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "devolucion.html", {"form": DevolucionForm()})
    def post(self, request):
        form = DevolucionForm(request.POST)
        if form.is_valid():
            p = form.save()
            messages.success(request, f"Entrega registrada. Duración: {p.duracion_horas} h")
            return redirect("devolucion_ok")
        return render(request, "devolucion.html", {"form": form})

# En uso ahora: solo operadores/staff
class PrestamosActivosView(OperadorRequiredMixin, View):
    def get(self, request):
        activos = (Prestamo.objects
                   .filter(fin_real__isnull=True)
                   .select_related("item")
                   .order_by("-inicio"))
        return render(request, "prestamos_activos.html", {"activos": activos})

# API: items disponibles por tipo (para el dropdown del formulario)
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

# API: KPIs con filtros (tipo, nivel, carrera, año) y rango de días
class KPIs(APIView):
    def get(self, request):
        days = int(request.GET.get("days", 30))
        tipo = request.GET.get("tipo")      # NB/TB/AL
        nivel = request.GET.get("nivel")    # SEC/SUP/PER
        carrera = request.GET.get("carrera")# TCD/PTEC
        anio = request.GET.get("anio")      # "1"/"2"

        since = timezone.now() - timedelta(days=days)
        qs = Prestamo.objects.filter(fin_real__isnull=False, fin_real__gte=since)

        if tipo in {k for k, _ in TipoItem.choices}:
            qs = qs.filter(item__tipo=tipo)

        if nivel in {k for k, _ in Nivel.choices}:
            qs = qs.filter(nivel=nivel)
            if nivel == "SUP":
                if carrera in {"TCD", "PTEC"}:
                    qs = qs.filter(carrera=carrera)
                if anio in {"1", "2"}:
                    qs = qs.filter(anio=int(anio))

        top = (qs.values("item__code", "item__tipo")
                 .annotate(horas=Sum("duracion_horas"))
                 .order_by("-horas")[:5])

        uso_por_turno = {
            t[0]: float(qs.filter(turno=t[0]).aggregate(h=Sum("duracion_horas"))["h"] or 0)
            for t in Turno.choices
        }
        promedio_duracion = float(qs.aggregate(avg=Avg("duracion_horas"))["avg"] or 0)
        en_mantenimiento = Item.objects.filter(estado=EstadoItem.MANTENIMIENTO).count()
        devoluciones_tardias = Prestamo.objects.filter(
            fin_prevista__isnull=False,
            fin_real__gt=F("fin_prevista")
        ).count()

        return Response({
            "top_items": list(top),
            "uso_por_turno": uso_por_turno,
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

# Vincular Discord (genera token para /vincular en el bot)
class DiscordLinkView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "registration/discord_link.html", {
            "token": None,
            "linked": bool(getattr(request.user.profile, "discord_user_id", None))
        })
    def post(self, request):
        code = get_random_string(6, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        DiscordLinkToken.objects.create(user=request.user, token=code)
        return render(request, "registration/discord_link.html", {
            "token": code,
            "linked": bool(getattr(request.user.profile, "discord_user_id", None))
        })