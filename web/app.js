const $ = id => document.getElementById(id);

let horasActual = 72;
let resumenActual = { sismos: [], estadisticas: null, enjambres: [], zonas: [], alertas: [] };
let marcadores = {};
let eligiendoCoord = false;
let audioCtx = null;
let sonidoActivo = true;
try { if (localStorage.getItem('sonidoAlerta') === '0') sonidoActivo = false; } catch (_) {}

function actualizarBtnSonido() {
  $('btn-sonido').textContent = sonidoActivo ? '🔊' : '🔇';
  $('btn-sonido').title = sonidoActivo ? 'Sonido activado (clic para silenciar)' : 'Sonido silenciado (clic para activar)';
}

function desbloquearAudio() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) audioCtx = new Ctx();
  }
  if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume().catch(() => {});
}
document.addEventListener('pointerdown', desbloquearAudio, { once: true });

function sonarAlerta(nivel = 'media') {
  if (!sonidoActivo) return;
  desbloquearAudio();
  if (!audioCtx) return;
  const secuencia = nivel === 'alta'
    ? [[980, 0, 0.16], [740, 0.2, 0.16], [980, 0.4, 0.16], [740, 0.6, 0.22]]
    : [[880, 0, 0.16], [660, 0.2, 0.22]];
  const ahora = audioCtx.currentTime;
  for (const [freq, offset, dur] of secuencia) {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(freq, ahora + offset);
    gain.gain.setValueAtTime(0.001, ahora + offset);
    gain.gain.exponentialRampToValueAtTime(0.25, ahora + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, ahora + offset + dur);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(ahora + offset);
    osc.stop(ahora + offset + dur + 0.02);
  }
}

function dispararAlertaVisualYSonora(alertas, esPrueba = false) {
  if (!alertas || !alertas.length) return;
  const al = alertas[0];
  $('alerta-texto').textContent = `🚨 ${esPrueba ? '[PRUEBA] ' : ''}ALERTA EN ZONA CRÍTICA: ${al.titulo} — ${al.detalle}`;
  $('alerta-banner').classList.remove('oculto');
  $('alerta-banner').classList.add('critica');
  sonarAlerta(al.nivel || 'alta');

  for (const a of alertas) {
    const z = (resumenActual.zonas || []).find(item => item.id === a.zona_id);
    if (z) {
      const anillo = L.marker([z.lat, z.lon], {
        icon: L.divIcon({ className: 'pulso', iconSize: [80, 80] }),
      }).addTo(mapa);
      setTimeout(() => mapa.removeLayer(anillo), 25000);
    }
  }
  if (!esPrueba && Notification?.permission === 'granted') {
    new Notification(`⚠️ ${al.titulo}`, { body: al.detalle, requireInteraction: true });
  }
}

// ---- Mapa base ----
const mapa = L.map('mapa', { zoomControl: true }).setView([8.5, -66.5], 6);
const esri = (s, o = {}) => L.tileLayer(
  `https://server.arcgisonline.com/ArcGIS/rest/services/${s}/MapServer/tile/{z}/{y}/{x}`,
  Object.assign({ attribution: 'Esri, HERE, Garmin, &copy; OpenStreetMap', maxZoom: 18 }, o)
);
const conEtiquetas = (base, ref) => L.layerGroup([base, ref]);
const mapasBase = {
  '🌑 Oscuro': conEtiquetas(esri('Canvas/World_Dark_Gray_Base', { maxZoom: 16 }), esri('Canvas/World_Dark_Gray_Reference', { maxZoom: 16 })),
  '⬜ Claro': conEtiquetas(esri('Canvas/World_Light_Gray_Base', { maxZoom: 16 }), esri('Canvas/World_Light_Gray_Reference', { maxZoom: 16 })),
  '🗺️ Calles (OSM)': L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap', maxZoom: 19 }),
  '🛰️ Satélite': conEtiquetas(esri('World_Imagery'), esri('Reference/World_Boundaries_and_Places')),
  '⛰️ Relieve': esri('World_Topo_Map'),
  '🌊 Océano': conEtiquetas(esri('Ocean/World_Ocean_Base', { maxZoom: 13 }), esri('Ocean/World_Ocean_Reference', { maxZoom: 13 })),
};
let elegido = '🌑 Oscuro';
try { const g = localStorage.getItem('mapaBase'); if (g && mapasBase[g]) elegido = g; } catch (_) {}
mapasBase[elegido].addTo(mapa);
L.control.layers(mapasBase, null, { position: 'topright', collapsed: true }).addTo(mapa);
mapa.on('baselayerchange', e => { try { localStorage.setItem('mapaBase', e.name); } catch (_) {} });

