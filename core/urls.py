from django.urls import path
from django.views.generic import TemplateView
from . import views
from .views import (
    Home, PrestamoRapidoView, DevolucionView, PrestamosActivosView,
    KPIs, ItemsDisponibles,
    SignupView, AuthLoginView, AuthLogoutView, DiscordLinkView,
    ReservasPendientesView, aprobar_reserva, cancelar_reserva
)
from core.views import PrediccionesML, PrediccionesMLExplain
urlpatterns = [
    path("", Home.as_view(), name="home"),
    path("prestamo/", PrestamoRapidoView.as_view(), name="prestamo"),
    path("prestamo/ok/", TemplateView.as_view(template_name="ok.html"), name="prestamo_ok"),
    path("devolucion/", DevolucionView.as_view(), name="devolucion"),
    path("devolucion/ok/", TemplateView.as_view(template_name="ok.html"), name="devolucion_ok"),
    path("prestamos/activos/", PrestamosActivosView.as_view(), name="prestamos_activos"),
    path("reservas/pendientes/", ReservasPendientesView.as_view(), name="reservas_pendientes"),
    path("reservas/<int:rid>/aprobar/", aprobar_reserva, name="aprobar_reserva"),
    path("reservas/<int:rid>/cancelar/", cancelar_reserva, name="cancelar_reserva"),
    path("dashboard/", TemplateView.as_view(template_name="dashboard.html"), name="dashboard"),
    path("api/stats/kpis/", KPIs.as_view(), name="kpis"),
    path("api/items/", ItemsDisponibles.as_view(), name="items_disponibles"),

    # Auth
    path("accounts/signup/", SignupView.as_view(), name="signup"),
    path("accounts/login/", AuthLoginView.as_view(), name="login"),
    path("accounts/logout/", AuthLogoutView.as_view(), name="logout"),
    path("accounts/discord/", DiscordLinkView.as_view(), name="discord_link"),

    #Chat
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/predicciones/', PrediccionesML.as_view(), name='predicciones'),
    path('api/predicciones_ml/', views.PrediccionesML.as_view(), name='predicciones_ml'),
    path('api/predicciones_ml/explain/', views.PrediccionesMLExplain.as_view(), name='predicciones_ml_explain'),
    path('api/predicciones_ml/explain/', PrediccionesMLExplain.as_view(), name='predicciones_ml_explain'),
]