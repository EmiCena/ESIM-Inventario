import json
import datetime as dt
import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Item, TipoItem, EstadoItem, Prestamo, Nivel, Turno, Reserva

@pytest.fixture
def user(db):
    u = User.objects.create_user(username="testuser", password="pass12345")
    return u

@pytest.fixture
def client_logged(client, user):
    client.force_login(user)
    return client

@pytest.fixture
def item_nb(db):
    return Item.objects.create(code="NB-01", tipo=TipoItem.NOTEBOOK, estado=EstadoItem.DISPONIBLE)

@pytest.fixture
def item_al(db):
    return Item.objects.create(code="AL-01", tipo=TipoItem.ALARGUE, estado=EstadoItem.DISPONIBLE)

def make_prestamo(item, solicitante="testuser", nivel=Nivel.SECUNDARIO, turno=Turno.MANANA, hours=2.0):
    inicio = timezone.now() - dt.timedelta(hours=hours)
    p = Prestamo.objects.create(
        item=item, nivel=nivel, turno=turno, aula="B1", solicitante=solicitante,
        inicio=inicio, fin_prevista=inicio + dt.timedelta(hours=1.5), estado="activo"
    )
    return p