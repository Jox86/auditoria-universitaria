"""Auditorías automatizadas: formulario de nueva auditoría y gestión de flujos.

Al guardar se genera un flujo automático persistente (JSON) que se puede
editar, pausar, ejecutar y eliminar. La ejecución usa datos reales del sitio:
lo que el sitio no entregue queda registrado en la cobertura con su motivo.
"""
import json
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import auditorias_sitio, cargar_config, exportadores, flujos  # noqa: E402

st.set_page_config(page_title="Auditorías automatizadas", page_icon="🛰️", layout="wide")
st.title("🛰️ Auditorías automatizadas de sitios")

cfg = cargar_config()
aud_cfg = cfg.get("auditorias", {})
sitio_def = aud_cfg.get("sitio_predeterminado", "https://evea.uh.cu")

# ------------------------------------------------------------------ planificador en 2º plano

class Planificador:
    """Hilo que ejecuta flujos vencidos mientras la aplicación esté abierta."""

    def __init__(self):
        self.detener = threading.Event()
        self.hilo = None


@st.cache_resource
def _planificador():
    return Planificador()


def _iniciar_planificador(plan: Planificador):
    def bucle():
        import time

        import logging
        logging.basicConfig(level=logging.INFO)
        log = logging.getLogger("planificador_ui")
        while not plan.detener.is_set():
            try:
                for flujo in flujos.flujos_vencidos():
                    log.info("Ejecutando flujo vencido %s", flujo["id"])
                    flujos.ejecutar_flujo(flujo["id"])
            except Exception:
                log.exception("Fallo del planificador")
            plan.detener.wait(60)
    plan.detener.clear()
    plan.hilo = threading.Thread(target=bucle, daemon=True, name="planificador-flujos")
    plan.hilo.start()


plan = _planificador()
encendido = st.sidebar.toggle("⏱️ Planificador en segundo plano", value=False,
                              help="Ejecuta los flujos vencidos mientras la aplicación esté abierta. "
                                   "Para producción use scripts/programar_flujos.py con cron/schtasks.")
if encendido and not (plan.hilo and plan.hilo.is_alive()):
    _iniciar_planificador(plan)
    st.sidebar.caption("Planificador activo (revisa cada 60 s).")
elif not encendido and plan.hilo:
    plan.detener.set()
    st.sidebar.caption("Planificador detenido.")

# ------------------------------------------------------------------ formulario

FORM_KEYS = ["f_nombre", "f_descripcion", "f_sitio", "f_usuario", "f_password",
             "f_con_admin", "f_admin_usuario", "f_admin_password", "f_tipos",
             "f_formatos", "f_modo", "f_n", "f_n_meses", "f_dia_semana",
             "f_dia_mes", "f_mes", "f_dia_anual", "f_hora", "f_fecha"]


def limpiar_formulario():
    for k in FORM_KEYS:
        st.session_state.pop(k, None)
    st.session_state.pop("_precargado", None)
    st.session_state.pop("editar_flujo_id", None)


editando = st.session_state.get("editar_flujo_id")
titulo_form = "✏️ Editar auditoría automatizada" if editando else "➕ Nueva auditoría automatizada"
if st.button("✖️ Cancelar edición" if editando else "🧹 Formulario limpio (nueva auditoría)"):
    limpiar_formulario()
    st.rerun()

st.subheader(titulo_form)
st.caption("Al guardar se genera un flujo automático editable y gestionable: la auditoría se "
           "ejecutará con credenciales reales y, si el sitio no entrega algún dato, el informe "
           "lo declarará como no disponible con el motivo (no se simula información).")

flujo_editado = None
if editando:
    try:
        flujo_editado = flujos.cargar_flujo(editando)
    except FileNotFoundError:
        st.error("El flujo que intentaba editar ya no existe.")
        limpiar_formulario()
        st.rerun()

