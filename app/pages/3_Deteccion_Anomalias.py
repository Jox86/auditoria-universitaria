"""Detección de anomalías: duplicados, saltos y outliers con filtros."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import cargar_config, ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Detección de Anomalías", page_icon="🚨", layout="wide")
st.title("🚨 Detección de Anomalías")

ruta = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "alertas_anomalias.json"
if not ruta.exists():
    st.warning("No hay alertas. Ejecute el análisis desde la página principal.")
    st.stop()
datos = json.loads(ruta.read_text(encoding="utf-8"))

r = datos["resumen"]
c = st.columns(4)
c[0].metric("Duplicados", r["duplicados"])
c[1].metric("Saltos de numeración", r["gaps"])
c[2].metric("Outliers", r["outliers"])
c[3].metric("Patrones de riesgo", r["patrones"])

dup = pd.DataFrame(datos["duplicados"])
out = pd.DataFrame(datos["outliers"])
pat = pd.DataFrame(datos["patrones"])
gaps = pd.DataFrame(datos["gaps"])
todas = pd.concat([x for x in (dup, out, pat) if len(x)], ignore_index=True)

tipos = sorted(todas["Tipo_Anomalia"].unique()) if len(todas) else []
sel_tipos = st.sidebar.multiselect("Tipo de anomalía", tipos, default=tipos)
facs = sorted(todas["Facultad"].unique()) if len(todas) else []
sel_facs = st.sidebar.multiselect("Facultad", facs, default=facs)
if len(todas):
    lo, hi = float(todas["Monto"].min()), float(todas["Monto"].max())
    rango = st.sidebar.slider("Rango de monto", lo, hi, (lo, hi)) if lo < hi else (lo, hi)
else:
    rango = (0.0, 0.0)


def filtrar(t):
    if t.empty:
        return t
    m = (t["Facultad"].isin(sel_facs) & t["Tipo_Anomalia"].isin(sel_tipos)
         & t["Monto"].between(*rango))
    return t[m]


st.subheader("Duplicados (Fecha + Cuenta + Monto + Documento)")
st.dataframe(filtrar(dup), use_container_width=True)
st.subheader("Saltos en secuencias de documentos")
st.dataframe(gaps, use_container_width=True)
st.subheader("Outliers (z-score > 3 / IQR 1,5×)")
st.dataframe(filtrar(out), use_container_width=True)
st.subheader("Patrones de riesgo (horario, monto redondo, bajo umbral)")
st.dataframe(filtrar(pat), use_container_width=True)
