"""Detección de anomalías: duplicados, saltos, outliers y patrones de riesgo."""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import cargar_config


def detectar_duplicados(df):
    """Duplicados por Fecha + Cuenta + Monto + Documento (más de una ocurrencia)."""
    claves = ["Fecha", "Cuenta", "Monto", "Numero_Documento"]
    mask = df.duplicated(subset=claves, keep=False)
    d = df[mask].sort_values(claves).copy()
    d["Tipo_Anomalia"] = "duplicado"
    return d


def detectar_gaps(df, min_secuencia=5):
    """Saltos en la numeración de documentos (por Facultad y Tipo_Transaccion).

    Extrae la parte numérica final de Numero_Documento. Devuelve un DataFrame
    con prefijo, número anterior, siguiente y cantidad de documentos faltantes.
    """
    filas = []
    num = df["Numero_Documento"].astype(str).str.extract(r"^(.*?)(\d+)$")
    tmp = df.assign(_pref=num[0], _num=pd.to_numeric(num[1], errors="coerce"))
    tmp = tmp.dropna(subset=["_num"])
    for (pref, tipo), g in tmp.groupby(["_pref", "Tipo_Transaccion"]):
        nums = np.sort(g["_num"].astype(int).unique())
        if len(nums) < min_secuencia:
            continue
        saltos = np.diff(nums)
        for i in np.where(saltos > 1)[0]:
            filas.append({"Prefijo": pref, "Tipo_Transaccion": tipo,
                          "Anterior": int(nums[i]), "Siguiente": int(nums[i + 1]),
                          "Faltantes": int(saltos[i] - 1)})
    return pd.DataFrame(filas, columns=["Prefijo", "Tipo_Transaccion", "Anterior",
                                        "Siguiente", "Faltantes"])


def detectar_outliers(df, z_umbral=3.0, iqr_factor=1.5):
    """Outliers por z-score e IQR sobre el Monto, dentro de cada Facultad."""
    resultados = []
    for fac, g in df.groupby("Facultad"):
        m = g["Monto"]
        if len(g) < 4:
            continue
        sd = m.std(ddof=1)
        z = (m - m.mean()) / sd if sd > 0 else pd.Series(0.0, index=g.index)
        q1, q3 = m.quantile([0.25, 0.75])
        ric = q3 - q1
        lim_inf, lim_sup = q1 - iqr_factor * ric, q3 + iqr_factor * ric
        out_z = z.abs() > z_umbral
        out_iqr = (m < lim_inf) | (m > lim_sup)
        sel = g[out_z | out_iqr].copy()
        sel["z_score"] = z[sel.index]
        sel["Metodo"] = np.where(out_z[sel.index] & out_iqr[sel.index], "z-score+IQR",
                                 np.where(out_z[sel.index], "z-score", "IQR"))
        sel["Tipo_Anomalia"] = "outlier"
        resultados.append(sel)
    return pd.concat(resultados) if resultados else pd.DataFrame()


def alertas_patrones(df, cfg_an):
    """Horarios inusuales, montos redondos y pagos justo bajo umbrales."""
    alertas = []
    # Horarios inusuales (solo si el dato incluye hora)
    if "Fecha_Hora" in df.columns:
        h = df["Fecha_Hora"].dt.hour
        tiene_hora = (df["Fecha_Hora"].dt.hour != 0) | (df["Fecha_Hora"].dt.minute != 0)
        ini, fin = cfg_an["hora_inusual_inicio"], cfg_an["hora_inusual_fin"]
        mask = tiene_hora & ((h >= ini) | (h < fin))
        a = df[mask].copy()
        a["Tipo_Anomalia"] = "horario_inusual"
        alertas.append(a)
    # Montos redondos sospechosos
    mult, minimo = cfg_an["monto_redondo_multiplo"], cfg_an["monto_redondo_minimo"]
    mask = (df["Monto"] >= minimo) & (np.isclose(df["Monto"] % mult, 0))
    a = df[mask].copy()
    a["Tipo_Anomalia"] = "monto_redondo"
    alertas.append(a)
    # Pagos justo bajo umbrales de aprobación
    mask = pd.Series(False, index=df.index)
    for u in cfg_an["umbrales_aprobacion"]:
        mask |= (df["Monto"] < u) & (df["Monto"] >= u * (1 - cfg_an["margen_bajo_umbral"]))
    a = df[mask].copy()
    a["Tipo_Anomalia"] = "bajo_umbral_aprobacion"
    alertas.append(a)
    return pd.concat(alertas) if alertas else pd.DataFrame()


_COLS_SALIDA = ["Facultad", "Centro_Costo", "Cuenta", "Descripcion", "Fecha",
                "Numero_Documento", "Tipo_Transaccion", "Monto", "Tipo_Anomalia"]


def _registros(d, extras=()):
    if d is None or len(d) == 0:
        return []
    cols = [c for c in list(_COLS_SALIDA) + list(extras) if c in d.columns]
    return json.loads(d[cols].to_json(orient="records", force_ascii=False))


def indices_alertados(df):
    """Serie booleana: True para las partidas con alguna alerta (duplicado, outlier
    o patrón de riesgo). Sirve como etiqueta para el modelo logístico."""
    cfg = cargar_config()["anomalias"]
    idx = set(detectar_duplicados(df).index)
    out = detectar_outliers(df, cfg["z_score_umbral"], cfg["iqr_factor"])
    if len(out):
        idx |= set(out.index)
    pat = alertas_patrones(df, cfg)
    if len(pat):
        idx |= set(pat.index)
    return df.index.isin(list(idx))


def ejecutar_deteccion(df, destino=None):
    """Ejecuta todas las detecciones y guarda alertas_anomalias.json."""
    cfg = cargar_config()["anomalias"]
    dup = detectar_duplicados(df)
    gaps = detectar_gaps(df, cfg["gap_min_secuencia"])
    out = detectar_outliers(df, cfg["z_score_umbral"], cfg["iqr_factor"])
    pat = alertas_patrones(df, cfg)
    res = {
        "resumen": {"duplicados": len(dup), "gaps": len(gaps), "outliers": len(out),
                    "patrones": len(pat), "total": len(dup) + len(gaps) + len(out) + len(pat)},
        "duplicados": _registros(dup),
        "gaps": json.loads(gaps.to_json(orient="records")) if len(gaps) else [],
        "outliers": _registros(out, extras=("z_score", "Metodo")),
        "patrones": _registros(pat),
    }
    if destino:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
    return res
