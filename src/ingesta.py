"""Ingesta: lectura y validación de archivos contables (CSV, Excel, JSON)."""
import json
import logging
from pathlib import Path

import pandas as pd

from . import cargar_config, ruta_proyecto

log = logging.getLogger(__name__)

COLUMNAS_OBLIGATORIAS = [
    "Facultad", "Centro_Costo", "Cuenta", "Descripcion", "Debe", "Haber",
    "Fecha", "Tipo_Transaccion", "Numero_Documento",
]
EXTENSIONES = {".csv", ".xlsx", ".xls", ".json"}


def leer_archivo(ruta):
    """Lee un archivo CSV, Excel o JSON y devuelve un DataFrame."""
    ruta = Path(ruta)
    ext = ruta.suffix.lower()
    if ext == ".csv":
        try:
            return pd.read_csv(ruta, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(ruta, dtype=str, encoding="latin-1")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(ruta, dtype=str)
    if ext == ".json":
        with open(ruta, "r", encoding="utf-8") as f:
            return pd.DataFrame(json.load(f)).astype(str)
    raise ValueError(f"Extensión no soportada: {ext}")


def validar_columnas(df, obligatorias=None):
    """Devuelve la lista de columnas obligatorias que faltan."""
    obligatorias = obligatorias or COLUMNAS_OBLIGATORIAS
    return [c for c in obligatorias if c not in df.columns]


def ingestar(carpeta_raw=None, columnas=None):
    """Lee todos los archivos de la carpeta raw, valida y consolida.

    Retorna (DataFrame, log_integridad). El log contiene filas leídas,
    descartadas y tipos de error por archivo.
    """
    cfg = cargar_config()
    carpeta = Path(carpeta_raw) if carpeta_raw else ruta_proyecto(cfg["rutas"]["raw"])
    columnas = columnas or cfg.get("columnas_obligatorias", COLUMNAS_OBLIGATORIAS)
    log_int = {"archivos": [], "filas_leidas": 0, "filas_descartadas": 0, "errores": {}}
    partes = []

    archivos = sorted(p for p in carpeta.glob("*") if p.suffix.lower() in EXTENSIONES)
    for arch in archivos:
        info = {"archivo": arch.name, "leidas": 0, "descartadas": 0, "error": None}
        try:
            df = leer_archivo(arch)
        except Exception as exc:  # archivo ilegible
            info["error"] = f"lectura: {exc}"
            log_int["errores"]["archivo_ilegible"] = log_int["errores"].get("archivo_ilegible", 0) + 1
            log_int["archivos"].append(info)
            continue
        info["leidas"] = len(df)
        faltan = validar_columnas(df, columnas)
        if faltan:
            info["error"] = f"columnas faltantes: {faltan}"
            info["descartadas"] = len(df)
            log_int["errores"]["columnas_faltantes"] = log_int["errores"].get("columnas_faltantes", 0) + 1
        else:
            # Se descartan filas sin Cuenta o sin Fecha (no auditables)
            validas = df["Cuenta"].notna() & df["Fecha"].notna()
            info["descartadas"] = int((~validas).sum())
            if info["descartadas"]:
                log_int["errores"]["fila_sin_cuenta_o_fecha"] = (
                    log_int["errores"].get("fila_sin_cuenta_o_fecha", 0) + info["descartadas"]
                )
            df = df[validas].copy()
            df["Archivo_Origen"] = arch.name
            partes.append(df)
        log_int["filas_leidas"] += info["leidas"]
        log_int["filas_descartadas"] += info["descartadas"]
        log_int["archivos"].append(info)

    datos = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=columnas)
    log.info("Ingesta: %s filas leídas, %s descartadas", log_int["filas_leidas"], log_int["filas_descartadas"])
    return datos, log_int


def exportar_log(log_int, carpeta=None):
    """Guarda el log de integridad en data/processed/log_integridad.json."""
    cfg = cargar_config()
    carpeta = Path(carpeta) if carpeta else ruta_proyecto(cfg["rutas"]["processed"])
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "log_integridad.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(log_int, f, ensure_ascii=False, indent=2)
    return destino
