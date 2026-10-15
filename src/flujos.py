"""Flujos de auditoría automatizada: guardado, programación y ejecución.

Un flujo es un JSON en data/flujos/ con credenciales, tipos, formatos y
programación. Se puede editar, pausar, ejecutar y eliminar desde la interfaz.
Las contraseñas se guardan en texto plano porque la ejecución desatendida las
necesita: la carpeta debe tener permisos restringidos (ver README).
"""
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from src import auditorias_sitio, exportadores, moodle_cliente

CARPETA_DEFECTO = "data/flujos"
LOG = logging.getLogger("flujos")

MODOS = {
    "una_vez": "Un día específico",
    "diaria": "Diaria",
    "cada_n_dias": "Cada N días",
    "semanal": "Semanal",
    "mensual": "Mensual",
    "cada_n_meses": "Cada N meses",
    "anual": "Anual",
}
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def carpeta_flujos(carpeta=None):
    return Path(carpeta) if carpeta else Path(__file__).resolve().parent.parent / CARPETA_DEFECTO


def _ruta(flujo_id, carpeta):
    return carpeta_flujos(carpeta) / f"{flujo_id}.json"


def validar_flujo(datos):
    """Devuelve la lista de errores de validación (vacía si el flujo es válido)."""
    e = []
    if not (datos.get("nombre") or "").strip():
        e.append("Falta el nombre de la auditoría.")
    try:
        moodle_cliente.url_base(datos.get("sitio") or "")
    except (ValueError, AttributeError):
        e.append("URL del sitio inválida o vacía.")
    tipos = datos.get("tipos_auditoria") or []
    desconocidos = [t for t in tipos if t not in auditorias_sitio.TIPOS]
    if not tipos:
        e.append("Seleccione al menos un tipo de auditoría.")
    elif desconocidos:
        e.append(f"Tipos de auditoría desconocidos: {', '.join(desconocidos)}.")
    formatos = datos.get("formatos") or []
    malos = [f for f in formatos if f not in exportadores.FORMATOS]
    if not formatos:
        e.append("Seleccione al menos un formato de entrega.")
    elif malos:
        e.append(f"Formatos desconocidos: {', '.join(malos)}.")

    prog = datos.get("programacion") or {}
    if prog.get("modo") not in MODOS:
        e.append("Modo de programación inválido.")
    else:
        if not re.fullmatch(r"\d{2}:\d{2}", prog.get("hora") or ""):
            e.append("La hora debe tener formato HH:MM (24 h).")
        else:
            h, m = map(int, prog["hora"].split(":"))
            if h > 23 or m > 59:
                e.append("Hora fuera de rango (00:00 a 23:59).")
        if prog["modo"] == "una_vez":
            try:
                datetime.strptime(prog.get("fecha") or "", "%Y-%m-%d")
            except ValueError:
                e.append("Para 'un día específico' indique la fecha (AAAA-MM-DD).")
        if prog["modo"] in ("cada_n_dias", "cada_n_meses"):
            n = prog.get("n")
            if not isinstance(n, int) or n < 1 or n > 365:
                e.append("El intervalo N debe ser un entero entre 1 y 365.")
        if prog["modo"] in ("mensual", "cada_n_meses", "anual"):
            d = prog.get("dia_mes")
            if not isinstance(d, int) or d < 1 or d > 28:
                e.append("El día del mes debe estar entre 1 y 28.")
        if prog["modo"] == "semanal":
            d = prog.get("dia_semana")
            if not isinstance(d, int) or d < 0 or d > 6:
                e.append("Día de la semana inválido (0=lunes … 6=domingo).")
        if prog["modo"] == "anual":
            try:
                datetime.strptime(f"2000-{prog.get('mes', 0):02d}-{prog.get('dia', 0):02d}",
                                  "%Y-%m-%d")
            except ValueError:
                e.append("Para el modo anual indique mes (1-12) y día (1-28/29) válidos.")
    return e


def _gen_id():
    return datetime.now().strftime("fl_%Y%m%d_%H%M%S_") + f"{int(datetime.now().microsecond/1000):04d}"