// ---- Capas temáticas ----
const capaMarcadores = L.layerGroup().addTo(mapa);
const capaEnjambres = L.layerGroup().addTo(mapa);
const capaZonas = L.layerGroup().addTo(mapa);
let capaCalor = null;

const colorProf = p => p < 20 ? '#ff4d3d' : p < 70 ? '#ff9f1a' : p < 150 ? '#f5d90a' : '#3dd6ff';
const radioMag = m => Math.max(4, Math.pow(2, m) * 1.15);

const leyenda = L.control({ position: 'bottomright' });
leyenda.onAdd = () => {
  const d = L.DomUtil.create('div', 'leyenda');
  d.innerHTML = '<b>Profundidad</b><br>' +
    [['< 20 km', '#ff4d3d'], ['20–70', '#ff9f1a'], ['70–150', '#f5d90a'], ['> 150', '#3dd6ff']]
      .map(([t, c]) => `<i style="background:${c}"></i>${t}`).join('<br>') +
    '<br><small>Tamaño = magnitud</small>';
  return d;
};
leyenda.addTo(mapa);

// ---- Controles quiosco y panel ----
function quiosco(activar) {
  document.body.classList.toggle('quiosco', activar);
  setTimeout(() => mapa.invalidateSize(), 60);
  if (activar && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
  if (!activar && document.fullscreenElement) document.exitFullscreen?.();
}
function toggleLista(ver) {
  document.body.classList.toggle('sin-lista', !ver);
  setTimeout(() => mapa.invalidateSize(), 60);
  try { localStorage.setItem('verLista2', ver ? '1' : '0'); } catch (_) {}
}
const addCtrl = (title, txt, fn) => {
  const c = L.control({ position: 'topleft' });
  c.onAdd = () => {
    const b = L.DomUtil.create('div', 'leaflet-bar btn-pc');
    b.title = title;
    b.textContent = txt;
    L.DomEvent.on(b, 'click', e => { L.DomEvent.stop(e); fn(); });
    return b;
  };
  c.addTo(mapa);
};
addCtrl('Pantalla completa / quiosco (tecla F)', '⛶', () => quiosco(!document.body.classList.contains('quiosco')));
addCtrl('Mostrar / ocultar panel lateral (tecla L)', '☰', () => toggleLista(document.body.classList.contains('sin-lista')));
try { if (localStorage.getItem('verLista2') === '0') toggleLista(false); } catch (_) {}

// ---- Tabs ----
document.querySelectorAll('.tab').forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('activo'));
    document.querySelectorAll('.tab-body').forEach(p => p.classList.remove('activo'));
    btn.classList.add('activo');
    $('tab-' + btn.dataset.tab).classList.add('activo');
  };
});

// ---- Renderizado ----
function popupSismo(s) {
  return `<b>M${s.magnitud.toFixed(1)} (${s.tipo_mag})</b><br>${s.fecha_hlv} HLV<br>` +
    `Prof: ${s.profundidad_km} km<br>${s.lat}, ${s.lon}<br><i>${s.referencia || ''}</i>`;
}

function mostrarUltimo(s) {
  if (!s) {
    $('u-mag').textContent = '--';
    $('u-ref').textContent = 'Sin sismos en esta ventana';
    $('u-det').textContent = '';
    return;
  }
  $('u-mag').textContent = `M ${s.magnitud.toFixed(1)}`;
  $('u-mag').style.color = colorProf(s.profundidad_km);
  $('u-ref').textContent = s.referencia || `${s.lat}, ${s.lon}`;
  $('u-det').textContent = `${s.fecha_hlv} HLV · Prof. ${s.profundidad_km} km`;
}

