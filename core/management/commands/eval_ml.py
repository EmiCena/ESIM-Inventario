from pathlib import Path
import json
import pandas as pd
import numpy as np
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.apps import apps
from sklearn.metrics import mean_absolute_error, mean_squared_error, roc_auc_score, average_precision_score, brier_score_loss, accuracy_score, balanced_accuracy_score, precision_recall_fscore_support, confusion_matrix
from core.models import Prestamo
from core.ml_runtime import get_demand_model, get_late_model

APP_CONFIG = apps.get_app_config("core")
MODEL_DIR = Path(APP_CONFIG.path) / "ml_models"
REPORT_PATH = MODEL_DIR / "metrics_report.json"

def _to_df(qs): return pd.DataFrame(list(qs))

# Vectorizado: Serie -> máscara booleana
def is_exam_mask(d_series):
    s = pd.to_datetime(d_series)
    m = s.dt.month
    d = s.dt.day
    return ((m == 6) & (d.between(10, 24))) | ((m == 11) & (d.between(10, 24)))

def build_demand_dataset():
    qs = (Prestamo.objects.filter(fin_real__isnull=False)
          .annotate(day=TruncDate("inicio"))
          .values("day", "item__tipo", "turno").annotate(c=Count("id")).order_by("day"))
    df = _to_df(qs)
    if df.empty: return df
    df = df.rename(columns={"item__tipo":"tipo"})
    df["day"] = pd.to_datetime(df["day"])
    df["dow"] = df["day"].dt.weekday
    df["month"] = df["day"].dt.month
    df["week"] = df["day"].dt.isocalendar().week.astype(int)
    df["is_weekend"] = (df["dow"]>=5).astype(int)
    df["is_exam"] = is_exam_mask(df["day"]).astype(int)
    start = df["day"].min()
    df["trend_idx"] = (df["day"] - start).dt.days.astype(int)
    df = df.sort_values(["tipo","turno","day"])
    df["lag7_avg"] = (df.groupby(["tipo","turno"])["c"].rolling(7, min_periods=1).mean().shift(1).reset_index(level=[0,1], drop=True))
    grp_mean = df.groupby(["tipo","turno"])["c"].transform("mean")
    df["lag7_avg"] = df["lag7_avg"].fillna(grp_mean).fillna(df["c"].mean())
    return df

def wape(y, yhat, eps=1e-9): return float(np.sum(np.abs(y-yhat))/(np.sum(y)+eps))
def smape(y, yhat, eps=1e-9):
    a = np.abs(y-yhat); b = (np.abs(y)+np.abs(yhat)+eps)/2.0
    return float(np.mean(a/b))

def demand_eval():
    df = build_demand_dataset()
    if df.empty: return {"error":"Sin datos de demanda"}
    df = df.sort_values("day"); n = len(df); split = max(1,int(n*0.8))
    train, test = df.iloc[:split], df.iloc[split:]
    feats_cat = ["tipo","turno"]
    feats_num = ["dow","month","week","is_weekend","is_exam","trend_idx","lag7_avg"]
    X_test = test[feats_cat+feats_num]; y_test = test["c"].values.astype(float)
    try:
        mdl = get_demand_model(); y_ml = np.clip(mdl.predict(X_test),0,None)
    except Exception:
        y_ml = np.zeros_like(y_test)
    g1 = train.groupby(["dow","tipo","turno"])["c"].mean().rename("mu").reset_index()
    key = test[["dow","tipo","turno"]].merge(g1, on=["dow","tipo","turno"], how="left")
    g2 = train.groupby(["tipo","turno"])["c"].mean().rename("mu2").reset_index()
    key = key.merge(g2, on=["tipo","turno"], how="left")
    y_dow = key["mu"].fillna(key["mu2"]).fillna(train["c"].mean()).values
    y_lag7 = test["lag7_avg"].values
    def pack(y, yhat): return {"MAE": float(mean_absolute_error(y,yhat)), "RMSE": float(np.sqrt(mean_squared_error(y,yhat))), "WAPE": round(wape(y,yhat),4), "sMAPE": round(smape(y,yhat),4)}
    return {"n_test": int(len(test)), "ml": pack(y_test,y_ml), "baseline_dow": pack(y_test,y_dow), "baseline_lag7": pack(y_test,y_lag7)}

