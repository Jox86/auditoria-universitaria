"""Aplicación principal Streamlit: Auditoría de Cuentas Universitarias."""
import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import cargar_config, estado_datos, ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Auditoría Universitaria", page_icon="📊", layout="wide")
st.title("📊 Auditoría de Cuentas Universitarias")

estado = estado_datos()
iconos = {"verde": "🟢 Datos cargados y actualizados",
          "amarillo": "🟡 Hay archivos nuevos en data/raw/: vuelva a ejecutar el análisis",
          "rojo": "🔴 Sin análisis: coloque datos en data/raw/ y ejecute el análisis"}
st.sidebar.header("Navegación")
st.sidebar.markdown("Use el menú de páginas de la izquierda:\n\n"
                    "1. Dashboard General\n2. Análisis por Facultad\n3. Detección de Anomalías\n"
                    "4. Muestreo Estadístico\n5. Informe OpenCode\n"
                    "6. Auditorías Automatizadas\n7. Informes de sitio")
st.sidebar.subheader("Estado de los datos")
st.sidebar.write(iconos[estado])

st.write("Sistema local de análisis estadístico y detección de anomalías para auditores internos.")
st.info(iconos[estado])

col1, col2 = st.columns(2)
usar_oc = col2.checkbox("Incluir informe con OpenCode (más lento)", value=False)
if col1.button("🔄 Ejecutar análisis completo", type="primary"):
    cmd = [sys.executable, str(RAIZ / "scripts" / "ejecutar_analisis.py")]
    if usar_oc:
        cmd.append("--opencode")
    with st.spinner("Ejecutando análisis..."):
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(RAIZ))
    if proc.returncode == 0:
        st.success("Análisis completado. Recargue la página para ver el estado actualizado.")
    else:
        st.error("El análisis falló.")
    with st.expander("Salida del proceso"):
        st.code((proc.stdout or "") + (proc.stderr or ""))

log = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "log_integridad.json"
if log.exists():
    d = json.loads(log.read_text(encoding="utf-8"))
    st.subheader("Integridad de la última carga")
    c1, c2 = st.columns(2)
    c1.metric("Filas leídas", d["filas_leidas"])
    c2.metric("Filas descartadas", d["filas_descartadas"])
    if d["errores"]:
        st.warning(f"Errores detectados: {d['errores']}")
