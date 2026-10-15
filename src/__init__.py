"""Paquete principal del sistema de auditoría universitaria."""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def cargar_config(ruta=None):
    """Carga config/config.yaml y devuelve un diccionario."""
    ruta = Path(ruta) if ruta else RAIZ / "config" / "config.yaml"
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ruta_proyecto(relativa):
    """Resuelve una ruta relativa respecto a la raíz del proyecto."""
    return RAIZ / relativa


def cargar_datos():
    """Carga data/processed/datos_limpios.csv (o None si aún no existe)."""
    import pandas as pd

    ruta = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "datos_limpios.csv"
    if not ruta.exists():
        return None
    df = pd.read_csv(ruta, dtype={"Cuenta": str, "Numero_Documento": str})
    df["Fecha_Hora"] = pd.to_datetime(df["Fecha_Hora"], errors="coerce")
    return df


def estado_datos():
    """Semáforo de carga: 'verde' (datos recientes), 'amarillo' (datos más
    nuevos en raw/ que el análisis) o 'rojo' (sin análisis)."""
    proc = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "datos_limpios.csv"
    if not proc.exists():
        return "rojo"
    raw = ruta_proyecto(cargar_config()["rutas"]["raw"])
    archivos = [p for p in raw.glob("*") if p.is_file()]
    if archivos and max(p.stat().st_mtime for p in archivos) > proc.stat().st_mtime:
        return "amarillo"
    return "verde"
