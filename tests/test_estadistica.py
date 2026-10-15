"""Pruebas de estadística y muestreo."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import estadistica, muestreo  # noqa: E402


def _df(n=200, seed=1):
    rng = np.random.default_rng(seed)
    monto = rng.lognormal(7, 1, n)
    return pd.DataFrame({
        "Facultad": rng.choice(["A", "B", "C"], n),
        "Debe": monto, "Haber": 0.0, "Saldo": monto, "Monto": monto,
        "Fecha": pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "Tipo_Transaccion": rng.choice(["Pago", "Compra"], n),
    })


def test_comparar_facultades_devuelve_pares_y_pvalores():
    r = estadistica.comparar_facultades(_df())
    assert len(r["pares"]) == 3
    assert all(0 <= p["p_valor"] <= 1 for p in r["pares"])
    assert r["anova"] is not None


def test_extrapolacion_nia530():
    r = estadistica.extrapolar_error_nia530(1_000_000, 100_000, 500, 20_000)
    assert r["error_proyectado"] == 5000
    assert r["supera_tolerable"] is False


def test_tamano_muestra_mum_aumenta_con_confianza():
    n95 = muestreo.tamano_muestra_mum(1_000_000, 50_000, 0, 0.95)
    n99 = muestreo.tamano_muestra_mum(1_000_000, 50_000, 0, 0.99)
    assert n99 > n95 > 0
    assert n95 == 60  # 1.000.000 * 2,9957 / 50.000 = 59,9 -> 60


def test_mum_selecciona_partidas_clave():
    df = _df()
    df.loc[0, "Monto"] = 5_000_000
    sel, meta = muestreo.muestreo_mum(df, 50_000, 0, 0.95)
    assert 0 in sel.index
    assert len(sel) <= meta["n_calculado"]


def test_estratificado_cubre_estratos():
    df = _df()
    sel, meta = muestreo.muestreo_estratificado(df, 50_000, 0, 0.95)
    assert set(sel["Facultad"]) == {"A", "B", "C"}