def crear_flujo(datos, carpeta=None):
    """Valida y crea el flujo (JSON persistente). Lanza ValueError si es inválido."""
    errores = validar_flujo(datos)
    if errores:
        raise ValueError(" ".join(errores))
    ahora = datetime.now().isoformat(timespec="seconds")
    flujo = {
        "id": _gen_id(),
        "nombre": datos["nombre"].strip(),
        "descripcion": (datos.get("descripcion") or "").strip(),
        "creado": ahora,
        "modificado": ahora,
        "sitio": datos["sitio"].strip(),
        "credenciales": {
            "usuario": {"usuario": (datos.get("usuario") or "").strip(),
                        "password": datos.get("password") or ""},
            "admin": ({"usuario": (datos.get("admin_usuario") or "").strip(),
                       "password": datos.get("admin_password") or ""}
                      if datos.get("con_admin") else None),
        },
        "tipos_auditoria": list(datos["tipos_auditoria"]),
        "formatos": list(datos["formatos"]),
        "programacion": dict(datos["programacion"]),
        "estado": "activo",
        "ultima_ejecucion": None,
        "ejecuciones": [],
    }
    carpeta_flujos(carpeta).mkdir(parents=True, exist_ok=True)
    guardar_flujo(flujo, carpeta)
    return flujo


def guardar_flujo(flujo, carpeta=None):
    flujo["modificado"] = datetime.now().isoformat(timespec="seconds")
    ruta = _ruta(flujo["id"], carpeta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(flujo, ensure_ascii=False, indent=2), encoding="utf-8")


