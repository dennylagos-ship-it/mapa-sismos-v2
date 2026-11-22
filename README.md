# Mapa Sísmico 2.0 – Gestión de Riesgos (FUNVISIS)

Plataforma de monitoreo sísmico en tiempo real y soporte a la gestión de riesgos para Venezuela, basada en los boletines públicos de **FUNVISIS** (`t.me/s/Funvisis` o Bot API de Telegram).

Desarrollada íntegramente con la **biblioteca estándar de Python** (sin dependencias externas) y una interfaz web interactiva con **Leaflet**.

---

## Características principales

- **Monitoreo en tiempo real (SSE):** Recepción automática de boletines desde la vista pública de Telegram (`t.me/s/Funvisis`) y/o Bot API oficial, con actualización instantánea en pantalla vía *Server-Sent Events*.
- **Histórico completo + filtro temporal:** Almacenamiento persistente en SQLite (`sismos.db`) con filtros rápidos en vivo para **72 horas**, **7 días**, **30 días** o **Todo** el histórico.
- **Detector de enjambres sísmicos y réplicas:** Agrupación espacio-temporal automática (radio de 35 km, ventana de 24 h, ≥ 3 sismos) mostrando rango de fechas (`inicio → fin HLV`), magnitudes, profundidad promedio y estado activo/histórico.
- **Zonas críticas (Geocercas) con alerta visual y sonora:**
  - Evaluación automática de distancia geodésica (Haversine) y magnitud mínima al llegar cada sismo.
  - **18 infraestructuras críticas de Venezuela precargadas** (represas Guri, Caruachi, Macagua, La Vueltosa, La Honda, Camatagua; puentes Rafael Urdaneta, Angostura, Viaductos Nuevo y Viejo de San Cristóbal; complejos refinadores/petroquímicos de Paraguaná, El Palito y José Antonio Anzoátegui; hospitales de referencia en Caracas, Mérida, San Cristóbal, Cumaná y Barquisimeto).
  - Selector de coordenadas haciendo clic directo en el mapa.
  - **Alerta visual y sonora** en tiempo real (banner superior pulsante, anillo expansivo sobre la zona afectada, notificación persistente en Windows y tonos de alarma con Web Audio API, más botón `🔔 Probar`).
- **Panel estadístico y mapa de calor (Heatmap):** KPIs clave, distribución por profundidad y magnitud, gráfica de actividad diaria (últimos 14 días) y ranking de zonas más recurrentes.
- **Importación y exportación GIS / Reportes:**
  - **Importar:** Carga masiva de registros históricos en **CSV** (separador `,` o `;`), **JSON** o **GeoJSON**, con detección automática de duplicados.
  - **Exportar:** Descarga directa en **CSV** (Excel), **GeoJSON** (QGIS / ArcGIS) y **Reporte Situacional HTML imprimible / PDF**.
- **Modo quiosco y personalización:** Pantalla completa (`F`), ocultar panel lateral (`L`) y carga de logo institucional desde el modal **Acerca de**.

---

## Requisitos y ejecución desde código fuente

- **Python 3.10+** (no requiere `pip install`; solo biblioteca estándar).
- Conexión a internet para consultar Telegram y cargar los mapas base.

```bash
cd mapa-sismos-v2
python servidor.py --abrir
```

La aplicación abrirá automáticamente en `http://localhost:8775` (en modo quiosco: `python servidor.py --quiosco --abrir`).

### Variables de entorno opcionales (`.env`)
| Variable | Descripción | Valor por defecto |
| --- | --- | --- |
| `PUERTO` | Puerto HTTP del servidor | `8775` |
| `CANAL_WEB` | Canal público de Telegram a consultar | `Funvisis` |
| `INTERVALO_SEG` | Intervalo de sondeo en segundos | `30` |
| `PAGINAS_HISTORIAL` | Páginas iniciales de historial al arrancar | `5` |
| `TELEGRAM_TOKEN` | Token opcional de Bot API (si se usa bot propio) | _(vacío)_ |
| `TELEGRAM_CANAL` | Canal específico para Bot API | _(vacío)_ |

---

## Compilar ejecutable e instalador (Windows)

Requiere `pyinstaller` (`pip install pyinstaller`) y **Inno Setup 6**:

```bat
construir.bat
```

Genera:
- `dist/MapaSismos2.exe` (ejecutable portable todo en uno)
- `dist/MapaSismos2_Setup_2.0.0.exe` (instalador de Windows con pantalla de licencia, accesos directos e ícono personalizado)

---

## Estructura del proyecto

```text
mapa-sismos-v2/
├── servidor.py                 # Servidor HTTP/SSE, parser FUNVISIS, motor de riesgos y SQLite
├── construir.bat               # Script de compilación (.exe + instalador Inno Setup)
├── web/
│   ├── index.html              # Interfaz principal
│   ├── styles.css              # Estilos y animaciones de alerta
│   ├── app.js                  # Mapa Leaflet, capas, enjambres, geocercas, audio y SSE
│   └── favicon.png             # Ícono de la aplicación
└── instalador/
    ├── MapaSismos2.iss         # Script de Inno Setup 6
    ├── licencia.txt            # Términos de licencia de uso
    ├── acerca.txt              # Información previa a la instalación
    ├── version_info.txt        # Metadatos de versión y copyright del .exe
    └── icono.ico               # Ícono multiresolución de Windows
```

---

## Licencia y autoría

© 2026 **Lcdo. Denny Lagos** · **Frontino Software Solutions**  
_«El poder de las grandes ideas hecho software»_

Consulta el archivo [instalador/licencia.txt](instalador/licencia.txt) para conocer los términos completos de uso y exención de responsabilidad sobre los boletines sísmicos de FUNVISIS.
