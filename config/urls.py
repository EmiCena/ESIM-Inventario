# config/urls.py
from django.contrib import admin
from django.urls import path
from core.views import (
    Home,
    ItemsDisponibles, KPIs,
    chat_api,
    PrediccionesML, PrediccionesMLExplain,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', Home.as_view(), name='home'),

    # APIs usadas por los tests
    path('api/items/disponibles/', ItemsDisponibles.as_view(), name='items_disponibles'),
    path('api/stats/kpis/', KPIs.as_view(), name='kpis'),
    path('api/chat/', chat_api, name='chat_api'),

    # Predicciones ML
    path('api/predicciones_ml/', PrediccionesML.as_view(), name='predicciones_ml'),
    path('api/predicciones_ml/explain/', PrediccionesMLExplain.as_view(), name='predicciones_ml_explain'),
]