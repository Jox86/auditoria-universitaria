"""Cliente HTTP real para sitios Moodle (sin datos simulados).

Cada función devuelve un dict con `estado` y evidencia textual real extraída
del sitio: nunca inventa resultados. Estados posibles:
  ok | credenciales_invalidas | captcha_o_sso | denegado | redirige_login |
  no_disponible | error_auth | error_red | error
"""
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

AGENTE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AuditoriaUniversitaria/1.0")

MARCAS_ADMIN = ["administración del sitio", "site administration", "/admin/search.php",
                "siteadmin", "administracion del sitio"]
MARCAS_LOGIN = ['name="logintoken"', 'name="username"', "/login/index.php"]
MARCAS_DENEGADO = ["accessdenied", "no tiene permiso", "you do not have permission",
                   "acceso no permitido", "nopermatologin", "error/requireslogin"]


def url_base(url):
    """Normaliza la URL del sitio a esquema://host[:puerto] sin barra final."""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL del sitio vacía")
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    return base.rstrip("/")


def _sesion():
    s = requests.Session()
    s.headers["User-Agent"] = AGENTE
    return s


def _texto(html):
    """Extrae texto visible aproximado (para mensajes de error del sitio)."""
    sin_scripts = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "",
                         flags=re.S | re.I)
    texto = re.sub(r"<[^>]+>", " ", sin_scripts)
    return re.sub(r"\s+", " ", texto).strip()


def extraer_logintoken(html):
    """Obtiene el token CSRF del formulario de login de Moodle, si existe."""
    m = re.search(r'name="logintoken"[^>]*value="([^"]+)"', html or "", re.I)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="logintoken"', html or "", re.I)
    return m.group(1) if m else None


def _contiene(html, marcas):
    b = (html or "").lower()
    return any(m.lower() in b for m in marcas)