function crearElementoSismo(s, esNuevo = false) {
  const c = L.circleMarker([s.lat, s.lon], {
    radius: radioMag(s.magnitud),
    color: '#fff',
    weight: 1,
    fillColor: colorProf(s.profundidad_km),
    fillOpacity: 0.82,
  }).bindPopup(popupSismo(s)).addTo(capaMarcadores);
  marcadores[s.id] = c;

  const li = document.createElement('li');
  li.innerHTML = `<div class="mag" style="background:${colorProf(s.profundidad_km)}">${s.magnitud.toFixed(1)}</div>` +
    `<div class="det">${s.referencia || (s.lat + ', ' + s.lon)}<small>${s.fecha_hlv} HLV · ${s.profundidad_km} km</small></div>`;
  li.onclick = () => { mapa.flyTo([s.lat, s.lon], 8); c.openPopup(); };
  if (esNuevo) {
    $('lista').prepend(li);
    li.classList.add('nuevo');
  } else {
    $('lista').append(li);
  }
}

function renderSismos(sismos) {
  capaMarcadores.clearLayers();
  marcadores = {};
  $('lista').innerHTML = '';
  $('cnt-sismos').textContent = sismos.length;
  sismos.forEach(s => crearElementoSismo(s, false));
  mostrarUltimo(sismos[0]);
  renderCalor(sismos);
}

function renderCalor(sismos) {
  if (capaCalor) {
    mapa.removeLayer(capaCalor);
    capaCalor = null;
  }
  if (!$('capa-calor').checked || !sismos.length || typeof L.heatLayer !== 'function') return;
  const puntos = sismos.map(s => [s.lat, s.lon, Math.min(1, Math.max(0.2, s.magnitud / 6))]);
  capaCalor = L.heatLayer(puntos, { radius: 26, blur: 18, maxZoom: 10 }).addTo(mapa);
}

function renderEnjambres(enjambres) {
  capaEnjambres.clearLayers();
  $('lista-enjambres').innerHTML = '';
  $('cnt-enj').textContent = enjambres.length;
  if (!enjambres.length) {
    $('lista-enjambres').innerHTML = '<li style="cursor:default;color:var(--muted)">Sin enjambres detectados en esta ventana.</li>';
    return;
  }
  enjambres.forEach(e => {
    const rangoFecha = e.inicio_hlv === e.fin_hlv ? `${e.fin_hlv} HLV` : `${e.inicio_hlv} → ${e.fin_hlv} HLV`;
    const circle = L.circle([e.centro_lat, e.centro_lon], {
      radius: e.radio_km * 1000,
      color: e.activo ? '#ff9f1a' : '#8b9bb0',
      weight: 2,
      dashArray: '6 4',
      fillOpacity: 0.08,
    }).bindPopup(
      `<b>Enjambre (${e.cantidad} sismos)</b><br>${e.referencia}<br>` +
      `Fecha: ${rangoFecha}<br>` +
      `Mag: ${e.mag_min.toFixed(1)} – ${e.mag_max.toFixed(1)}<br>Prof. prom: ${e.prof_prom} km`
    ).addTo(capaEnjambres);

    const li = document.createElement('li');
    li.innerHTML = `<div class="mag" style="background:${e.activo ? '#d35400' : '#34495e'}">${e.cantidad}</div>` +
      `<div class="det">${e.referencia} <span class="tag ${e.activo ? 'activo' : 'hist'}">${e.activo ? 'Activo' : 'Histórico'}</span>` +
      `<small>📅 ${rangoFecha}</small>` +
      `<small>M ${e.mag_min.toFixed(1)}–${e.mag_max.toFixed(1)} · Prof. prom. ${e.prof_prom} km</small></div>`;
    li.onclick = () => { mapa.flyTo([e.centro_lat, e.centro_lon], 9); circle.openPopup(); };
    $('lista-enjambres').append(li);
  });
}

