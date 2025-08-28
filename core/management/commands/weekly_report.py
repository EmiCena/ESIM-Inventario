from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
from core.models import Prestamo, TipoItem
from core.discord import send_discord

def heuristicas(tipos_horas: dict):
    tips = []
    if tipos_horas.get(TipoItem.NOTEBOOK, 0) >= 40: tips.append("Revisar notebooks: ≥40 h acumuladas.")
    if tipos_horas.get(TipoItem.TABLET, 0) >= 40: tips.append("Revisar tablets: ≥40 h.")
    if tipos_horas.get(TipoItem.ALARGUE, 0) >= 60: tips.append("Chequeo de alargues: ≥60 h.")
    return tips or ["Todo dentro de parámetros."]

class Command(BaseCommand):
    help = "Envía reporte semanal a Discord"

    def handle(self, *args, **kwargs):
        now = timezone.now()
        since = now - timedelta(days=7)
        qs = Prestamo.objects.filter(fin_real__gte=since)

        total_horas = float(qs.aggregate(h=Sum("duracion_horas"))["h"] or 0)
        by_tipo = qs.values("item__tipo").annotate(h=Sum("duracion_horas"))
        tipos_horas = {r["item__tipo"]: float(r["h"]) for r in by_tipo}
        top = (qs.values("item__code").annotate(h=Sum("duracion_horas")).order_by("-h")[:5])
        top_msg = ", ".join([f"{r['item__code']} ({r['h']:.1f} h)" for r in top]) if top else "Sin movimientos"

        tips = heuristicas(tipos_horas)
        msg = (
            f"📊 Resumen Semanal\n"
            f"- Horas totales: {total_horas:.1f}\n"
            f"- Notebooks: {tipos_horas.get(TipoItem.NOTEBOOK,0):.1f} | "
            f"Tablets: {tipos_horas.get(TipoItem.TABLET,0):.1f} | "
            f"Alargues: {tipos_horas.get(TipoItem.ALARGUE,0):.1f}\n"
            f"- Top ítems: {top_msg}\n"
            f"- Recomendaciones: " + " ".join([f"• {t}" for t in tips])
        )
        send_discord(msg)
        self.stdout.write(self.style.SUCCESS("Reporte semanal enviado."))