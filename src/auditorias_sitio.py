"""Módulos de auditoría sobre un sitio Moodle, con datos reales.

Cada módulo usa solo lo que el sitio entrega realmente (web services o
páginas administrativas). Lo que no se pudo obtener queda registrado en la
cobertura con el motivo exacto devuelto por el sitio: nunca se simulan datos.
"""
import re
import time
from collections import defaultdict

from src import moodle_cliente

TIPOS = {
    "sitio": "Sitio (información general)",
    "cuentas": "Cuentas de usuario",
    "roles": "Roles",
    "permisos": "Permisos",
    "almacenamiento": "Almacenamiento",
    "cuentas_por_areas": "Cuentas por áreas o facultades",
}

DIAS_SIN_ACCESO_ALERTA = 90


def _pares(prefijo, diccionario):
    """Codifica un diccionario como params[i][clave]=valor para web services."""
    return {f"{prefijo}[{k}]": str(v) for k, v in diccionario.items()}


def _limite(seq, cap, etiqueta):
    """Aplica un tope y devuelve (lista, nota de corte o None)."""
    if len(seq) > cap:
        return list(seq[:cap]), (f"se analizaron {cap} de {len(seq)} {etiqueta} "
                                 f"(tope configurado) para no saturar la consulta")
    return list(seq), None


def _fecha(iso):
    """Fecha legible desde un epoch ISO o texto."""
    if iso in (None, "", 0):
        return "nunca"
    try:
        return str(iso)[:10]
    except (TypeError, ValueError):
        return str(iso)


class Contexto:
    """Estado compartido por los módulos de auditoría de un sitio."""

    def __init__(self, url, timeout=30, sesion=None, token=None, caps=None):
        self.url = url
        self.timeout = timeout
        self.sesion = sesion
        self.token = token
        self.caps = caps or {}
        self.max_cursos = int(self.caps.get("max_cursos", 200))
        self.max_usuarios = int(self.caps.get("max_usuarios", 5000))
        self.max_paginas = int(self.caps.get("max_paginas", 50))
        self.max_roles = int(self.caps.get("max_roles", 20))
        self.cobertura = []
        self.secciones = {}
        self.info_sitio = None

    def registrar(self, modulo, seccion, estado, detalle):
        self.cobertura.append({"modulo": modulo, "seccion": seccion,
                               "estado": estado, "detalle": detalle})

    def agregar(self, titulo, descripcion=None, tabla=None, texto=None,
                no_disponible=None, detalle=None):
        self.secciones[titulo] = {"descripcion": descripcion, "tabla": tabla,
                                  "texto": texto, "no_disponible": no_disponible,
                                  "detalle": detalle}

    def ws(self, funcion, params=None, modulo="", seccion=""):
        """Llama un web service; en fallo registra la cobertura y devuelve None."""
        if not self.token:
            self.registrar(modulo, seccion, "no_disponible",
                           "no hay token de web services (login no disponible o servicio deshabilitado)")
            return None
        r = moodle_cliente.llamar_ws(self.url, self.token, funcion, params, self.timeout)
        if r["estado"] != "ok":
            det = f"{funcion}: {r.get('errorcode') or ''} {r.get('mensaje') or ''}".strip()
            self.registrar(modulo, seccion, "denegado" if r["estado"] == "denegado" else "no_disponible", det)
            return None
        return r["datos"]


# --------------------------------------------------------------------------- sitio

