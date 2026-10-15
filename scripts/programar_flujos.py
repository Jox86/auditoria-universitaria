"""Planificador de flujos de auditoría: ejecuta los flujos vencidos.

Mientras el proceso esté activo, revisa cada cierto tiempo los flujos con
programación vencida (diaria, semanal, cada N días, mensual, cada N meses,
anual o un día específico) y los ejecuta con datos reales.

    python scripts/programar_flujos.py              # bucle continuo
    python scripts/programar_flujos.py --intervalo 60
    python scripts/programar_flujos.py --una-vez    # una pasada y salir (útil para cron)

La alternativa recomendada en producción es llamarlo con --una-vez desde
cron o el Programador de tareas de Windows a intervalos regulares.
"""
import argparse
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import flujos, ruta_proyecto  # noqa: E402


def configurar_logs():
    carpeta = ruta_proyecto("logs")
    carpeta.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    if not raiz.handlers:
        for h in (RotatingFileHandler(carpeta / "flujos.log", maxBytes=1_000_000, backupCount=3),
                  logging.StreamHandler(sys.stdout)):
            h.setFormatter(fmt)
            raiz.addHandler(h)


def pasada():
    vencidos = flujos.flujos_vencidos()
    if vencidos:
        logging.getLogger("programar_flujos").info("Flujos vencidos: %d", len(vencidos))
    for flujo in vencidos:
        try:
            flujos.ejecutar_flujo(flujo["id"])
        except Exception:  # un flujo con fallo no detiene a los demás
            logging.getLogger("programar_flujos").exception("Falló el flujo %s", flujo["id"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Planificador de flujos de auditoría.")
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre revisiones (defecto: 60)")
    ap.add_argument("--una-vez", action="store_true", help="una pasada y salir (para cron/schtasks)")
    args = ap.parse_args()
    configurar_logs()
    if args.una_vez:
        pasada()
    else:
        while True:
            pasada()
            time.sleep(args.intervalo)
