"""Prueba real del sistema contra un sitio Moodle (por defecto evea.uh.cu).

No simula datos ni procedimientos: ejecuta el flujo completo real
(conexión -> login -> token -> auditorías -> informes) y reporta con
honestidad lo que el sitio respondió, incluido lo que no se pudo obtener.

Uso:
    python scripts/prueba_real.py
        Diagnóstico completo sin credenciales (anónimo): conectividad,
        comportamiento del login, web services y cobertura de datos.

    python scripts/prueba_real.py --usuariojuan@uh.cu --password SECRETA
        Prueba con una cuenta de usuario real.

    python scripts/prueba_real.py --usuario X --password Y --admin-usuario A --admin-password B
        Prueba completa: si la cuenta de admin tiene permisos, la auditoría
        cubre cuentas, roles, permisos, almacenamiento y áreas.

Otras opciones: --url, --tipos cuentas,roles,... --formatos xlsx,md,... --timeout N.
Los informes se guardan en data/informes/prueba_real/<fecha_hora>/.

Códigos de salida: 0 sistema funcionó (aunque el acceso fuera limitado),
2 sitio inalcanzable, 1 error interno del sistema.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src import auditorias_sitio, exportadores, moodle_cliente  # noqa: E402

try:  # consola Windows con acentos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

URL_DEFECTO = "https://evea.uh.cu"


def paso(titulo):
    print(f"\n=== {titulo} " + "=" * max(0, 60 - len(titulo)))


def linea(estado, texto):
    marcas = {"ok": "[OK]            ", "parcial": "[PARCIAL]       ",
              "denegado": "[SIN PERMISO]   ", "no_disponible": "[NO DISPONIBLE] ",
              "credenciales_invalidas": "[CRED. INVALIDAS]",
              "error_auth": "[ERROR AUTH]    ", "error_red": "[ERROR RED]     ",
              "error": "[ERROR]         ", "info": "[INFO]          "}
    print(f" {marcas.get(estado, '[?]             ')} {texto}")


def main():
    ap = argparse.ArgumentParser(description="Prueba real del sistema de auditoría de sitios Moodle.")
    ap.add_argument("--url", default=URL_DEFECTO, help=f"sitio a auditar (defecto: {URL_DEFECTO})")
    ap.add_argument("--usuario", default=os.environ.get("AUDIT_USUARIO", ""),
                    help="cuenta de usuario (o variable de entorno AUDIT_USUARIO)")
    ap.add_argument("--password", default=os.environ.get("AUDIT_PASSWORD", ""),
                    help="contraseña (o variable de entorno AUDIT_PASSWORD)")
    ap.add_argument("--admin-usuario", default=os.environ.get("AUDIT_ADMIN_USUARIO", ""),
                    help="cuenta de administrador/superadmin (opcional)")
    ap.add_argument("--admin-password", default=os.environ.get("AUDIT_ADMIN_PASSWORD", ""),
                    help="contraseña del administrador (opcional)")
    ap.add_argument("--tipos", default=",".join(auditorias_sitio.TIPOS),
                    help=f"tipos de auditoría separados por coma ({','.join(auditorias_sitio.TIPOS)})")
    ap.add_argument("--formatos", default="xlsx,md",
                    help="formatos de informe: xlsx,pdf,md,html,csv,json (defecto: xlsx,md)")
    ap.add_argument("--timeout", type=int, default=30, help="segundos de espera por petición")
    args = ap.parse_args()

    tipos = [t.strip() for t in args.tipos.split(",") if t.strip()]
    formatos = [f.strip() for f in args.formatos.split(",") if f.strip()]
    print("PRUEBA REAL DEL SISTEMA — sin datos simulados")
    print(f"Sitio: {args.url} (login: /login/index.php)")
    cred_info = (f"credenciales: usuario={args.usuario or '(ninguna)'}; "
                 f"admin={args.admin_usuario or '(ninguno)'}")
    print(cred_info)

    # 1) Conexión real al login
    paso("1. Conexión al sitio")
    conexion = moodle_cliente.probar_conexion(args.url, timeout=args.timeout)
    linea(conexion["estado"], f"HTTP {conexion['http']} — latencia {conexion['latencia_ms']} ms — "
                              f"título: {conexion['titulo']!r}" if conexion["http"] else "sin respuesta")
    for ev in conexion["evidencias_moodle"]:
        linea("info", f"evidencia de Moodle: {ev}")
    if conexion["estado"] != "ok":
        linea(conexion["estado"], conexion["error"])
        print("\nEl sitio no está accesible; no se puede continuar con datos reales.")
        _guardar({"conexion": conexion}, formatos)
        return 2

    # 2) Login real (solo si hay credenciales)
    sesion_admin, sesion_usuario, token = None, None, None
    resultado_acceso = {}
    if args.admin_usuario:
        paso("2. Inicio de sesión del administrador")
        r = moodle_cliente.iniciar_sesion(args.url, args.admin_usuario, args.admin_password,
                                          timeout=args.timeout)
        resultado_acceso["admin"] = {k: v for k, v in r.items() if k != "sesion"}
        linea(r["estado"], r.get("mensaje_sitio") or "sesión iniciada según la respuesta del sitio")
        sesion_admin = r.get("sesion")
        if sesion_admin:
            sondeos = moodle_cliente.sondear_admin(sesion_admin, args.url, timeout=args.timeout)
            resultado_acceso["admin"]["sondeos"] = sondeos
            conclusion = moodle_cliente.detectar_admin_por_sondeo(sondeos)
            resultado_acceso["admin"]["evidencia_admin"] = conclusion
            if conclusion["es_admin"]:
                linea("ok", "el sitio dio acceso a las páginas de administración: cuenta admin confirmada")
            else:
                linea("denegado", "la cuenta inició sesión pero NO tiene páginas de administración "
                                  "accesibles: la auditoría completa no podrá realizarse")
    if args.usuario:
        paso("3. Inicio de sesión del usuario")
        r = moodle_cliente.iniciar_sesion(args.url, args.usuario, args.password, timeout=args.timeout)
        resultado_acceso["usuario"] = {k: v for k, v in r.items() if k != "sesion"}
        linea(r["estado"], r.get("mensaje_sitio") or "sesión iniciada según la respuesta del sitio")
        sesion_usuario = r.get("sesion")
        if sesion_usuario:
            sondeos_u = moodle_cliente.sondear_admin(sesion_usuario, args.url, timeout=args.timeout)
            resultado_acceso["usuario"]["sondeos"] = sondeos_u
            if moodle_cliente.detectar_admin_por_sondeo(sondeos_u)["es_admin"] and not sesion_admin:
                sesion_admin = sesion_usuario
                linea("ok", "esta cuenta de usuario también tiene permisos de administración")
    elif not args.admin_usuario:
        paso("2. Credenciales")
        linea("info", "sin credenciales no hay login: se ejecuta el diagnóstico anónimo "
                      "(las auditorías quedan marcadas como no disponibles con su motivo)")

    # 3) Web services
    paso("4. Web services (token)")
    if args.admin_usuario:
        r = moodle_cliente.obtener_token(args.url, args.admin_usuario, args.admin_password,
                                         timeout=args.timeout)
        resultado_acceso["token_admin"] = {k: v for k, v in r.items() if k != "token"}
        token = r.get("token")
        linea(r["estado"], (r.get("errorcode") or "token obtenido para la cuenta de admin")
              + (f" — {r.get('mensaje')}" if r.get("mensaje") else ""))
    if token is None and args.usuario:
        r = moodle_cliente.obtener_token(args.url, args.usuario, args.password, timeout=args.timeout)
        resultado_acceso["token_usuario"] = {k: v for k, v in r.items() if k != "token"}
        token = r.get("token")
        linea(r["estado"], (r.get("errorcode") or "token obtenido para la cuenta de usuario")
              + (f" — {r.get('mensaje')}" if r.get("mensaje") else ""))
    if token is None:
        linea("no_disponible", "sin token: los datos se obtendrán solo de páginas web accesibles "
                               "o quedarán como no disponibles")

    # 4) Auditorías reales
    paso("5. Auditoría del sitio (datos reales)")
    nivel = "admin" if sesion_admin else ("usuario" if sesion_usuario else "anonimo")
    print(f" Nivel de acceso real: {nivel}")
    aud = auditorias_sitio.ejecutar_auditoria(
        args.url, tipos, timeout=args.timeout, sesion=sesion_admin or sesion_usuario,
        token=token, conexion=conexion, sesiones_login=resultado_acceso)

    # 5) Cobertura honesta
    paso("6. Cobertura de la auditoría")
    for c in aud["cobertura"]:
        linea(c["estado"], f"{c['modulo']} / {c['seccion']}: {c['detalle']}")
    secciones_nd = [t for t, s in aud["secciones"].items() if s.get("no_disponible")]
    if secciones_nd:
        print("\n Secciones sin datos porque el sitio no los entregó: " + ", ".join(secciones_nd))
        print(" (no se simulan: el informe las declara con el motivo real)")

    # 6) Informes
    paso("7. Informes")
    resultado = {"flujo_id": "prueba_real", "nombre": "Prueba real del sistema",
                 "sitio": args.url, "generado": datetime.now().isoformat(timespec="seconds"),
                 "conexion": conexion, "acceso": resultado_acceso,
                 "nivel_acceso": {"nivel": nivel},
                 "secciones": aud["secciones"], "cobertura": aud["cobertura"]}
    carpeta = RAIZ / "data" / "informes" / "prueba_real" / datetime.now().strftime("%Y%m%d_%H%M%S")
    generados = exportadores.exportar_resultado(resultado, carpeta, formatos)
    for g in generados:
        linea("ok", f"informe {g['formato']}: {g['ruta']}")
    print("\nRESULTADO: el sistema se ejecutó de principio a fin con datos reales."
          if aud["cobertura"] else "RESULTADO: el sistema se ejecutó pero el sitio no entregó datos.")
    return 0


def _guardar(resultado, formatos):
    carpeta = RAIZ / "data" / "informes" / "prueba_real" / datetime.now().strftime("%Y%m%d_%H%M%S")
    exportadores.exportar_resultado(resultado, carpeta, formatos)
    print(f" Evidencia del fallo guardada en: {carpeta}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # error del sistema: reportarlo, no ocultarlo
        print(f"\n[ERROR] Fallo interno del sistema: {type(exc).__name__}: {exc}")
        sys.exit(1)