def build_tardiness_dataset():
    qs = (Prestamo.objects.filter(fin_real__isnull=False, fin_prevista__isnull=False)
          .values("inicio","fin_prevista","fin_real","item__tipo","nivel","turno"))
    df = _to_df(qs)
    if df.empty: return df
    df = df.rename(columns={"item__tipo":"tipo"})
    df["inicio"] = pd.to_datetime(df["inicio"])
    df["fin_prevista"] = pd.to_datetime(df["fin_prevista"])
    df["fin_real"] = pd.to_datetime(df["fin_real"])
    df["late"] = (df["fin_real"] > df["fin_prevista"]).astype(int)
    df["hour"] = df["inicio"].dt.hour + df["inicio"].dt.minute/60.0
    df["dow"] = df["inicio"].dt.weekday
    df["month"] = df["inicio"].dt.month
    df["is_weekend"] = (df["dow"]>=5).astype(int)
    df["dur_prevista_h"] = (df["fin_prevista"] - df["inicio"]).dt.total_seconds()/3600.0
    df["is_exam"] = is_exam_mask(df["inicio"].dt.floor("D")).astype(int)
    return df

def optimal_threshold(y_true, proba):
    ts = np.linspace(0.05,0.95,19); best_t, best_f1 = 0.5, -1
    from sklearn.metrics import precision_recall_fscore_support
    for t in ts:
        y_pred = (proba>=t).astype(int)
        p,r,f1,_ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
        if f1>best_f1: best_f1, best_t = f1, t
    return float(best_t)

def tardiness_eval():
    from sklearn.metrics import average_precision_score
    df = build_tardiness_dataset()
    if df.empty: return {"error":"Sin datos de tardanza"}
    df = df.sort_values("inicio"); n=len(df); split=max(1,int(n*0.8))
    train,test = df.iloc[:split], df.iloc[split:]
    feats_cat = ["tipo","nivel","turno"]
    feats_num = ["hour","dow","month","is_weekend","dur_prevista_h","is_exam"]
    X_train,y_train = train[feats_cat+feats_num], train["late"].values.astype(int)
    X_test,y_test = test[feats_cat+feats_num], test["late"].values.astype(int)
    try:
        mdl = get_late_model()
        proba_tr = mdl.predict_proba(X_train)[:,1] if len(X_train) else np.array([])
        proba_te = mdl.predict_proba(X_test)[:,1] if len(X_test) else np.array([])
    except Exception:
        proba_tr = np.zeros_like(y_train, dtype=float); proba_te = np.zeros_like(y_test, dtype=float)
    thr = optimal_threshold(y_train, proba_tr) if len(proba_tr) else 0.5
    from sklearn.metrics import precision_recall_fscore_support
    y05 = (proba_te>=0.5).astype(int) if len(proba_te) else np.array([])
    yop = (proba_te>=thr).astype(int) if len(proba_te) else np.array([])
    def metr(y, proba, ypred):
        out = {"positives_rate": float(np.mean(y)) if len(y) else None}
        if len(y) and len(np.unique(y))>1 and len(proba):
            out["AUC"] = float(roc_auc_score(y, proba))
            out["AP"] = float(average_precision_score(y, proba))
            out["Brier"] = float(brier_score_loss(y, proba))
        if len(y):
            out["Acc"] = float(accuracy_score(y, ypred))
            out["BalancedAcc"] = float(balanced_accuracy_score(y, ypred))
            p,r,f1,_ = precision_recall_fscore_support(y, ypred, average="binary", zero_division=0)
            out["Precision"], out["Recall"], out["F1"] = float(p), float(r), float(f1)
            out["CM"] = confusion_matrix(y, ypred).tolist()
        return out
    return {"n_train": int(len(train)), "n_test": int(len(test)), "threshold_opt_f1": float(thr),
            "metrics_t05": metr(y_test, proba_te, y05), "metrics_topt": metr(y_test, proba_te, yop)}

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        demand = demand_eval(); tardy = tardiness_eval()
        report = {"generated_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"), "demand": demand, "tardiness": tardy}
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f: json.dump(report, f, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS("Reporte guardado en: " + str(REPORT_PATH)))
        self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))