def auditar_sitio(ctx):
    """Información general real del sitio: nombre, versión, funciones WS habilitadas."""
    mod = "sitio"
    info = ctx.ws("core_webservice_get_site_info", modulo=mod, seccion="información general")
    ctx.info_sitio = info
    if info:
        tabla = [{"Campo": k, "Valor": str(info[k])} for k in
                 ("sitename", "siteurl", "release", "version", "username", "fullname",
                  "lang", "userid") if k in info]
        funciones = info.get("functions") or []
        if funciones:
            tabla.append({"Campo": "funciones WS habilitadas", "Valor": str(len(funciones))})
        ctx.agregar("Información general del sitio", descripcion="Datos entregados por el propio sitio (core_webservice_get_site_info).",
                    tabla=tabla)
        ctx.registrar(mod, "información general", "ok", f"{len(tabla)} campos obtenidos del sitio")
        return
    # Sin token: solo lo que la conexión ya demostró
    conn = getattr(ctx, "conexion", None) or {}
    lineas = [f"URL probada: {conn.get('url', ctx.url)}",
              f"Título de la página de login: {conn.get('titulo') or '(sin título)'}",
              f"HTTP: {conn.get('http')} — latencia {conn.get('latencia_ms')} ms"]
    for ev in conn.get("evidencias_moodle", []):
        lineas.append(f"Evidencia: {ev}")
    ctx.agregar("Información general del sitio",
                descripcion="Sin token de web services el sitio solo expone esta información pública.",
                texto="\n".join(lineas))
    ctx.registrar(mod, "información general", "parcial",
                  "datos limitados a la página pública de login (sin credenciales válidas no se puede consultar más)")


# --------------------------------------------------------------------------- cuentas

def _cuentas_por_ws(ctx, mod):
    datos = ctx.ws("core_user_get_users", _pares("criteria[0]", {"key": "search", "value": ""}),
                   modulo=mod, seccion="listado de cuentas")
    if datos is None:
        return None
    usuarios = datos.get("users", datos) if isinstance(datos, dict) else datos
    return usuarios or []


def _cuentas_por_cursos(ctx, mod, cursos):
    """Sin privilegios de administrador: cuentas visibles vía matrículas de cursos."""
    if not cursos:
        return None
    cuentas, roles_cuenta = {}, defaultdict(set)
    for c in cursos:
        resp = ctx.ws("core_enrol_get_enrolled_users", {"courseid[0]": c["id"]},
                      modulo=mod, seccion="matrículas de cursos")
        if resp is None:
            continue
        for u in resp:
            uid = u.get("id")
            if uid not in cuentas:
                cuentas[uid] = {"id": uid, "username": u.get("username", ""),
                                "fullname": u.get("fullname", ""), "cursos": set()}
            cuentas[uid]["cursos"].add(c.get("fullname") or c.get("shortname") or c["id"])
            for r in u.get("roles", []) or []:
                roles_cuenta[uid].add(r.get("shortname") or r.get("name") or "")
    return list(cuentas.values()), roles_cuenta


def _scrapear_admin_users(ctx, mod):
    """Con sesión de administrador: páginas reales /admin/user.php."""
    pagina, total, nombres = 0, 0, []
    while pagina < ctx.max_paginas:
        s = moodle_cliente.sondear_pagina(ctx.sesion, ctx.url,
                                          f"/admin/user.php?page={pagina}", ctx.timeout)
        if s["estado"] != "admin_disponible":
            ctx.registrar(mod, "listado de cuentas", "denegado",
                          f"/admin/user.php?page={pagina}: {s.get('evidencia')}")
            return None
        ids = re.findall(r"user/profile\.php\?id=(\d+)", s.get("html", "") or "")
        if not ids:
            break
        total += len(set(ids))
        pagina += 1
    ctx.registrar(mod, "listado de cuentas", "ok",
                  f"{total} cuentas contadas en {pagina} páginas de /admin/user.php "
                  f"(el listado administrativo no expone todos los campos en HTML)")
    return {"total": total}