function renderZonas(zonas) {
  capaZonas.clearLayers();
  $('lista-zonas').innerHTML = '';
  if (!zonas.length) {
    $('lista-zonas').innerHTML = '<li style="cursor:default;color:var(--muted)">Agrega zonas críticas arriba para monitorearlas.</li>';
    return;
  }
  zonas.forEach(z => {
    const c = L.circle([z.lat, z.lon], {
      radius: z.radio_km * 1000,
      color: '#3dd6ff',
      weight: 1.5,
      fillColor: '#3dd6ff',
      fillOpacity: 0.07,
    }).bindPopup(`<b>${z.nombre}</b> (${z.tipo})<br>Radio: ${z.radio_km} km · Mag ≥ ${z.mag_min}`).addTo(capaZonas);
    L.circleMarker([z.lat, z.lon], { radius: 5, color: '#fff', fillColor: '#3dd6ff', fillOpacity: 1 }).addTo(capaZonas);

    const li = document.createElement('li');
    li.innerHTML = `<div class="det"><b>${z.nombre}</b> (${z.tipo})<small>Radio ${z.radio_km} km · M ≥ ${z.mag_min} · ${z.lat}, ${z.lon}</small></div>` +
      `<button data-del="${z.id}" title="Eliminar zona">🗑</button>`;
    li.onclick = e => {
      if (e.target.dataset.del) return;
      mapa.flyTo([z.lat, z.lon], 9);
      c.openPopup();
    };
    li.querySelector('button').onclick = async () => {
      await fetch(`/api/zonas/${z.id}`, { method: 'DELETE' });
      cargarResumen(false);
    };
    $('lista-zonas').append(li);
  });
}

function renderAlertas(alertas) {
  const activas = alertas.filter(a => !a.atendida);
  $('cnt-al').textContent = activas.length;
  $('lista-alertas').innerHTML = '';
  if (!alertas.length) {
    $('lista-alertas').innerHTML = '<li style="cursor:default;color:var(--muted)">Sin alertas registradas.</li>';
    return;
  }
  alertas.slice(0, 20).forEach(a => {
    const li = document.createElement('li');
    li.style.opacity = a.atendida ? '0.55' : '1';
    li.innerHTML = `<div class="det"><span class="tag ${a.nivel}">${a.nivel}</span> <b>${a.titulo}</b><small>${a.detalle}</small></div>` +
      (a.atendida ? '' : `<button data-at="${a.id}">Atender</button>`);
    const btn = li.querySelector('button');
    if (btn) {
      btn.onclick = async () => {
        await fetch(`/api/alertas/${a.id}/atender`, { method: 'POST' });
        cargarResumen(false);
      };
    }
    $('lista-alertas').append(li);
  });
}

function renderBarras(contenedorId, obj, colores) {
  const cont = $(contenedorId);
  cont.innerHTML = '';
  const total = Object.values(obj).reduce((a, b) => a + b, 0) || 1;
  Object.entries(obj).forEach(([k, v], idx) => {
    const pct = Math.round((v / total) * 100);
    const row = document.createElement('div');
    row.className = 'barra-row';
    row.innerHTML = `<span>${k}</span><div class="barra-track"><div class="barra-fill" style="width:${pct}%;background:${colores[idx]}"></div></div><b>${v}</b>`;
    cont.append(row);
  });
}

function renderStats(st) {
  if (!st) return;
  $('st-total').textContent = st.total;
  $('st-magmax').textContent = st.mag_max.toFixed(1);
  $('st-prof').textContent = `${st.prof_prom} km`;
  $('st-sup').textContent = st.superficiales;

  renderBarras('st-barras-prof', st.por_profundidad, ['#ff4d3d', '#ff9f1a', '#f5d90a', '#3dd6ff']);
  renderBarras('st-barras-mag', st.por_magnitud, ['#5c768d', '#3dd6ff', '#ff9f1a', '#ff4d3d']);

  const dias = $('st-dias');
  dias.innerHTML = '';
  const maxD = Math.max(1, ...st.por_dia.map(d => d.cantidad));
  st.por_dia.forEach(d => {
    const h = Math.max(4, Math.round((d.cantidad / maxD) * 68));
    const col = document.createElement('div');
    col.className = 'dia-col';
    col.title = `${d.fecha}: ${d.cantidad} sismos`;
    col.innerHTML = `<div class="dia-bar" style="height:${h}px"></div><span class="dia-lbl">${d.fecha.slice(8)}</span>`;
    dias.append(col);
  });

  const refs = $('st-refs');
  refs.innerHTML = st.top_referencias.map(r => `<li><span>${r.referencia}</span><b>${r.cantidad}</b></li>`).join('') ||
    '<li style="color:var(--muted)">Sin datos</li>';
}

