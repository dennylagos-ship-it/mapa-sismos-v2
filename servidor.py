"""
Mapa Sísmico 2.0 – Plataforma de Monitoreo y Gestión de Riesgos (FUNVISIS).

Características v2.0:
- Histórico completo en SQLite (sismos.db) con filtro temporal en vivo (72h, 7d, 30d, todo).
- Detector de enjambres sísmicos y secuencias de réplicas (agrupación espacio-temporal).
- Geocercas / infraestructura crítica con evaluación automática de distancia y magnitud.
- Panel estadístico y mapa de calor (heatmap).
- Exportación GIS (CSV, GeoJSON) y reporte situacional imprimible (HTML/PDF).

Solo usa la biblioteca estándar de Python (sin pip install).
"""
import csv
import io
import json
import math
import os
import queue
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONGELADO = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DATOS = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MapaSismos2") if CONGELADO else Path(__file__).parent
DATOS.mkdir(parents=True, exist_ok=True)
DB = DATOS / "sismos.db"

VERSION = "2.0.0"
AUTOR = "Lcdo. Denny Lagos"
EMPRESA = "Frontino Software Solutions"
LEMA = "El poder de las grandes ideas hecho software"

LOGO_TIPOS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
LOGO_MAX = 2_000_000
PUERTO = int(os.environ.get("PUERTO", "8775"))


def logo_actual():
    for ext in LOGO_TIPOS:
        p = DATOS / f"logo{ext}"
        if p.exists():
            return p
    return None


# ---------- configuración (.env opcional) ----------
env_file = DATOS / ".env"
if env_file.exists():
    for linea in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.strip().startswith("#"):
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CANAL = os.environ.get("TELEGRAM_CANAL", "").lstrip("@").lower()

# ---------- parser del boletín ----------
PATRON = re.compile(
    r"Sismo\s+(?P<fecha>\d{2}/\d{2}/\d{4})\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?).*?"
    r"Mag\s*\((?P<tipo>\w+)\)\s*:\s*(?P<mag>[\d.,]+).*?"
    r"Prof\s*:\s*(?P<prof>[\d.,]+)\s*km.*?"
    r"Epicentro\s*:\s*(?P<lat>-?[\d.,]+)\s*(?P<ns>[NS])\s+(?P<lon>-?[\d.,]+)\s*(?P<eo>[EOW])"
    r"[ \t]*\n?(?P<ref>[^\n]*)",
    re.S | re.I,
)
HLV = timezone(timedelta(hours=-4))


def num(s: str) -> float:
    return float(s.replace(",", "."))


def parsear_boletin(texto: str):
    m = PATRON.search(texto or "")
    if not m:
        return None
    hora = m["hora"] if m["hora"].count(":") == 2 else m["hora"] + ":00"
    local = datetime.strptime(f'{m["fecha"]} {hora}', "%d/%m/%Y %H:%M:%S").replace(tzinfo=HLV)
    lat = abs(num(m["lat"])) * (1 if m["ns"].upper() == "N" else -1)
    lon = abs(num(m["lon"])) * (1 if m["eo"].upper() == "E" else -1)
    return {
        "fecha_hlv": local.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha_utc": local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "magnitud": num(m["mag"]),
        "tipo_mag": m["tipo"],
        "profundidad_km": num(m["prof"]),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "referencia": (m["ref"] or "").strip(),
    }


# ---------- base de datos ----------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


