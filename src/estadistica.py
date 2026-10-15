"""Análisis estadístico descriptivo e inferencial.

Todas las funciones devuelven estructuras serializables a JSON.
"""
import itertools
import math

import numpy as np
import pandas as pd
from scipy import stats

from . import cargar_config


def _limpio(obj):
    """Convierte tipos numpy/pandas a tipos nativos para serializar a JSON."""
    if isinstance(obj, dict):
        return {str(k): _limpio(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_limpio(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    if obj is pd.NA:
        return None
    return obj


# ---------------------------------------------------------------- descriptiva
def descriptiva(df):
    """Tendencia central, dispersión, frecuencias, estratos y antigüedad."""
    cfg = cargar_config()
    m = df["Monto"]
    out = {
        "tendencia_central": {"media": m.mean(), "mediana": m.median(),
                              "moda": m.mode().iloc[0] if not m.mode().empty else None},
        "dispersion": {"desv_est": m.std(ddof=1), "varianza": m.var(ddof=1),
                       "rango": m.max() - m.min(),
                       "ric": m.quantile(0.75) - m.quantile(0.25),
                       "coef_variacion": m.std(ddof=1) / m.mean() if m.mean() else None},
        "forma": {"asimetria": stats.skew(m), "curtosis": stats.kurtosis(m)},
    }
    # Distribución de frecuencias por rangos de monto
    bins = list(cfg["muestreo"]["rangos_monto"]) + [np.inf]
    rangos = pd.cut(m, bins=bins, right=False)
    frec = rangos.value_counts().sort_index()
    out["frecuencias_monto"] = [
        {"rango": str(k), "n": int(v), "pct": float(v / len(m) * 100),
         "monto": float(m[rangos == k].sum())}
        for k, v in frec.items()
    ]
    # Antigüedad de saldos respecto a la fecha más reciente del conjunto
    ref = df["Fecha_Hora"].max() if "Fecha_Hora" in df.columns else pd.to_datetime(df["Fecha"]).max()
    dias = (ref - (df["Fecha_Hora"] if "Fecha_Hora" in df.columns else pd.to_datetime(df["Fecha"]))).dt.days
    edges = list(cfg["estadistica"]["antiguedad_bins_dias"]) + [np.inf]
    cat = pd.cut(dias, bins=edges, right=False, include_lowest=True)
    ant = df.assign(_c=cat).groupby("_c", observed=False)["Saldo"].agg(["count", "sum"])
    out["antiguedad_saldos"] = [{"tramo_dias": str(k), "n": int(r["count"]), "saldo": float(r["sum"])}
                                for k, r in ant.iterrows()]
    return _limpio(out)


# ----------------------------------------------------------------- inferencial
def comparar_facultades(df, alfa=None):
    """t-test de Welch por pares de facultades sobre el Monto (con Bonferroni)."""
    alfa = alfa or cargar_config()["estadistica"]["alfa"]
    grupos = {f: g["Monto"].values for f, g in df.groupby("Facultad") if len(g) >= 2}
    pares = list(itertools.combinations(sorted(grupos), 2))
    resultados = []
    for a, b in pares:
        t, p = stats.ttest_ind(grupos[a], grupos[b], equal_var=False)
        resultados.append({"facultad_a": a, "facultad_b": b,
                           "media_a": grupos[a].mean(), "media_b": grupos[b].mean(),
                           "t": t, "p_valor": p})
    k = max(len(resultados), 1)
    for r in resultados:
        r["p_ajustado"] = min(r["p_valor"] * k, 1.0) if r["p_valor"] is not None else None
        r["significativo"] = bool(r["p_ajustado"] is not None and r["p_ajustado"] < alfa)
    # ANOVA global
    anova = None
    if len(grupos) >= 3:
        f, p = stats.f_oneway(*grupos.values())
        anova = {"F": f, "p_valor": p}
    return _limpio({"pares": resultados, "anova": anova, "alfa": alfa})


def chi_cuadrado_facultad_rango(df):
    """Prueba chi-cuadrado de independencia entre Facultad y rango de monto."""
    cfg = cargar_config()
    bins = list(cfg["muestreo"]["rangos_monto"]) + [np.inf]
    rango = pd.cut(df["Monto"], bins=bins, right=False).astype(str)
    tabla = pd.crosstab(df["Facultad"], rango)
    if tabla.shape[0] < 2 or tabla.shape[1] < 2:
        return {"chi2": None, "p_valor": None, "gl": None, "nota": "tabla insuficiente"}
    chi2, p, gl, _ = stats.chi2_contingency(tabla)
    return _limpio({"chi2": chi2, "p_valor": p, "gl": gl,
                    "tabla": tabla.reset_index().to_dict(orient="records")})


def correlaciones(df):
    """Correlaciones de Pearson y Spearman entre variables contables."""
    num = df[["Debe", "Haber", "Saldo", "Monto"]].copy()
    num["Mes"] = pd.to_datetime(df["Fecha"]).dt.month
    num = num.loc[:, num.std() > 0]
    return _limpio({"pearson": num.corr(method="pearson").to_dict(),
                    "spearman": num.corr(method="spearman").to_dict()})


def regresion_lineal_monto(df):
    """Regresión OLS del monto sobre mes y tipo de transacción."""
    import statsmodels.formula.api as smf
    d = df.copy()
    d["Mes"] = pd.to_datetime(d["Fecha"]).dt.month
    if d["Tipo_Transaccion"].nunique() < 2 or len(d) < 10:
        return {"nota": "datos insuficientes"}
    try:
        mod = smf.ols("Monto ~ Mes + C(Tipo_Transaccion)", data=d).fit()
        return _limpio({"r2": mod.rsquared, "r2_ajustado": mod.rsquared_adj,
                        "coeficientes": mod.params.to_dict(),
                        "p_valores": mod.pvalues.to_dict(), "n": int(mod.nobs)})
    except Exception as exc:
        return {"nota": f"no se pudo ajustar: {exc}"}


def regresion_logistica_riesgo(df, etiqueta=None):
    """Regresión logística de la probabilidad de partida de riesgo.

    `etiqueta` es una serie booleana (p. ej. partidas con alerta). Si no se
    entrega, se usa como proxy el outlier por IQR en el monto.
    """
    import statsmodels.api as sm
    d = df.copy()
    if etiqueta is None:
        q1, q3 = d["Monto"].quantile([0.25, 0.75])
        etiqueta = d["Monto"] > q3 + 1.5 * (q3 - q1)
    y = pd.Series(etiqueta, index=d.index).astype(int)
    if y.sum() < 3 or (len(y) - y.sum()) < 3:
        return {"nota": "pocas observaciones positivas/negativas para modelar"}
    X = pd.DataFrame({
        "log_monto": np.log1p(d["Monto"]),
        "mes": pd.to_datetime(d["Fecha"]).dt.month,
        "es_debe": (d["Debe"] > 0).astype(int),
    })
    try:
        mod = sm.Logit(y, sm.add_constant(X)).fit(disp=0, maxiter=200)
        return _limpio({"pseudo_r2": mod.prsquared, "coeficientes": mod.params.to_dict(),
                        "odds_ratio": np.exp(mod.params).to_dict(),
                        "p_valores": mod.pvalues.to_dict(), "n": int(mod.nobs)})
    except Exception as exc:  # separación perfecta, singularidad, etc.
        return {"nota": f"no se pudo ajustar el modelo: {exc}"}


def extrapolar_error_nia530(valor_poblacion, valor_muestra, error_muestra,
                            error_tolerable=None):
    """Proyección de errores según NIA 530 (método de razón).

    error_proyectado = error_muestra / valor_muestra * valor_poblacion
    """
    if valor_muestra <= 0:
        return {"error_proyectado": None, "nota": "valor de muestra nulo"}
    proy = error_muestra / valor_muestra * valor_poblacion
    out = {"error_muestra": error_muestra, "valor_muestra": valor_muestra,
           "valor_poblacion": valor_poblacion, "error_proyectado": proy}
    if error_tolerable is not None:
        out["error_tolerable"] = error_tolerable
        out["supera_tolerable"] = bool(proy > error_tolerable)
    return _limpio(out)


def analisis_completo(df, etiqueta_riesgo=None):
    """Ejecuta todos los análisis y devuelve un único diccionario."""
    return _limpio({
        "descriptiva": descriptiva(df),
        "comparacion_facultades": comparar_facultades(df),
        "chi_cuadrado": chi_cuadrado_facultad_rango(df),
        "correlaciones": correlaciones(df),
        "regresion_lineal": regresion_lineal_monto(df),
        "regresion_logistica": regresion_logistica_riesgo(df, etiqueta_riesgo),
    })
