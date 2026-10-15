"""Pruebas del cliente Moodle que no requieren red: análisis de HTML real y
clasificación de respuestas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import moodle_cliente  # noqa: E402

LOGIN_HTML = """
<html><head><title>EVeA: Entrar al sitio</title></head>
<body><form action="https://evea.uh.cu/login/index.php" method="post" id="login">
<input type="hidden" name="logintoken" value="abc123def456">
<input type="text" name="username" value="">
<input type="password" name="password" value="">
</form></body></html>
"""

LOGIN_ERROR_HTML = """
<html><body>
<div class="loginerrors">Nombre de usuario o contraseña incorrectos. Vuelva a intentarlo.</div>
<form action="/login/index.php" method="post" id="login">
<input type="hidden" name="logintoken" value="xyz789">
<input type="text" name="username" value="">
<input type="password" name="password" value="">
</form></body></html>
"""


def test_url_base_normaliza():
    assert moodle_cliente.url_base("https://evea.uh.cu/login/index.php") == "https://evea.uh.cu"
    assert moodle_cliente.url_base("evea.uh.cu") == "https://evea.uh.cu"
    assert moodle_cliente.url_base("http://host.local:8080/") == "http://host.local:8080"


def test_extraer_logintoken():
    assert moodle_cliente.extraer_logintoken(LOGIN_HTML) == "abc123def456"
    assert moodle_cliente.extraer_logintoken(LOGIN_ERROR_HTML) == "xyz789"
    assert moodle_cliente.extraer_logintoken("<html>sin formulario</html>") is None


def test_texto_extrae_mensaje_del_sitio():
    texto = moodle_cliente._texto(LOGIN_ERROR_HTML)
    assert "Nombre de usuario o contraseña incorrectos" in texto
    assert "<div" not in texto


def test_deteccion_admin_por_sondeo():
    admin = [{"ruta": "/admin/index.php", "estado": "admin_disponible", "evidencia": ""},
             {"ruta": "/admin/user.php", "estado": "admin_disponible", "evidencia": ""}]
    usuario = [{"ruta": "/admin/index.php", "estado": "denegado", "evidencia": "HTTP 403"}]
    anonimo = [{"ruta": "/admin/index.php", "estado": "no_disponible", "evidencia": "sin sesión"}]
    assert moodle_cliente.detectar_admin_por_sondeo(admin)["es_admin"] is True
    assert moodle_cliente.detectar_admin_por_sondeo(usuario)["es_admin"] is False
    assert moodle_cliente.detectar_admin_por_sondeo(anonimo)["es_admin"] is False
