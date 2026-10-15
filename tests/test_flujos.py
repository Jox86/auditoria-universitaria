"""Pruebas de flujos: validación, programación y CRUD (sin red)."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import flujos  # noqa: E402


def _datos(**cambios):
    datos = {
        "nombre": "Auditoría de prueba",
        "sitio": "https://evea.uh.cu",
        "usuario": "auditor", "password": "secreta", "con_admin": False,
        "admin_usuario": "", "admin_password": "",
        "tipos_auditoria": ["sitio", "cuentas"],
        "formatos": ["xlsx", "md"],
        "programacion": {"modo": "diaria", "hora": "02:00"},
    }
    datos.update(cambios)
    return datos


def _flujo(tmp_path, **cambios):
    return flujos.crear_flujo(_datos(**cambios), carpeta=tmp_path)


# ------------------------------------------------------------------ validación

def test_flujo_valido_no_genera_errores():
    assert flujos.validar_flujo(_datos()) == []


@pytest.mark.parametrize("cambios,fragmento", [
    ({"nombre": ""}, "nombre"),
    ({"sitio": "no es una url ///"}, "URL"),
    ({"tipos_auditoria": []}, "tipo de auditoría"),
    ({"tipos_auditoria": ["inexistente"]}, "desconocidos"),
    ({"formatos": ["docx"]}, "Formatos desconocidos"),
    ({"programacion": {"modo": "raro", "hora": "02:00"}}, "programación"),
    ({"programacion": {"modo": "diaria", "hora": "25:00"}}, "Hora"),
    ({"programacion": {"modo": "una_vez", "hora": "02:00"}}, "fecha"),
    ({"programacion": {"modo": "semanal", "hora": "02:00", "dia_semana": 9}}, "semana"),
    ({"programacion": {"modo": "mensual", "hora": "02:00", "dia_mes": 40}}, "día del mes"),
])
def test_validacion_detecta_errores(cambios, fragmento):
    errores = flujos.validar_flujo(_datos(**cambios))
    assert any(fragmento.lower() in e.lower() for e in errores)


# ------------------------------------------------------------------ programación

def _f(prog, creado="2026-01-10T00:00:00", ultima=None):
    return {"id": "x", "creado": creado, "ultima_ejecucion": ultima, "programacion": prog}


def test_diaria_avanza_al_siguiente_dia():
    f = _f({"modo": "diaria", "hora": "02:00"})
    assert flujos.calcular_proxima(f, datetime(2026, 10, 15, 3, 0)) == datetime(2026, 10, 16, 2, 0)
    assert flujos.calcular_proxima(f, datetime(2026, 10, 15, 1, 0)) == datetime(2026, 10, 15, 2, 0)


def test_cada_dos_dias_desde_la_creacion():
    f = _f({"modo": "cada_n_dias", "hora": "08:00", "n": 2})
    assert flujos.calcular_proxima(f, datetime(2026, 1, 10, 9, 0)) == datetime(2026, 1, 12, 8, 0)


def test_semanal_elige_el_dia_correcto():
    f = _f({"modo": "semanal", "hora": "08:00", "dia_semana": 0})  # lunes
    assert flujos.calcular_proxima(f, datetime(2026, 10, 9, 12, 0)) == datetime(2026, 10, 12, 8, 0)


def test_mensual_y_cada_dos_meses():
    f = _f({"modo": "mensual", "hora": "02:00", "dia_mes": 15})
    assert flujos.calcular_proxima(f, datetime(2026, 10, 15, 5, 0)) == datetime(2026, 11, 15, 2, 0)
    f2 = _f({"modo": "cada_n_meses", "hora": "02:00", "dia_mes": 10, "n": 2})
    assert flujos.calcular_proxima(f2, datetime(2026, 1, 11, 0, 0)) == datetime(2026, 3, 10, 2, 0)


def test_anual_y_una_vez():
    f = _f({"modo": "anual", "hora": "09:00", "mes": 3, "dia": 5})
    assert flujos.calcular_proxima(f, datetime(2026, 10, 15, 0, 0)) == datetime(2027, 3, 5, 9, 0)
    f2 = _f({"modo": "una_vez", "hora": "09:00", "fecha": "2026-12-24"})
    assert flujos.calcular_proxima(f2, datetime(2026, 10, 15, 0, 0)) == datetime(2026, 12, 24, 9, 0)
    # pasado o ya ejecutado: no vuelve a programarse
    f3 = _f({"modo": "una_vez", "hora": "09:00", "fecha": "2025-12-24"})
    assert flujos.calcular_proxima(f3, datetime(2026, 10, 15, 0, 0)) is None
    f4 = _f({"modo": "una_vez", "hora": "09:00", "fecha": "2026-12-24"}, ultima="2026-12-24T09:00:00")
    assert flujos.calcular_proxima(f4, datetime(2026, 12, 25, 0, 0)) is None


def test_flujos_vencidos_solo_activos_y_vencidos(tmp_path):
    vencido = _flujo(tmp_path)
    vencido["ultima_ejecucion"] = "2020-01-01T02:00:00"
    flujos.guardar_flujo(vencido, tmp_path)
    pausado = _flujo(tmp_path, nombre="Pausada")
    pausado["estado"] = "pausado"
    flujos.guardar_flujo(pausado, tmp_path)
    futuro = _flujo(tmp_path, nombre="Futura",
                    programacion={"modo": "una_vez", "hora": "02:00",
                                  "fecha": "2999-01-01"})
    ids = {f["id"] for f in flujos.flujos_vencidos(carpeta=tmp_path)}
    assert vencido["id"] in ids and futuro["id"] not in ids and pausado["id"] not in ids


# ------------------------------------------------------------------ CRUD

def test_crear_cargar_listar_eliminar(tmp_path):
    flujo = _flujo(tmp_path)
    ruta = tmp_path / f"{flujo['id']}.json"
    assert ruta.exists()
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["credenciales"]["usuario"]["password"] == "secreta"
    assert flujos.cargar_flujo(flujo["id"], tmp_path)["nombre"] == "Auditoría de prueba"
    assert len(flujos.listar_flujos(tmp_path)) == 1
    assert flujos.calcular_proxima(flujo) is not None
    flujos.eliminar_flujo(flujo["id"], tmp_path)
    assert flujos.listar_flujos(tmp_path) == []
    with pytest.raises(FileNotFoundError):
        flujos.cargar_flujo(flujo["id"], tmp_path)


def test_crear_rechaza_flujo_invalido(tmp_path):
    with pytest.raises(ValueError):
        flujos.crear_flujo(_datos(sitio=""), carpeta=tmp_path)
    assert flujos.listar_flujos(tmp_path) == []


def test_flujo_sin_credenciales_es_valido(tmp_path):
    """El usuario puede no tener credenciales: el flujo se crea y la ejecución
    posterior registrará honestamente el modo anónimo."""
    flujo = _flujo(tmp_path, usuario="", password="")
    assert flujo["credenciales"]["usuario"]["usuario"] == ""


def test_ejecucion_con_sitio_inalcanzable(tmp_path, monkeypatch):
    """Con el sitio caído la ejecución debe completar el ciclo, registrar la
    cobertura como no disponible y guardar la evidencia (sin fingir datos)."""
    from src import moodle_cliente

    def conexion_falsa(url, timeout=30):
        return {"url": url, "estado": "error_red", "error": "fallo de red (prueba unitaria)",
                "http": None, "latencia_ms": None, "titulo": None,
                "logintoken": False, "evidencias_moodle": []}

    monkeypatch.setattr(moodle_cliente, "probar_conexion", conexion_falsa)
    flujo = _flujo(tmp_path)
    resultado = flujos.ejecutar_flujo(flujo["id"], carpeta=tmp_path)
    assert resultado["cobertura"][0]["estado"] == "no_disponible"
    assert resultado["nivel_acceso"]["nivel"] == "anonimo"
    assert all(s.get("no_disponible") or s.get("texto") or s.get("tabla")
               for s in resultado["secciones"].values())
    f = flujos.cargar_flujo(flujo["id"], tmp_path)
    assert f["ejecuciones"][0]["estado"] == "completada"
    assert f["ultima_ejecucion"] is not None
    assert Path(resultado["carpeta_informe"], "resultado.json").exists()
