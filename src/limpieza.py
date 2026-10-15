"""Limpieza y normalización de datos contables."""
import pandas as pd


def _a_float(serie):
    """Convierte a float tolerando separadores de miles y coma decimal."""
    s = serie.astype(str).str.strip().str.replace(" ", "", regex=False)
    # "1.234,56" -> "1234.56"; "1,234.56" -> "1234.56"
    con_ambos = s.str.contains(",") & s.str.contains(r"\.")
    s = s.where(~con_ambos, s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    solo_coma = s.str.contains(",") & ~s.str.contains(r"\.")
    s = s.where(~solo_coma, s.str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


def limpiar(df):
    """Limpia el DataFrame. Retorna (df_limpio, df_duplicados_exactos)."""
    df = df.copy()
    for col in ("Facultad", "Centro_Costo", "Cuenta", "Descripcion",
                "Tipo_Transaccion", "Numero_Documento", "Area_Administrativa"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    # Fechas a ISO, conservando la hora si existe
    fecha = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=False)
    df["Fecha_Hora"] = fecha
    df["Fecha"] = fecha.dt.strftime("%Y-%m-%d")
    df = df[fecha.notna()].copy()

    for col in ("Debe", "Haber"):
        df[col] = _a_float(df[col]).fillna(0.0)

    # Duplicados exactos: se eliminan pero se registran
    cols_dup = [c for c in df.columns if c != "Archivo_Origen"]
    mascara = df.duplicated(subset=cols_dup, keep="first")
    duplicados = df[mascara].copy()
    df = df[~mascara].copy()

    df["Saldo"] = df["Debe"] - df["Haber"]
    df["Monto"] = df[["Debe", "Haber"]].max(axis=1)
    df["Periodo"] = pd.to_datetime(df["Fecha"]).dt.strftime("%Y-%m")
    return df.reset_index(drop=True), duplicados.reset_index(drop=True)
