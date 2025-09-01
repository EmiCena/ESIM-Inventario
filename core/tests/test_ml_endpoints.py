import json
import numpy as np
from django.utils import timezone
import datetime as dt
from core.models import Prestamo, Nivel, Turno

def test_predicciones_ml_demanda_lag7_and_dow(db, client, item_nb, user):
    # Generar un préstamo reciente para que lag7>0
    p = Prestamo.objects.create(
        item=item_nb, nivel=Nivel.SECUNDARIO, turno=Turno.MANANA, aula="B1",
        solicitante=user.username, inicio=timezone.now() - dt.timedelta(hours=1)
    )
    p.cerrar(cuando=timezone.now())

    # lag7
    r1 = client.get("/api/predicciones_ml/?kind=demanda&h=3&mode=lag7")
    assert r1.status_code == 200
    data1 = r1.json()["predicciones"]
    # 3 tipos x 3 turnos x 3 días = 27
    assert len(data1) == 27

    # dow (estacionalidad)
    r2 = client.get("/api/predicciones_ml/?kind=demanda&h=3&mode=dow&hist_days=7")
    assert r2.status_code == 200
    data2 = r2.json()["predicciones"]
    assert len(data2) == 27

def test_predicciones_ml_tardanza_monkeypatched(db, client, monkeypatch):
    # Stub del modelo para evitar depender de joblib
    class FakeLateModel:
        def predict_proba(self, X):
            # devuelve prob=0.7 para clase positiva
            return np.array([[0.3, 0.7]])

    from core import ml_runtime
    monkeypatch.setattr("core.views.get_late_model", lambda: FakeLateModel())

    r = client.get("/api/predicciones_ml/?kind=tardanza&tipo=NB&nivel=SEC&turno=N&thr_med=0.2&thr_high=0.65")
    assert r.status_code == 200
    data = r.json()
    assert "prediccion" in data
    assert data["prediccion"]["tier"] == "alto"

def test_explain_demanda_without_model(db, client, monkeypatch):
    # Forzamos que no haya modelo de demanda para que igual responda con lag7 y explain_ml None
    from core import ml_runtime
    def boom(): raise RuntimeError("no model")
    monkeypatch.setattr(ml_runtime, "get_demand_model", boom, raising=True)

    r = client.get("/api/predicciones_ml/explain/?kind=demanda&tipo=NB&turno=N&date=2025-09-02")
    assert r.status_code == 200
    data = r.json()
    assert "explain_ml" in data
    # Debe devolver al menos la pred de lag7/selected
    assert "pred" in data and "selected" in data["pred"]