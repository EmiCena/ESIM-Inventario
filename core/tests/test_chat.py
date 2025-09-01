import json
from core.models import Reserva, Prestamo, EstadoItem, Nivel, Turno
from django.utils import timezone
import datetime as dt

def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")

def test_chat_reserva_flujo_basico(db, client_logged, item_nb, user):
    # 1) iniciar reserva
    r = post_json(client_logged, "/api/chat/", {"message":"reservar NB-01"})
    assert r.status_code == 200
    assert "¿Cuál es tu nivel" in r.json()["reply"]

    # 2) nivel
    r = post_json(client_logged, "/api/chat/", {"message":"Secundario"})
    assert r.status_code == 200
    assert "¿Aula?" in r.json()["reply"]

    # 3) aula y confirmación
    r = post_json(client_logged, "/api/chat/", {"message":"-"})
    assert "Confirmar reserva" in r.json()["reply"]

    # 4) confirmación final
    r = post_json(client_logged, "/api/chat/", {"message":"confirmo"})
    data = r.json()
    assert r.status_code == 200
    assert "Reserva creada" in data["reply"]

    # Verificaciones
    rr = Reserva.objects.filter(solicitante=user.username, estado="activa").first()
    assert rr is not None
    item_nb.refresh_from_db()
    assert item_nb.estado == EstadoItem.RESERVADO

def test_chat_devolucion_flujo(db, client_logged, item_nb, user):
    # Crear préstamo activo
    inicio = timezone.now() - dt.timedelta(hours=1)
    p = Prestamo.objects.create(
        item=item_nb, nivel=Nivel.SECUNDARIO, turno=Turno.MANANA, aula="B1",
        solicitante=user.username, inicio=inicio
    )
    # 1) pedir devolución
    r = post_json(client_logged, "/api/chat/", {"message":"devolver NB-01"})
    reply = r.json()["reply"].lower()
    assert "¿confirmás?" in reply or "¿confirmas?" in reply



    # 2) confirmar
    r = post_json(client_logged, "/api/chat/", {"message":"si"})
    p.refresh_from_db(); item_nb.refresh_from_db()
    assert p.fin_real is not None
    assert p.estado == "devuelto"
    assert item_nb.estado == EstadoItem.DISPONIBLE