if flujo_editado:
    # Precargar el formulario una sola vez por edición
    if not st.session_state.get("_precargado") == editando:
        cred = flujo_editado.get("credenciales", {})
        adm = cred.get("admin") or {}
        prog = flujo_editado["programacion"]
        h, m = map(int, (prog.get("hora") or "02:00").split(":"))
        precarga = {
            "f_nombre": flujo_editado["nombre"], "f_descripcion": flujo_editado.get("descripcion", ""),
            "f_sitio": flujo_editado["sitio"], "f_usuario": (cred.get("usuario") or {}).get("usuario", ""),
            "f_con_admin": bool(adm), "f_admin_usuario": adm.get("usuario", ""),
            "f_tipos": flujo_editado["tipos_auditoria"], "f_formatos": flujo_editado["formatos"],
            "f_modo": prog["modo"], "f_hora": datetime.strptime(prog.get("hora", "02:00"), "%H:%M").time(),
        }
        for campo in ("n", "n_meses", "dia_semana", "dia_mes", "mes", "dia_anual"):
            if prog.get(campo) is not None:
                precarga[f"f_{campo}"] = int(prog[campo])
        if prog.get("fecha"):
            precarga["f_fecha"] = datetime.strptime(prog["fecha"], "%Y-%m-%d").date()
        st.session_state.update(precarga)
        st.session_state["_precargado"] = editando

c1, c2 = st.columns(2)
c1.text_input("Nombre de la auditoría", placeholder="p. ej. Auditoría mensual EVeA",
              key="f_nombre")
c2.text_area("Descripción (opcional)", height=70, key="f_descripcion")

st.markdown("#### 1. Sitio y credenciales")
c1, c2 = st.columns(2)
c1.text_input("URL del sitio", value=sitio_def, key="f_sitio",
              help="Por defecto el sitio institucional; puede apuntar a otro sitio Moodle.")
c2.markdown("&nbsp;")
c1, c2 = st.columns(2)
c1.text_input("Usuario (cuenta con la que se audita)", key="f_usuario",
              help="Puede ser la cuenta del auditor; si además tiene rol de administrador, "
                   "la auditoría completa podrá realizarse.")
c2.text_input("Contraseña del usuario", type="password", key="f_password",
              help="Se guarda en el flujo local (data/flujos/) para la ejecución desatendida; "
                   "restrinja los permisos de esa carpeta.")
con_admin = st.checkbox("También dispongo de cuenta de administrador o superadmin",
                        key="f_con_admin",
                        help="Con credenciales de administrador la auditoría puede cubrir cuentas, "
                             "roles, permisos y páginas administrativas; sin ellas, el sistema "
                             "auditará solo lo que el sitio exponga y lo declarará así.")
if con_admin:
    c1, c2 = st.columns(2)
    c1.text_input("Usuario administrador", key="f_admin_usuario")
    c2.text_input("Contraseña del administrador", type="password", key="f_admin_password")

st.markdown("#### 2. Tipo de auditoría")
etiqueta_a_tipo = {v: k for k, v in auditorias_sitio.TIPOS.items()}
tipos_sel = st.multiselect("Qué auditar (puede combinar varios)", list(auditorias_sitio.TIPOS.values()),
                           default=["Sitio (información general)"], key="f_tipos",
                           help="Si el sitio no puede entregar el dato de un tipo (por ejemplo la "
                                "matriz completa de permisos), el informe lo marcará como no "
                                "disponible con el motivo real.")

st.markdown("#### 3. Formato de entrega")
ETIQUETA_FORMATO = {f"{v} ({k})": k for k, v in exportadores.FORMATOS.items()}
formatos_sel = st.multiselect("Exportar el informe en", list(ETIQUETA_FORMATO),
                              default=["Excel (.xlsx) (xlsx)", "Markdown (.md) (md)"],
                              key="f_formatos")

st.markdown("#### 4. Periodicidad del informe")
etiqueta_modo = {v: k for k, v in flujos.MODOS.items()}
modo = st.radio("Con qué frecuencia se repetirá la auditoría", list(flujos.MODOS.values()),
                horizontal=True, key="f_modo")