def cargar_flujo(flujo_id, carpeta=None):
    ruta = _ruta(flujo_id, carpeta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el flujo {flujo_id}")
    return json.loads(ruta.read_text(encoding="utf-8"))


def listar_flujos(carpeta=None):
    carpeta = carpeta_flujos(carpeta)
    if not carpeta.exists():
        return []
    flujos = []
    for f in sorted(carpeta.glob("fl_*.json"), reverse=True):
        try:
            flujos.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            LOG.warning("Flujo ilegible %s: %s", f.name, exc)
    return flujos


def eliminar_flujo(flujo_id, carpeta=None):
    ruta = _ruta(flujo_id, carpeta)
    if ruta.exists():
        ruta.unlink()


def _hora_dt(fecha, hhmm):
    h, m = map(int, hhmm.split(":"))
    return fecha.replace(hour=h, minute=m, second=0, microsecond=0)


def calcular_proxima(flujo, desde=None):
    """Próxima ejecución (datetime) según la programación, o None si no hay más.

    El punto de partida es la última ejecución (o la creación del flujo) y se
    avanza hasta superar `desde`, para que las ejecuciones perdidas no se
    salten hacia atrás.
    """
    prog = flujo["programacion"]
    modo = prog["modo"]
    desde = desde or datetime.now()
    base_txt = flujo.get("ultima_ejecucion") or flujo["creado"]
    try:
        base = datetime.fromisoformat(base_txt)
    except ValueError:
        base = desde
    hhmm = prog.get("hora") or "02:00"

    if modo == "una_vez":
        try:
            fecha = datetime.strptime(prog["fecha"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            return None
        candidata = _hora_dt(fecha, hhmm)
        return candidata if (candidata > desde and not flujo.get("ultima_ejecucion")) else None
    if modo == "diaria":
        candidata = _hora_dt(desde.date(), hhmm)
        return candidata if candidata > desde else candidata + timedelta(days=1)
    if modo == "cada_n_dias":
        candidata = _hora_dt(base.date(), hhmm)
        while candidata <= desde:
            candidata += timedelta(days=int(prog["n"]))
        return candidata
    if modo == "semanal":
        objetivo = int(prog["dia_semana"])
        candidata = _hora_dt(desde.date() + timedelta(days=(objetivo - desde.weekday()) % 7), hhmm)
        if candidata <= desde:
            candidata += timedelta(days=7)
        return candidata
    if modo in ("mensual", "cada_n_meses"):
        paso = 1 if modo == "mensual" else int(prog["n"])
        y, m = base.year, base.month
        while True:
            candidata = _hora_dt(fecha := datetime(y, m, int(prog["dia_mes"])), hhmm)
            if candidata > desde:
                return candidata
            y, m = (y + (m - 1 + paso) // 12, (m - 1 + paso) % 12 + 1)
    if modo == "anual":
        y = desde.year
        candidata = _hora_dt(datetime(y, int(prog["mes"]), int(prog["dia"])), hhmm)
        if candidata <= desde:
            candidata = _hora_dt(datetime(y + 1, int(prog["mes"]), int(prog["dia"])), hhmm)
        return candidata
    return None


def flujos_vencidos(ahora=None, carpeta=None):
    """Flujos activos cuya próxima ejecución ya venció."""
    ahora = ahora or datetime.now()
    vencidos = []
    for flujo in listar_flujos(carpeta):
        if flujo.get("estado") != "activo":
            continue
        proxima = calcular_proxima(flujo, ahora)
        limite = (datetime.fromisoformat(flujo["ultima_ejecucion"])
                  if flujo.get("ultima_ejecucion") else None)
        if proxima is None:
            continue
        if limite is None or proxima > limite:
            if proxima <= ahora:
                vencidos.append(flujo)
    return vencidos


def _resumen_cobertura(cobertura):
    resumen = {"ok": 0, "parcial": 0, "no_disponible": 0, "denegado": 0}
    for c in cobertura:
        resumen[c["estado"]] = resumen.get(c["estado"], 0) + 1
    return resumen


def ejecutar_flujo(flujo_id, carpeta=None, caps=None):
    """Ejecuta el flujo real: conexión, logins, auditorías e informes.

    Devuelve el resultado estructurado; registra la ejecución en el flujo.
    Nada se simula: cada paso registra lo que el sitio respondió realmente.
    """
    flujo = cargar_flujo(flujo_id, carpeta)
    inicio = datetime.now()
    LOG.info("Ejecutando flujo %s (%s) contra %s", flujo_id, flujo["nombre"], flujo["sitio"])
    url = flujo["sitio"]
    timeout = int((caps or {}).get("timeout_s", 30))
    resultado = {"flujo_id": flujo_id, "nombre": flujo["nombre"], "sitio": url,
                 "generado": inicio.isoformat(timespec="seconds"),
                 "tipos_auditoria": flujo["tipos_auditoria"]}

    # 1) Conexión real
    conexion = moodle_cliente.probar_conexion(url, timeout=timeout)
    resultado["conexion"] = {k: v for k, v in conexion.items() if k != "logintoken"}
    resultado["conexion"]["logintoken_presente"] = conexion.get("logintoken", False)

    cred = flujo.get("credenciales") or {}
    usuario = (cred.get("usuario") or {})
    admin = (cred.get("admin") or {}) if cred.get("admin") else {}
    resultado["acceso"] = {}

    sesion_admin, sesion_usuario, token = None, None, None
    if conexion["estado"] == "ok":
        # 2) Login de administrador (si hay credenciales) y sondeo de páginas admin
        if admin.get("usuario"):
            r = moodle_cliente.iniciar_sesion(url, admin["usuario"], admin.get("password", ""),
                                              timeout=timeout)
            resultado["acceso"]["admin"] = {k: v for k, v in r.items() if k != "sesion"}
            sesion_admin = r.get("sesion")
            if sesion_admin:
                sondeos = moodle_cliente.sondear_admin(sesion_admin, url, timeout=timeout)
                resultado["acceso"]["admin"]["sondeos"] = sondeos
                conclusion = moodle_cliente.detectar_admin_por_sondeo(sondeos)
                resultado["acceso"]["admin"]["evidencia_admin"] = conclusion
                if not conclusion["es_admin"]:
                    resultado["acceso"]["admin"]["advertencia"] = (
                        "las credenciales de administrador iniciaron sesión pero el sitio no mostró "
                        "páginas de administración: la cuenta podría no tener el rol de admin/superadmin")
        # 3) Login del usuario y sondeo con esa sesión (¿tiene permisos de admin?)
        if usuario.get("usuario"):
            r = moodle_cliente.iniciar_sesion(url, usuario["usuario"], usuario.get("password", ""),
                                              timeout=timeout)
            resultado["acceso"]["usuario"] = {k: v for k, v in r.items() if k != "sesion"}
            sesion_usuario = r.get("sesion")
            if sesion_usuario:
                sondeos_u = moodle_cliente.sondear_admin(sesion_usuario, url, timeout=timeout)
                resultado["acceso"]["usuario"]["sondeos"] = sondeos_u
                if moodle_cliente.detectar_admin_por_sondeo(sondeos_u)["es_admin"] and not sesion_admin:
                    sesion_admin = sesion_usuario
                    resultado["acceso"]["usuario"]["nota"] = (
                        "esta cuenta de usuario tiene permisos de administración según las páginas a las que el sitio le dio acceso")
        # 4) Token de web services (prioriza al administrador)
        if admin.get("usuario"):
            r = moodle_cliente.obtener_token(url, admin["usuario"], admin.get("password", ""),
                                             timeout=timeout)
            resultado["acceso"]["token_admin"] = {k: v for k, v in r.items() if k != "token"}
            token = r.get("token")
        if token is None and usuario.get("usuario"):
            r = moodle_cliente.obtener_token(url, usuario["usuario"], usuario.get("password", ""),
                                             timeout=timeout)
            resultado["acceso"]["token_usuario"] = {k: v for k, v in r.items() if k != "token"}
            token = r.get("token")
        if token is None:
            resultado["acceso"]["web_services"] = {
                "estado": "no_disponible",
                "detalle": "ninguna credencial obtuvo token (credenciales inválidas o web services "
                           "deshabilitados para el servicio moodle_mobile_app)"}
    else:
        resultado["acceso"]["conectividad"] = {
            "estado": "error_red",
            "detalle": f"no se pudo alcanzar la página de login: {conexion.get('error')}"}

    nivel = "admin" if sesion_admin else ("usuario" if sesion_usuario else "anonimo")
    resultado["nivel_acceso"] = {"nivel": nivel,
                                 "detalle": "admin: sesión con páginas de administración disponibles; "
                                            "usuario: sesión sin privilegios; anónimo: sin credenciales válidas"}

    # 5) Auditorías con lo que realmente se pudo acceder
    if conexion["estado"] == "ok":
        aud = auditorias_sitio.ejecutar_auditoria(
            url, flujo["tipos_auditoria"], timeout=timeout,
            sesion=sesion_admin or sesion_usuario, token=token,
            caps=caps, conexion=conexion, sesiones_login=resultado["acceso"])
        resultado.update(aud)
    else:
        resultado["secciones"] = {}
        resultado["cobertura"] = [{"modulo": "conectividad", "seccion": "todo",
                                   "estado": "no_disponible",
                                   "detalle": f"sitio inalcanzable: {conexion.get('error')}"}]

    # 6) Informes en los formatos pedidos
    cfg_caps = caps or {}
    carpeta_base = (Path(carpeta).resolve().parent if carpeta
                    else Path(__file__).resolve().parent.parent)
    carpeta_inf = carpeta_base / "data" / "informes" / "auditorias_sitio" / flujo_id \
        / inicio.strftime("%Y%m%d_%H%M%S")
    generados = exportadores.exportar_resultado(resultado, carpeta_inf, flujo["formatos"])
    resultado["informes"] = generados

    # 7) Registrar ejecución en el flujo (sin contraseñas)
    fin = datetime.now()
    resumen = _resumen_cobertura(resultado["cobertura"])
    ejecucion = {"inicio": inicio.isoformat(timespec="seconds"),
                 "fin": fin.isoformat(timespec="seconds"),
                 "estado": "completada",
                 "nivel_acceso": nivel,
                 "cobertura": resumen,
                 "informes": generados}
    flujo.setdefault("ejecuciones", []).append(ejecucion)
    flujo["ejecuciones"] = flujo["ejecuciones"][-20:]
    flujo["ultima_ejecucion"] = fin.isoformat(timespec="seconds")
    if flujo["programacion"]["modo"] == "una_vez":
        flujo["estado"] = "completado"
    guardar_flujo(flujo, carpeta)
    resultado["carpeta_informe"] = str(carpeta_inf)
    resultado["resumen_cobertura"] = resumen
    LOG.info("Flujo %s terminado: cobertura %s", flujo_id, resumen)
    return resultado