def auditar_cuentas(ctx):
    mod = "cuentas"
    usuarios = None
    if ctx.token:
        usuarios = _cuentas_por_ws(ctx, mod)
    if usuarios is None and ctx.token:
        # Sin privilegios de administrador: cuentas visibles vía matrículas de cursos
        cursos = _cursos(ctx)
        if cursos:
            muestreo, nota_c = _limite(cursos, ctx.max_cursos, "cursos")
            datos = _cuentas_por_cursos(ctx, mod, muestreo)
            if datos:
                cuentas, roles_cuenta = datos
                lineas = [f"Cuentas obtenidas: {len(cuentas)} (vía matrículas de {len(muestreo)} cursos)",
                          "Método: sin privilegios de administrador el sitio solo expone cuentas "
                          "vinculadas a matrículas; puede omitir cuentas sin cursos"]
                ctx.agregar("Resumen de cuentas", descripcion="Vista limitada calculada desde matrículas de cursos.",
                            texto="\n".join(lineas))
                filas = [{"ID": c["id"], "Usuario": c["username"], "Nombre": c["fullname"],
                          "Cursos": len(c["cursos"]),
                          "Roles observados": ", ".join(sorted(r for r in roles_cuenta[c["id"]] if r)) or "-"}
                         for c in cuentas[:ctx.max_usuarios]]
                ctx.agregar("Listado de cuentas (vía matrículas)", tabla=filas,
                            detalle=nota_c or f"muestreo de {len(muestreo)} cursos")
                ctx.registrar(mod, "listado de cuentas", "parcial",
                              f"{len(cuentas)} cuentas vía matrículas (vista sin administrador)"
                              + (f"; {nota_c}" if nota_c else ""))
                return
    if usuarios is None and ctx.sesion:
        scraping = _scrapear_admin_users(ctx, mod)
        if scraping:
            ctx.agregar("Resumen de cuentas",
                        descripcion="Conteo desde /admin/user.php (sesión de administrador).",
                        texto=f"Cuentas encontradas: {scraping['total']}")
        elif not any(c["modulo"] == mod for c in ctx.cobertura):
            ctx.registrar(mod, "listado de cuentas", "no_disponible",
                          "sin token de web services ni acceso administrativo a /admin/user.php")
        return
    if usuarios is None:
        ctx.registrar(mod, "listado de cuentas", "no_disponible",
                      "requiere credenciales válidas (web services o sesión administrativa)")
        ctx.agregar("Resumen de cuentas", no_disponible="requiere credenciales válidas",
                    detalle="el sitio no entrega cuentas a usuarios anónimos")
        return
    total = len(usuarios)
    suspendidos = sum(1 for u in usuarios if u.get("suspended"))
    no_confirmados = sum(1 for u in usuarios if not u.get("confirmed"))
    sin_acceso = 0
    ahora = time.time()
    for u in usuarios:
        la = float(u.get("lastaccess") or 0)
        if la and (ahora - la) / 86400 > DIAS_SIN_ACCESO_ALERTA:
            sin_acceso += 1
    lineas = [f"Total de cuentas obtenidas del sitio: {total}",
              f"Suspendidas: {suspendidos}", "No confirmadas: " + str(no_confirmados),
              f"Sin acceso hace más de {DIAS_SIN_ACCESO_ALERTA} días: {sin_acceso}"]
    ctx.agregar("Resumen de cuentas", descripcion="Conteos calculados sobre los registros que el sitio devolvió.",
                texto="\n".join(lineas))
    tabla, nota = _limite(usuarios, ctx.max_usuarios, "cuentas")
    filas = [{"ID": u.get("id"), "Usuario": u.get("username", ""), "Nombre": u.get("fullname", ""),
              "Email": u.get("email", ""), "Confirmada": "sí" if u.get("confirmed") else "no",
              "Suspendida": "sí" if u.get("suspended") else "no",
              "Último acceso": _fecha(u.get("lastaccess"))} for u in tabla]
    ctx.agregar("Listado de cuentas", tabla=filas, detalle=nota)
    ctx.registrar(mod, "listado de cuentas", "ok" if nota is None else "parcial",
                  f"{total} cuentas obtenidas vía core_user_get_users" + (f"; {nota}" if nota else ""))


# --------------------------------------------------------------------------- roles

def _roles_definidos_ws(ctx, mod):
    return ctx.ws("core_role_get_roles", modulo=mod, seccion="roles definidos")


def _roles_por_define(ctx, mod):
    s = moodle_cliente.sondear_pagina(ctx.sesion, ctx.url, "/admin/roles/define.php", ctx.timeout)
    if s["estado"] != "admin_disponible":
        ctx.registrar(mod, "roles definidos", "denegado",
                      f"/admin/roles/define.php: {s.get('evidencia')}")
        return None
    pares = re.findall(r'define\.php\?[^"]*roleid=(\d+)[^"]*"[^>]*>([^<]+)<', s.get("html", ""))
    vistos, roles = set(), []
    for rid, nombre in pares:
        if rid not in vistos:
            vistos.add(rid)
            roles.append({"id": rid, "name": nombre.strip()})
    return roles or None