modo_cod = etiqueta_modo[modo]
hora = st.time_input("Hora de ejecución", key="f_hora")
prog = {"modo": modo_cod, "hora": f"{hora.hour:02d}:{hora.minute:02d}"}
if modo_cod == "una_vez":
    fecha = st.date_input("Día específico", min_value=datetime.now().date(),
                          value=datetime.now().date() + timedelta(days=1), key="f_fecha")
    prog["fecha"] = fecha.strftime("%Y-%m-%d")
elif modo_cod == "cada_n_dias":
    prog["n"] = int(st.number_input("Cada cuántos días", min_value=1, max_value=365, value=2, key="f_n"))
elif modo_cod == "semanal":
    prog["dia_semana"] = st.selectbox("Día de la semana", range(7),
                                      format_func=lambda i: flujos.DIAS_SEMANA[i], key="f_dia_semana")
elif modo_cod == "mensual":
    prog["dia_mes"] = int(st.number_input("Día del mes", min_value=1, max_value=28, value=1, key="f_dia_mes"))
elif modo_cod == "cada_n_meses":
    prog["n"] = int(st.number_input("Cada cuántos meses", min_value=1, max_value=12, value=2, key="f_n_meses"))
    prog["dia_mes"] = int(st.number_input("Día del mes", min_value=1, max_value=28, value=1, key="f_dia_mes"))
elif modo_cod == "anual":
    prog["mes"] = st.selectbox("Mes", range(1, 13),
                               format_func=lambda m: ["enero", "febrero", "marzo", "abril", "mayo",
                                                      "junio", "julio", "agosto", "septiembre",
                                                      "octubre", "noviembre", "diciembre"][m - 1],
                               key="f_mes")
    prog["dia"] = int(st.number_input("Día", min_value=1, max_value=31, value=1, key="f_dia_anual"))

col_b, col_info = st.columns([1, 2])
guardar = col_b.button("💾 Guardar y generar flujo automático", type="primary",
                       key="btn_guardar")

if guardar:
    cred_usuario = (st.session_state.get("f_usuario", ""), st.session_state.get("f_password", ""))
    cred_admin = (st.session_state.get("f_admin_usuario", ""), st.session_state.get("f_admin_password", ""))
    datos = {
        "nombre": st.session_state.get("f_nombre", ""),
        "descripcion": st.session_state.get("f_descripcion", ""),
        "sitio": st.session_state.get("f_sitio", ""),
        "usuario": cred_usuario[0], "password": cred_usuario[1],
        "con_admin": bool(st.session_state.get("f_con_admin")),
        "admin_usuario": cred_admin[0], "admin_password": cred_admin[1],
        "tipos_auditoria": [etiqueta_a_tipo[t] for t in tipos_sel],
        "formatos": [ETIQUETA_FORMATO[f] for f in formatos_sel],
        "programacion": prog,
    }
    errores = flujos.validar_flujo(datos)
    if errores:
        for e in errores:
            st.error(e)
    elif editando:
        flujo = flujos.cargar_flujo(editando)
        cred = {"usuario": {"usuario": datos["usuario"], "password": datos["password"] or
                            (flujo["credenciales"].get("usuario") or {}).get("password", "")}}
        if datos["con_admin"]:
            previa = flujo["credenciales"].get("admin") or {}
            cred["admin"] = {"usuario": datos["admin_usuario"],
                             "password": datos["admin_password"] or previa.get("password", "")}
        else:
            cred["admin"] = None
        flujo.update({"nombre": datos["nombre"], "descripcion": datos["descripcion"],
                      "sitio": datos["sitio"], "credenciales": cred,
                      "tipos_auditoria": datos["tipos_auditoria"],
                      "formatos": datos["formatos"], "programacion": datos["programacion"]})
        flujos.guardar_flujo(flujo)
        limpiar_formulario()
        st.success(f"Flujo actualizado: {flujo['nombre']}")
        st.rerun()
    else:
        flujo = flujos.crear_flujo(datos)
        st.success(f"✅ Flujo automático generado y guardado: `{flujo['id']}`")
        st.write(f"**Próxima ejecución:** {flujos.calcular_proxima(flujo):%Y-%m-%d %H:%M}")
        with st.expander("Ver el flujo generado (editable como JSON en data/flujos/)"):
            st.json(flujo)
        limpiar_formulario()

