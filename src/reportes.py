"""Generación de reportes en JSON, Markdown, HTML y PDF."""
import html
import json
from datetime import datetime


def informe_a_markdown(informe):
    """Convierte el informe estructurado a Markdown."""
    L = ["# Informe de Auditoría", ""]
    meta = informe.get("metadatos", {})
    if meta:
        L.append(f"*Generado:* {meta.get('generado', '')} — *Origen:* {meta.get('origen', '')}")
        L.append("")
    L += ["## Resumen ejecutivo", "", str(informe.get("resumen_ejecutivo", "")), ""]
    L += ["## Hallazgos", ""]
    for h in informe.get("hallazgos", []):
        if isinstance(h, dict):
            L.append(f"- **{h.get('titulo', '')}**: {h.get('descripcion', '')}"
                     + (f" _(evidencia: {h['evidencia']})_" if h.get("evidencia") else ""))
        else:
            L.append(f"- {h}")
    L += ["", "## Riesgos", ""]
    for r in informe.get("riesgos", []):
        if isinstance(r, dict):
            L.append(f"- **{r.get('riesgo', '')}** [{r.get('nivel', '')}]: {r.get('descripcion', '')}")
        else:
            L.append(f"- {r}")
    L += ["", "## Recomendaciones", ""]
    L += [f"{i}. {x}" for i, x in enumerate(informe.get("recomendaciones", []), 1)]
    return "\n".join(L) + "\n"


def informe_a_html(informe, tablas=None, figuras=None):
    """HTML autónomo. `tablas`: dict titulo->DataFrame; `figuras`: dict titulo->figura Plotly."""
    e = html.escape
    partes = ["<html><head><meta charset='utf-8'><title>Informe de Auditoría</title>"
              "<style>body{font-family:sans-serif;max-width:900px;margin:2em auto}"
              "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}"
              "</style></head><body>", "<h1>Informe de Auditoría</h1>",
              f"<h2>Resumen ejecutivo</h2><p>{e(str(informe.get('resumen_ejecutivo', '')))}</p>",
              "<h2>Hallazgos</h2><ul>"]
    for h in informe.get("hallazgos", []):
        partes.append("<li>" + (f"<b>{e(str(h.get('titulo', '')))}</b>: {e(str(h.get('descripcion', '')))}"
                                if isinstance(h, dict) else e(str(h))) + "</li>")
    partes.append("</ul><h2>Riesgos</h2><ul>")
    for r in informe.get("riesgos", []):
        partes.append("<li>" + (f"<b>{e(str(r.get('riesgo', '')))}</b> [{e(str(r.get('nivel', '')))}]: "
                                f"{e(str(r.get('descripcion', '')))}" if isinstance(r, dict) else e(str(r))) + "</li>")
    partes.append("</ul><h2>Recomendaciones</h2><ol>")
    partes += [f"<li>{e(str(x))}</li>" for x in informe.get("recomendaciones", [])]
    partes.append("</ol>")
    for titulo, df in (tablas or {}).items():
        partes.append(f"<h2>{e(titulo)}</h2>" + df.to_html(index=False, float_format="{:,.2f}".format))
    for i, (titulo, fig) in enumerate((figuras or {}).items()):
        partes.append(f"<h2>{e(titulo)}</h2>" +
                      fig.to_html(full_html=False, include_plotlyjs="inline" if i == 0 else False))
    partes.append("</body></html>")
    return "\n".join(partes)


def informe_a_pdf(informe):
    """Genera un PDF (bytes) simple con fpdf2."""
    from fpdf import FPDF

    def t(s):  # fpdf core fonts solo admiten latin-1
        return str(s).encode("latin-1", "replace").decode("latin-1")

    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, t("Informe de Auditoria"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, t(f"Generado: {datetime.now():%Y-%m-%d %H:%M}"), new_x="LMARGIN", new_y="NEXT")

    def seccion(titulo, lineas):
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, t(titulo), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for ln in lineas:
            pdf.multi_cell(0, 5, t(ln), new_x="LMARGIN", new_y="NEXT")

    seccion("Resumen ejecutivo", [informe.get("resumen_ejecutivo", "")])
    seccion("Hallazgos", [f"- {h.get('titulo', '')}: {h.get('descripcion', '')}" if isinstance(h, dict)
                          else f"- {h}" for h in informe.get("hallazgos", [])])
    seccion("Riesgos", [f"- {r.get('riesgo', '')} [{r.get('nivel', '')}]: {r.get('descripcion', '')}"
                        if isinstance(r, dict) else f"- {r}" for r in informe.get("riesgos", [])])
    seccion("Recomendaciones", [f"{i}. {x}" for i, x in enumerate(informe.get("recomendaciones", []), 1)])
    return bytes(pdf.output())


def informe_a_json(informe):
    """Serializa el informe a JSON legible."""
    return json.dumps(informe, ensure_ascii=False, indent=2)
