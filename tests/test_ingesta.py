"""Pruebas de ingesta y limpieza."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import ingesta, limpieza  # noqa: E402

COLS = ["Facultad", "Centro_Costo", "Cuenta", "Descripcion", "Debe", "Haber",
        "Fecha", "Tipo_Transaccion", "Numero_Documento"]


def _csv(carpeta, nombre, filas, cols=COLS):
    pd.DataFrame(filas, columns=cols).to_csv(carpeta / nombre, index=False)


def test_ingesta_lee_y_registra_descartes(tmp_path):
    _csv(tmp_path, "a.csv", [["F1", "C1", "6101", "x", "100", "0", "2026-01-05", "Pago", "P-1"],
                             ["F1", "C1", None, "x", "50", "0", "2026-01-06", "Pago", "P-2"]])
    df, log = ingesta.ingestar(tmp_path)
    assert log["filas_leidas"] == 2
    assert log["filas_descartadas"] == 1
    assert len(df) == 1


def test_ingesta_detecta_columnas_faltantes(tmp_path):
    _csv(tmp_path, "b.csv", [["F1", "C1"]], cols=["Facultad", "Centro_Costo"])
    df, log = ingesta.ingestar(tmp_path)
    assert df.empty
    assert log["errores"]["columnas_faltantes"] == 1


def test_limpieza_calcula_saldo_periodo_y_duplicados():
    filas = [["F1", "C1", "6101", "x", "1.234,50", "", "2026-02-10", "Pago", "P-1"]] * 2
    df = pd.DataFrame(filas, columns=COLS)
    limpio, dups = limpieza.limpiar(df)
    assert len(limpio) == 1 and len(dups) == 1
    assert limpio.loc[0, "Debe"] == 1234.5
    assert limpio.loc[0, "Haber"] == 0.0          # nulo -> 0
    assert limpio.loc[0, "Saldo"] == 1234.5
    assert limpio.loc[0, "Periodo"] == "2026-02"
    assert limpio.loc[0, "Fecha"] == "2026-02-10"
