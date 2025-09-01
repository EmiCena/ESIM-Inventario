from django.urls import path
from django.views.generic import TemplateView

from .views import (
    Home,
    PrestamoRapidoView, DevolucionView,
    PrestamosActivosView, ReservasPendientesView,
    aprobar_reserva, cancelar_reserva,
    SignupView, AuthLoginView, AuthLogoutView, DiscordLinkView,
    ItemsDisponibles, KPIs, chat_api,
    PrediccionesML, PrediccionesMLExplain,
)

urlpatterns = [
    # Páginas
    path('', Home.as_view(), name='home'),
    path('dashboard/', TemplateView.as_view(template_name='dashboard.html'), name='dashboard'),

    # Préstamo / Devolución
    path('prestamo/', PrestamoRapidoView.as_view(), name='prestamo'),
    path('prestamo/ok/', TemplateView.as_view(template_name='ok.html'), name='prestamo_ok'),
    path('devolucion/', DevolucionView.as_view(), name='devolucion'),
    path('devolucion/ok/', TemplateView.as_view(template_name='ok.html'), name='devolucion_ok'),

    # Staff / Mostrador
    path('prestamos/activos/', PrestamosActivosView.as_view(), name='prestamos_activos'),
    path('reservas/pendientes/', ReservasPendientesView.as_view(), name='reservas_pendientes'),
    path('reservas/<int:rid>/aprobar/', aprobar_reserva, name='aprobar_reserva'),
    path('reservas/<int:rid>/cancelar/', cancelar_reserva, name='cancelar_reserva'),

    # Auth
    path('accounts/login/',  AuthLoginView.as_view(), name='login'),
    path('accounts/logout/', AuthLogoutView.as_view(), name='logout'),
    path('accounts/signup/', SignupView.as_view(), name='signup'),
    path('accounts/discord/', DiscordLinkView.as_view(), name='discord_link'),

    # APIs
    path('api/items/disponibles/', ItemsDisponibles.as_view(), name='items_disponibles'),
    path('api/stats/kpis/', KPIs.as_view(), name='kpis'),
    path('api/chat/', chat_api, name='chat_api'),

    # Predicciones ML
    path('api/predicciones_ml/', PrediccionesML.as_view(), name='predicciones_ml'),
    path('api/predicciones_ml/explain/', PrediccionesMLExplain.as_view(), name='predicciones_ml_explain'),
]