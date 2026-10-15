"""Informe con OpenCode: generación, visualización, descarga e historial."""
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import cargar_config, opencode_bridge, reportes, ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Informe OpenCode", page_icon="🤖", layout="wide")
st.title("🤖 Informe con OpenCode")

cfg = cargar_config()
carpeta = ruta_proyecto(cfg["rutas"]["informes"])
carpeta.mkdir(parents=True, exist_ok=True)
proc = ruta_proyecto(cfg["rutas"]["processed"])

if st.button("🤖 Generar informe con OpenCode", type="primary"):
    if not (proc / "alertas_anomalias.json").exists():
        st.error("Primero ejecute el análisis completo desde la página principal.")
    else:
        barra = st.progress(0, text="OpenCode está procesando (puede tardar varios minutos)...")
        try:
            informe = opencode_bridge.analizar_con_opencode(proc)
            barra.progress(100, text="Informe generado")
            st.session_state["informe"] = informe
        except opencode_bridge.OpenCodeError as exc:
            barra.empty()
            st.session_state["error_opencode"] = str(exc)

if st.session_state.get("error_opencode"):
    st.error(f"No se pudo usar OpenCode: {st.session_state['error_opencode']}")
    if st.button("Generar informe local (sin IA)"):
        st.session_state["informe"] = opencode_bridge.informe_local(proc)
        st.session_state.pop("error_opencode", None)

historial = sorted(carpeta.glob("informe_*.json"), reverse=True)
if "informe" not in st.session_state and historial:
    st.session_state["informe"] = json.loads(historial[0].read_text(encoding="utf-8"))

informe = st.session_state.get("informe")
if informe:
    st.subheader("Resumen ejecutivo")
    st.write(informe.get("resumen_ejecutivo", ""))
    st.subheader("Hallazgos")
    for h in informe.get("hallazgos", []):
        st.markdown(f"- **{h.get('titulo', '')}**: {h.get('descripcion', '')}" if isinstance(h, dict) else f"- {h}")
    st.subheader("Riesgos")
    for r in informe.get("riesgos", []):
        st.markdown(f"- **{r.get('riesgo', '')}** [{r.get('nivel', '')}]: {r.get('descripcion', '')}"
                    if isinstance(r, dict) else f"- {r}")
    st.subheader("Recomendaciones")
    for i, x in enumerate(informe.get("recomendaciones", []), 1):
        st.markdown(f"{i}. {x}")
    c = st.columns(3)
    c[0].download_button("⬇️ JSON", reportes.informe_a_json(informe), "informe.json", "application/json")
    c[1].download_button("⬇️ Markdown", reportes.informe_a_markdown(informe), "informe.md", "text/markdown")
    try:
        c[2].download_button("⬇️ PDF", reportes.informe_a_pdf(informe), "informe.pdf", "application/pdf")
    except Exception as exc:
        c[2].caption(f"PDF no disponible: {exc}")

st.subheader("Historial de informes")
if not historial:
    st.caption("Aún no hay informes.")
for f in historial:
    with st.expander(f.name):
        st.json(json.loads(f.read_text(encoding="utf-8")))
