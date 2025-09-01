import json
import datetime as dt
from django.urls import reverse
from django.utils import timezone
from core.models import TipoItem, EstadoItem, Prestamo, Nivel, Turno, Reserva

def test_items_disponibles_returns_only_available(db, client, item_nb):
    # item disponible y otro reservado (no debe salir)
    from core.models import Item
    item_res = Item.objects.create(code="NB-02", tipo=TipoItem.NOTEBOOK, estado=EstadoItem.RESERVADO)
    r = client.get("/api/items/disponibles/?tipo=NB")
    data = r.json()
    codes = {x["code"] for x in data}
    assert "NB-01" in codes
    assert "NB-02" not in codes

def test_kpis_structure(db, client, item_nb, user):
    # Crear un préstamo devuelto para que haya datos
    inicio = timezone.now() - dt.timedelta(hours=2)
    p = Prestamo.objects.create(
        item=item_nb, nivel=Nivel.SECUNDARIO, turno=Turno.MANANA, aula="B1",
        solicitante=user.username, inicio=inicio, fin_prevista=inicio + dt.timedelta(hours=1.5)
    )
    p.cerrar(cuando=timezone.now())
    r = client.get("/api/stats/kpis/?days=90")
    assert r.status_code == 200
    data = r.json()
    for key in ["top_items", "uso_por_turno", "horas_por_tipo", "promedio_duracion", "en_mantenimiento", "devoluciones_tardias"]:
        assert key in data