def auditar_roles(ctx):
    mod = "roles"
    roles = None
    if ctx.token:
        roles = _roles_definidos_ws(ctx, mod)
        if roles is None and ctx.sesion:
            roles = _roles_por_define(ctx, mod)
    elif ctx.sesion:
        roles = _roles_por_define(ctx, mod)
    if roles:
        tabla = [{"ID": r.get("id"), "Rol": r.get("name", ""), "Identificador": r.get("shortname", ""),
                  "Arquetipo": r.get("archetype", "") or "-"} for r in roles]
        ctx.agregar("Roles definidos", descripcion="Roles que el sitio declaró.",
                    tabla=tabla)
        ctx.registrar(mod, "roles definidos", "ok", f"{len(roles)} roles obtenidos")
    else:
        ctx.agregar("Roles definidos", no_disponible="el sitio no expuso el listado de roles",
                    detalle="con los accesos disponibles no se obtuvo ningún rol")

    # Uso real de roles: asignaciones observadas en las matrículas de cursos
    cursos = _cursos(ctx)
    if cursos:
        muestreo, nota_cursos = _limite(cursos, ctx.max_cursos, "cursos")
        por_rol = defaultdict(set)      # rol -> ids de usuarios únicos
        asignaciones = defaultdict(int)  # rol -> nº de asignaciones observadas
        cursos_ok = 0
        for c in muestreo:
            resp = ctx.ws("core_enrol_get_enrolled_users", {"courseid[0]": c["id"]},
                          modulo=mod, seccion="asignaciones de roles")
            if resp is None:
                continue
            cursos_ok += 1
            for u in resp:
                for r in u.get("roles", []) or []:
                    clave = r.get("shortname") or r.get("name") or str(r.get("roleid"))
                    por_rol[clave].add(u.get("id"))
                    asignaciones[clave] += 1
        if cursos_ok:
            tabla = [{"Rol": rol, "Usuarios únicos": len(ids), "Asignaciones": asignaciones[rol]}
                     for rol, ids in sorted(por_rol.items(), key=lambda x: -len(x[1]))]
            detalle = f"observado en {cursos_ok} cursos"
            if nota_cursos:
                detalle += f"; {nota_cursos}"
            ctx.agregar("Uso de roles (asignaciones observadas)",
                        descripcion="Roles que aparecen en las matrículas de cursos que el sitio permitió consultar.",
                        tabla=tabla, detalle=detalle)
            ctx.registrar(mod, "asignaciones de roles", "ok", detalle)
        else:
            ctx.registrar(mod, "asignaciones de roles", "no_disponible",
                          "ningún curso permitió consultar matrículas")
    else:
        ctx.registrar(mod, "asignaciones de roles", "no_disponible",
                      "el sitio no entregó el listado de cursos")


# --------------------------------------------------------------------------- permisos

def _permisos_por_pagina(ctx, mod, roles):
    """Con sesión de administrador: cuenta permisos por rol desde la página real
    /admin/roles/permissions.php (valores Moodle: 1 permitir, 0 heredar,
    -1 impedir, -2 prohibir)."""
    tabla = []
    for r in roles[:ctx.max_roles]:
        rid = r.get("id")
        s = moodle_cliente.sondear_pagina(ctx.sesion, ctx.url,
                                          f"/admin/roles/permissions.php?roleid={rid}&contextid=1",
                                          ctx.timeout)
        html = s.get("html", "") or ""
        if s["estado"] != "admin_disponible":
            ctx.registrar(mod, "matriz de permisos", "denegado",
                          f"rol {r.get('name')}: {s.get('evidencia')}")
            return None
        elegidos = re.findall(r'<option value="(-?\d+)"[^>]*selected[^>]*>', html, re.I)
        if not elegidos:
            ctx.registrar(mod, "matriz de permisos", "no_disponible",
                          f"rol {r.get('name')}: la página no tuvo la estructura esperada "
                          f"(el sitio pudo mostrar un error o un formulario distinto)")
            return None
        c = {"permitir": elegidos.count("1"), "heredar": elegidos.count("0"),
             "impedir": elegidos.count("-1"), "prohibir": elegidos.count("-2")}
        tabla.append({"Rol": r.get("name", rid), "Permitir": c["permitir"], "Heredar": c["heredar"],
                      "Impedir": c["impedir"], "Prohibir": c["prohibir"],
                      "Capacidades evaluadas": len(elegidos)})
    return tabla


