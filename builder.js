// Harness Builder: vanilla-JS canvas UI driven by the vendored ranchharness
// Python core, running in-browser via Pyodide. All geometry (pin positions,
// box sizes, wire curves) comes from Python so the canvas and the SVG/CSV
// exports always agree.

const CORE_BASE = 'ranchharness-core';
const CORE_FILES = ['__init__.py', 'model.py', 'library.py', 'layout.py',
  'colors.py', 'svg.py', 'exports.py', 'checks.py', 'tools.py'];

const GRID = 10;
const HIT_R = 13;
const ZOOM_FACTOR = 1.15;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 6;

let pyodide, webApi;
let appState = { connectors: [], wires: [], issues: [], selected: null };
let view = { scale: 1, tx: 60, ty: 60 };
let selection = null; // {kind: 'connector'|'wire', id}
let pinIndex = [];    // flat [{cid, pin, x, y}] rebuilt from appState each render

const canvas = document.getElementById('harness-canvas');
const ctx = canvas.getContext('2d');
const wrap = canvas.closest('.canvas-wrap');

function pyCall(name, ...args) {
  const r = webApi[name](...args);
  if (r && typeof r.toJs === 'function') {
    const out = r.toJs({ dict_converter: Object.fromEntries });
    r.destroy();
    return out;
  }
  return r;
}

function pyCallKw(name, args, kwargs) {
  const r = webApi[name].callKwargs(...args, kwargs);
  if (r && typeof r.toJs === 'function') {
    const out = r.toJs({ dict_converter: Object.fromEntries });
    r.destroy();
    return out;
  }
  return r;
}

async function initPyodide() {
  pyodide = await loadPyodide();
  pyodide.FS.mkdirTree(`/${CORE_BASE}/ranchharness`);
  for (const f of CORE_FILES) {
    const text = await (await fetch(`${CORE_BASE}/ranchharness/${f}`)).text();
    pyodide.FS.writeFile(`/${CORE_BASE}/ranchharness/${f}`, text);
  }
  const webApiText = await (await fetch(`${CORE_BASE}/web_api.py`)).text();
  pyodide.FS.writeFile(`/${CORE_BASE}/web_api.py`, webApiText);
  pyodide.runPython(`import sys\nsys.path.insert(0, '/${CORE_BASE}')`);
  webApi = pyodide.pyimport('web_api');
}

// ---- rendering ------------------------------------------------------------

function resizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const w = wrap.clientWidth, h = wrap.clientHeight;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  draw();
}

function toScreen(x, y) { return [x * view.scale + view.tx, y * view.scale + view.ty]; }
function toModel(x, y) { return [(x - view.tx) / view.scale, (y - view.ty) / view.scale]; }

function rebuildPinIndex() {
  pinIndex = [];
  for (const c of appState.connectors) {
    for (const pin of c.pins) {
      const [x, y] = c.pin_ports[pin];
      pinIndex.push({ cid: c.id, pin, x, y, isNode: c.is_node });
    }
  }
}

function connectorAt(mx, my) {
  for (let i = appState.connectors.length - 1; i >= 0; i--) {
    const c = appState.connectors[i];
    if (mx >= c.x && mx <= c.x + c.w && my >= c.y && my <= c.y + c.h) return c;
  }
  return null;
}

function pinAt(mx, my, excludeCid, excludePin, allowNodes = true) {
  let best = null, bestD = HIT_R;
  for (const p of pinIndex) {
    if (p.cid === excludeCid && p.pin === excludePin) continue;
    if (p.isNode && !allowNodes) continue;
    const d = Math.hypot(p.x - mx, p.y - my);
    if (d <= bestD) { best = p; bestD = d; }
  }
  return best;
}

function bezierPoint(pts, t) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = pts;
  const u = 1 - t;
  return [
    u ** 3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t ** 3 * x3,
    u ** 3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y3,
  ];
}

function distToWire(wire, mx, my) {
  let best = Infinity;
  for (let i = 0; i <= 20; i++) {
    const [x, y] = bezierPoint(wire.curve, i / 20);
    best = Math.min(best, Math.hypot(x - mx, y - my));
  }
  return best;
}

let dragWire = null; // {fromCid, fromPin, x, y, hover}
let dragConn = null; // {cid}

