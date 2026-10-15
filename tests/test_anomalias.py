"""Pruebas de detección de anomalías."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import anomalias  # noqa: E402


def _base():
    return pd.DataFrame({
        "Facultad": ["A"] * 10, "Centro_Costo": ["C1"] * 10, "Cuenta": ["6101"] * 10,
        "Descripcion": ["x"] * 10, "Tipo_Transaccion": ["Pago"] * 10,
        "Monto": [100.0 + i for i in range(10)],
        "Fecha": [f"2026-03-{i + 1:02d}" for i in range(10)],
        "Numero_Documento": [f"P-{i + 1:05d}" for i in range(10)],
    })


def test_detecta_duplicados():
    df = _base()
    df.loc[1, ["Fecha", "Monto", "Numero_Documento"]] = df.loc[0, ["Fecha", "Monto", "Numero_Documento"]]
    assert len(anomalias.detectar_duplicados(df)) == 2


def test_detecta_gaps_en_numeracion():
    df = _base().drop(index=[4, 5, 6])   # faltan P-5, P-6, P-7
    g = anomalias.detectar_gaps(df, min_secuencia=5)
    assert len(g) == 1 and g.loc[0, "Faltantes"] == 3


def test_detecta_outlier_extremo():
    df = pd.concat([_base()] * 3, ignore_index=True)
    df.loc[0, "Monto"] = 100_000.0
    out = anomalias.detectar_outliers(df, 3.0, 1.5)
    assert 0 in out.index


def test_alertas_bajo_umbral_y_monto_redondo():
    cfg = {"hora_inusual_inicio": 20, "hora_inusual_fin": 6, "monto_redondo_multiplo": 1000,
           "monto_redondo_minimo": 5000, "umbrales_aprobacion": [10000], "margen_bajo_umbral": 0.03}
    df = _base()
    df.loc[0, "Monto"] = 9900.0      # 1 % bajo el umbral
    df.loc[1, "Monto"] = 20000.0     # redondo
    a = anomalias.alertas_patrones(df, cfg)
    tipos = set(a["Tipo_Anomalia"])
    assert {"bajo_umbral_aprobacion", "monto_redondo"} <= tipos
