# Auditoría Universitaria — análisis estadístico automatizado

Sistema local (sin costo, sin nube) para que auditores internos analicen cuentas por facultad,
centro de costo y área: estadística descriptiva e inferencial, detección de anomalías,
muestreo NIA 530, informes con IA local (OpenCode + Ollama) y dashboard en Streamlit.

## 1. Requisitos e instalación

- Python 3.10 o superior
- (Opcional, para informes con IA) Ollama y OpenCode, ver sección 3

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # una sola vez; después funciona sin internet
```

## 2. Uso rápido con datos de ejemplo

```bash
cp EJEMPLO_DATOS.csv data/raw/                 # Windows: copy EJEMPLO_DATOS.csv data\raw\
python scripts/ejecutar_analisis.py            # análisis completo (un solo comando)
streamlit run app/app.py                       # http://localhost:8501
```

> Antes de analizar datos reales, **borre EJEMPLO_DATOS.csv de `data/raw/`** para no mezclarlos.

Datos propios: coloque CSV, Excel o JSON en `data/raw/` con las columnas
`Facultad, Centro_Costo, Cuenta, Descripcion, Debe, Haber, Fecha, Tipo_Transaccion, Numero_Documento`
(opcional: `Area_Administrativa`). Si `Fecha` incluye hora (`2026-03-14 23:15`) se activa la alerta de horario inusual.

Opciones del script: `--opencode` (añade informe con IA) y `--metodo mum|estratificado`.

## 2b. Auditorías automatizadas de sitios (Moodle)

Módulo para auditar directamente el sitio institucional (por defecto **https://evea.uh.cu**,
un Moodle) sin importar CSV: se conecta, inicia sesión, detecta permisos reales y produce
informes periódicos. Sin datos simulados: lo que el sitio no entregue queda declarado en la
cobertura con el motivo exacto que devolvió el sitio.

### Flujo de trabajo

1. `streamlit run app/app.py` → página **6. Auditorías Automatizadas** → botón
   **➕ Nueva auditoría automatizada**. El formulario pide:
   - **URL del sitio** (precargada con `auditorias.sitio_predeterminado` de config.yaml)
   - **Credenciales de usuario** y, si dispone de ellas, **de administrador o superadmin**
     (con administrador puede realizarse la auditoría completa; sin ellas el sistema audita
     solo lo que el sitio exponga y lo declara)
   - **Tipo de auditoría**: Sitio (general), Cuentas, Roles, Permisos, Almacenamiento,
     Cuentas por áreas o facultades (combinables)
   - **Formato de entrega**: Excel (.xlsx), PDF, Markdown, HTML, CSV, JSON
   - **Periodicidad**: diaria, semanal, cada N días, mensual, cada N meses, anual o un día específico
2. Al guardar se genera un **flujo automático editable y gestionable** (JSON en `data/flujos/`):
   puede ejecutarlo cuando quiera, pausarlo/reanudarlo, editarlo o eliminarlo desde la misma página,
   y ver su historial de ejecuciones. El planificador puede correr en segundo plano mientras la
   app esté abierta, o de forma permanente con `python scripts/programar_flujos.py`
   (una pasada con `--una-vez` para cron/schtasks).
3. Los informes quedan en `data/informes/auditorias_sitio/<flujo>/<fecha>/` y se consultan con
   descarga en la página **7. Informes de sitio**, junto a la tabla de **cobertura**.

### Prueba real (sin datos simulados)

```bash
python scripts/prueba_real.py          # diagnóstico anónimo completo contra evea.uh.cu
python scripts/prueba_real.py --usuario juan@uh.cu --password SECRETA
python scripts/prueba_real.py --usuario U --password P --admin-usuario A --admin-password B
```

El script ejecuta el sistema completo contra https://evea.uh.cu/login/index.php: conexión,
análisis del login, intentos reales de sesión, token de web services, auditorías y exportación
de informes a `data/informes/prueba_real/`. Cada paso imprime `[OK]`, `[PARCIAL]`,
`[SIN PERMISO]`, `[NO DISPONIBLE]` o `[ERROR]` con la respuesta real del sitio. Si no tiene
credenciales correctas, la prueba no se detiene: muestra hasta dónde llegó y qué no se pudo
obtener (ese es exactamente el comportamiento del sistema en producción). Códigos de salida:
0 sistema ejecutado, 2 sitio inalcanzable, 1 error interno. Credenciales opcionales por
variables de entorno: `AUDIT_USUARIO`, `AUDIT_PASSWORD`, `AUDIT_ADMIN_USUARIO`, `AUDIT_ADMIN_PASSWORD`.

### Cómo maneja las limitaciones reales de un sitio

- **Credenciales inválidas**: registra el mensaje de error textual que devuelve el propio sitio
  y continúa en modo anónimo con lo alcanzable.
- **Cuenta sin permisos de administrador**: verifica accediendo a `/admin/index.php` y páginas
  administrativas; si el sitio las deniega, las auditorías que las requieren (p. ej. la matriz
  de permisos) quedan como *no disponibles* con ese motivo, y las demás se realizan por
  web services con el usuario (cuentas vía matrículas, roles observados, contenidos de cursos).
- **Sitios que no entregan todos los datos** (web services deshabilitados, plugins ausentes,
  topes de tamaño): cada fuente se sondea de verdad y la cobertura enumera qué se obtuvo, qué
  se midió parcialmente (con el tope alcanzado) y qué no se pudo, con el código de error real
  (`accesscontrolexception`, `invalidlogin`, HTTP 403/404, ...). Los informes declaran estas
  limitaciones en lugar de inventar cifras.

### Seguridad de las credenciales

Las contraseñas se guardan en texto plano dentro del flujo (`data/flujos/*.json`) porque la
ejecución desatendida las necesita. Es un sistema local: restrinja los permisos de esa carpeta
al equipo del auditor y no compartirla. Las contraseñas nunca aparecen en los informes ni en
los registros de ejecución.

## 3. Integración con OpenCode + Ollama (opcional)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3-coder
ollama serve
curl -fsSL https://opencode.ai/install | bash
```

`~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "provider": {
    "ollama": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://localhost:11434/v1" },
      "models": { "qwen3-coder": {} }
    }
  }
}
```

El modelo, permisos y tiempo límite se ajustan en `config/config.yaml` (sección `opencode`).
El puente (`src/opencode_bridge.py`) ejecuta `opencode run --model <modelo> "<prompt con datos>"`,
exige una respuesta JSON (resumen ejecutivo, hallazgos, riesgos, recomendaciones) y la guarda en
`data/informes/informe_YYYYMMDD_HHMM.json`. Si OpenCode no está instalado o falla, el flujo
no se detiene: se genera un informe local determinista (sin IA), marcado como tal.

> La sintaxis de la CLI de OpenCode puede cambiar entre versiones; si `opencode run` no coincide con
> la suya, ajuste la línea `cmd = [...]` en `opencode_bridge.py`.

## 4. Qué produce

| Archivo | Contenido |
|---|---|
| `data/processed/datos_limpios.csv` | datos normalizados (Saldo, Periodo, Monto) |
| `data/processed/duplicados_exactos_eliminados.csv` | filas idénticas eliminadas en la limpieza (auditable) |
| `data/processed/log_integridad.json` | filas leídas/descartadas y errores por archivo |
| `data/processed/resumen_por_categoria.csv` | estadísticas por facultad, centro y área |
| `data/processed/alertas_anomalias.json` | duplicados, saltos, outliers, patrones de riesgo |
| `data/processed/analisis_estadistico.json` | descriptiva, t-test/ANOVA, chi-cuadrado, correlaciones, regresiones |
| `data/processed/muestra_estadistica.csv` | hoja de trabajo con la muestra seleccionada |
| `data/informes/informe_*.json` | informes (OpenCode o locales) |
| `data/flujos/fl_*.json` | flujos de auditoría automatizada (editables, con historial) |
| `data/informes/auditorias_sitio/<flujo>/<fecha>/` | informes por ejecución (xlsx/pdf/md/html/csv + resultado.json y cobertura) |
| `data/informes/prueba_real/<fecha>/` | evidencia de las pruebas reales del script `prueba_real.py` |

## 5. Criterios de diseño que conviene conocer

- **Duplicados:** los duplicados *exactos* se eliminan en la limpieza y se registran. La detección de
  anomalías busca además duplicados por `Fecha + Cuenta + Monto + Numero_Documento` (p. ej. mismo
  documento contabilizado en dos centros de costo).
- **Monto:** columna derivada `Monto = max(Debe, Haber)`; las estadísticas se calculan sobre ella.
- **Outliers:** z-score > 3 o IQR 1,5× dentro de cada facultad. Con montos muy asimétricos el IQR marca
  bastantes partidas: úselo para priorizar revisión, no como prueba de error.
- **Muestreo MUM:** `n = V × FC / (ET − EE × factor de expansión)`, FC = −ln(1−confianza). Las partidas
  mayores al intervalo se seleccionan con certeza, por lo que la muestra puede tener menos partidas que `n`.
- **Estratificado:** asignación proporcional al valor por facultad × rango de monto; el rango superior se revisa al 100 %.
- **Extrapolación NIA 530:** método de razón (error de la muestra / valor de la muestra × valor de la población).
  Sirve como apoyo al juicio profesional; no sustituye la evaluación del auditor.
- **Regresión logística:** la "probabilidad de riesgo" se modela contra las partidas que ya tienen alerta; es
  un indicador exploratorio, no una prueba de fraude.

## 6. Ejecución periódica

```bash
python scripts/programar_tarea.py        # con `schedule`, cada noche (hora en config.yaml)
```
cron (Linux/Mac): `0 2 * * * cd /ruta/auditoria_universitaria && .venv/bin/python scripts/ejecutar_analisis.py --opencode`

Windows: `schtasks /Create /SC DAILY /ST 02:00 /TN "AuditoriaUniversitaria" /TR "C:\ruta\.venv\Scripts\python.exe C:\ruta\scripts\ejecutar_analisis.py --opencode"`

Registros en `logs/auditoria.log` (rotativo, 5 copias de 1 MB).

## 7. Pruebas

```bash
pytest -q
```

## 8. Próximos pasos

- Conectar con el SIAF/ERP real (consulta directa o exportación programada a `data/raw/`).
- Alertas por correo cuando aparezcan anomalías de severidad alta.
- Modelos de machine learning (Isolation Forest, ley de Benford) para detección de fraude.
- Autenticación y registro de quién ejecuta y revisa cada informe.
- Plantillas de papeles de trabajo exportables a Excel con firmas y referencias.
- Notificaciones cuando una ejecución programada quede con secciones *no disponibles*.
