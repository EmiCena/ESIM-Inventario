from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
import random

from core.models import (
    Item, Prestamo, Nivel, Turno, EstadoItem,
    CarreraSup, AnioSup
)

class Command(BaseCommand):
    help = "Genera préstamos históricos y algunos activos para probar el dashboard"

    def handle(self, *args, **kwargs):
        random.seed(42)
        now = timezone.now()
        items = list(Item.objects.all().order_by("code"))

        if not items:
            self.stdout.write(self.style.ERROR("No hay items. Corré primero: python manage.py seed_items"))
            return

        niveles = [Nivel.SECUNDARIO, Nivel.SUPERIOR]
        turnos_por_nivel = {
            Nivel.SECUNDARIO: [Turno.MANANA, Turno.TARDE],
            Nivel.SUPERIOR: [Turno.NOCHE],
        }
        aulas = ["A1", "A2", "B1", "Lab", "Maker"]
        nombres = ["Ana", "Luis", "María", "Juan", "Sofía", "Pedro", "Lucía"]

        creados = 0
        with transaction.atomic():
            # 80 préstamos históricos en los últimos 30 días
            for _ in range(80):
                it = random.choice(items)
                nivel = random.choice(niveles)
                turno = random.choice(turnos_por_nivel[nivel])

                carrera = None
                anio = None
                if nivel == Nivel.SUPERIOR:
                    carrera = random.choice([CarreraSup.TCD, CarreraSup.PTEC])
                    anio = random.choice([AnioSup.PRIMERO, AnioSup.SEGUNDO])

                inicio = now - timedelta(days=random.randint(1, 30), hours=random.randint(0, 12))
                dur_h = round(random.uniform(0.5, 3.5), 2)

                p = Prestamo.objects.create(
                    item=it,
                    nivel=nivel,
                    carrera=carrera,
                    anio=anio,
                    turno=turno,
                    aula=random.choice(aulas),
                    solicitante=random.choice(nombres) if nivel == Nivel.SECUNDARIO else "",
                    inicio=inicio,
                    fin_prevista=None,
                )
                # Cerrar con duración simulada
                p.cerrar(cuando=inicio + timedelta(hours=dur_h))
                creados += 1

            # Crear 6 préstamos activos ahora (si hay disponibles)
            disponibles = list(Item.objects.filter(estado=EstadoItem.DISPONIBLE).order_by("code"))
            for it in disponibles[:6]:
                nivel = random.choice(niveles)
                turno = random.choice(turnos_por_nivel[nivel])

                carrera = None
                anio = None
                if nivel == Nivel.SUPERIOR:
                    carrera = random.choice([CarreraSup.TCD, CarreraSup.PTEC])
                    anio = random.choice([AnioSup.PRIMERO, AnioSup.SEGUNDO])

                p = Prestamo.objects.create(
                    item=it,
                    nivel=nivel,
                    carrera=carrera,
                    anio=anio,
                    turno=turno,
                    aula=random.choice(aulas),
                    solicitante=random.choice(nombres) if nivel == Nivel.SECUNDARIO else "",
                    inicio=now - timedelta(minutes=random.randint(5, 120)),
                    fin_prevista=None,
                )
                it.estado = EstadoItem.EN_USO
                it.save(update_fields=["estado"])
                creados += 1

        self.stdout.write(self.style.SUCCESS(f"Generados {creados} préstamos de prueba."))