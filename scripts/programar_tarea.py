"""Ejecución periódica del análisis.

Opción 1 (esta herramienta, mientras el proceso esté activo):
    python scripts/programar_tarea.py           # ejecuta cada noche a la hora de config.yaml

Opción 2 (recomendada en producción) - cron (Linux/Mac), todos los días a las 02:00:
    0 2 * * * cd /ruta/auditoria_universitaria && /ruta/venv/bin/python scripts/ejecutar_analisis.py --opencode

Opción 3 - Programador de tareas de Windows:
    schtasks /Create /SC DAILY /ST 02:00 /TN "AuditoriaUniversitaria" ^
      /TR "C:\\ruta\\venv\\Scripts\\python.exe C:\\ruta\\auditoria_universitaria\\scripts\\ejecutar_analisis.py --opencode"

Los registros se guardan en logs/auditoria.log (rotativo).
"""
import logging
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

import schedule  # noqa: E402

from ejecutar_analisis import configurar_logs, ejecutar  # noqa: E402
from src import cargar_config  # noqa: E402


def tarea():
    """Tarea nocturna: análisis completo con informe de OpenCode."""
    try:
        ejecutar(usar_opencode=True)
    except BaseException:  # SystemExit incluido: no se debe detener el planificador
        logging.getLogger("programar_tarea").exception("Falló la ejecución programada")


if __name__ == "__main__":
    configurar_logs()
    hora = cargar_config()["programacion"]["hora_diaria"]
    schedule.every().day.at(hora).do(tarea)
    logging.getLogger("programar_tarea").info("Programado análisis diario a las %s", hora)
    while True:
        schedule.run_pending()
        time.sleep(30)
