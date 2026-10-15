"""Dashboard general: métricas, barras, pastel, serie temporal y mapa de calor."""
import json
import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import cargar_config, cargar_datos, ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Dashboard General", page_icon="📊", layout="wide")
st.title("📊 Dashboard General")

df = cargar_datos()
if df is None:
    st.warning("No hay datos procesados. Ejecute el análisis desde la página principal.")
    st.stop()

# Filtros: facultad, centro de costo y período
st.sidebar.header("Filtros")
facs = st.sidebar.multiselect("Facultad", sorted(df["Facultad"].unique()))
d = df[df["Facultad"].isin(facs)] if facs else df
ccs = st.sidebar.multiselect("Centro de costo", sorted(d["Centro_Costo"].unique()))
d = d[d["Centro_Costo"].isin(ccs)] if ccs else d
periodos = sorted(d["Periodo"].unique())
p_ini, p_fin = st.sidebar.select_slider("Período", options=periodos, value=(periodos[0], periodos[-1]))
d = d[(d["Periodo"] >= p_ini) & (d["Periodo"] <= p_fin)]

alertas = 0
ruta = ruta_proyecto(cargar_config()["rutas"]["processed"]) / "alertas_anomalias.json"
if ruta.exists():
    alertas = json.loads(ruta.read_text(encoding="utf-8"))["resumen"]["total"]

c = st.columns(5)
c[0].metric("Transacciones", f"{len(d):,}")
c[1].metric("Monto total", f"{d['Monto'].sum():,.2f}")
c[2].metric("Facultades", d["Facultad"].nunique())
c[3].metric("Centros de costo", d["Centro_Costo"].nunique())
c[4].metric("Alertas activas", alertas)

a, b = st.columns(2)
por_fac = d.groupby("Facultad", as_index=False)["Monto"].sum()
a.plotly_chart(px.bar(por_fac, x="Facultad", y="Monto", title="Ejecución por facultad"),
               use_container_width=True)
por_cc = d.groupby("Centro_Costo", as_index=False)["Monto"].sum()
b.plotly_chart(px.pie(por_cc, names="Centro_Costo", values="Monto",
                      title="Distribución por centro de costo"), use_container_width=True)

mensual = d.groupby("Periodo", as_index=False)["Monto"].sum()
st.plotly_chart(px.line(mensual, x="Periodo", y="Monto", markers=True,
                        title="Evolución mensual del gasto"), use_container_width=True)

piv = d.pivot_table(index="Facultad", columns="Periodo", values="Monto", aggfunc="sum", fill_value=0)
st.plotly_chart(px.imshow(piv, aspect="auto", color_continuous_scale="YlOrRd",
                          title="Gasto por facultad × mes"), use_container_width=True)