def probar_conexion(url, timeout=30):
    """Comprueba que el sitio responde y analiza su página de login real."""
    base = url_base(url)
    inicio = datetime.now()
    salida = {"url": base, "ruta_login": "/login/index.php", "http": None,
              "latencia_ms": None, "titulo": None, "logintoken": False,
              "evidencias_moodle": [], "estado": "ok", "error": None}
    try:
        r = _sesion().get(f"{base}/login/index.php", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        salida.update(estado="error_red", error=f"{type(exc).__name__}: {exc}")
        return salida
    salida["latencia_ms"] = int((datetime.now() - inicio).total_seconds() * 1000)
    salida["http"] = r.status_code
    html = r.text
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        salida["titulo"] = _texto(m.group(1))[:200]
    salida["logintoken"] = extraer_logintoken(html) is not None
    if _contiene(html, MARCAS_LOGIN):
        salida["evidencias_moodle"].append("formulario de login estándar de Moodle (/login/index.php)")
    if "/theme/" in html or "/lib/javascript" in html:
        salida["evidencias_moodle"].append("recursos estáticos /theme/ /lib/ de Moodle")
    if _contiene(html, ["moodle"]):
        salida["evidencias_moodle"].append("la página menciona 'Moodle'")
    if r.status_code != 200:
        salida.update(estado="error",
                      error=f"la página de login respondió HTTP {r.status_code}")
    elif not salida["evidencias_moodle"]:
        salida.update(estado="error",
                      error="la página responde pero no presenta evidencias de ser un sitio Moodle")
    return salida


def iniciar_sesion(url, usuario, password, timeout=30, sesion=None):
    """Intenta iniciar sesión real en /login/index.php (maneja logintoken CSRF).

    Devuelve dict con `sesion` (requests.Session autenticada si ok) y el
    mensaje de error textual que el propio sitio mostró, si lo hubo.
    """
    base = url_base(url)
    sesion = sesion or _sesion()
    salida = {"usuario": usuario, "estado": "ok", "mensaje_sitio": None, "sesion": None}
    try:
        r = sesion.get(f"{base}/login/index.php", timeout=timeout)
        datos = {"username": usuario, "password": password, "anchor": ""}
        token = extraer_logintoken(r.text)
        if token:
            datos["logintoken"] = token
        r = sesion.post(f"{base}/login/index.php", data=datos, timeout=timeout,
                        allow_redirects=True)
    except requests.RequestException as exc:
        salida.update(estado="error_red", mensaje_sitio=f"{type(exc).__name__}: {exc}")
        return salida

    html = r.text
    texto = _texto(html)
    if "/login/logout.php" in html:
        salida["sesion"] = sesion
        return salida
    if _contiene(html, MARCAS_LOGIN) and 'name="password"' in html:
        # Volvió al formulario de login: extraer el error exacto que mostró el sitio
        m = re.search(r'class="loginerrors"[^>]*>(.*?)<', html, re.S)
        error = _texto(m.group(1)) if m else None
        if not error and _contiene(html, ["loginerr", "invalid", "incorrecto"]):
            m2 = re.search(r"(?i)(.{0,150}(?:invalid|incorrecto|inválid).{0,150})", texto)
            error = m2.group(1).strip() if m2 else "credenciales rechazadas por el sitio"
        if not error and 'name="password"' not in html:
            salida.update(estado="captcha_o_sso",
                          mensaje_sitio="el sitio presenta un mecanismo adicional (captcha o SSO); "
                                        "no admite inicio de sesión automático con usuario/contraseña")
            return salida
        salida.update(estado="credenciales_invalidas",
                      mensaje_sitio=error or "el sitio devolvió el formulario de login sin error explícito")
        return salida
    if _contiene(html, MARCAS_DENEGADO) or r.status_code in (401, 403):
        salida.update(estado="denegado",
                      mensaje_sitio=f"HTTP {r.status_code}: el sitio denegó el acceso tras autenticar")
        return salida
    # Respuesta sin formulario de login ni logout visible: evidencia ambigua
    salida.update(estado="ok" if r.status_code == 200 else "error",
                  mensaje_sitio=f"HTTP {r.status_code}: el sitio no muestra ni formulario de login "
                                f"ni enlace de cierre de sesión; sesión incierta")
    if r.status_code == 200:
        salida["sesion"] = sesion
    return salida


def obtener_token(url, usuario, password, servicio="moodle_mobile_app", timeout=30):
    """Obtiene un token de web services vía /login/token.php (flujo real de Moodle)."""
    base = url_base(url)
    salida = {"estado": "ok", "token": None, "errorcode": None, "mensaje": None}
    try:
        r = _sesion().post(f"{base}/login/token.php",
                           data={"username": usuario, "password": password, "service": servicio},
                           timeout=timeout)
    except requests.RequestException as exc:
        salida.update(estado="error_red", mensaje=f"{type(exc).__name__}: {exc}")
        return salida
    try:
        d = r.json()
    except ValueError:
        salida.update(estado="error",
                      mensaje=f"HTTP {r.status_code}: /login/token.php no devolvió JSON "
                              f"(¿web services deshabilitados en el sitio?)")
        return salida
    if "token" in d:
        salida["token"] = d["token"]
        return salida
    errorcode = d.get("errorcode", "desconocido")
    salida.update(estado="error_auth" if errorcode == "invalidlogin" else "error",
                  errorcode=errorcode,
                  mensaje=re.sub(r"<[^>]+>", " ", d.get("error", "")).strip() or errorcode)
    return salida


def llamar_ws(url, token, funcion, params=None, timeout=30):
    """Llama una función de web services REST de Moodle. Registra el error real
    del sitio (invalidtoken, accesscontrolexception, nosuchfunction, ...)."""
    base = url_base(url)
    datos = {"wstoken": token, "wsfunction": funcion, "moodlewsrestformat": "json"}
    datos.update(params or {})
    salida = {"funcion": funcion, "estado": "ok", "datos": None,
              "errorcode": None, "mensaje": None}
    try:
        r = _sesion().post(f"{base}/webservice/rest/server.php", data=datos, timeout=timeout)
    except requests.RequestException as exc:
        salida.update(estado="error_red", mensaje=f"{type(exc).__name__}: {exc}")
        return salida
    try:
        d = r.json()
    except ValueError:
        salida.update(estado="error", mensaje=f"HTTP {r.status_code}: respuesta no JSON")
        return salida
    if isinstance(d, dict) and d.get("exception"):
        salida.update(estado="denegado" if d.get("errorcode") == "accesscontrolexception"
                      else "error",
                      errorcode=d.get("errorcode"), mensaje=d.get("message"))
        return salida
    salida["datos"] = d
    return salida


def sondear_pagina(sesion, url, ruta, timeout=30):
    """Clasifica el acceso real a una página del sitio (para sondear páginas de
    administración sin fingir datos): admin_disponible | denegado |
    redirige_login | no_encontrado | error_red | error."""
    salida = {"ruta": ruta, "http": None, "estado": "error", "evidencia": None}
    if sesion is None:
        salida.update(estado="no_disponible", evidencia="sin sesión iniciada")
        return salida
    try:
        r = sesion.get(f"{url_base(url)}{ruta}", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        salida.update(estado="error_red", evidencia=f"{type(exc).__name__}: {exc}")
        return salida
    salida["http"] = r.status_code
    html = r.text
    salida["html"] = html
    if _contiene(html, MARCAS_LOGIN) and 'name="password"' in html:
        salida.update(estado="redirige_login", evidencia="el sitio pide iniciar sesión")
    elif _contiene(html, MARCAS_ADMIN):
        salida.update(estado="admin_disponible", evidencia="la página muestra la administración del sitio")
    elif _contiene(html, MARCAS_DENEGADO) or r.status_code == 403:
        salida.update(estado="denegado", evidencia=f"HTTP {r.status_code}: permiso insuficiente")
    elif r.status_code == 404:
        salida.update(estado="no_encontrado", evidencia="la página no existe en este sitio (plugin no instalado)")
    elif r.status_code == 200:
        salida.update(estado="admin_disponible" if "/admin/" in ruta or "/report/" in ruta
                      else "ok", evidencia=f"HTTP 200")
    else:
        salida.update(estado="error", evidencia=f"HTTP {r.status_code}")
    return salida


def sondear_admin(sesion, url, timeout=30):
    """Sondea páginas de administración reales para detectar nivel de acceso."""
    rutas = ["/admin/index.php", "/admin/user.php", "/admin/roles/define.php"]
    return [sondear_pagina(sesion, url, ruta, timeout) for ruta in rutas]


def detectar_admin_por_sondeo(sondeos):
    """Concluye si hay evidencia de administración a partir de sondeos reales.

    La prueba decisiva es /admin/index.php: un administrador la ve con el
    panel de administración; cualquier otra cuenta recibe un error de
    permisos del propio sitio.
    """
    positivos = [s["ruta"] for s in sondeos if s["estado"] == "admin_disponible"]
    denegados = [s["ruta"] for s in sondeos if s["estado"] == "denegado"]
    puerta = next((s for s in sondeos if s["ruta"] == "/admin/index.php"), None)
    return {"es_admin": puerta is not None and puerta["estado"] == "admin_disponible",
            "paginas_admin_accesibles": positivos, "paginas_denegadas": denegados}