ZONAS_PRECARGADAS = [
    ("Represa de Guri (Simón Bolívar)", "represa", 7.7655, -63.0003, 60.0, 4.0),
    ("Represa de Caruachi", "represa", 8.1602, -62.7982, 50.0, 4.0),
    ("Represa de Macagua", "represa", 8.3040, -62.6743, 50.0, 4.0),
    ("Central La Vueltosa (Uribante-Caparo)", "represa", 7.9667, -71.7500, 50.0, 3.5),
    ("Presa La Honda (Embalse Uribante)", "represa", 7.9255, -71.7392, 50.0, 3.5),
    ("Embalse de Camatagua", "represa", 9.8255, -66.9933, 45.0, 3.5),
    ("Puente General Rafael Urdaneta", "puente", 10.5742, -71.5760, 45.0, 3.5),
    ("Puente Angostura (Río Orinoco)", "puente", 8.1444, -63.5981, 45.0, 3.8),
    ("Viaducto Nuevo (San Cristóbal)", "puente", 7.7628, -72.2211, 35.0, 3.2),
    ("Viaducto Viejo / La Bermeja (San Cristóbal)", "puente", 7.7625, -72.2353, 35.0, 3.2),
    ("Complejo Refinador de Paraguaná (Amuay)", "otro", 11.7467, -70.1950, 50.0, 3.5),
    ("Refinería El Palito", "otro", 10.4991, -68.1285, 45.0, 3.5),
    ("Complejo Petroquímico J. A. Anzoátegui", "otro", 10.0710, -64.8600, 50.0, 3.5),
    ("Hospital Universitario de Caracas (HUC)", "hospital", 10.4903, -66.8939, 35.0, 3.2),
    ("IAHULA – Hosp. Univ. de Los Andes (Mérida)", "hospital", 8.5820, -71.1563, 35.0, 3.2),
    ("Hospital Central de San Cristóbal", "hospital", 7.7560, -72.2264, 35.0, 3.2),
    ("Hosp. Univ. Antonio Patricio de Alcalá (Cumaná)", "hospital", 10.4691, -64.1617, 35.0, 3.2),
    ("Hosp. Central Antonio María Pineda (Barquisimeto)", "hospital", 10.0806, -69.3097, 35.0, 3.2),
]


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS sismos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_hlv TEXT, fecha_utc TEXT, magnitud REAL, tipo_mag TEXT,
            profundidad_km REAL, lat REAL, lon REAL, referencia TEXT,
            texto TEXT, recibido TEXT,
            UNIQUE(fecha_hlv, lat, lon))""")
        con.execute("""CREATE TABLE IF NOT EXISTS zonas_criticas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'otro',
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            radio_km REAL NOT NULL DEFAULT 50,
            mag_min REAL NOT NULL DEFAULT 3.5,
            creado TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS alertas(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            nivel TEXT NOT NULL,
            titulo TEXT NOT NULL,
            detalle TEXT NOT NULL,
            sismo_id INTEGER,
            zona_id INTEGER,
            fecha_utc TEXT NOT NULL,
            atendida INTEGER NOT NULL DEFAULT 0)""")
        cant = con.execute("SELECT COUNT(*) FROM zonas_criticas").fetchone()[0]
        if cant == 0:
            ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            con.executemany(
                "INSERT INTO zonas_criticas(nombre,tipo,lat,lon,radio_km,mag_min,creado) VALUES(?,?,?,?,?,?,?)",
                [(n, t, lat, lon, r, m, ahora) for n, t, lat, lon, r, m in ZONAS_PRECARGADAS],
            )


init_db()


# ---------- motor de gestión de riesgos ----------
def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia geodésica aproximada (Haversine) en kilómetros."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_utc(fecha_utc: str) -> datetime:
    return datetime.strptime(fecha_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fmt_hlv(fecha_hlv: str) -> str:
    """Convierte 'YYYY-MM-DD HH:MM:SS' a 'DD/MM/YYYY HH:MM:SS' para presentación."""
    if len(fecha_hlv) >= 10 and fecha_hlv[4] == "-" and fecha_hlv[7] == "-":
        return f"{fecha_hlv[8:10]}/{fecha_hlv[5:7]}/{fecha_hlv[:4]}{fecha_hlv[10:]}"
    return fecha_hlv


def evaluar_geocercas(con: sqlite3.Connection, sismo: dict) -> list[dict]:
    zonas = con.execute("SELECT * FROM zonas_criticas").fetchall()
    generadas = []
    for z in zonas:
        dist = distancia_km(sismo["lat"], sismo["lon"], z["lat"], z["lon"])
        if dist <= z["radio_km"] and sismo["magnitud"] >= z["mag_min"]:
            nivel = "alta" if (sismo["magnitud"] >= 4.5 or (sismo["magnitud"] >= 3.8 and sismo["profundidad_km"] < 20)) else "media"
            titulo = f"Sismo M{sismo['magnitud']:.1f} cerca de {z['nombre']}"
            detalle = (
                f"Distancia: {dist:.1f} km (umbral {z['radio_km']:.0f} km) · "
                f"Prof: {sismo['profundidad_km']} km · {fmt_hlv(sismo['fecha_hlv'])} HLV"
            )
            cur = con.execute(
                """INSERT INTO alertas(tipo, nivel, titulo, detalle, sismo_id, zona_id, fecha_utc, atendida)
                   VALUES('geocerca', ?, ?, ?, ?, ?, ?, 0)""",
                (nivel, titulo, detalle, sismo["id"], z["id"], sismo["fecha_utc"]),
            )
            generadas.append({
                "id": cur.lastrowid,
                "tipo": "geocerca",
                "nivel": nivel,
                "titulo": titulo,
                "detalle": detalle,
                "sismo_id": sismo["id"],
                "zona_id": z["id"],
                "fecha_utc": sismo["fecha_utc"],
                "atendida": 0,
            })
    return generadas


def detectar_enjambres(sismos: list[dict], radio_km: float = 35.0, ventana_horas: float = 24.0, min_sismos: int = 3) -> list[dict]:
    """Agrupa sismos cercanos en espacio y tiempo para detectar enjambres o réplicas."""
    n = len(sismos)
    if n < min_sismos:
        return []
    tiempos = [parse_utc(s["fecha_utc"]) for s in sismos]
    visitado = [False] * n
    enjambres = []
    ahora = datetime.now(timezone.utc)

    for i in range(n):
        if visitado[i]:
            continue
        cola = deque([i])
        visitado[i] = True
        comp = []
        while cola:
            u = cola.popleft()
            comp.append(u)
            su = sismos[u]
            tu = tiempos[u]
            for v in range(n):
                if visitado[v]:
                    continue
                if abs((tu - tiempos[v]).total_seconds()) <= ventana_horas * 3600:
                    if distancia_km(su["lat"], su["lon"], sismos[v]["lat"], sismos[v]["lon"]) <= radio_km:
                        visitado[v] = True
                        cola.append(v)
        if len(comp) >= min_sismos:
            grupo = [sismos[idx] for idx in comp]
            mags = [g["magnitud"] for g in grupo]
            profs = [g["profundidad_km"] for g in grupo]
            fechas = sorted(g["fecha_utc"] for g in grupo)
            fin_dt = parse_utc(fechas[-1])
            ref = Counter(g["referencia"] for g in grupo if g["referencia"]).most_common(1)
            enjambres.append({
                "cantidad": len(grupo),
                "centro_lat": round(sum(g["lat"] for g in grupo) / len(grupo), 4),
                "centro_lon": round(sum(g["lon"] for g in grupo) / len(grupo), 4),
                "radio_km": radio_km,
                "mag_max": max(mags),
                "mag_min": min(mags),
                "prof_prom": round(sum(profs) / len(profs), 1),
                "inicio_utc": fechas[0],
                "fin_utc": fechas[-1],
                "inicio_hlv": min(g["fecha_hlv"] for g in grupo),
                "fin_hlv": max(g["fecha_hlv"] for g in grupo),
                "referencia": ref[0][0] if ref else "Zona sin referencia",
                "activo": (ahora - fin_dt).total_seconds() <= 24 * 3600,
                "sismos_ids": [g["id"] for g in grupo],
            })
    enjambres.sort(key=lambda e: (e["activo"], e["cantidad"], e["mag_max"]), reverse=True)
    return enjambres


def calcular_estadisticas(sismos: list[dict]) -> dict:
    if not sismos:
        return {
            "total": 0,
            "mag_max": 0.0,
            "mag_prom": 0.0,
            "prof_prom": 0.0,
            "superficiales": 0,
            "por_profundidad": {"<20": 0, "20-70": 0, "70-150": 0, ">150": 0},
            "por_magnitud": {"<3.0": 0, "3.0-3.9": 0, "4.0-4.9": 0, ">=5.0": 0},
            "por_dia": [],
            "top_referencias": [],
        }
    mags = [s["magnitud"] for s in sismos]
    profs = [s["profundidad_km"] for s in sismos]
    por_prof = {"<20": 0, "20-70": 0, "70-150": 0, ">150": 0}
    for p in profs:
        if p < 20:
            por_prof["<20"] += 1
        elif p < 70:
            por_prof["20-70"] += 1
        elif p < 150:
            por_prof["70-150"] += 1
        else:
            por_prof[">150"] += 1

    por_mag = {"<3.0": 0, "3.0-3.9": 0, "4.0-4.9": 0, ">=5.0": 0}
    for m in mags:
        if m < 3.0:
            por_mag["<3.0"] += 1
        elif m < 4.0:
            por_mag["3.0-3.9"] += 1
        elif m < 5.0:
            por_mag["4.0-4.9"] += 1
        else:
            por_mag[">=5.0"] += 1

    dias = Counter(s["fecha_hlv"][:10] for s in sismos)
    por_dia = [{"fecha": d, "cantidad": c} for d, c in sorted(dias.items())[-14:]]
    refs = Counter(s["referencia"] for s in sismos if s["referencia"]).most_common(5)
    return {
        "total": len(sismos),
        "mag_max": round(max(mags), 1),
        "mag_prom": round(sum(mags) / len(mags), 2),
        "prof_prom": round(sum(profs) / len(profs), 1),
        "superficiales": por_prof["<20"],
        "por_profundidad": por_prof,
        "por_magnitud": por_mag,
        "por_dia": por_dia,
        "top_referencias": [{"referencia": r, "cantidad": c} for r, c in refs],
    }


def guardar(texto: str):
    s = parsear_boletin(texto)
    if not s:
        return None
    s["texto"] = texto
    s["recibido"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    alertas_nuevas = []
    with db() as con:
        cur = con.execute(
            """INSERT OR IGNORE INTO sismos(fecha_hlv,fecha_utc,magnitud,tipo_mag,
               profundidad_km,lat,lon,referencia,texto,recibido)
               VALUES(:fecha_hlv,:fecha_utc,:magnitud,:tipo_mag,:profundidad_km,
               :lat,:lon,:referencia,:texto,:recibido)""",
            s,
        )
        if cur.rowcount == 0:
            return None
        s["id"] = cur.lastrowid
        alertas_nuevas = evaluar_geocercas(con, s)
    s.pop("texto")
    print(f"[sismo] M{s['magnitud']} {s['fecha_hlv']} {s['referencia']}")
    difundir({"tipo": "sismo", "sismo": s, "alertas": alertas_nuevas})
    return s


def listar(horas: int = 72) -> list[dict]:
    with db() as con:
        if horas and horas > 0:
            limite = (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%SZ")
            filas = con.execute(
                "SELECT id,fecha_hlv,fecha_utc,magnitud,tipo_mag,profundidad_km,lat,lon,referencia,recibido "
                "FROM sismos WHERE fecha_utc >= ? ORDER BY fecha_utc DESC LIMIT 2000",
                (limite,),
            ).fetchall()
        else:
            filas = con.execute(
                "SELECT id,fecha_hlv,fecha_utc,magnitud,tipo_mag,profundidad_km,lat,lon,referencia,recibido "
                "FROM sismos ORDER BY fecha_utc DESC LIMIT 5000"
            ).fetchall()
    return [dict(f) for f in filas]


def listar_zonas() -> list[dict]:
    with db() as con:
        filas = con.execute("SELECT * FROM zonas_criticas ORDER BY id DESC").fetchall()
    return [dict(f) for f in filas]


def listar_alertas(solo_activas: bool = False) -> list[dict]:
    with db() as con:
        q = "SELECT * FROM alertas " + ("WHERE atendida = 0 " if solo_activas else "") + "ORDER BY id DESC LIMIT 100"
        filas = con.execute(q).fetchall()
    return [dict(f) for f in filas]


# ---------- tiempo real (SSE) ----------
clientes: list[queue.Queue] = []
clientes_lock = threading.Lock()


def difundir(evento: dict):
    with clientes_lock:
        for q in clientes:
            q.put(evento)


# ---------- lector de Telegram ----------
def tg(metodo: str, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def lector_telegram():
    offset = 0
    print("[telegram] escuchando el canal…")
    while True:
        try:
            r = tg(
                "getUpdates",
                offset=offset,
                timeout=50,
                allowed_updates=json.dumps(["channel_post", "edited_channel_post", "message"]),
            )
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("channel_post") or u.get("edited_channel_post") or u.get("message") or {}
                chat = msg.get("chat", {})
                if CANAL and CANAL not in (str(chat.get("username", "")).lower(), str(chat.get("id"))):
                    continue
                texto = msg.get("text") or msg.get("caption") or ""
                guardar(texto)
        except Exception as e:
            print("[telegram] error:", e)
            time.sleep(5)


# ---------- lector de la vista web pública ----------
CANAL_WEB = os.environ.get("CANAL_WEB", "Funvisis")
INTERVALO = int(os.environ.get("INTERVALO_SEG", "30"))
PAGINAS_HISTORIAL = int(os.environ.get("PAGINAS_HISTORIAL", "5"))
_RE_POST = re.compile(r'data-post="[^"/]+/(\d+)".*?tgme_widget_message_text[^>]*>(.*?)</div>', re.S)


def leer_pagina(antes: int | None = None):
    import html as h

    url = f"https://t.me/s/{CANAL_WEB}" + (f"?before={antes}" if antes else "")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        pagina = r.read().decode("utf-8", "replace")
    posts = []
    for num_post, cuerpo in _RE_POST.findall(pagina):
        texto = re.sub(r"<br\s*/?>", "\n", cuerpo)
        texto = h.unescape(re.sub(r"<[^>]+>", "", texto))
        posts.append((int(num_post), texto))
    return posts


def lector_web():
    print(f"[web] leyendo t.me/s/{CANAL_WEB} cada {INTERVALO}s")
    antes = None
    for _ in range(PAGINAS_HISTORIAL):
        try:
            posts = leer_pagina(antes)
        except Exception as e:
            print("[web] error historial:", e)
            break
        if not posts:
            break
        for _, texto in posts:
            guardar(texto)
        antes = min(p for p, _ in posts)
    while True:
        try:
            for _, texto in leer_pagina():
                guardar(texto)
        except Exception as e:
            print("[web] error:", e)
        time.sleep(INTERVALO)


# ---------- exportación y reportes ----------
def generar_csv(sismos: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "fecha_hlv", "fecha_utc", "magnitud", "tipo_mag", "profundidad_km", "lat", "lon", "referencia"])
    for s in sismos:
        w.writerow([
            s["id"], fmt_hlv(s["fecha_hlv"]), s["fecha_utc"], s["magnitud"],
            s["tipo_mag"], s["profundidad_km"], s["lat"], s["lon"], s["referencia"],
        ])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def generar_geojson(sismos: list[dict]) -> bytes:
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                "properties": {
                    "id": s["id"],
                    "fecha_hlv": s["fecha_hlv"],
                    "fecha_utc": s["fecha_utc"],
                    "magnitud": s["magnitud"],
                    "tipo_mag": s["tipo_mag"],
                    "profundidad_km": s["profundidad_km"],
                    "referencia": s["referencia"],
                },
            }
            for s in sismos
        ],
    }
    return json.dumps(fc, ensure_ascii=False, indent=2).encode("utf-8")


def generar_reporte_html(sismos: list[dict], horas: int) -> bytes:
    import html as h

    stats = calcular_estadisticas(sismos)
    enjambres = detectar_enjambres(sismos)
    alertas = listar_alertas()
    etiqueta = f"Últimas {horas} horas" if horas > 0 else "Histórico completo"
    ahora_hlv = datetime.now(HLV).strftime("%d/%m/%Y %H:%M:%S HLV")

    filas_sismos = "".join(
        f"<tr><td>{h.escape(fmt_hlv(s['fecha_hlv']))}</td><td><b>{s['magnitud']:.1f}</b> ({h.escape(s['tipo_mag'])})</td>"
        f"<td>{s['profundidad_km']} km</td><td>{s['lat']}, {s['lon']}</td><td>{h.escape(s['referencia'])}</td></tr>"
        for s in sismos[:200]
    )
    filas_enj = "".join(
        f"<tr><td>{e['cantidad']} sismos</td><td>M{e['mag_max']:.1f}</td><td>{e['prof_prom']} km</td>"
        f"<td>{h.escape(fmt_hlv(e['inicio_hlv']))} → {h.escape(fmt_hlv(e['fin_hlv']))}</td>"
        f"<td>{h.escape(e['referencia'])}</td><td>{'ACTIVO' if e['activo'] else 'Histórico'}</td></tr>"
        for e in enjambres
    ) or "<tr><td colspan='6'>No se detectaron enjambres en este período.</td></tr>"
    filas_al = "".join(
        f"<tr><td>{h.escape(a['nivel'].upper())}</td><td>{h.escape(a['titulo'])}</td>"
        f"<td>{h.escape(a['detalle'])}</td></tr>"
        for a in alertas[:30]
    ) or "<tr><td colspan='3'>Sin alertas de geocercas registradas.</td></tr>"

    doc = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Reporte Situacional Sísmico – {etiqueta}</title>
<style>
  body {{ font-family: system-ui, sans-serif; color:#111; max-width:960px; margin:24px auto; padding:0 16px; }}
  h1,h2 {{ margin:0 0 8px; }} h2 {{ margin-top:24px; border-bottom:1px solid #ccc; padding-bottom:4px; font-size:16px; }}
  .meta {{ color:#555; font-size:13px; margin-bottom:16px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:16px 0; }}
  .kpi {{ border:1px solid #ddd; border-radius:6px; padding:10px; }}
  .kpi b {{ display:block; font-size:22px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }}
  th,td {{ border:1px solid #ddd; padding:6px 8px; text-align:left; }}
  th {{ background:#f4f6f8; }}
  .btn {{ padding:8px 14px; background:#0f1720; color:#fff; border:none; border-radius:6px; cursor:pointer; float:right; }}
  @media print {{ .btn {{ display:none; }} }}
</style></head><body>
<button class="btn" onclick="window.print()">Imprimir / Guardar PDF</button>
<h1>Reporte Situacional Sísmico (FUNVISIS)</h1>
<div class="meta">Ventana: <b>{etiqueta}</b> · Generado: {ahora_hlv} · Mapa Sísmico {VERSION}</div>
<div class="kpis">
  <div class="kpi"><small>Total eventos</small><b>{stats['total']}</b></div>
  <div class="kpi"><small>Magnitud máxima</small><b>M {stats['mag_max']}</b></div>
  <div class="kpi"><small>Prof. promedio</small><b>{stats['prof_prom']} km</b></div>
  <div class="kpi"><small>Superficiales (&lt;20 km)</small><b>{stats['superficiales']}</b></div>
</div>
<h2>Enjambres / Secuencias Detectadas (radio 35 km / 24h)</h2>
<table><thead><tr><th>Eventos</th><th>Mag. Máx</th><th>Prof. Prom</th><th>Período (HLV)</th><th>Referencia</th><th>Estado</th></tr></thead>
<tbody>{filas_enj}</tbody></table>
<h2>Alertas en Zonas Críticas</h2>
<table><thead><tr><th>Nivel</th><th>Evento</th><th>Detalle</th></tr></thead>
<tbody>{filas_al}</tbody></table>
<h2>Registro de Sismos (máx. 200 más recientes)</h2>
<table><thead><tr><th>Fecha (HLV)</th><th>Magnitud</th><th>Profundidad</th><th>Coordenadas</th><th>Referencia</th></tr></thead>
<tbody>{filas_sismos}</tbody></table>
<p style="margin-top:24px;font-size:11px;color:#666;border-top:1px solid #ddd;padding-top:8px;">© 2026 {AUTOR} · {EMPRESA} — «{LEMA}»</p>
</body></html>"""
    return doc.encode("utf-8")


