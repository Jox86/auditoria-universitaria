"""Puente hacia OpenCode (agente local con Ollama) para generar informes."""
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import cargar_config, ruta_proyecto

log = logging.getLogger(__name__)

PROMPT_BASE = """Eres un auditor interno de una universidad pública. Analiza los datos de
auditoría adjuntos (resumen por categoría, estadística y alertas de anomalías) y
responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional, con estas claves:
  "resumen_ejecutivo": string,
  "hallazgos": lista de objetos {"titulo", "descripcion", "evidencia"},
  "riesgos": lista de objetos {"riesgo", "nivel" (alto|medio|bajo), "descripcion"},
  "recomendaciones": lista de strings.
Basa cada afirmación únicamente en los datos entregados. Escribe en español."""


class OpenCodeError(RuntimeError):
    """Error al invocar OpenCode."""


def _extraer_json(texto):
    """Extrae el primer objeto JSON balanceado de un texto."""
    texto = re.sub(r"\x1b\[[0-9;]*m", "", texto)  # quitar códigos ANSI
    inicio = texto.find("{")
    while inicio != -1:
        nivel = 0
        en_cadena = False
        escape = False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if en_cadena:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    en_cadena = False
                continue
            if c == '"':
                en_cadena = True
            elif c == "{":
                nivel += 1
            elif c == "}":
                nivel -= 1
                if nivel == 0:
                    try:
                        return json.loads(texto[inicio:i + 1])
                    except json.JSONDecodeError:
                        break
        inicio = texto.find("{", inicio + 1)
    raise OpenCodeError("La respuesta de OpenCode no contiene un JSON válido")


def _resumen_para_prompt(ruta_datos, max_chars=12000):
    """Arma un texto compacto con los archivos procesados para incluir en el prompt."""
    ruta = Path(ruta_datos)
    partes = []
    for nombre in ("resumen_por_categoria.csv", "analisis_estadistico.json",
                   "alertas_anomalias.json"):
        f = ruta / nombre
        if f.exists():
            txt = f.read_text(encoding="utf-8")
            if nombre == "alertas_anomalias.json":
                # solo el resumen y un máximo de 10 registros por tipo
                datos = json.loads(txt)
                compacto = {"resumen": datos.get("resumen")}
                for k in ("duplicados", "gaps", "outliers", "patrones"):
                    compacto[k] = datos.get(k, [])[:10]
                txt = json.dumps(compacto, ensure_ascii=False)
            partes.append(f"### {nombre}\n{txt[:max_chars // 3]}")
    return "\n\n".join(partes)


def analizar_con_opencode(ruta_datos=None, prompt=None, guardar=True):
    """Envía los datos procesados a OpenCode y guarda el informe estructurado.

    Retorna el diccionario del informe (incluye 'metadatos'). Lanza OpenCodeError
    si OpenCode no está disponible, expira o devuelve algo no interpretable.
    """
    cfg = cargar_config()
    oc = cfg["opencode"]
    ruta_datos = Path(ruta_datos) if ruta_datos else ruta_proyecto(cfg["rutas"]["processed"])
    exe = shutil.which(oc.get("comando", "opencode"))
    if not exe:
        raise OpenCodeError("No se encontró el ejecutable 'opencode'. Consulte el README.")

    mensaje = f"{prompt or PROMPT_BASE}\n\nDATOS:\n{_resumen_para_prompt(ruta_datos)}"
    env = os.environ.copy()
    # Permisos definidos en config.yaml, inyectados como configuración de OpenCode
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": oc.get("permission", {})})
    cmd = [exe, "run", "--model", oc["model"], mensaje]
    log.info("Invocando OpenCode (modelo %s)", oc["model"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              timeout=oc.get("timeout_s", 600), cwd=str(ruta_proyecto(".")))
    except subprocess.TimeoutExpired as exc:
        raise OpenCodeError(f"OpenCode excedió el tiempo límite de {oc.get('timeout_s')} s") from exc
    if proc.returncode != 0:
        raise OpenCodeError(f"OpenCode terminó con error: {proc.stderr.strip()[:500]}")

    informe = _extraer_json(proc.stdout)
    for clave in ("resumen_ejecutivo", "hallazgos", "riesgos", "recomendaciones"):
        informe.setdefault(clave, [] if clave != "resumen_ejecutivo" else "")
    informe["metadatos"] = {"generado": datetime.now().isoformat(timespec="seconds"),
                            "modelo": oc["model"], "origen": "opencode"}
    if guardar:
        guardar_informe(informe)
    return informe


def guardar_informe(informe, carpeta=None):
    """Guarda el informe como informe_YYYYMMDD_HHMM.json y devuelve la ruta."""
    cfg = cargar_config()
    carpeta = Path(carpeta) if carpeta else ruta_proyecto(cfg["rutas"]["informes"])
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"informe_{datetime.now():%Y%m%d_%H%M}.json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(informe, f, ensure_ascii=False, indent=2)
    return destino


def informe_local(ruta_datos=None, guardar=True):
    """Informe determinista (sin IA) como respaldo cuando OpenCode no está disponible."""
    cfg = cargar_config()
    ruta = Path(ruta_datos) if ruta_datos else ruta_proyecto(cfg["rutas"]["processed"])
    alertas = json.loads((ruta / "alertas_anomalias.json").read_text(encoding="utf-8"))
    r = alertas["resumen"]
    informe = {
        "resumen_ejecutivo": (f"Se detectaron {r['total']} alertas: {r['duplicados']} duplicados, "
                              f"{r['gaps']} saltos de numeración, {r['outliers']} outliers y "
                              f"{r['patrones']} alertas de patrones de riesgo."),
        "hallazgos": [{"titulo": k.capitalize(), "descripcion": f"{r[k]} registros",
                       "evidencia": "alertas_anomalias.json"} for k in
                      ("duplicados", "gaps", "outliers", "patrones")],
        "riesgos": [{"riesgo": "Posible fraccionamiento de pagos", "nivel": "medio",
                     "descripcion": "Pagos justo bajo umbrales de aprobación."}],
        "recomendaciones": ["Revisar los documentos duplicados y los saltos de numeración.",
                            "Seleccionar muestra y verificar soportes de las partidas de mayor riesgo."],
        "metadatos": {"generado": datetime.now().isoformat(timespec="seconds"),
                      "modelo": None, "origen": "local (sin IA)"},
    }
    if guardar:
        guardar_informe(informe)
    return informe