# ------------------------------------------------------------------ gestión de flujos

st.subheader("📋 Flujos automatizados")
todos = flujos.listar_flujos()
if not todos:
    st.info("Aún no hay auditorías automatizadas. Use el formulario de arriba para crear la primera.")
estados_icono = {"activo": "🟢", "pausado": "⏸️", "completado": "🏁"}

for flujo in todos:
    icono = estados_icono.get(flujo.get("estado"), "⚪")
    proxima = flujos.calcular_proxima(flujo)
    encabezado = (f"{icono} {flujo['nombre']} — {flujo['sitio']} "
                  f"({flujos.MODOS.get(flujo['programacion']['modo'], '?')})")
    with st.expander(encabezado):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Estado", flujo.get("estado", "?"))
        c2.metric("Próxima ejecución",
                  f"{proxima:%Y-%m-%d %H:%M}" if proxima else "—")
        c3.metric("Tipos", ", ".join(auditorias_sitio.TIPOS[t] for t in flujo["tipos_auditoria"]))
        c4.metric("Formatos", ", ".join(flujo["formatos"]))
        if flujo.get("descripcion"):
            st.caption(flujo["descripcion"])

        b1, b2, b3, b4, b5 = st.columns(5)
        if b1.button("▶️ Ejecutar ahora", key=f"run_{flujo['id']}"):
            with st.spinner(f"Ejecutando la auditoría real contra {flujo['sitio']} ..."):
                try:
                    resultado = flujos.ejecutar_flujo(flujo["id"])
                    resumen = resultado.get("resumen_cobertura", {})
                    st.success(f"Auditoría completada (nivel: {resultado['nivel_acceso']['nivel']}). "
                               f"Cobertura: {resumen.get('ok', 0)} OK · {resumen.get('parcial', 0)} parcial · "
                               f"{resumen.get('no_disponible', 0)} sin datos · {resumen.get('denegado', 0)} denegados.")
                    st.write(f"Informes en: `{resultado.get('carpeta_informe', '')}` — véalos en la página "
                             "📄 Informes de sitio.")
                except Exception as exc:
                    st.error(f"La ejecución falló: {type(exc).__name__}: {exc}")
        if b2.button("⏸️ Pausar" if flujo.get("estado") == "activo" else "▶️ Reanudar",
                     key=f"pause_{flujo['id']}"):
            flujo["estado"] = "pausado" if flujo.get("estado") == "activo" else "activo"
            flujos.guardar_flujo(flujo)
            st.rerun()
        if b3.button("✏️ Editar", key=f"edit_{flujo['id']}"):
            st.session_state["editar_flujo_id"] = flujo["id"]
            st.session_state.pop("_precargado", None)
            st.rerun()
        confirmar = b4.checkbox("Confirmar", key=f"conf_{flujo['id']}")
        if b5.button("🗑️ Eliminar", key=f"del_{flujo['id']}", disabled=not confirmar):
            flujos.eliminar_flujo(flujo["id"])
            st.rerun()

        if flujo.get("ejecuciones"):
            st.markdown("**Historial de ejecuciones**")
            for e in reversed(flujo["ejecuciones"][-5:]):
                cob = e.get("cobertura", {})
                st.markdown(f"- {e['inicio']} — {e.get('estado')} — nivel {e.get('nivel_acceso')} — "
                            f"OK {cob.get('ok', 0)} · parcial {cob.get('parcial', 0)} · "
                            f"sin datos {cob.get('no_disponible', 0)} · denegados {cob.get('denegado', 0)}")
        else:
            st.caption("Sin ejecuciones registradas todavía.")
        with st.expander("Definición del flujo (JSON)"):
            st.json(flujo)