async function cargarResumen(ajustarVista = false) {
  const r = await fetch(`/api/resumen?horas=${horasActual}`);
  resumenActual = await r.json();
  renderSismos(resumenActual.sismos);
  renderEnjambres(resumenActual.enjambres);
  renderZonas(resumenActual.zonas);
  renderAlertas(resumenActual.alertas);
  renderStats(resumenActual.estadisticas);
  if (ajustarVista && resumenActual.sismos.length) {
    mapa.fitBounds(resumenActual.sismos.map(s => [s.lat, s.lon]), { padding: [40, 40], maxZoom: 7 });
  }
}

// ---- Filtros, capas y exportación ----
$('filtro-horas').querySelectorAll('button').forEach(btn => {
  btn.onclick = () => {
    $('filtro-horas').querySelectorAll('button').forEach(b => b.classList.remove('activo'));
    btn.classList.add('activo');
    horasActual = Number(btn.dataset.horas);
    cargarResumen(false);
  };
});

$('capa-marcadores').onchange = e => e.target.checked ? capaMarcadores.addTo(mapa) : mapa.removeLayer(capaMarcadores);
$('capa-calor').onchange = () => renderCalor(resumenActual.sismos);
$('capa-enjambres').onchange = e => e.target.checked ? capaEnjambres.addTo(mapa) : mapa.removeLayer(capaEnjambres);
$('capa-zonas').onchange = e => e.target.checked ? capaZonas.addTo(mapa) : mapa.removeLayer(capaZonas);

$('imp-btn').onclick = () => $('imp-arch').click();
$('imp-arch').onchange = async () => {
  const f = $('imp-arch').files[0];
  if (!f) return;
  const r = await fetch('/api/importar', { method: 'POST', body: f });
  const j = await r.json().catch(() => ({}));
  $('imp-arch').value = '';
  if (r.ok) {
    $('alerta-texto').textContent = `📥 Importación completada: ${j.insertados} registros agregados (${j.omitidos} duplicados o no válidos).`;
    $('alerta-banner').classList.remove('oculto');
    cargarResumen(true);
  } else {
    alert(j.error || 'No se pudo importar el archivo.');
  }
};
$('exp-csv').onclick = () => location.href = `/api/exportar?formato=csv&horas=${horasActual}`;
$('exp-geojson').onclick = () => location.href = `/api/exportar?formato=geojson&horas=${horasActual}`;
$('exp-html').onclick = () => window.open(`/api/exportar?formato=html&horas=${horasActual}`, '_blank');

// ---- Zonas críticas (picker y formulario) ----
$('z-pick').onclick = () => {
  eligiendoCoord = !eligiendoCoord;
  $('mapa').classList.toggle('picking', eligiendoCoord);
  $('z-pick').classList.toggle('activo', eligiendoCoord);
};
mapa.on('click', e => {
  if (!eligiendoCoord) return;
  $('z-lat').value = e.latlng.lat.toFixed(4);
  $('z-lon').value = e.latlng.lng.toFixed(4);
  eligiendoCoord = false;
  $('mapa').classList.remove('picking');
  $('z-pick').classList.remove('activo');
});
$('form-zona').onsubmit = async e => {
  e.preventDefault();
  const payload = {
    nombre: $('z-nombre').value.trim(),
    tipo: $('z-tipo').value,
    radio_km: Number($('z-radio').value),
    mag_min: Number($('z-mag').value),
    lat: Number($('z-lat').value),
    lon: Number($('z-lon').value),
  };
  const r = await fetch('/api/zonas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (r.ok) {
    $('z-nombre').value = '';
    cargarResumen(false);
  }
};

$('alerta-cerrar').onclick = () => {
  $('alerta-banner').classList.add('oculto');
  $('alerta-banner').classList.remove('critica');
};
$('alerta-ver-zonas').onclick = () => {
  document.querySelector('.tab[data-tab="zonas"]').click();
};
actualizarBtnSonido();
$('btn-sonido').onclick = () => {
  sonidoActivo = !sonidoActivo;
  try { localStorage.setItem('sonidoAlerta', sonidoActivo ? '1' : '0'); } catch (_) {}
  actualizarBtnSonido();
  if (sonidoActivo) sonarAlerta('media');
};
$('btn-probar-alerta').onclick = () => {
  const z = (resumenActual.zonas && resumenActual.zonas[0]) || { id: null, nombre: 'Zona Crítica de Prueba' };
  dispararAlertaVisualYSonora([{
    nivel: 'alta',
    zona_id: z.id,
    titulo: `Sismo M4.5 cerca de ${z.nombre}`,
    detalle: 'Distancia: 12.4 km · Prof: 10 km (simulación)',
  }], true);
};

