import datetime as dt
from django.utils import timezone
from core.models import EstadoItem, Reserva, Nivel, Turno

def test_prestamo_cerrar_updates_item(db, item_nb, user):
    from core.tests.conftest import make_prestamo
    p = make_prestamo(item_nb, solicitante=user.username, hours=2.0)
    assert p.fin_real is None
    p.cerrar(cuando=timezone.now())
    p.refresh_from_db()
    item_nb.refresh_from_db()
    assert p.fin_real is not None
    assert p.estado == "devuelto"
    assert float(p.duracion_horas) > 0
    assert item_nb.estado == EstadoItem.DISPONIBLE
    assert item_nb.usos_acumulados >= 1

def test_reserva_cancelar_releases_item(db, item_nb, user):
    from core.models import Reserva
    item_nb.estado = EstadoItem.RESERVADO
    item_nb.save(update_fields=["estado"])
    r = Reserva.objects.create(
        item=item_nb, tipo=item_nb.tipo, nivel=Nivel.SECUNDARIO,
        turno=Turno.MANANA, aula="", solicitante=user.username,
        expira=timezone.now() + dt.timedelta(hours=1)
    )
    r.cancelar(user=user, motivo="test")
    r.refresh_from_db(); item_nb.refresh_from_db()
    assert r.estado == "cancelada"
    assert item_nb.estado == EstadoItem.DISPONIBLE

def test_reserva_aprobar_convertir_crea_prestamo(db, item_nb, user):
    from core.models import Reserva
    r = Reserva.objects.create(
        item=item_nb, tipo=item_nb.tipo, nivel=Nivel.SECUNDARIO,
        turno=Turno.MANANA, aula="A1", solicitante=user.username,
        expira=timezone.now() + dt.timedelta(hours=2)
    )
    p = r.aprobar_y_convertir(user)
    r.refresh_from_db(); item_nb.refresh_from_db()
    assert r.estado == "convertida"
    assert p is not None
    assert p.item_id == item_nb.id
    assert item_nb.estado == EstadoItem.EN_USO