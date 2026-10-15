"""Muestreo de auditoría (NIA 530): MUM y estratificado."""
import math

import numpy as np
import pandas as pd
from scipy import stats

from . import cargar_config


def factor_confianza(nivel_confianza):
    """Factor de confiabilidad Poisson para cero errores: FC = -ln(1 - NC)
    (p. ej. 3,0 para 95 %)."""
    return -math.log(1 - nivel_confianza)


def tamano_muestra_mum(valor_poblacion, error_tolerable, error_esperado=0.0,
                       nivel_confianza=0.95):
    """Tamaño de muestra MUM: n = V * FC / (ET - EE * factor_expansion)."""
    if error_tolerable <= error_esperado:
        raise ValueError("El error tolerable debe ser mayor que el error esperado")
    fc = factor_confianza(nivel_confianza)
    factor_exp = 1.6 if nivel_confianza <= 0.95 else 1.9  # tabla clásica de expansión
    n = valor_poblacion * fc / (error_tolerable - error_esperado * factor_exp)
    return max(1, math.ceil(n))


def muestreo_mum(df, error_tolerable, error_esperado=0.0, nivel_confianza=0.95, semilla=42):
    """Muestreo por Unidades Monetarias con intervalo fijo y arranque aleatorio.

    Las partidas con monto >= intervalo se seleccionan con certeza (estrato
    de partidas clave).
    """
    d = df[df["Monto"] > 0].copy()
    valor = d["Monto"].sum()
    n = tamano_muestra_mum(valor, error_tolerable, error_esperado, nivel_confianza)
    intervalo = valor / n
    rng = np.random.default_rng(semilla)
    inicio = rng.uniform(0, intervalo)
    acumulado = d["Monto"].cumsum().values
    puntos = inicio + intervalo * np.arange(n)
    idx = np.unique(np.searchsorted(acumulado, puntos, side="left").clip(0, len(d) - 1))
    sel = d.iloc[idx].copy()
    sel["Justificacion"] = np.where(sel["Monto"] >= intervalo,
                                    "Partida clave (monto >= intervalo de muestreo)",
                                    "Selección MUM por intervalo fijo")
    sel["Metodo"] = "MUM"
    meta = {"metodo": "MUM", "valor_poblacion": float(valor), "n_calculado": int(n),
            "n_seleccionado": len(sel), "intervalo": float(intervalo), "semilla": semilla,
            "nota": "n_seleccionado puede ser menor que n_calculado: una partida mayor al intervalo cubre varios puntos"}
    return sel, meta


def muestreo_estratificado(df, error_tolerable, error_esperado=0.0, nivel_confianza=0.95,
                           rangos=None, semilla=42):
    """Muestreo estratificado por facultad y rango de monto (asignación proporcional
    al valor monetario del estrato; estrato superior revisado al 100 %)."""
    cfg = cargar_config()
    rangos = rangos or cfg["muestreo"]["rangos_monto"]
    d = df[df["Monto"] > 0].copy()
    n_total = tamano_muestra_mum(d["Monto"].sum(), error_tolerable, error_esperado, nivel_confianza)
    n_total = min(n_total, len(d))
    d["Rango"] = pd.cut(d["Monto"], bins=list(rangos) + [np.inf], right=False).astype(str)
    estratos = d.groupby(["Facultad", "Rango"])
    valor_total = d["Monto"].sum()
    rng = np.random.default_rng(semilla)
    max_rango = str(pd.cut([rangos[-1]], bins=list(rangos) + [np.inf], right=False)[0])
    partes = []
    for (fac, rango), g in estratos:
        if rango == max_rango:
            sel = g.copy()
            sel["Justificacion"] = f"Estrato de alto valor ({fac}, {rango}): revisión al 100 %"
        else:
            k = max(1, round(n_total * g["Monto"].sum() / valor_total))
            k = min(k, len(g))
            sel = g.sample(n=k, random_state=int(rng.integers(0, 2**31 - 1)))
            sel["Justificacion"] = f"Muestra aleatoria del estrato {fac} / {rango}"
        partes.append(sel)
    res = pd.concat(partes) if partes else d.iloc[0:0]
    res["Metodo"] = "Estratificado"
    meta = {"metodo": "Estratificado", "valor_poblacion": float(valor_total),
            "n_calculado": int(n_total), "n_seleccionado": len(res), "semilla": semilla}
    return res, meta


def hoja_trabajo(sel, meta):
    """Genera la hoja de trabajo (DataFrame) con columnas para el auditor."""
    cols = ["Facultad", "Centro_Costo", "Cuenta", "Descripcion", "Fecha",
            "Numero_Documento", "Monto", "Metodo", "Justificacion"]
    ws = sel[[c for c in cols if c in sel.columns]].copy()
    ws["Verificado"] = ""
    ws["Error_Detectado"] = ""
    ws["Observaciones"] = ""
    return ws
