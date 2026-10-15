"""Orquesta todo el flujo: ingesta -> limpieza -> resumen -> anomalías ->
estadística -> muestreo -> (opcional) informe con OpenCode.

Uso:
    python scripts/ejecutar_analisis.py [--opencode] [--metodo mum|estratificado]
"""
import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import cargar_config, ruta_proyecto  # noqa: E402
from src import anomalias, categorizacion, estadistica, ingesta, limpieza, muestreo  # noqa: E402
from src import opencode_bridge  # noqa: E402


def configurar_logs():
    """Log rotativo en logs/auditoria.log y salida por consola."""
    carpeta = ruta_proyecto("logs")
    carpeta.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    if not raiz.handlers:
        for h in (RotatingFileHandler(carpeta / "auditoria.log", maxBytes=1_000_000,
                                      backupCount=5, encoding="utf-8"),
                  logging.StreamHandler()):
            h.setFormatter(fmt)
            raiz.addHandler(h)


def ejecutar(usar_opencode=False, metodo="mum"):
    """Ejecuta el análisis completo y devuelve un diccionario con las rutas de salida."""
    configurar_logs()
    log = logging.getLogger("ejecutar_analisis")
    cfg = cargar_config()
    proc = ruta_proyecto(cfg["rutas"]["processed"])
    proc.mkdir(parents=True, exist_ok=True)

    log.info("1/6 Ingesta")
    datos, log_int = ingesta.ingestar()
    ingesta.exportar_log(log_int)
    if datos.empty:
        raise SystemExit("No hay datos válidos en data/raw/. Copie allí un CSV/Excel/JSON "
                         "(ver EJEMPLO_DATOS.csv).")

    log.info("2/6 Limpieza")
    df, duplicados = limpieza.limpiar(datos)
    df.to_csv(proc / "datos_limpios.csv", index=False, encoding="utf-8-sig")
    duplicados.to_csv(proc / "duplicados_exactos_eliminados.csv", index=False, encoding="utf-8-sig")

    log.info("3/6 Resumen por categoría")
    categorizacion.exportar_resumen(df, proc / "resumen_por_categoria.csv")

    log.info("4/6 Anomalías")
    anomalias.ejecutar_deteccion(df, proc / "alertas_anomalias.json")
    etiqueta = anomalias.indices_alertados(df)

    log.info("5/6 Estadística")
    res = estadistica.analisis_completo(df, etiqueta)
    with open(proc / "analisis_estadistico.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    log.info("6/6 Muestreo (%s)", metodo)
    m = cfg["muestreo"]
    fn = muestreo.muestreo_mum if metodo == "mum" else muestreo.muestreo_estratificado
    sel, meta = fn(df, m["error_tolerable"], m["error_esperado"], m["nivel_confianza"],
                   semilla=m["semilla"])
    muestreo.hoja_trabajo(sel, meta).to_csv(proc / "muestra_estadistica.csv", index=False,
                                            encoding="utf-8-sig")

    salida = {"processed": str(proc), "filas": len(df), "muestra": len(sel)}
    if usar_opencode:
        try:
            informe = opencode_bridge.analizar_con_opencode(proc)
        except opencode_bridge.OpenCodeError as exc:
            log.warning("OpenCode no disponible (%s); se genera informe local", exc)
            informe = opencode_bridge.informe_local(proc)
        salida["informe_origen"] = informe["metadatos"]["origen"]
    log.info("Análisis completo: %s", salida)
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--opencode", action="store_true", help="generar informe con OpenCode")
    ap.add_argument("--metodo", choices=["mum", "estratificado"], default="mum")
    a = ap.parse_args()
    ejecutar(a.opencode, a.metodo)