// ---- Acerca de + logo ----
function refrescarLogo(hay) {
  const src = hay ? '/api/logo?t=' + Date.now() : '';
  for (const id of ['logo-lat', 'logo-q', 'logo-prev']) {
    const im = $(id);
    if (hay) { im.src = src; im.style.display = id === 'logo-q' ? '' : 'block'; }
    else { im.removeAttribute('src'); im.style.display = 'none'; }
  }
  $('logo-q').classList.toggle('hay', hay);
  $('logo-quitar').style.display = hay ? '' : 'none';
}
fetch('/api/info').then(r => r.json()).then(i => { $('ver').textContent = 'Versión ' + i.version; refrescarLogo(i.logo); });
$('abrir-acerca').onclick = () => $('acerca').classList.add('abierto');
$('abrir-acerca-link').onclick = e => { e.preventDefault(); $('acerca').classList.add('abierto'); };
$('cerrar-acerca').onclick = () => $('acerca').classList.remove('abierto');
$('acerca').onclick = e => { if (e.target.id === 'acerca') $('acerca').classList.remove('abierto'); };
$('logo-cargar').onclick = () => $('logo-arch').click();
$('logo-arch').onchange = async () => {
  const f = $('logo-arch').files[0]; if (!f) return;
  const r = await fetch('/api/logo', { method: 'POST', headers: { 'Content-Type': f.type }, body: f });
  const j = await r.json().catch(() => ({}));
  $('logo-msg').textContent = r.ok ? 'Logo cargado ✔' : (j.error || 'No se pudo cargar');
  if (r.ok) refrescarLogo(true);
  $('logo-arch').value = '';
};
$('logo-quitar').onclick = async () => {
  const r = await fetch('/api/logo', { method: 'DELETE' });
  $('logo-msg').textContent = r.ok ? 'Logo quitado' : 'No se pudo quitar';
  if (r.ok) refrescarLogo(false);
};

// ---- Atajos de teclado y reloj ----
document.addEventListener('keydown', e => {
  if ($('acerca').classList.contains('abierto')) { if (e.key === 'Escape') $('acerca').classList.remove('abierto'); return; }
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === 'f' || e.key === 'F') quiosco(!document.body.classList.contains('quiosco'));
  if (e.key === 'l' || e.key === 'L') toggleLista(document.body.classList.contains('sin-lista'));
  if (e.key === 'Escape') quiosco(false);
});
if (new URLSearchParams(location.search).has('quiosco')) quiosco(true);

setInterval(() => {
  $('reloj').textContent = new Date().toLocaleString('es-VE', {
    timeZone: 'America/Caracas', hour12: false,
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }) + ' HLV';
}, 1000);

// ---- Tiempo real (SSE) ----
function conectar() {
  const es = new EventSource('/api/stream');
  const p = $('punto'), e = $('estado');
  es.onopen = () => { p.classList.add('vivo'); e.textContent = 'en vivo'; };
  es.onmessage = ev => {
    const data = JSON.parse(ev.data);
    const s = data.sismo || data;
    const alertas = data.alertas || [];
    if (!marcadores[s.id]) {
      resumenActual.sismos.unshift(s);
      crearElementoSismo(s, true);
      mostrarUltimo(s);
      const onda = L.marker([s.lat, s.lon], { icon: L.divIcon({ className: 'pulso', iconSize: [60, 60] }) }).addTo(mapa);
      setTimeout(() => mapa.removeLayer(onda), 15000);
      mapa.flyTo([s.lat, s.lon], 8);
      marcadores[s.id].openPopup();
      document.title = `🔴 M${s.magnitud} – Sismos 2.0`;
      if (Notification?.permission === 'granted' && !alertas.length) new Notification(`Sismo M${s.magnitud}`, { body: s.referencia });
      cargarResumen(false);
    }
    if (alertas.length) {
      dispararAlertaVisualYSonora(alertas, false);
    }
  };
  es.onerror = () => { p.classList.remove('vivo'); e.textContent = 'reconectando…'; };
}

cargarResumen(true);
conectar();
if (window.Notification && Notification.permission === 'default') Notification.requestPermission();
