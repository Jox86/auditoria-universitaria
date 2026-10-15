"""Muestreo estadístico (NIA 530): MUM o estratificado."""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import cargar_config, cargar_datos, estadistica, muestreo, ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Muestreo Estadístico", page_icon="🎯", layout="wide")
st.title("🎯 Muestreo Estadístico (NIA 530)")

df = cargar_datos()
if df is None:
    st.warning("No hay datos procesados. Ejecute el análisis desde la página principal.")
    st.stop()

cfg = cargar_config()["muestreo"]
with st.form("parametros"):
    c1, c2, c3 = st.columns(3)
    nc = c1.slider("Nivel de confianza", 0.80, 0.99, float(cfg["nivel_confianza"]), 0.01)
    et = c2.number_input("Error tolerable", min_value=1.0, value=float(cfg["error_tolerable"]))
    ee = c3.number_input("Error esperado (tasa esperada en monto)", min_value=0.0,
                         value=float(cfg["error_esperado"]))
    metodo = st.radio("Método", ["MUM", "Estratificado"], horizontal=True)
    ok = st.form_submit_button("Generar muestra", type="primary")

if ok:
    try:
        fn = muestreo.muestreo_mum if metodo == "MUM" else muestreo.muestreo_estratificado
        sel, meta = fn(df, et, ee, nc, semilla=cfg["semilla"])
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    ws = muestreo.hoja_trabajo(sel, meta)
    destino = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "muestra_estadistica.csv"
    ws.to_csv(destino, index=False, encoding="utf-8-sig")
    st.success(f"{len(ws)} partidas seleccionadas (tamaño calculado: {meta['n_calculado']}).")
    st.dataframe(ws, use_container_width=True)
    st.download_button("⬇️ Descargar hoja de trabajo", ws.to_csv(index=False).encode("utf-8-sig"),
                       "muestra_estadistica.csv", "text/csv")
    st.session_state["muestra"] = (sel, meta)

if "muestra" in st.session_state:
    sel, meta = st.session_state["muestra"]
    st.subheader("Extrapolación de errores (NIA 530)")
    err = st.number_input("Error encontrado en la muestra (monto)", min_value=0.0, value=0.0)
    if st.button("Proyectar error"):
        r = estadistica.extrapolar_error_nia530(meta["valor_poblacion"], float(sel["Monto"].sum()),
                                                err, et)
        st.json(r)
