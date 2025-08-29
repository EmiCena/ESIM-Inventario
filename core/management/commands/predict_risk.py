from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Item, Mantenimiento

def riesgo_item(it: Item) -> float:
    # Heurística 0–100 basada en uso y tickets recientes
    horas = float(it.uso_acumulado_horas or 0)
    usos  = float(it.usos_acumulados or 0)
    since = timezone.now() - timezone.timedelta(days=60)
    tickets = Mantenimiento.objects.filter(item=it, fecha_apertura__gte=since).count()

    s_horas   = min(horas / 80.0, 1.0)        # 80h = alto uso
    s_usos    = min(usos  / 100.0, 1.0)       # 100 usos = alto
    s_tickets = min(tickets / 3.0, 1.0)       # 3 tickets recientes = alto

    score = 100 * (0.5*s_horas + 0.3*s_usos + 0.2*s_tickets)
    return round(score, 1)

class Command(BaseCommand):
    help = "Calcula score de riesgo por ítem y alerta si supera umbral"

    def add_arguments(self, parser):
        parser.add_argument("--umbral", type=float, default=70.0)

    def handle(self, *args, **opts):
        umbral = opts["umbral"]
        altos = []
        for it in Item.objects.all():
            s = riesgo_item(it)
            if s >= umbral:
                altos.append((it.code, s))
        if altos:
            altos.sort(key=lambda x: x[1], reverse=True)
            msg = "⚠️ Ítems con riesgo alto: " + ", ".join([f"{c} ({s})" for c,s in altos[:8]])
            print(msg)
        else:
            print("Sin riesgos altos.")