"""Análisis por facultad: estadísticas descriptivas y comparación (t-test)."""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import cargar_datos, categorizacion, estadistica  # noqa: E402

st.set_page_config(page_title="Análisis por Facultad", page_icon="🏛️", layout="wide")
st.title("🏛️ Análisis por Facultad")

df = cargar_datos()
if df is None:
    st.warning("No hay datos procesados. Ejecute el análisis desde la página principal.")
    st.stop()

facs = st.sidebar.multiselect("Facultades", sorted(df["Facultad"].unique()),
                              default=sorted(df["Facultad"].unique()))
d = df[df["Facultad"].isin(facs)]
ccs = st.sidebar.multiselect("Centros de costo", sorted(d["Centro_Costo"].unique()))
d = d[d["Centro_Costo"].isin(ccs)] if ccs else d
periodos = sorted(d["Periodo"].unique())
if len(periodos) > 1:
    p_ini, p_fin = st.sidebar.select_slider("Período", options=periodos,
                                            value=(periodos[0], periodos[-1]))
    d = d[(d["Periodo"] >= p_ini) & (d["Periodo"] <= p_fin)]

if d.empty:
    st.info("Sin datos para los filtros elegidos.")
    st.stop()

st.subheader("Estadísticas descriptivas")
nivel = st.radio("Nivel de agrupación", ["Facultad", "Facultad y centro de costo"], horizontal=True)
cols = ["Facultad"] if nivel == "Facultad" else ["Facultad", "Centro_Costo"]
res = categorizacion.resumen_por_categoria(d, cols)
res = res[res["Nivel"] == "/".join(cols)]
st.dataframe(res, use_container_width=True)
st.download_button("⬇️ Descargar CSV", res.to_csv(index=False).encode("utf-8-sig"),
                   "analisis_por_facultad.csv", "text/csv")

st.subheader("Comparación estadística entre facultades (t-test de Welch)")
if d["Facultad"].nunique() < 2:
    st.info("Seleccione al menos dos facultades.")
else:
    comp = estadistica.comparar_facultades(d)
    st.dataframe(pd.DataFrame(comp["pares"]), use_container_width=True)
    if comp["anova"]:
        st.write(f"ANOVA global: F = {comp['anova']['F']:.3f}, p = {comp['anova']['p_valor']:.4f}")
    st.caption(f"p ajustado con Bonferroni; nivel de significancia α = {comp['alfa']}.")