def auditar_permisos(ctx):
    mod = "permisos"
    aviso = ("La matriz completa de capacidades no está expuesta por web services de Moodle; "
             "los datos solo se pueden obtener desde páginas administrativas con sesión de administrador.")
    roles = None
    if ctx.token:
        roles = _roles_definidos_ws(ctx, mod)
    if roles is None and ctx.sesion:
        roles = _roles_por_define(ctx, mod)
    if not roles:
        ctx.agregar("Matriz de permisos por rol", no_disponible="se requiere sesión de administrador",
                    detalle=aviso)
        ctx.registrar(mod, "matriz de permisos", "no_disponible",
                      "sin roles obtenibles ni sesión administrativa: " + aviso)
        return
    tabla = _permisos_por_pagina(ctx, mod, roles) if ctx.sesion else None
    if tabla:
        ctx.agregar("Matriz de permisos por rol",
                    descripcion="Recuento real de capacidades por rol desde /admin/roles/permissions.php.",
                    tabla=tabla)
        ctx.registrar(mod, "matriz de permisos", "ok",
                      f"permisos contados para {len(tabla)} de {len(roles)} roles")
    else:
        ctx.agregar("Matriz de permisos por rol", no_disponible="el sitio no permitió leer las páginas de permisos",
                    detalle=aviso)


# --------------------------------------------------------------------------- almacenamiento

def _tamanio_curso(curso_id, ctx):
    resp = ctx.ws("core_course_get_contents", {"courseid": curso_id},
                  modulo="almacenamiento", seccion="contenidos de cursos")
    if resp is None:
        return None
    nbytes, narch = 0, 0
    for sec in resp:
        for modu in sec.get("modules", []):
            for cont in modu.get("contents", []) or []:
                if cont.get("type") == "file" or cont.get("filesize"):
                    nbytes += int(cont.get("filesize") or 0)
                    narch += 1
    return nbytes, narch


def auditar_almacenamiento(ctx):
    mod = "almacenamiento"
    cursos = _cursos(ctx)
    if not cursos:
        ctx.agregar("Almacenamiento", no_disponible="el sitio no entregó el listado de cursos",
                    detalle="sin cursos no hay contenidos que medir")
        return
    muestreo, nota = _limite(cursos, ctx.max_cursos, "cursos")
    filas, tot_b, tot_a, ok = [], 0, 0, 0
    for c in muestreo:
        med = _tamanio_curso(c["id"], ctx)
        if not med:
            continue
        ok += 1
        b, a = med
        tot_b += b
        tot_a += a
        filas.append({"Curso": c.get("fullname") or c.get("shortname"), "Archivos": a,
                      "MB": round(b / 1_048_576, 2)})
    if not ok:
        ctx.agregar("Almacenamiento", no_disponible="ningún curso permitió leer sus contenidos",
                    detalle="el sitio rechazó core_course_get_contents para todos los cursos probados")
        return
    detalle = f"medido sobre {ok} de {len(cursos)} cursos"
    if nota:
        detalle += f"; {nota}"
    filas = sorted(filas, key=lambda x: -x["MB"])
    texto = (f"Espacio en archivos de contenidos de cursos: {tot_b / 1_048_576:,.1f} MB "
             f"({tot_a} archivos).\n\n"
             "Alcance real de esta medición: solo archivos publicados como contenidos de cursos. "
             "No incluye copias de seguridad, archivos personales de usuarios, repositorios externos "
             "ni registros del servidor, que Moodle no expone por web services.")
    ctx.agregar("Almacenamiento (contenidos de cursos)", descripcion=detalle, texto=texto)
    ctx.agregar("Cursos por espacio ocupado", tabla=filas[:25],
                detalle="25 cursos mayores; el resto en resultado.json")
    ctx.registrar(mod, "contenidos de cursos", "ok" if ok == len(cursos) else "parcial", detalle)


