# core/management/commands/seed_fake_data.py
# Generador sintético con señales más fuertes:
# - Mayor demanda en semanas de exámenes (junio y noviembre).
# - Tendencia creciente en el tiempo (para que "month/week" importen).
# - Más tardanzas en Noche, Superior, cerca de las 22:00 y en exámenes.
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from random import random, randint, choice, gauss
from datetime import timedelta, time, datetime, date as date_cls

from core.models import (
    Item, Prestamo, Nivel, Turno, TipoItem, EstadoItem,
)

USERS = ["pedro", "sofia", "lucia", "marcos", "ana", "juan", "carla", "maria", "tomas", "vale"]

def exam_windows_for_year(y:int):
    # 2 tandas de exámenes (ajustá si querés): mitad de junio y mitad de noviembre
    return [
        (date_cls(y, 6, 10), date_cls(y, 6, 24)),
        (date_cls(y, 11, 10), date_cls(y, 11, 24)),
    ]

def is_exam_day(d:date_cls):
    for a,b in exam_windows_for_year(d.year):
        if a <= d <= b:
            return True
    return False

def make_time_uniform(base_date, h1, m1, h2, m2):
    start_minutes = h1*60 + m1
    end_minutes = h2*60 + m2
    minute = randint(start_minutes, end_minutes)
    return timezone.make_aware(datetime.combine(base_date, time(minute // 60, minute % 60)))

def make_time_biased_end(base_date, h1, m1, h2, m2):
    # sesgado hacia el final de la ventana (para acercarnos a las 22:00 en Noche)
    start = h1*60 + m1
    end = h2*60 + m2
    r = 1 - (random() ** 3)  # más masa cerca de 1
    minute = int(start + r * (end - start))
    return timezone.make_aware(datetime.combine(base_date, time(minute // 60, minute % 60)))

def turno_window(turno):
    if turno == Turno.MANANA:
        return (8, 0, 11, 30)
    if turno == Turno.TARDE:
        return (13, 15, 16, 45)
    return (18, 15, 22, 0)

def typical_duration(turno):
    return 2.0 if turno == Turno.NOCHE else 1.5

def base_demand(tipo, turno):
    # Demanda base por tipo/turno
    if tipo == TipoItem.NOTEBOOK:
        return {Turno.MANANA: 2.0, Turno.TARDE: 1.3, Turno.NOCHE: 2.2}[turno]
    if tipo == TipoItem.TABLET:
        return {Turno.MANANA: 1.1, Turno.TARDE: 1.1, Turno.NOCHE: 1.0}[turno]
    return {Turno.MANANA: 2.0, Turno.TARDE: 2.0, Turno.NOCHE: 3.0}[turno]  # ALARGUE

def demand_multiplier(d:date_cls, tipo, turno, progress:float):
    # progress ∈ [0,1] (0 = hace muchos días, 1 = más reciente)
    mult = 0.85 + 0.4*progress  # tendencia creciente suave (±40%)
    if is_exam_day(d):
        if tipo == TipoItem.NOTEBOOK:
            mult += 0.9 if turno == Turno.NOCHE else 0.5
        elif tipo == TipoItem.TABLET:
            mult += 0.3
    # fines de semana menos demanda, salvo noche
    if d.weekday() >= 5 and turno != Turno.NOCHE:
        mult *= 0.7
    return max(0.2, mult)

def late_base(turno):
    if turno == Turno.NOCHE: return 0.18
    if turno == Turno.TARDE: return 0.12
    return 0.10

def late_prob_adjusted(d:date_cls, tipo, nivel, turno, hour:float):
    p = late_base(turno)
    # más tardanzas cerca del cierre (21–22hs) y en exámenes
    if turno == Turno.NOCHE and hour >= 21.0:
        p += 0.12
    if nivel == Nivel.SUPERIOR and turno == Turno.NOCHE:
        p += 0.12
    if is_exam_day(d):
        p += 0.12
        if tipo == TipoItem.NOTEBOOK and turno == Turno.NOCHE:
            p += 0.08
    # acotar
    return max(0.02, min(0.85, p))

class Command(BaseCommand):
    help = "Genera históricos sintéticos con señales fuertes (exámenes/tendencia) para probar ML."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365, help="Cantidad de días hacia atrás")
        parser.add_argument("--clear", action="store_true", help="Resetea uso acumulado e inventario")

    @transaction.atomic
    def handle(self, *args, **opts):
        days = int(opts["days"])
        # inventario mínimo
        def ensure_items(prefix, n, tipo):
            created = 0
            for i in range(1, n+1):
                code = f"{prefix}-{i:02d}"
                if not Item.objects.filter(code=code).exists():
                    Item.objects.create(code=code, tipo=tipo, estado=EstadoItem.DISPONIBLE)
                    created += 1
            return created
        nb = ensure_items("NB", 20, TipoItem.NOTEBOOK)
        tb = ensure_items("TB", 10, TipoItem.TABLET)
        al = ensure_items("AL", 16, TipoItem.ALARGUE)
        self.stdout.write(self.style.SUCCESS(f"Items creados: NB={nb}, TB={tb}, AL={al}"))

        if opts["clear"]:
            Item.objects.update(uso_acumulado_horas=0, usos_acumulados=0, estado=EstadoItem.DISPONIBLE)

        items_by_tipo = {
            TipoItem.NOTEBOOK: list(Item.objects.filter(tipo=TipoItem.NOTEBOOK)),
            TipoItem.TABLET: list(Item.objects.filter(tipo=TipoItem.TABLET)),
            TipoItem.ALARGUE: list(Item.objects.filter(tipo=TipoItem.ALARGUE)),
        }

        now = timezone.localtime()
        start_date = (now - timedelta(days=days)).date()
        total = 0

        for back in range(days, 0, -1):
            d = (now - timedelta(days=back)).date()
            progress = (d - start_date).days / max(1, (now.date() - start_date).days)  # 0..1

            for turno in [Turno.MANANA, Turno.TARDE, Turno.NOCHE]:
                for tipo in [TipoItem.NOTEBOOK, TipoItem.TABLET, TipoItem.ALARGUE]:
                    base = base_demand(tipo, turno)
                    mult = demand_multiplier(d, tipo, turno, progress)
                    mu = max(0.0, base * mult)

                    # número esperado +/- ruido
                    n = max(0, int(round(mu + gauss(0, 0.8))))
                    for _ in range(n):
                        it = choice(items_by_tipo[tipo])
                        # 70% Secundario, 20% Superior, 10% Personal (aprox)
                        r = random()
                        nivel = Nivel.SECUNDARIO if r < 0.7 else (Nivel.SUPERIOR if r < 0.9 else Nivel.PERSONAL)
                        t = Turno.NOCHE if nivel == Nivel.SUPERIOR else turno

                        h1, m1, h2, m2 = turno_window(t)
                        if is_exam_day(d) and t == Turno.NOCHE and tipo == TipoItem.NOTEBOOK:
                            inicio = make_time_biased_end(d, h1, m1, h2, m2)  # más tarde
                        else:
                            inicio = make_time_uniform(d, h1, m1, h2, m2)

                        exp_hours = typical_duration(t)
                        fin_prevista = inicio + timedelta(hours=exp_hours)

                        hour = inicio.hour + inicio.minute/60.0
                        p_late = late_prob_adjusted(d, tipo, nivel, t, hour)
                        late = random() < p_late

                        # si tarde -> +extra, si no -> -extra (puede ser antes)
                        extra = (abs(gauss(0.45, 0.25)) if late else -abs(gauss(0.25, 0.20)))
                        dur_real = max(0.25, exp_hours + extra)
                        fin_real = inicio + timedelta(hours=dur_real)

                        p = Prestamo.objects.create(
                            item=it, nivel=nivel, carrera=None, anio=None, turno=t,
                            aula=choice(["B1","B2","A1","A2","Lab","Maker","7","5","3",""]) if nivel != Nivel.PERSONAL else "",
                            solicitante=choice(USERS),
                            inicio=inicio, fin_prevista=fin_prevista,
                            estado="activo", observaciones=""
                        )
                        p.cerrar(cuando=fin_real)
                        total += 1

        self.stdout.write(self.style.SUCCESS(f"Generados {total} préstamos sintéticos en {days} días."))