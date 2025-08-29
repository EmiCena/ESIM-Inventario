from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Reserva
from core.discord import send_discord

class Command(BaseCommand):
    help = "Expira/cancela reservas vencidas (por expira) y auto-cancela si ya pasaron las 23:00"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        # Expirar por 'expira' pasado
        vencidas = Reserva.objects.filter(estado="activa", expira__lte=now)
        for r in vencidas:
            r.expirar()
            send_discord(f"⏰ Reserva expirada: {r.item.code if r.item else r.tipo}")

        # Auto-cancelar todo lo activo si ya pasaron las 23:00 locales
        local = timezone.localtime(now)
        if local.hour >= 23:
            activas = Reserva.objects.filter(estado="activa")
            for r in activas:
                r.cancelar(user=None, motivo="Auto-cancel 23:00")
                send_discord(f"🌙 Reserva cancelada por horario (>23:00): {r.item.code if r.item else r.tipo}")

        self.stdout.write(self.style.SUCCESS("Reservas procesadas."))