function draw() {
  const dpr = window.devicePixelRatio || 1;
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);
  ctx.fillStyle = '#0e1114';
  ctx.fillRect(0, 0, canvas.width / dpr, canvas.height / dpr);

  // wires
  for (const w of appState.wires) {
    const pts = w.curve.map(([x, y]) => toScreen(x, y));
    const selected = selection && selection.kind === 'wire' && selection.id === w.id;
    ctx.beginPath();
    ctx.moveTo(...pts[0]);
    ctx.bezierCurveTo(pts[1][0], pts[1][1], pts[2][0], pts[2][1], pts[3][0], pts[3][1]);
    ctx.lineWidth = selected ? 3.5 : 2.5;
    ctx.strokeStyle = selected ? '#ef3b2d' : (w.hex || '#9aa6b2');
    ctx.lineCap = 'round';
    ctx.stroke();
    if (view.scale > 0.5) {
      const [mx, my] = bezierPoint(w.curve, 0.5);
      const [sx, sy] = toScreen(mx, my);
      ctx.font = '10px "JetBrains Mono", monospace';
      ctx.fillStyle = '#9aa6b2';
      ctx.fillText(w.label, sx + 4, sy - 4);
    }
  }

  // drag-to-wire preview
  if (dragWire) {
    const [sx1, sy1] = toScreen(dragWire.x0, dragWire.y0);
    const [sx2, sy2] = toScreen(dragWire.x, dragWire.y);
    ctx.save();
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = '#ef3b2d';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sx1, sy1);
    ctx.lineTo(sx2, sy2);
    ctx.stroke();
    ctx.restore();
  }

  // connectors
  for (const c of appState.connectors) {
    const selected = selection && selection.kind === 'connector' && selection.id === c.id;
    const [sx, sy] = toScreen(c.x, c.y);
    const sw = c.w * view.scale, sh = c.h * view.scale;

    if (c.is_node) {
      const [cx, cy] = [sx + sw / 2, sy + sh / 2];
      ctx.beginPath();
      ctx.arc(cx, cy, Math.max(4, sw / 2), 0, Math.PI * 2);
      ctx.fillStyle = '#1a2027';
      ctx.strokeStyle = selected ? '#ef3b2d' : '#9aa6b2';
      ctx.lineWidth = selected ? 2.5 : 1.5;
      ctx.fill();
      ctx.stroke();
      if (view.scale > 0.3) {
        ctx.fillStyle = '#ef3b2d';
        ctx.font = `${Math.max(9, 11 * view.scale)}px "JetBrains Mono", monospace`;
        ctx.textAlign = 'center';
        ctx.fillText(c.ref, cx, cy - 8 * view.scale - 4);
        if (c.label) {
          ctx.fillStyle = '#9aa6b2';
          ctx.font = `${Math.max(8, 10 * view.scale)}px Inter, sans-serif`;
          ctx.fillText(truncate(c.label, 20), cx, cy + sw / 2 + 14);
        }
        ctx.textAlign = 'left';
      }
      for (const pin of c.pins) {
        const [px, py] = c.pin_ports[pin];
        const [spx, spy] = toScreen(px, py);
        const hover = dragWire && dragWire.hover && dragWire.hover.cid === c.id && dragWire.hover.pin === pin;
        ctx.beginPath();
        ctx.arc(spx, spy, hover ? 6 : 3, 0, Math.PI * 2);
        ctx.fillStyle = hover ? '#ef3b2d' : '#0e1114';
        ctx.strokeStyle = '#9aa6b2';
        ctx.lineWidth = 1.5;
        ctx.fill();
        ctx.stroke();
      }
      continue;
    }

    ctx.fillStyle = '#1a2027';
    ctx.strokeStyle = selected ? '#ef3b2d' : '#2a323b';
    ctx.lineWidth = selected ? 2.5 : 1.5;
    roundRect(sx, sy, sw, sh, 6 * view.scale);
    ctx.fill();
    ctx.stroke();

    const headerH = 46 * view.scale;
    ctx.fillStyle = '#ef3b2d';
    ctx.font = `${Math.max(9, 12 * view.scale)}px "JetBrains Mono", monospace`;
    ctx.fillText(c.ref, sx + 8 * view.scale, sy + 16 * view.scale);
    if (view.scale > 0.35) {
      ctx.fillStyle = '#e7ebef';
      ctx.font = `${Math.max(9, 12 * view.scale)}px Inter, sans-serif`;
      const label = c.label || '(unlabeled)';
      ctx.fillText(truncate(label, 24), sx + 8 * view.scale, sy + 34 * view.scale);
    }

    if (view.scale > 0.3) {
      c.pins.forEach((pin, i) => {
        const rowY = sy + headerH + (22 * view.scale) * i;
        ctx.strokeStyle = '#2a323b';
        ctx.beginPath();
        ctx.moveTo(sx, rowY);
        ctx.lineTo(sx + sw, rowY);
        ctx.stroke();
        ctx.fillStyle = '#9aa6b2';
        ctx.font = `${Math.max(8, 10 * view.scale)}px "JetBrains Mono", monospace`;
        ctx.fillText(pin, sx + 6 * view.scale, rowY + 15 * view.scale);
        const name = c.pin_names[pin];
        if (name) {
          ctx.fillStyle = '#e7ebef';
          ctx.font = `${Math.max(8, 10 * view.scale)}px Inter, sans-serif`;
          ctx.fillText(truncate(name, 16), sx + 28 * view.scale, rowY + 15 * view.scale);
        }
      });
    }

    // pin dots
    for (const pin of c.pins) {
      const [px, py] = c.pin_ports[pin];
      const [spx, spy] = toScreen(px, py);
      const hover = dragWire && dragWire.hover && dragWire.hover.cid === c.id && dragWire.hover.pin === pin;
      ctx.beginPath();
      ctx.arc(spx, spy, hover ? 6 : 4, 0, Math.PI * 2);
      ctx.fillStyle = hover ? '#ef3b2d' : '#0e1114';
      ctx.strokeStyle = '#9aa6b2';
      ctx.lineWidth = 1.5;
      ctx.fill();
      ctx.stroke();
    }
  }

  ctx.restore();
}

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }

