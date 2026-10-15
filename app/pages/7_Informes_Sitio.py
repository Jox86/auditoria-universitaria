"""Informes de sitio: resultados reales de las auditorías automatizadas y de
la prueba real. Muestra la cobertura: qué datos entregó el sitio y qué no se
pudo obtener, con el motivo.
"""
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import ruta_proyecto  # noqa: E402

st.set_page_config(page_title="Informes de sitio", page_icon="📄", layout="wide")
st.title("📄 Informes de auditoría de sitio")

raiz = ruta_proyecto(".")
carpetas = []
for padre in (raiz / "data" / "informes" / "auditorias_sitio",
              raiz / "data" / "informes" / "prueba_real"):
    if padre.exists():
        for f in sorted(padre.glob("*/*")):
            if f.is_dir() and (f / "resultado.json").exists():
                carpetas.append(f)

if not carpetas:
    st.info("Todavía no hay informes. Ejecute una auditoría automatizada (página 🛰️) o "
            "`python scripts/prueba_real.py` y aparecerán aquí.")
    st.stop()

opciones = {}
for carpeta in reversed(carpetas):
    r = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
    opciones[f"{r.get('generado', '')} — {r.get('nombre', '')} ({carpeta.parent.name})"] = carpeta
seleccion = st.selectbox("Informe", list(opciones))
carpeta = opciones[seleccion]
resultado = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sitio", resultado.get("sitio", ""))
c2.metric("Nivel de acceso", resultado.get("nivel_acceso", {}).get("nivel", ""))
conn = resultado.get("conexion", {})
c3.metric("Conexión", f"HTTP {conn.get('http', '—')}",
          f"{conn.get('latencia_ms', '—')} ms")
resumen = resultado.get("resumen_cobertura") or {}
cob = resultado.get("cobertura", [])
c4.metric("Cobertura", f"{resumen.get('ok', 0)} OK",
          f"{resumen.get('parcial', 0)} parcial · {resumen.get('no_disponible', 0)} sin datos · "
          f"{resumen.get('denegado', 0)} denegados")

st.caption(f"Generado: {resultado.get('generado', '')} — flujo: "
           f"{resultado.get('nombre', '')} ({resultado.get('flujo_id', '')})")

if conn.get("titulo"):
    st.write(f"**Título de la página de login:** {conn['titulo']} — estado: {conn.get('estado')}"
             + (f" — {conn.get('error')}" if conn.get("error") else ""))

acc = resultado.get("acceso") or {}
if acc:
    st.subheader("Acceso utilizado")
    for quien, info in acc.items():
        detalle = (info.get("mensaje_sitio") or info.get("mensaje") or info.get("detalle")
                   or "")
        linea = f"**{quien}**: {info.get('estado', '—')}"
        if detalle:
            linea += f" — {detalle}"
        if info.get("advertencia"):
            linea += f" — ⚠️ {info['advertencia']}"
        st.markdown("- " + linea)

st.subheader("Secciones de la auditoría")
for titulo, sec in (resultado.get("secciones") or {}).items():
    st.markdown(f"#### {titulo}")
    if sec.get("descripcion"):
        st.caption(sec["descripcion"])
    if sec.get("texto"):
        st.markdown(sec["texto"])
    if sec.get("tabla"):
        st.dataframe(sec["tabla"], use_container_width=True, hide_index=True)
    if sec.get("detalle"):
        st.caption("Nota: " + sec["detalle"])
    if sec.get("no_disponible"):
        st.warning(f"**Dato no disponible** ({sec['no_disponible']}) — el sitio no entregó esta "
                   f"información con el acceso disponible. No se simulan datos.")

st.subheader("Cobertura")
st.caption("Registro de cada fuente de datos: lo que el sitio entregó y lo que no, con el motivo real.")
st.dataframe(cob, use_container_width=True, hide_index=True)

st.subheader("Archivos del informe")
archivos = sorted(p for p in carpeta.iterdir() if p.is_file())
for p in archivos:
    col1, col2 = st.columns([3, 1])
    col1.markdown(f"`{p.name}` ({p.stat().st_size:,} bytes)")
    col2.download_button(f"⬇️ Descargar {p.suffix.strip('.')}", p.read_bytes(), p.name,
                         key=f"dl_{carpeta.name}_{p.name}")
