"""Pruebas de exportadores: los seis formatos a partir de un resultado real
estructurado (sin red)."""
import json
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import exportadores  # noqa: E402


def _resultado():
    return {
        "flujo_id": "fl_demo", "nombre": "Auditoría demo", "sitio": "https://evea.uh.cu",
        "generado": "2026-10-15T09:00:00",
        "conexion": {"http": 200, "latencia_ms": 340, "titulo": "EVeA: Entrar al sitio",
                     "estado": "ok", "error": None},
        "acceso": {"usuario": {"estado": "ok"}},
        "nivel_acceso": {"nivel": "admin"},
        "secciones": {
            "Resumen de cuentas": {"descripcion": "Sobre los registros que el sitio devolvió.",
                                   "texto": "Total de cuentas: 2",
                                   "tabla": [{"Usuario": "ana", "Suspendida": "no"},
                                             {"Usuario": "luis", "Suspendida": "sí"}],
                                   "detalle": None, "no_disponible": None},
            "Matriz de permisos por rol": {"descripcion": None, "texto": None, "tabla": None,
                                           "detalle": "requiere sesión de administrador",
                                           "no_disponible": "el sitio no expuso la matriz"},
        },
        "cobertura": [{"modulo": "cuentas", "seccion": "listado", "estado": "ok", "detalle": "2 cuentas"},
                      {"modulo": "permisos", "seccion": "matriz", "estado": "no_disponible",
                       "detalle": "requiere sesión de administrador"}],
    }


def test_exporta_los_seis_formatos(tmp_path):
    carpeta = tmp_path / "informe"
    generados = exportadores.exportar_resultado(_resultado(), carpeta,
                                                ["json", "md", "html", "pdf", "xlsx", "csv"])
    nombres = {g["archivo"] for g in generados}
    assert {"resultado.json", "informe.md", "informe.html", "informe.pdf",
            "informe.xlsx", "resumen-de-cuentas.csv"} <= nombres

    md = (carpeta / "informe.md").read_text(encoding="utf-8")
    assert "## Cobertura de la auditoría" in md
    assert "DATO NO DISPONIBLE" in md
    assert "| Usuario | Suspendida |" in md

    html = (carpeta / "informe.html").read_text(encoding="utf-8")
    assert "meta charset='utf-8'" in html and "<table>" in html

    assert (carpeta / "informe.pdf").stat().st_size > 200

    wb = openpyxl.load_workbook(carpeta / "informe.xlsx")
    assert {"Resumen", "Cobertura", "Resumen de cuentas"} <= set(wb.sheetnames)
    assert wb["Cobertura"]["A2"].value == "cuentas"

    csv_texto = (carpeta / "resumen-de-cuentas.csv").read_text(encoding="utf-8-sig")
    assert "Usuario" in csv_texto and "ana" in csv_texto

    resultado_json = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
    assert resultado_json["cobertura"][1]["estado"] == "no_disponible"


def test_formato_fallido_no_tumba_el_informe(tmp_path, monkeypatch):
    def pdf_roto(resultado):
        raise RuntimeError("fpdf no disponible")

    monkeypatch.setattr(exportadores, "a_pdf", pdf_roto)
    resultado = _resultado()
    generados = exportadores.exportar_resultado(resultado, tmp_path, ["pdf", "md"])
    assert {"resultado.json", "informe.md"} <= {g["archivo"] for g in generados}
    assert any("pdf" in e for e in resultado["errores_exportacion"])


def test_secciones_sin_tabla_no_generan_csv(tmp_path):
    r = _resultado()
    r["secciones"]["Resumen de cuentas"]["tabla"] = None
    generados = exportadores.exportar_resultado(r, tmp_path, ["csv"])
    assert [g["archivo"] for g in generados] == ["resultado.json"]