// ---- state / side panel -----------------------------------------------

function applyState(next, keepSelection) {
  appState = next;
  rebuildPinIndex();
  if (!keepSelection) {
    selection = appState.selected
      ? (appState.wires.some(w => w.id === appState.selected)
          ? { kind: 'wire', id: appState.selected }
          : { kind: 'connector', id: appState.selected })
      : null;
  }
  syncSidePanel();
  syncChecks();
  syncQuoteJson();
  draw();
}

function syncQuoteJson() {
  const field = document.getElementById('quote-harness-json');
  if (field) field.value = pyCall('to_json');
}

function syncChecks() {
  const list = document.getElementById('checks-list');
  const empty = document.getElementById('checks-empty');
  const badge = document.getElementById('checks-badge');
  list.innerHTML = '';
  const issues = appState.issues || [];
  badge.hidden = issues.length === 0;
  badge.textContent = String(issues.length);
  empty.hidden = issues.length > 0;
  for (const issue of issues) {
    const li = document.createElement('li');
    li.className = issue.level;
    li.innerHTML = `<span class="level-dot"></span><span>${escapeHtml(issue.message)}</span>`;
    list.appendChild(li);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const AWG_SELECT = document.getElementById('w-awg');
const COLOR_SELECT = document.getElementById('w-color');
const TYPE_SELECT = document.getElementById('w-type');

function fillCatalog() {
  const cat = pyCall('catalog');
  AWG_SELECT.innerHTML = cat.awg.map(a => `<option value="${a}">${a} AWG</option>`).join('');
  COLOR_SELECT.innerHTML = cat.colors.map(c => `<option value="${c}">${c}</option>`).join('');
  TYPE_SELECT.innerHTML = cat.wire_types.map(t => `<option value="${t}">${t}</option>`).join('');
}

function syncSidePanel() {
  const empty = document.getElementById('details-empty');
  const cForm = document.getElementById('connector-form');
  const wForm = document.getElementById('wire-form');
  cForm.hidden = true; wForm.hidden = true; empty.hidden = false;

  if (!selection) return;
  if (selection.kind === 'connector') {
    const c = appState.connectors.find(x => x.id === selection.id);
    if (!c) { selection = null; return; }
    empty.hidden = true; cForm.hidden = false;
    document.getElementById('c-kind-label').textContent = c.is_node ? 'Splice' : 'Connector';
    document.getElementById('c-pins-wrap').hidden = c.is_node;
    document.getElementById('c-ref').value = c.ref;
    document.getElementById('c-label').value = c.label;
    document.getElementById('c-positions').value = c.positions || c.pins.length;
    document.getElementById('c-flipped').checked = c.flipped;
  } else {
    const w = appState.wires.find(x => x.id === selection.id);
    if (!w) { selection = null; return; }
    empty.hidden = true; wForm.hidden = false;
    document.getElementById('w-label').value = w.label;
    document.getElementById('w-signal').value = w.signal;
    AWG_SELECT.value = String(w.awg);
    COLOR_SELECT.value = w.color;
    TYPE_SELECT.value = w.wire_type;
    document.getElementById('w-length').value = w.length_mm;
  }
}

// ---- toolbar ------------------------------------------------------------

document.getElementById('add-connector-btn').addEventListener('click', () => {
  const positions = Math.max(1, Math.min(48, parseInt(document.getElementById('pin-count').value, 10) || 1));
  const label = document.getElementById('conn-label').value.trim();
  const [mx, my] = toModel(wrap.clientWidth / 2, wrap.clientHeight / 2);
  const x = Math.round(mx / GRID) * GRID - 105;
  const y = Math.round(my / GRID) * GRID - 40;
  applyState(pyCall('add_connector', 'GENERIC-CONN', positions, x, y, label));
  document.getElementById('conn-label').value = '';
});

document.getElementById('add-splice-btn').addEventListener('click', () => {
  const label = document.getElementById('conn-label').value.trim();
  const [mx, my] = toModel(wrap.clientWidth / 2, wrap.clientHeight / 2);
  const x = Math.round(mx / GRID) * GRID;
  const y = Math.round(my / GRID) * GRID;
  applyState(pyCall('add_connector', 'SPLICE', 1, x, y, label));
  document.getElementById('conn-label').value = '';
});

document.getElementById('save-json-btn').addEventListener('click', () => {
  const text = pyCall('to_json');
  const name = (appState.name || 'harness').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'harness';
  download(`${name}.harness.json`, text, 'application/json');
});

document.getElementById('load-btn').addEventListener('click', () => document.getElementById('load-input').click());
document.getElementById('load-input').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  try {
    applyState(pyCall('load_harness', text));
  } catch (err) {
    alert("That doesn't look like a valid .harness.json file.");
  }
  e.target.value = '';
});

