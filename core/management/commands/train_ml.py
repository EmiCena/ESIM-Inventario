# core/management/commands/train_ml.py
import json
from pathlib import Path

import pandas as pd
import numpy as np
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.apps import apps

from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor, LogisticRegression
from sklearn.metrics import (
    mean_absolute_error, mean_poisson_deviance,
    roc_auc_score, accuracy_score, brier_score_loss
)
from sklearn.dummy import DummyClassifier
from sklearn.calibration import CalibratedClassifierCV
import joblib

from core.models import Prestamo

APP_CONFIG = apps.get_app_config("core")
MODEL_DIR = Path(APP_CONFIG.path) / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

def _to_df(qs):
    return pd.DataFrame(list(qs))

# Vectorizado: acepta Serie/Index/array de fechas y devuelve Serie booleana
def is_exam_mask(d_series):
    s = pd.to_datetime(d_series)
    m = s.dt.month
    d = s.dt.day
    return ((m == 6) & (d.between(10, 24))) | ((m == 11) & (d.between(10, 24)))

def build_demand_dataset():
    qs = (Prestamo.objects
          .filter(fin_real__isnull=False)
          .annotate(day=TruncDate("inicio"))
          .values("day", "item__tipo", "turno")
          .annotate(c=Count("id"))
          .order_by("day"))
    df = _to_df(qs)
    if df.empty:
        return df

    df = df.rename(columns={"item__tipo": "tipo"})
    df["day"] = pd.to_datetime(df["day"])
    df["dow"] = df["day"].dt.weekday
    df["month"] = df["day"].dt.month
    df["week"] = df["day"].dt.isocalendar().week.astype(int)
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["is_exam"] = is_exam_mask(df["day"]).astype(int)

    start_day = df["day"].min()
    df["trend_idx"] = (df["day"] - start_day).dt.days.astype(int)

    df = df.sort_values(["tipo", "turno", "day"])
    df["lag7_avg"] = (df.groupby(["tipo", "turno"])["c"]
                        .rolling(7, min_periods=1).mean()
                        .shift(1)
                        .reset_index(level=[0,1], drop=True))
    grp_mean = df.groupby(["tipo","turno"])["c"].transform("mean")
    df["lag7_avg"] = df["lag7_avg"].fillna(grp_mean).fillna(df["c"].mean())
    return df

def train_demand(df):
    df = df.sort_values("day")
    n = len(df)
    split = max(1, int(n * 0.8))
    train, test = df.iloc[:split], df.iloc[split:]

    feats_cat = ["tipo", "turno"]
    feats_num = ["dow", "month", "week", "is_weekend", "is_exam", "trend_idx", "lag7_avg"]
    X_train, y_train = train[feats_cat + feats_num], train["c"]
    X_test, y_test = test[feats_cat + feats_num], test["c"]

    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), feats_cat),
            ("num", Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("sc", StandardScaler())
            ]), feats_num),
        ]
    )

    model = PoissonRegressor(alpha=0.8, max_iter=3000)
    pipe = Pipeline(steps=[("pre", pre), ("model", model)])
    pipe.fit(X_train, y_train)

    y_pred = np.clip(pipe.predict(X_test), 0, None)
    metrics = {
        "mae": float(mean_absolute_error(y_test, y_pred)) if len(y_test) else None,
        "poisson_deviance": float(mean_poisson_deviance(y_test, y_pred)) if len(y_test) else None,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "last_train_date": train["day"].max().strftime("%Y-%m-%d") if len(train) else None
    }
    return pipe, metrics

