from pathlib import Path
from datetime import timedelta, date as date_cls
import json
import joblib

from django.apps import apps
from django.utils import timezone

from core.models import Prestamo, Turno

APP_CONFIG = apps.get_app_config("core")
MODEL_DIR = Path(APP_CONFIG.path) / "ml_models"

_DEMAND = None
_LATE = None
_START_DAY_DEMAND = None  # para trend_idx

def get_demand_model():
    global _DEMAND
    if _DEMAND is None:
        _DEMAND = joblib.load(MODEL_DIR / "demand_model.joblib")
    return _DEMAND

def get_late_model():
    global _LATE
    if _LATE is None:
        _LATE = joblib.load(MODEL_DIR / "late_model.joblib")
    return _LATE

def typical_duration(turno):
    return 2.0 if turno == Turno.NOCHE else 1.5

def lag7_avg_for(tipo, turno):
    since = timezone.localtime() - timedelta(days=7)
    total = Prestamo.objects.filter(
        item__tipo=tipo, turno=turno, inicio__gte=since, fin_real__isnull=False
    ).count()
    return total / 7.0

def _is_exam_date(d: date_cls) -> int:
    # Ventanas de exámenes: 10–24 de junio y 10–24 de noviembre (ajústalo si querés)
    m, day = d.month, d.day
    return int((m == 6 and 10 <= day <= 24) or (m == 11 and 10 <= day <= 24))

def _load_demand_start_day():
    """
    Obtiene el día de inicio del entrenamiento para computar trend_idx.
    1) Intenta leerlo de demand_meta.json (clave train_start_day).
    2) Si no está, usa la fecha del primer préstamo en BD.
    3) Fallback: hoy.
    """
    global _START_DAY_DEMAND
    if _START_DAY_DEMAND is not None:
        return _START_DAY_DEMAND

    meta_path = MODEL_DIR / "demand_meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            sd = meta.get("train_start_day") or meta.get("start_day")
            if sd:
                _START_DAY_DEMAND = date_cls.fromisoformat(sd)
                return _START_DAY_DEMAND
        except Exception:
            pass

    try:
        first = Prestamo.objects.filter(fin_real__isnull=False).earliest("inicio").inicio
        _START_DAY_DEMAND = timezone.localtime(first).date()
    except Exception:
        _START_DAY_DEMAND = timezone.localdate()
    return _START_DAY_DEMAND

def demand_feature_row(d, tipo, turno):
    """
    Devuelve TODAS las columnas que el modelo espera:
    ['tipo','turno','dow','month','week','is_weekend','is_exam','trend_idx','lag7_avg']
    """
    start_day = _load_demand_start_day()
    dow = d.weekday()
    month = d.month
    week = int(d.isocalendar()[1])
    is_weekend = 1 if dow >= 5 else 0
    is_exam = _is_exam_date(d)
    trend_idx = (d - start_day).days
    lag7 = lag7_avg_for(tipo, turno)

    return {
        "tipo": tipo,
        "turno": turno,
        "dow": dow,
        "month": month,
        "week": week,
        "is_weekend": is_weekend,
        "is_exam": is_exam,
        "trend_idx": int(trend_idx),
        "lag7_avg": lag7,
    }

def late_feature_row(now_dt, tipo, nivel, turno, dur_prevista_h=None):
    """
    Devuelve TODAS las columnas que el modelo de tardanza espera:
    ['tipo','nivel','turno','hour','dow','month','is_weekend','dur_prevista_h','is_exam']
    """
    if dur_prevista_h is None:
        dur_prevista_h = typical_duration(turno)

    hour = now_dt.hour + now_dt.minute / 60.0
    dow = now_dt.weekday()
    month = now_dt.month
    is_weekend = 1 if dow >= 5 else 0
    is_exam = _is_exam_date(now_dt.date())

    return {
        "tipo": tipo,
        "nivel": nivel,
        "turno": turno,
        "hour": float(hour),
        "dow": dow,
        "month": month,
        "is_weekend": is_weekend,
        "dur_prevista_h": float(dur_prevista_h),
        "is_exam": is_exam,
    }