document.getElementById('export-svg').addEventListener('click', (e) => {
  e.preventDefault();
  download('harness.svg', pyCall('export_svg'), 'image/svg+xml');
});
document.getElementById('export-wirelist').addEventListener('click', (e) => {
  e.preventDefault();
  download('wire-list.csv', pyCall('export_wirelist_csv'), 'text/csv');
});
document.getElementById('export-bom').addEventListener('click', (e) => {
  e.preventDefault();
  download('bom.csv', pyCall('export_bom_csv'), 'text/csv');
});

function download(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// side-tab switching
document.querySelectorAll('.side-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.side-tab').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
    document.querySelectorAll('.side-panel').forEach(p => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
  });
});

// connector property form
const cLabel = document.getElementById('c-label');
const cPositions = document.getElementById('c-positions');
const cFlipped = document.getElementById('c-flipped');
[cLabel].forEach(el => el.addEventListener('change', () => {
  if (selection?.kind === 'connector') applyState(pyCallKw('update_connector', [selection.id], { label: cLabel.value }), true);
}));
cPositions.addEventListener('change', () => {
  if (selection?.kind === 'connector') {
    const n = Math.max(1, Math.min(48, parseInt(cPositions.value, 10) || 1));
    applyState(pyCallKw('update_connector', [selection.id], { positions: n }), true);
  }
});
cFlipped.addEventListener('change', () => {
  if (selection?.kind === 'connector') applyState(pyCallKw('update_connector', [selection.id], { flipped: cFlipped.checked }), true);
});
document.getElementById('c-delete').addEventListener('click', () => {
  if (selection?.kind === 'connector') { applyState(pyCall('delete_connector', selection.id)); selection = null; syncSidePanel(); draw(); }
});

// wire property form
const wLabel = document.getElementById('w-label');
const wSignal = document.getElementById('w-signal');
const wLength = document.getElementById('w-length');
[wLabel, wSignal].forEach(el => el.addEventListener('change', () => {
  if (selection?.kind === 'wire') applyState(pyCallKw('update_wire', [selection.id], { label: wLabel.value, signal: wSignal.value }), true);
}));
wLength.addEventListener('change', () => {
  if (selection?.kind === 'wire') applyState(pyCallKw('update_wire', [selection.id], { length_mm: parseFloat(wLength.value) || 0 }), true);
});
[AWG_SELECT, COLOR_SELECT, TYPE_SELECT].forEach(el => el.addEventListener('change', () => {
  if (selection?.kind === 'wire') {
    applyState(pyCallKw('update_wire', [selection.id], {
      awg: parseInt(AWG_SELECT.value, 10), color: COLOR_SELECT.value, wire_type: TYPE_SELECT.value,
    }), true);
  }
}));
document.getElementById('w-delete').addEventListener('click', () => {
  if (selection?.kind === 'wire') { applyState(pyCall('delete_wire', selection.id)); selection = null; syncSidePanel(); draw(); }
});

// ---- canvas interaction ---------------------------------------------------

let panDrag = null;

canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('mousedown', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const [mx, my] = toModel(sx, sy);

  if (e.button === 1 || e.button === 2) {
    panDrag = { sx, sy, tx0: view.tx, ty0: view.ty };
    return;
  }

  const pin = pinAt(mx, my, null, null, e.ctrlKey || e.metaKey);
  if (pin) {
    dragWire = { fromCid: pin.cid, fromPin: pin.pin, x0: pin.x, y0: pin.y, x: mx, y: my, hover: null };
    return;
  }

  const conn = connectorAt(mx, my);
  if (conn) {
    selection = { kind: 'connector', id: conn.id };
    syncSidePanel();
    dragConn = { cid: conn.id, offX: mx - conn.x, offY: my - conn.y, moved: false };
    draw();
    return;
  }

  let hitWire = null;
  for (const w of appState.wires) {
    if (distToWire(w, mx, my) <= 6 / view.scale) { hitWire = w; break; }
  }
  selection = hitWire ? { kind: 'wire', id: hitWire.id } : null;
  syncSidePanel();
  draw();
});

canvas.addEventListener('mousemove', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const [mx, my] = toModel(sx, sy);

  if (panDrag) {
    view.tx = panDrag.tx0 + (sx - panDrag.sx);
    view.ty = panDrag.ty0 + (sy - panDrag.sy);
    draw();
    return;
  }
  if (dragWire) {
    dragWire.x = mx; dragWire.y = my;
    dragWire.hover = pinAt(mx, my, dragWire.fromCid, dragWire.fromPin);
    draw();
    return;
  }
  if (dragConn) {
    dragConn.moved = true;
    const nx = Math.round((mx - dragConn.offX) / GRID) * GRID;
    const ny = Math.round((my - dragConn.offY) / GRID) * GRID;
    applyState(pyCall('move_connector', dragConn.cid, nx, ny), true);
    selection = { kind: 'connector', id: dragConn.cid };
  }
});

window.addEventListener('mouseup', () => {
  if (dragWire) {
    if (dragWire.hover) {
      applyState(pyCallKw('add_wire', [dragWire.fromCid, dragWire.fromPin, dragWire.hover.cid, dragWire.hover.pin],
        { awg: 18, color: 'BK', wire_type: 'TXL', length_mm: 500, signal: '' }));
    }
    dragWire = null;
    draw();
  }
  dragConn = null;
  panDrag = null;
});

canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const factor = e.deltaY < 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;
  zoomAt(sx, sy, factor);
}, { passive: false });

function zoomAt(sx, sy, factor) {
  const newScale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, view.scale * factor));
  const [mx, my] = toModel(sx, sy);
  view.scale = newScale;
  view.tx = sx - mx * newScale;
  view.ty = sy - my * newScale;
  draw();
}

document.getElementById('zoom-in').addEventListener('click', () => zoomAt(wrap.clientWidth / 2, wrap.clientHeight / 2, ZOOM_FACTOR));
document.getElementById('zoom-out').addEventListener('click', () => zoomAt(wrap.clientWidth / 2, wrap.clientHeight / 2, 1 / ZOOM_FACTOR));
document.getElementById('zoom-fit').addEventListener('click', fitView);

function fitView() {
  if (appState.connectors.length === 0) { view = { scale: 1, tx: 60, ty: 60 }; draw(); return; }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const c of appState.connectors) {
    minX = Math.min(minX, c.x); minY = Math.min(minY, c.y);
    maxX = Math.max(maxX, c.x + c.w); maxY = Math.max(maxY, c.y + c.h);
  }
  const pad = 40;
  const scaleX = wrap.clientWidth / (maxX - minX + pad * 2);
  const scaleY = wrap.clientHeight / (maxY - minY + pad * 2);
  view.scale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.min(scaleX, scaleY)));
  view.tx = -minX * view.scale + pad * view.scale;
  view.ty = -minY * view.scale + pad * view.scale;
  draw();
}

window.addEventListener('keydown', (e) => {
  if ((e.key === 'Delete' || e.key === 'Backspace') && selection &&
      !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
    if (selection.kind === 'connector') applyState(pyCall('delete_connector', selection.id));
    else applyState(pyCall('delete_wire', selection.id));
    selection = null;
  }
});

new ResizeObserver(resizeCanvas).observe(wrap);

// ---- boot -----------------------------------------------------------------

(async function boot() {
  await initPyodide();
  fillCatalog();
  applyState(pyCall('new_harness', 'Untitled harness'));
  resizeCanvas();
  document.getElementById('builder-loading').classList.add('hidden');
  document.getElementById('builder-app').setAttribute('aria-busy', 'false');
})().catch((err) => {
  console.error(err);
  const loading = document.getElementById('builder-loading');
  loading.querySelector('p').textContent = 'Something went wrong loading the builder. Try reloading the page.';
});