# --------------------------------------------------------------------------- cuentas por áreas

def auditar_cuentas_por_areas(ctx):
    mod = "cuentas_por_areas"
    categorias = ctx.ws("core_course_get_categories", modulo=mod, seccion="categorías")
    cursos = _cursos(ctx)
    if not cursos:
        ctx.agregar("Cuentas por áreas o facultades",
                    no_disponible="el sitio no entregó cursos ni categorías",
                    detalle="requiere credenciales válidas; sin ellas el sitio no publica la estructura")
        return
    muestreo, nota = _limite(cursos, ctx.max_cursos, "cursos")
    por_cat = defaultdict(lambda: {"cursos": 0, "matriculas": 0, "usuarios": set()})
    sin_categoria = {"cursos": 0, "matriculas": 0, "usuarios": set()}
    for c in muestreo:
        resp = ctx.ws("core_enrol_get_enrolled_users", {"courseid[0]": c["id"]},
                      modulo=mod, seccion="matrículas por curso")
        n, ids = 0, set()
        for u in resp or []:
            n += 1
            ids.add(u.get("id"))
        cat = por_cat[c.get("categoryid")] if c.get("categoryid") is not None else None
        destino = cat if cat is not None else sin_categoria
        destino["cursos"] += 1
        destino["matriculas"] += n
        destino["usuarios"] |= ids
    nombres = {c["id"]: (c.get("name") or c.get("idnumber") or str(c["id"]))
               for c in (categorias or [])}
    padres = {c["id"]: c.get("parent") for c in (categorias or [])}

    def ruta(cid):
        partes = []
        while cid in nombres and cid not in partes:
            partes.append(cid)
            cid = padres.get(cid) or 0
        return " / ".join(nombres[p] for p in reversed(partes)) or str(cid)

    filas = []
    for cid, d in list(por_cat.items()) + ([("sin categoría", sin_categoria)] if sin_categoria["cursos"] else []):
        filas.append({"Área / categoría": ruta(cid) if cid != "sin categoría" else "(sin categoría)",
                      "Cursos": d["cursos"], "Matrículas totales": d["matriculas"],
                      "Usuarios únicos": len(d["usuarios"])})
    filas = sorted(filas, key=lambda x: -x["Usuarios únicos"])
    detalle = f"medido sobre {len(muestreo)} de {len(cursos)} cursos"
    if nota:
        detalle += f"; {nota}"
    ctx.agregar("Cuentas por áreas o facultades",
                descripcion="Las categorías de cursos de Moodle se asumen como áreas o facultades; "
                            "confirme la equivalencia con la organización real.",
                tabla=filas, detalle=detalle)
    ctx.registrar(mod, "categorías y matrículas", "ok" if nota is None else "parcial", detalle)


def _cursos(ctx):
    """Lista de cursos del sitio (una sola llamada por ejecución)."""
    if getattr(ctx, "_cursos_cache", None) is not None:
        return ctx._cursos_cache
    datos = ctx.ws("core_course_get_courses", modulo="cursos", seccion="listado de cursos")
    ctx._cursos_cache = datos or []
    return ctx._cursos_cache


MODULOS = {"sitio": auditar_sitio, "cuentas": auditar_cuentas, "roles": auditar_roles,
           "permisos": auditar_permisos, "almacenamiento": auditar_almacenamiento,
           "cuentas_por_areas": auditar_cuentas_por_areas}


def ejecutar_auditoria(url, tipos, timeout=30, sesion=None, token=None, caps=None,
                       conexion=None, sesiones_login=None):
    """Ejecuta los módulos pedidos sobre el sitio y devuelve el resultado completo.

    `sesiones_login`: dict con los intentos de login ya realizados (para registrar
    la evidencia sin repetirlos). Nunca incluye contraseñas.
    """
    ctx = Contexto(url, timeout=timeout, sesion=sesion, token=token, caps=caps)
    ctx.conexion = conexion or {}
    ctx.sesiones_login = sesiones_login or {}
    ctx._cursos_cache = None
    for tipo in tipos:
        MODULOS[tipo](ctx)
    return {"secciones": ctx.secciones, "cobertura": ctx.cobertura,
            "nivel": ctx.info_sitio}
