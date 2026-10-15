"""Agrupación y resumen por categorías (facultad, centro de costo, área)."""
import pandas as pd


def resumen_por_categoria(df, columnas=None):
    """Calcula estadísticas por categoría y devuelve un DataFrame único."""
    if columnas is None:
        columnas = ["Facultad", "Centro_Costo"]
        if "Area_Administrativa" in df.columns:
            columnas.append("Area_Administrativa")

    def _resumir(g):
        m = g["Monto"]
        return pd.Series({
            "Total_Debe": g["Debe"].sum(),
            "Total_Haber": g["Haber"].sum(),
            "Saldo": g["Saldo"].sum(),
            "Num_Transacciones": len(g),
            "Media": m.mean(),
            "Mediana": m.median(),
            "Desv_Est": m.std(ddof=1) if len(g) > 1 else 0.0,
            "Minimo": m.min(),
            "Maximo": m.max(),
            "RIC": m.quantile(0.75) - m.quantile(0.25),
        })

    partes = []
    for nivel in range(1, len(columnas) + 1):
        cols = columnas[:nivel]
        agr = df.groupby(cols, dropna=False).apply(_resumir, include_groups=False).reset_index()
        agr.insert(0, "Nivel", "/".join(cols))
        partes.append(agr)
    return pd.concat(partes, ignore_index=True)


def exportar_resumen(df, destino):
    """Calcula y guarda el resumen en CSV."""
    res = resumen_por_categoria(df)
    res.to_csv(destino, index=False, encoding="utf-8-sig")
    return res