# ---------- importación de históricos (CSV / JSON / GeoJSON) ----------
def _parsear_fecha_import(valor: str, hora_extra: str = "") -> tuple[str, str] | None:
    txt = (valor or "").strip()
    if hora_extra and " " not in txt and "T" not in txt:
        txt = f"{txt} {hora_extra.strip()}"
    if not txt:
        return None
    if txt.endswith("Z"):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                dt = datetime.strptime(txt, fmt).replace(tzinfo=timezone.utc)
                return dt.astimezone(HLV).strftime("%Y-%m-%d %H:%M:%S"), dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(txt[:19], fmt).replace(tzinfo=HLV)
            return dt.strftime("%Y-%m-%d %H:%M:%S"), dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return None


def _normalizar_fila(row: dict) -> dict | None:
    norm = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
    f_utc_raw = str(norm.get("fecha_utc") or norm.get("utc") or "").strip()
    f_hlv_raw = str(norm.get("fecha_hlv") or norm.get("fecha") or norm.get("date") or norm.get("time") or "").strip()
    hora_raw = str(norm.get("hora") or "").strip()

    fechas = _parsear_fecha_import(f_utc_raw) if f_utc_raw else _parsear_fecha_import(f_hlv_raw, hora_raw)
    if not fechas:
        return None
    fecha_hlv, fecha_utc = fechas

    try:
        mag = num(str(norm.get("magnitud") or norm.get("mag") or norm.get("mw") or norm.get("ml") or ""))
        lat = num(str(norm.get("lat") or norm.get("latitud") or norm.get("latitude") or ""))
        lon = num(str(norm.get("lon") or norm.get("longitud") or norm.get("longitude") or norm.get("lng") or ""))
        prof_raw = norm.get("profundidad_km") or norm.get("profundidad") or norm.get("prof") or norm.get("depth") or "10"
        prof = num(str(prof_raw))
    except Exception:
        return None

    return {
        "fecha_hlv": fecha_hlv,
        "fecha_utc": fecha_utc,
        "magnitud": mag,
        "tipo_mag": str(norm.get("tipo_mag") or norm.get("tipo") or "Mw").strip() or "Mw",
        "profundidad_km": prof,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "referencia": str(norm.get("referencia") or norm.get("ref") or norm.get("lugar") or norm.get("place") or "").strip(),
        "texto": "importado",
        "recibido": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def importar_datos(contenido: bytes) -> dict:
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1", "replace")
    texto = texto.strip()
    if not texto:
        return {"insertados": 0, "omitidos": 0}

    registros = []
    if texto.startswith("{") or texto.startswith("["):
        data = json.loads(texto)
        if isinstance(data, dict) and data.get("type") == "FeatureCollection":
            for feat in data.get("features", []):
                props = dict(feat.get("properties") or {})
                coords = (feat.get("geometry") or {}).get("coordinates") or []
                if len(coords) >= 2:
                    props.setdefault("lon", coords[0])
                    props.setdefault("lat", coords[1])
                registros.append(props)
        elif isinstance(data, list):
            registros = [x for x in data if isinstance(x, dict)]
    else:
        primera = texto.splitlines()[0]
        delim = ";" if primera.count(";") > primera.count(",") else ","
        lector = csv.DictReader(io.StringIO(texto), delimiter=delim)
        registros = list(lector)

    insertados = 0
    omitidos = 0
    with db() as con:
        for r in registros:
            s = _normalizar_fila(r)
            if not s:
                omitidos += 1
                continue
            cur = con.execute(
                """INSERT OR IGNORE INTO sismos(fecha_hlv,fecha_utc,magnitud,tipo_mag,
                   profundidad_km,lat,lon,referencia,texto,recibido)
                   VALUES(:fecha_hlv,:fecha_utc,:magnitud,:tipo_mag,:profundidad_km,
                   :lat,:lon,:referencia,:texto,:recibido)""",
                s,
            )
            if cur.rowcount > 0:
                insertados += 1
            else:
                omitidos += 1
    return {"insertados": insertados, "omitidos": omitidos}


# ---------- servidor web ----------
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(BASE / "web"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        cuerpo = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8", "replace"))

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _horas_param(self, default=72) -> int:
        q = self._query()
        try:
            return max(0, int(q.get("horas", [default])[0]))
        except ValueError:
            return default

    def do_GET(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta == "/api/info":
            return self._json({
                "app": "MapaSismos",
                "version": VERSION,
                "autor": AUTOR,
                "empresa": EMPRESA,
                "lema": LEMA,
                "logo": logo_actual() is not None,
            })
        if ruta == "/api/logo":
            p = logo_actual()
            if not p:
                return self.send_error(404)
            datos = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", LOGO_TIPOS[p.suffix])
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(datos)
            return
        if ruta == "/api/sismos":
            return self._json(listar(self._horas_param(72)))
        if ruta == "/api/resumen":
            horas = self._horas_param(72)
            sismos = listar(horas)
            return self._json({
                "horas": horas,
                "sismos": sismos,
                "estadisticas": calcular_estadisticas(sismos),
                "enjambres": detectar_enjambres(sismos),
                "zonas": listar_zonas(),
                "alertas": listar_alertas(),
            })
        if ruta == "/api/zonas":
            return self._json(listar_zonas())
        if ruta == "/api/alertas":
            return self._json(listar_alertas())
        if ruta == "/api/exportar":
            horas = self._horas_param(72)
            fmt = (self._query().get("formato", ["csv"])[0]).lower()
            sismos = listar(horas)
            if fmt == "geojson":
                datos = generar_geojson(sismos)
                ct, ext = "application/geo+json; charset=utf-8", "geojson"
            elif fmt == "html":
                datos = generar_reporte_html(sismos, horas)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)
                return
            else:
                datos = generar_csv(sismos)
                ct, ext = "text/csv; charset=utf-8", "csv"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Disposition", f'attachment; filename="sismos_{horas or "todo"}h.{ext}"')
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return
        if ruta == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q: queue.Queue = queue.Queue()
            with clientes_lock:
                clientes.append(q)
            try:
                while True:
                    try:
                        ev = q.get(timeout=20)
                        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                with clientes_lock:
                    clientes.remove(q)
            return
        return super().do_GET()

    def _solo_local(self):
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            self._json({"error": "solo desde esta PC"}, 403)
            return False
        return True

    def do_DELETE(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta == "/api/logo" and self._solo_local():
            p = logo_actual()
            if p:
                p.unlink()
            return self._json({"ok": True})
        if ruta.startswith("/api/zonas/"):
            try:
                zid = int(ruta.rsplit("/", 1)[-1])
            except ValueError:
                return self._json({"error": "id inválido"}, 400)
            with db() as con:
                con.execute("DELETE FROM zonas_criticas WHERE id = ?", (zid,))
            return self._json({"ok": True})
        self.send_error(404)

    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta == "/api/logo":
            if not self._solo_local():
                return
            tipo = self.headers.get("Content-Type", "").split(";")[0].strip()
            ext = next((e for e, t in LOGO_TIPOS.items() if t == tipo), None)
            n = int(self.headers.get("Content-Length", 0))
            if not ext or n <= 0 or n > LOGO_MAX:
                return self._json({"error": "imagen PNG, JPG, SVG, WEBP o GIF de hasta 2 MB"}, 400)
            datos = self.rfile.read(n)
            p = logo_actual()
            if p:
                p.unlink()
            (DATOS / f"logo{ext}").write_bytes(datos)
            return self._json({"ok": True}, 201)
        if ruta == "/api/zonas":
            try:
                d = self._leer_json()
                nombre = str(d.get("nombre", "")).strip()
                tipo = str(d.get("tipo", "otro")).strip() or "otro"
                lat = float(d["lat"])
                lon = float(d["lon"])
                radio_km = float(d.get("radio_km", 50))
                mag_min = float(d.get("mag_min", 3.5))
                if not nombre or radio_km <= 0:
                    raise ValueError("datos inválidos")
            except Exception:
                return self._json({"error": "nombre, lat, lon, radio_km y mag_min válidos requeridos"}, 400)
            creado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with db() as con:
                cur = con.execute(
                    "INSERT INTO zonas_criticas(nombre,tipo,lat,lon,radio_km,mag_min,creado) VALUES(?,?,?,?,?,?,?)",
                    (nombre, tipo, lat, lon, radio_km, mag_min, creado),
                )
                zid = cur.lastrowid
            return self._json({
                "id": zid, "nombre": nombre, "tipo": tipo,
                "lat": lat, "lon": lon, "radio_km": radio_km, "mag_min": mag_min, "creado": creado,
            }, 201)
        if ruta.startswith("/api/alertas/") and ruta.endswith("/atender"):
            try:
                aid = int(ruta.split("/")[3])
            except Exception:
                return self._json({"error": "id inválido"}, 400)
            with db() as con:
                con.execute("UPDATE alertas SET atendida = 1 WHERE id = ?", (aid,))
            return self._json({"ok": True})
        if ruta == "/api/importar":
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0 or n > 20_000_000:
                return self._json({"error": "archivo vacío o mayor a 20 MB"}, 400)
            try:
                res = importar_datos(self.rfile.read(n))
                return self._json({"ok": True, **res}, 200)
            except Exception as e:
                return self._json({"error": f"no se pudo importar: {e}"}, 400)
        if ruta == "/api/ingest":
            n = int(self.headers.get("Content-Length", 0))
            texto = self.rfile.read(n).decode("utf-8", "replace")
            s = guardar(texto)
            if s:
                return self._json(s, 201)
            return self._json({"error": "no se reconoció el boletín o ya existe"}, 400)
        self.send_error(404)


if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=lector_telegram, daemon=True).start()
    threading.Thread(target=lector_web, daemon=True).start()
    QUIOSCO = "--quiosco" in sys.argv

    import socket

    class Servidor(ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    def es_mapa_sismos(puerto: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/info", timeout=2) as r:
                info = json.load(r)
                return info.get("app") == "MapaSismos" and str(info.get("version", "")).startswith("2.")
        except Exception:
            return False

    servidor, ya_corre = None, False
    for PUERTO in range(PUERTO, PUERTO + 20):
        try:
            servidor = Servidor(("0.0.0.0", PUERTO), Handler)
            break
        except OSError:
            if es_mapa_sismos(PUERTO):
                ya_corre = True
                break
    else:
        print("No se encontró un puerto libre.")
        sys.exit(1)
    url = f"http://localhost:{PUERTO}" + ("/?quiosco=1" if QUIOSCO else "")

    def abrir():
        import subprocess
        perfil = DATOS / "navegador"
        for edge in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ):
            if Path(edge).exists():
                comun = [f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check"]
                if QUIOSCO:
                    subprocess.Popen([edge, *comun, "--kiosk", url, "--edge-kiosk-type=fullscreen"])
                else:
                    subprocess.Popen([edge, *comun, f"--app={url}", "--start-maximized"])
                return
        webbrowser.open(url)

    if ya_corre:
        print(f"Ya está en ejecución. Abriendo {url}")
        abrir()
        sys.exit(0)
    print(f"Mapa Sísmico 2.0 en {url}  (Ctrl+C o cerrar esta ventana para detener)")
    print(f"Datos en {DATOS}")
    if CONGELADO or "--abrir" in sys.argv:
        threading.Timer(1.0, abrir).start()
    servidor.serve_forever()