def build_tardiness_dataset():
    qs = (Prestamo.objects
          .filter(fin_real__isnull=False, fin_prevista__isnull=False)
          .values("inicio", "fin_prevista", "fin_real", "item__tipo", "nivel", "turno"))
    df = _to_df(qs)
    if df.empty:
        return df

    df = df.rename(columns={"item__tipo": "tipo"})
    df["inicio"] = pd.to_datetime(df["inicio"])
    df["fin_prevista"] = pd.to_datetime(df["fin_prevista"])
    df["fin_real"] = pd.to_datetime(df["fin_real"])

    df["late"] = (df["fin_real"] > df["fin_prevista"]).astype(int)
    df["hour"] = df["inicio"].dt.hour + df["inicio"].dt.minute/60.0
    df["dow"] = df["inicio"].dt.weekday
    df["month"] = df["inicio"].dt.month
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["dur_prevista_h"] = (df["fin_prevista"] - df["inicio"]).dt.total_seconds()/3600.0
    df["is_exam"] = is_exam_mask(df["inicio"].dt.floor("D")).astype(int)
    return df

def train_tardiness(df):
    df = df.sort_values("inicio")
    n = len(df)
    split = max(1, int(n * 0.8))
    train, test = df.iloc[:split], df.iloc[split:]

    feats_cat = ["tipo", "nivel", "turno"]
    feats_num = ["hour", "dow", "month", "is_weekend", "dur_prevista_h", "is_exam"]
    X_train, y_train = train[feats_cat + feats_num], train["late"]
    X_test, y_test = test[feats_cat + feats_num], test["late"]

    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), feats_cat),
            ("num", Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("sc", StandardScaler())
            ]), feats_num),
        ]
    )

    unique_classes = int(pd.Series(y_train).nunique())
    if unique_classes < 2:
        clf = DummyClassifier(strategy="prior")
    else:
        base = LogisticRegression(max_iter=3000, class_weight="balanced")
        try:
    # sklearn >= 1.3
            clf = CalibratedClassifierCV(estimator=base, method="isotonic", cv=5)
        except TypeError:
    # sklearn <= 1.2 (fallback)
            clf = CalibratedClassifierCV(base_estimator=base, method="isotonic", cv=5)

    pipe = Pipeline(steps=[("pre", pre), ("clf", clf)])
    pipe.fit(X_train, y_train)

    metrics = {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "last_train_date": train["inicio"].max().strftime("%Y-%m-%d") if len(train) else None
    }
    try:
        proba = pipe.predict_proba(X_test)[:, 1] if len(X_test) and hasattr(pipe, "predict_proba") else np.array([])
        if len(y_test) and len(np.unique(y_test)) > 1 and len(proba):
            metrics.update({
                "auc": float(roc_auc_score(y_test, proba)),
                "acc@0.5": float(accuracy_score(y_test, (proba>=0.5).astype(int))),
                "brier": float(brier_score_loss(y_test, proba)),
            })
    except Exception:
        pass

    return pipe, metrics

class Command(BaseCommand):
    help = "Entrena modelos ML (demanda/tardanza) con features nuevas y guarda en core/ml_models/"

    def handle(self, *args, **kwargs):
        now = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")

        # DEMANDA
        df_d = build_demand_dataset()
        if df_d.empty:
            self.stdout.write(self.style.ERROR("Sin datos para demanda."))
        else:
            m_d, m_d_metrics = train_demand(df_d)
            joblib.dump(m_d, MODEL_DIR / "demand_model.joblib")
            start_day_str = df_d["day"].min().strftime("%Y-%m-%d")
            with open(MODEL_DIR / "demand_meta.json", "w", encoding="utf-8") as f:
                json.dump({"trained_at": now, "metrics": m_d_metrics, "train_start_day": start_day_str}, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Modelo demanda entrenado. Metrics: {m_d_metrics}"))

        # TARDANZA
        df_t = build_tardiness_dataset()
        if df_t.empty:
            self.stdout.write(self.style.ERROR("Sin datos para tardanza."))
        else:
            m_t, m_t_metrics = train_tardiness(df_t)
            joblib.dump(m_t, MODEL_DIR / "late_model.joblib")
            with open(MODEL_DIR / "late_meta.json", "w", encoding="utf-8") as f:
                json.dump({"trained_at": now, "metrics": m_t_metrics}, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Modelo tardanza entrenado. Metrics: {m_t_metrics}"))