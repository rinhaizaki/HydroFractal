/* HydroFractal Web — интерфейс приложения.
   Все расчёты выполняет сервер (app.py + core/), браузер отвечает за холст,
   инструменты и отображение результатов. */
(function () {
  'use strict';

  // GitHub Pages: серверного API нет, расчёты выполняет static/client-core.js
  const STATIC_MODE = !!(window.HFClient && (window.HF_STATIC || /github\.io$/i.test(location.hostname) || location.protocol === 'file:'));

  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const fmt = (v, n = 3) => (v === null || v === undefined || Number.isNaN(Number(v))
    ? '—' : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: n, minimumFractionDigits: 0 }));

  const el = {
    photoCanvas: $('photoCanvas'), photoWrap: $('photoWrap'), photoPlaceholder: $('photoPlaceholder'),
    minimapBox: $('minimapBox'), minimapCanvas: $('minimapCanvas'),
    photoInfo: $('photoInfo'), cursorInfo: $('cursorInfo'),
    report: $('reportText'), plot: $('plotImg'), plotEmpty: $('plotEmpty'),
    tableWrap: $('tableWrap'), streamWrap: $('streamWrap'),
    tableDetails: $('tableDetails'), streamDetails: $('streamDetails'),
    mapCanvas: $('mapCanvas'), mapWrap: $('mapWrap'), mapPlaceholder: $('mapPlaceholder'),
    mapReport: $('mapReport'), mapPlot: $('mapPlotImg'), mapPlotEmpty: $('mapPlotEmpty'),
    mapTableWrap: $('mapTableWrap'), mapTableDetails: $('mapTableDetails'),
    mapCredit: $('mapCredit'), mapZoom: $('mapZoom'), mapCoords: $('mapCoords'),
    mapLat: $('mapLat'), mapLon: $('mapLon'), mapMarkText: $('mapMarkText'),
    leafletWrap: $('leafletMap'),
    mapMinimapBox: $('mapMinimapBox'), mapMinimapCanvas: $('mapMinimapCanvas'),
    status: $('status'), statusRight: $('statusRight'),
    toast: $('toast'), modal: $('modal'), modalTitle: $('modalTitle'), modalBody: $('modalBody'),
    fileInput: $('fileInput')
  };

  const maskCanvas = document.createElement('canvas');
  const maskCtx = maskCanvas.getContext('2d', { willReadFrequently: true });
  const apiMaskCanvas = document.createElement('canvas');
  const apiMaskCtx = apiMaskCanvas.getContext('2d');

  const S = {
    baseDataURL: null, image: null, W: 0, H: 0, sourceName: '',
    seed: null, colorPoints: [], view: 'overlay', tool: 'point',
    zoom: 1, cx: 0, cy: 0, fit: 1,
    undo: [], redo: [], painting: false, panning: false, lastPaint: null, lastPointer: null,
    result: null, waterPixels: 0, waterShare: 0, minimapVisible: false, maskNonEmpty: false,
    overlayDataURL: null, maskTouched: false,
    crop: { active: false, start: null, end: null },
    mapTabLoaded: false, activeTab: 'photo',
    map: {
      lon: 30.33510, lat: 59.93428, zoom: 11, source: 'esri', relief: false,
      img: null, geo: null, outlet: null, result: null, info: null,
      credit: 'Карта: Esri · Рельеф: AWS Terrain Tiles', demo: false, cell: 0,
      panDx: 0, panDy: 0, dragStart: null, moved: false, loading: false,
      tiles: [], reliefImg: null, overlayImg: null, reportImage: null, mask: null, width: 0, height: 0,
      minimapVisible: false, miniKey: '', miniResp: null,
      leaflet: null, tileLayer: null, layerIndex: 0, tileErrors: 0,
      marks: [], markMode: false,
      leafletCredit: 'Снимок: Esri, Maxar, Earthstar Geographics',
      overlayGeo: null, reliefGeo: null, moveTimer: null
    }
  };

  const INITIAL_REPORT = el.report.textContent;
  const INITIAL_MAP_REPORT = el.mapReport.textContent;

  // ------------------------------------------------------------------ utils
  function status(message, error) {
    el.status.textContent = message;
    el.status.classList.toggle('error', !!error);
  }
  let toastTimer = null;
  function toast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 3600);
  }
  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('Не удалось прочитать изображение.'));
      img.src = src;
    });
  }
  async function api(path, payload) {
    if (STATIC_MODE) return window.HFClient.dispatch(path, payload || {});
    let res;
    try {
      res = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
      });
    } catch (e) {
      throw new Error('Нет связи с сервером. Проверьте, что запущен app.py.');
    }
    let data;
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `Ошибка сервера (${res.status}).`);
    }
    return data;
  }
  async function download(path, payload, filename) {
    if (STATIC_MODE) return window.HFClient.download(path, payload || {}, filename);
    let res;
    try {
      res = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
      });
    } catch (e) { throw new Error('Нет связи с сервером.'); }
    if (!res.ok) {
      let data = {};
      try { data = await res.json(); } catch (e) { /* ignore */ }
      throw new Error(data.error || `Ошибка сервера (${res.status}).`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  function busy(isBusy, message) {
    document.body.style.cursor = isBusy ? 'progress' : '';
    if (message) status(message);
    ['btnSegment', 'btnAnalyze', 'btnSaveMask', 'btnSaveReport', 'btnMapCatch', 'btnMapDim', 'btnMapPdf']
      .forEach((id) => { $(id).disabled = isBusy; });
  }
  function openModal(title, html) {
    el.modalTitle.textContent = title;
    el.modalBody.innerHTML = html;
    el.modal.hidden = false;
  }
  function closeModal() { el.modal.hidden = true; }

  function buildTable(rows, target, headings) {
    if (!rows || !rows.length) { target.innerHTML = ''; return; }
    const parts = ['<table class="data"><thead><tr>'];
    headings.forEach((h) => parts.push(`<th>${h}</th>`));
    parts.push('</tr></thead><tbody>');
    rows.forEach((r) => {
      parts.push('<tr>');
      r.forEach((c) => parts.push(`<td>${String(c)}</td>`));
      parts.push('</tr>');
    });
    parts.push('</tbody></table>');
    target.innerHTML = parts.join('');
  }

  // ----------------------------------------------------------- состояние маски
  function initMask(w, h) {
    maskCanvas.width = apiMaskCanvas.width = w;
    maskCanvas.height = apiMaskCanvas.height = h;
    maskCtx.clearRect(0, 0, w, h);
    apiMaskCtx.clearRect(0, 0, w, h);
    S.maskNonEmpty = false;
  }
  function hasMask() { return !!S.maskNonEmpty; }
  async function setMaskFromDataURL(dataURL) {
    const img = await loadImage(dataURL);
    const tmp = document.createElement('canvas');
    tmp.width = S.W; tmp.height = S.H;
    const ctx = tmp.getContext('2d');
    ctx.drawImage(img, 0, 0, S.W, S.H);
    // сервер отдаёт ч/б PNG: белая вода, чёрный фон. Яркость → прозрачность.
    const pixels = ctx.getImageData(0, 0, S.W, S.H);
    for (let i = 0; i < pixels.data.length; i += 4) {
      const luminance = pixels.data[i];
      pixels.data[i] = 40; pixels.data[i + 1] = 220; pixels.data[i + 2] = 80;
      pixels.data[i + 3] = luminance;
    }
    ctx.putImageData(pixels, 0, 0);
    maskCtx.clearRect(0, 0, S.W, S.H);
    maskCtx.drawImage(tmp, 0, 0);
    S.maskNonEmpty = true;
  }
  function maskForApi() {
    const src = maskCtx.getImageData(0, 0, S.W, S.H).data;
    const out = apiMaskCtx.createImageData(S.W, S.H);
    for (let i = 0, p = 0; i < src.length; i += 4, p += 4) {
      const v = src[i + 3] > 127 ? 255 : 0;
      out.data[p] = out.data[p + 1] = out.data[p + 2] = v;
      out.data[p + 3] = 255;
    }
    apiMaskCtx.putImageData(out, 0, 0);
    return apiMaskCanvas.toDataURL('image/png');
  }
  function pushUndo() {
    if (!S.W) return;
    S.undo.push({
      data: maskCtx.getImageData(0, 0, S.W, S.H),
      seed: S.seed ? { ...S.seed } : null,
      points: S.colorPoints.map((p) => ({ ...p })),
      nonEmpty: S.maskNonEmpty
    });
    if (S.undo.length > 24) S.undo.shift();
    S.redo.length = 0;
    updateHistoryButtons();
  }
  function restoreSnapshot(snap) {
    maskCtx.putImageData(snap.data, 0, 0);
    S.seed = snap.seed;
    S.colorPoints = snap.points.map((p) => ({ ...p }));
    S.maskNonEmpty = !!snap.nonEmpty;
    updateHistoryButtons();
    renderPhoto();
  }
  function undo() {
    if (!S.undo.length) return;
    S.redo.push({
      data: maskCtx.getImageData(0, 0, S.W, S.H),
      seed: S.seed ? { ...S.seed } : null,
      points: S.colorPoints.map((p) => ({ ...p })),
      nonEmpty: S.maskNonEmpty
    });
    restoreSnapshot(S.undo.pop());
    status('Отменено последнее действие.');
  }
  function redo() {
    if (!S.redo.length) return;
    S.undo.push({
      data: maskCtx.getImageData(0, 0, S.W, S.H),
      seed: S.seed ? { ...S.seed } : null,
      points: S.colorPoints.map((p) => ({ ...p })),
      nonEmpty: S.maskNonEmpty
    });
    restoreSnapshot(S.redo.pop());
    status('Действие повторено.');
  }
  function updateHistoryButtons() {
    $('btnUndo').disabled = !S.undo.length;
    $('btnRedo').disabled = !S.redo.length;
  }
  function clearMask() {
    if (!S.image) { toast('Сначала загрузите снимок.'); return; }
    pushUndo();
    maskCtx.clearRect(0, 0, S.W, S.H);
    S.maskNonEmpty = false; S.maskTouched = true;
    renderPhoto();
    status('Маска очищена. Нажмите «Рассчитать D», чтобы обновить результат.');
  }

  // ------------------------------------------------------------------ холст
  function prepCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width)), h = Math.max(1, Math.round(rect.height));
    const iw = Math.max(1, Math.round(rect.width * dpr)), ih = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== iw || canvas.height !== ih) { canvas.width = iw; canvas.height = ih; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx, w, h };
  }
  function photoTransform(cw, ch) {
    const scale = S.fit * S.zoom;
    return { scale, dx: cw / 2 - S.cx * scale, dy: ch / 2 - S.cy * scale };
  }
  function clampView() {
    if (!S.image) return;
    const rect = el.photoCanvas.getBoundingClientRect();
    const scale = S.fit * S.zoom;
    if (!scale) return;
    const halfW = rect.width / (2 * scale), halfH = rect.height / (2 * scale);
    S.cx = halfW >= S.W / 2 ? S.W / 2 : clamp(S.cx, halfW, S.W - halfW);
    S.cy = halfH >= S.H / 2 ? S.H / 2 : clamp(S.cy, halfH, S.H - halfH);
  }
  function screenToImage(px, py, cw, ch) {
    const t = photoTransform(cw, ch);
    return { x: (px - t.dx) / t.scale, y: (py - t.dy) / t.scale };
  }
  function imageToScreen(pt, t) {
    return { x: t.dx + pt.x * t.scale, y: t.dy + pt.y * t.scale };
  }
  function drawPhotoMarkers(ctx, t) {
    const marker = (pt, color, label) => {
      const p = imageToScreen(pt, t);
      if (p.x < -30 || p.y < -30 || p.x > el.photoCanvas.clientWidth + 30 || p.y > el.photoCanvas.clientHeight + 30) return;
      ctx.save();
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(p.x, p.y, 9, 0, 2 * Math.PI); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p.x - 15, p.y); ctx.lineTo(p.x + 15, p.y);
      ctx.moveTo(p.x, p.y - 15); ctx.lineTo(p.x, p.y + 15);
      ctx.stroke();
      ctx.font = 'bold 12px Segoe UI, sans-serif';
      ctx.fillText(label, p.x + 12, p.y - 10);
      ctx.restore();
    };
    S.colorPoints.forEach((p, i) => marker(p, '#F5CD46', String(i + 2)));
    if (S.seed) marker(S.seed, '#FF3C3C', '1');
  }
  function renderPhoto() {
    const { ctx, w, h } = prepCanvas(el.photoCanvas);
    el.photoPlaceholder.hidden = !!S.image;
    if (!S.image) return;
    const rect = el.photoCanvas.getBoundingClientRect();
    S.fit = Math.min(rect.width / S.W, rect.height / S.H);
    clampView();
    const t = photoTransform(w, h);
    const dw = S.W * t.scale, dh = S.H * t.scale;
    ctx.save();
    if (S.view === 'mask') {
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(t.dx, t.dy, dw, dh);
      ctx.strokeStyle = '#DACAB0'; ctx.lineWidth = 1; ctx.strokeRect(t.dx, t.dy, dw, dh);
      ctx.drawImage(maskCanvas, t.dx, t.dy, dw, dh);
    } else {
      ctx.drawImage(S.image, t.dx, t.dy, dw, dh);
      if (S.view === 'overlay' && hasMask()) {
        ctx.globalAlpha = 0.48;
        ctx.drawImage(maskCanvas, t.dx, t.dy, dw, dh);
        ctx.globalAlpha = 1;
      }
    }
    ctx.restore();
    drawPhotoMarkers(ctx, t);
    if (S.crop.active && S.crop.start && S.crop.end) {
      const x = Math.min(S.crop.start.x, S.crop.end.x);
      const y = Math.min(S.crop.start.y, S.crop.end.y);
      const cw = Math.abs(S.crop.end.x - S.crop.start.x);
      const ch = Math.abs(S.crop.end.y - S.crop.start.y);
      ctx.save();
      ctx.fillStyle = 'rgba(95,0,1,.08)';
      ctx.strokeStyle = '#5F0001'; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
      ctx.fillRect(t.dx + x * t.scale, t.dy + y * t.scale, cw * t.scale, ch * t.scale);
      ctx.strokeRect(t.dx + x * t.scale, t.dy + y * t.scale, cw * t.scale, ch * t.scale);
      ctx.restore();
    }
    if (S.minimapVisible) renderMinimap();
    el.photoInfo.textContent = `${S.W} × ${S.H} px · масштаб ${S.zoom.toFixed(2)}×` +
      (S.waterPixels ? ` · воды ${fmt(S.waterShare, 2)} %` : '');
  }
  function renderMinimap() {
    if (!S.image || !S.minimapVisible) return;
    const c = el.minimapCanvas, ctx = c.getContext('2d');
    const w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    const s = Math.min((w - 4) / S.W, (h - 4) / S.H);
    const ox = (w - S.W * s) / 2, oy = (h - S.H * s) / 2;
    ctx.drawImage(S.image, ox, oy, S.W * s, S.H * s);
    ctx.drawImage(maskCanvas, ox, oy, S.W * s, S.H * s);
    if (S.seed) {
      ctx.fillStyle = '#ff3c3c';
      ctx.beginPath(); ctx.arc(ox + S.seed.x * s, oy + S.seed.y * s, 3, 0, 2 * Math.PI); ctx.fill();
    }
    const rect = el.photoCanvas.getBoundingClientRect();
    const scale = S.fit * S.zoom;
    const vx = (0 - (rect.width / 2 - S.cx * scale)) / scale;
    const vy = (0 - (rect.height / 2 - S.cy * scale)) / scale;
    const vw = rect.width / scale, vh = rect.height / scale;
    ctx.strokeStyle = '#733933'; ctx.lineWidth = 1.5;
    ctx.strokeRect(ox + vx * s, oy + vy * s, Math.max(3, vw * s), Math.max(3, vh * s));
  }
  function zoomAt(factor, px, py) {
    if (!S.image) return;
    const rect = el.photoCanvas.getBoundingClientRect();
    const before = screenToImage(px === undefined ? rect.width / 2 : px,
      py === undefined ? rect.height / 2 : py, rect.width, rect.height);
    S.zoom = clamp(S.zoom * factor, 1, 12);
    if (S.zoom <= 1.001) { S.cx = S.W / 2; S.cy = S.H / 2; }
    else {
      const scale = S.fit * S.zoom;
      S.cx = before.x - ((px === undefined ? rect.width / 2 : px) - rect.width / 2) / scale;
      S.cy = before.y - ((py === undefined ? rect.height / 2 : py) - rect.height / 2) / scale;
    }
    clampView();
    renderPhoto();
  }
  function resetView() {
    S.zoom = 1; S.cx = S.W / 2; S.cy = S.H / 2;
    renderPhoto();
  }

  function paintBrush(pt) {
    const r = Number($('brushNum').value) || 18;
    const eraser = S.tool === 'eraser';
    maskCtx.save();
    maskCtx.globalCompositeOperation = eraser ? 'destination-out' : 'source-over';
    maskCtx.fillStyle = '#28dc50';
    maskCtx.beginPath(); maskCtx.arc(pt.x, pt.y, r, 0, 2 * Math.PI); maskCtx.fill();
    maskCtx.restore();
    if (!eraser) S.maskNonEmpty = true;
    S.maskTouched = true;
  }
  function paintLine(a, b) {
    const dist = Math.hypot(b.x - a.x, b.y - a.y);
    const step = Math.max(1, (Number($('brushNum').value) || 18) / 3);
    const n = Math.min(500, Math.ceil(dist / step));
    for (let i = 1; i <= n; i++) {
      paintBrush({ x: a.x + (b.x - a.x) * i / n, y: a.y + (b.y - a.y) * i / n });
    }
  }

  // ------------------------------------------------------------------- обрезка
  function toggleCrop() {
    if (!S.image) { toast('Сначала загрузите снимок.'); return; }
    S.crop.active = !S.crop.active;
    S.crop.start = S.crop.end = null;
    $('btnCrop').classList.toggle('selected-accent', S.crop.active);
    status(S.crop.active
      ? 'Обрезка: выделите прямоугольник на снимке ЛКМ. Повторное нажатие — отмена.'
      : 'Обрезка отменена.');
    renderPhoto();
  }
  function cropCanvas(source, x, y, w, h, whiteMask) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.drawImage(source, x, y, w, h, 0, 0, w, h);
    if (whiteMask) {
      const d = ctx.getImageData(0, 0, w, h);
      for (let i = 0; i < d.data.length; i += 4) {
        const v = d.data[i + 3] > 127 ? 255 : 0;
        d.data[i] = d.data[i + 1] = d.data[i + 2] = v;
        d.data[i + 3] = 255;
      }
      ctx.putImageData(d, 0, 0);
    }
    return c.toDataURL('image/png');
  }
  async function finishCrop() {
    const a = S.crop.start, b = S.crop.end;
    S.crop.active = false; S.crop.start = S.crop.end = null;
    $('btnCrop').classList.remove('selected-accent');
    if (!a || !b) { renderPhoto(); return; }
    const x = clamp(Math.round(Math.min(a.x, b.x)), 0, S.W - 1);
    const y = clamp(Math.round(Math.min(a.y, b.y)), 0, S.H - 1);
    const w = clamp(Math.round(Math.abs(b.x - a.x)), 1, S.W - x);
    const h = clamp(Math.round(Math.abs(b.y - a.y)), 1, S.H - y);
    if (w < 10 || h < 10) { toast('Область слишком маленькая.'); renderPhoto(); return; }
    const base = cropCanvas(S.image, x, y, w, h, false);
    const mask = cropCanvas(maskCanvas, x, y, w, h, true);
    await showPhoto(base, `${S.sourceName} (обрезано)`);
    await setMaskFromDataURL(mask);
    const md = maskCtx.getImageData(0, 0, S.W, S.H).data;
    S.maskNonEmpty = false;
    for (let i = 3; i < md.length; i += 4) {
      if (md[i] > 127) { S.maskNonEmpty = true; break; }
    }
    S.seed = S.seed && S.seed.x >= x && S.seed.x < x + w &&
      S.seed.y >= y && S.seed.y < y + h
      ? { x: S.seed.x - x, y: S.seed.y - y } : null;
    S.colorPoints = S.colorPoints
      .filter((p) => p.x >= x && p.x < x + w && p.y >= y && p.y < y + h)
      .map((p) => ({ x: p.x - x, y: p.y - y }));
    S.maskTouched = true;
    S.result = null;
    S.waterPixels = 0; S.waterShare = 0;
    resetView();
    renderPhoto();
    status(`Снимок обрезан до ${w} × ${h} px. Пересчитайте D заново.` +
      (S.seed ? '' : ' Створ был вне области — отметьте его снова.'));
    toast('Снимок обрезан');
  }

  // ------------------------------------------------------------------ загрузка
  async function loadRawImage(raw, name) {
    status(`Загружается ${name}…`);
    busy(true);
    try {
      const resp = await api('/api/upload', { image: raw });
      await showPhoto(resp.image, name);
      status(`Загружен снимок «${name}» (${resp.width} × ${resp.height}). Отметьте точку на реке.`);
      toast('Снимок загружен');
    } catch (e) {
      status(e.message, true); toast(e.message);
    } finally { busy(false); }
  }
  async function loadFile(file) {
    if (!file) return;
    if (!file.type.startsWith('image/') && !/\.(tiff?|bmp)$/i.test(file.name)) {
      toast('Нужен файл изображения (JPG, PNG, TIFF, BMP).'); return;
    }
    const reader = new FileReader();
    let raw;
    try {
      raw = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Не удалось прочитать файл.'));
        reader.readAsDataURL(file);
      });
    } catch (e) { status(e.message, true); toast(e.message); return; }
    await loadRawImage(raw, file.name);
  }
  function generateDemoImage() {
    // Небольшой синтетический «спутниковый» снимок разветвлённой реки —
    // чтобы все этапы работы можно было попробовать без готового файла.
    const c = document.createElement('canvas');
    c.width = 720; c.height = 460;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#74824f'; ctx.fillRect(0, 0, c.width, c.height);
    let seed = 42;
    const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
    for (let i = 0; i < 420; i++) {
      ctx.fillStyle = rnd() > 0.5 ? 'rgba(90,104,61,.35)' : 'rgba(139,142,79,.28)';
      ctx.beginPath();
      ctx.ellipse(rnd() * c.width, rnd() * c.height, 8 + rnd() * 38, 5 + rnd() * 18, rnd() * 3, 0, 2 * Math.PI);
      ctx.fill();
    }
    // русло снизу вверх с изгибами
    const channel = (width, color) => {
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = width;
      ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(360, 470);
      ctx.bezierCurveTo(300, 350, 430, 280, 350, 180);
      ctx.bezierCurveTo(300, 110, 420, 70, 370, -10);
      ctx.stroke();
    };
    channel(26, '#486b74'); channel(18, '#244e68');
    // дельта / притоки выше створа
    [[350, 180, 160, 75], [370, 140, 560, 60], [330, 240, 120, 160], [380, 250, 610, 180],
     [352, 100, 245, 30], [375, 90, 490, 25], [340, 300, 215, 250], [385, 305, 520, 270]]
      .forEach(([x0, y0, x1, y1], i) => {
        ctx.strokeStyle = '#2a546c'; ctx.lineWidth = i < 4 ? 10 : 6; ctx.lineCap = 'round';
        ctx.beginPath(); ctx.moveTo(x0, y0);
        ctx.quadraticCurveTo((x0 + x1) / 2 + (i % 2 ? 35 : -35), (y0 + y1) / 2, x1, y1);
        ctx.stroke();
      });
    return c.toDataURL('image/png');
  }
  async function showPhoto(dataURL, name) {
    const img = await loadImage(dataURL);
    S.image = img; S.baseDataURL = dataURL;
    S.W = img.naturalWidth; S.H = img.naturalHeight;
    S.sourceName = name || 'screenshot.png';
    initMask(S.W, S.H);
    S.crop.active = false; S.crop.start = S.crop.end = null;
    $('btnCrop').classList.remove('selected-accent');
    S.seed = null; S.colorPoints = []; S.result = null; S.waterPixels = 0; S.waterShare = 0;
    S.overlayDataURL = null; S.maskTouched = false;
    S.undo.length = 0; S.redo.length = 0; updateHistoryButtons();
    resetView();
    el.report.textContent = INITIAL_REPORT;
    el.plot.hidden = true; el.plotEmpty.hidden = false;
    el.tableWrap.innerHTML = ''; el.streamWrap.innerHTML = '';
    setBadge('resultBadge', 'ожидание');
  }
  function closePhoto() {
    S.image = null; S.baseDataURL = null; S.W = S.H = 0;
    S.seed = null; S.colorPoints = []; S.result = null;
    S.undo.length = 0; S.redo.length = 0; S.maskNonEmpty = false; updateHistoryButtons();
    el.photoPlaceholder.hidden = false;
    el.report.textContent = INITIAL_REPORT;
    el.plot.hidden = true; el.plotEmpty.hidden = false;
    el.tableWrap.innerHTML = ''; el.streamWrap.innerHTML = '';
    el.photoInfo.textContent = 'Снимок не загружен';
    setBadge('resultBadge', 'ожидание');
    renderPhoto();
    status('Снимок закрыт.');
  }

  // ---------------------------------------------------------- вычисления фото
  async function segment() {
    if (!S.image) { toast('Сначала загрузите снимок.'); return; }
    if (!S.seed) { status('Сначала отметьте точку на реке — инструмент «Точка расхода».', true); toast('Отметьте точку на реке'); return; }
    busy(true, 'Выделение водной поверхности…');
    try {
      const resp = await api('/api/segment', {
        image: S.baseDataURL, seed: S.seed, extras: S.colorPoints,
        tol: Number($('tolNum').value), method: $('method').value,
        keep_largest: $('largest').checked
      });
      S.baseDataURL = resp.image;
      S.overlayDataURL = resp.overlay;
      S.maskTouched = false;
      await setMaskFromDataURL(resp.mask);
      S.waterPixels = resp.water_pixels;
      S.waterShare = resp.water_share;
      S.result = null;
      renderPhoto();
      status(`Выделено ${fmt(S.waterPixels, 0)} пикселей воды (${fmt(S.waterShare, 2)} %). ` +
        'Проверьте маску и сотрите всё ниже створа.');
      toast('Река выделена');
    } catch (e) { status(e.message, true); toast(e.message); }
    finally { busy(false); }
  }
  async function analyze() {
    if (!S.image) { toast('Сначала загрузите снимок.'); return; }
    if (!hasMask()) { status('Маска пуста. Сначала выделите реку или дорисуйте её кистью.', true); return; }
    busy(true, 'Расчёт фрактальной размерности…');
    try {
      const resp = await api('/api/analyze', {
        mask: maskForApi(), object: $('object').value,
        max_divs: Number($('maxDivsNum').value)
      });
      S.result = resp.result;
      showResult(S.result);
      setBadge('resultBadge', 'готово', 'ok');
      status(`Расчёт завершён: D = ${fmt(S.result.D, 4)} ± ${fmt(S.result.dD, 4)}, R² = ${fmt(S.result.r2, 4)}.`);
      toast('Расчёт завершён');
    } catch (e) { status(e.message, true); toast(e.message); }
    finally { busy(false); }
  }
  function showResult(result) {
    const stream = result.stream || {};
    const lines = [
      'ФРАКТАЛЬНАЯ РАЗМЕРНОСТЬ РЕКИ',
      '========================================',
      'Метод: ' + result.method,
      'Объект: ' + ({ skeleton: 'скелет (центр русла)', boundary: 'граница воды', mask: 'заполненная маска' }[result.object] || result.object),
      '',
      'D  = ' + fmt(result.D, 6) + '  ± ' + fmt(result.dD, 6),
      'h  = ' + fmt(result.h, 6) + '  ± ' + fmt(result.dh, 6),
      'R² = ' + fmt(result.r2, 6),
      'Делений сетки использовано: ' + result.n_divs_used,
      'Пикселей воды: ' + fmt(result.water_pixels, 0),
      '',
      'ХАРАКТЕРИСТИКИ СТОКА (оценка по D)',
      '  Qср   = ' + fmt(stream.Q_mean, 2) + ' м³/с',
      '  Cv    = ' + fmt(stream.Cv, 4),
      '  Cs    = ' + fmt(stream.Cs, 4),
      '  ошибка Qср = ' + fmt(stream.rel_err_Q, 2) + ' %',
      '',
      'Оценка ориентировочная: калибровочные связи Cv = 2(D−1),',
      'Cs = 2Cv и распределение Пирсона III типа.',
      '',
      'Коэффициенты обеспеченности Kp:'
    ];
    (stream.qp || []).slice(0, 7).forEach((p) => {
      lines.push('  P = ' + fmt(p.p, 1) + ' % → Kp = ' + fmt(p.k, 3) + ', Q = ' + fmt(p.q, 1) + ' м³/с');
    });
    el.report.textContent = lines.join('\n');
    if (result.plot) {
      el.plot.src = result.plot; el.plot.hidden = false; el.plotEmpty.hidden = true;
    }
    buildTable(result.table || [], el.tableWrap, ['n', 'ε, px', 'N(ε)']);
    buildTable((stream.qp || []).map((p) => [fmt(p.p, 1) + ' %', fmt(p.k, 4), fmt(p.q, 2)]),
      el.streamWrap, ['Обеспеченность P', 'Kp', 'Qp, м³/с']);
  }
  function setBadge(id, text, kind) {
    const b = $(id);
    b.textContent = text;
    b.className = 'badge' + (kind ? ' ' + kind : '');
  }
  function seedRgbAt(point) {
    if (!point || !S.image) return null;
    const c = document.createElement('canvas');
    c.width = S.W; c.height = S.H;
    const ctx = c.getContext('2d');
    ctx.drawImage(S.image, 0, 0);
    const x = clamp(Math.round(point.x), 0, S.W - 1);
    const y = clamp(Math.round(point.y), 0, S.H - 1);
    const d = ctx.getImageData(x, y, 1, 1).data;
    return [d[0], d[1], d[2]];
  }
  function photoReportPayload() {
    return {
      title: 'Анализ фрактальной размерности по спутниковому снимку',
      source_name: S.sourceName,
      width: S.W, height: S.H,
      seed: S.seed, seed_rgb: seedRgbAt(S.seed),
      color_pts: S.colorPoints,
      method: $('method').value, tol: Number($('tolNum').value),
      object: $('object').value, max_divs: Number($('maxDivsNum').value),
      mask_touched: S.maskTouched,
      scale_text: $('scaleText').value,
      mask: hasMask() ? maskForApi() : null,
      params: [
        ['Источник', S.sourceName],
        ['Размер снимка', `${S.W} × ${S.H} px`],
        ['Способ выделения', $('method').selectedOptions[0].text],
        ['Допуск по цвету', $('tolNum').value],
        ['Точка створа', S.seed ? `x=${Math.round(S.seed.x)}, y=${Math.round(S.seed.y)}` : 'не задана'],
        ['Доп. точки цвета', String(S.colorPoints.length)],
        ['Объект расчёта', $('object').selectedOptions[0].text],
        ['Число делений сетки', $('maxDivsNum').value],
        ['Пикселей воды', String(S.waterPixels)],
        ['Масштаб, м/пиксель', $('scaleText').value || 'не указан']
      ],
      result: S.result || {}, table: S.result ? S.result.table : [],
      stream: S.result ? S.result.stream : {}, plot: S.result ? S.result.plot : null,
      image: S.overlayDataURL || S.baseDataURL
    };
  }
  async function saveMask() {
    if (!S.image || !hasMask()) { toast('Нет выделенной маски для сохранения.'); return; }
    busy(true, 'Сохранение маски…');
    try {
      await download('/api/mask/png', {
        mask: maskForApi(), scale_text: $('scaleText').value,
        source_name: S.sourceName, seed: S.seed
      }, 'river_mask.png');
      status('Маска сохранена в PNG с метаданными.');
    } catch (e) { status(e.message, true); toast(e.message); }
    finally { busy(false); }
  }
  async function saveReport() {
    if (!S.result) { toast('Сначала рассчитайте D.'); return; }
    busy(true, 'Формирование PDF-отчёта…');
    try {
      await download('/api/report', photoReportPayload(), 'gidrofraktal-report.pdf');
      status('PDF-отчёт сохранён.');
    } catch (e) { status(e.message, true); toast(e.message); }
    finally { busy(false); }
  }

  // ---------------------------------------------------------- поворот/отражение
  function transformPoint(pt, op) {
    const x = pt.x, y = pt.y, H = S.H, W = S.W;
    if (op === 'rot1') return { x: y, y: W - 1 - x };
    if (op === 'rot2') return { x: W - 1 - x, y: H - 1 - y };
    if (op === 'rot3') return { x: H - 1 - y, y: x };
    if (op === 'fliph') return { x: W - 1 - x, y };
    if (op === 'flipv') return { x, y: H - 1 - y };
    return { x, y };
  }
  function transformedCanvas(source, op, dw, dh) {
    const c = document.createElement('canvas');
    c.width = dw; c.height = dh;
    const ctx = c.getContext('2d');
    const W = source.width, H = source.height;
    if (op === 'rot1') { ctx.translate(0, W); ctx.rotate(-Math.PI / 2); }
    if (op === 'rot2') { ctx.translate(W, H); ctx.rotate(Math.PI); }
    if (op === 'rot3') { ctx.translate(H, 0); ctx.rotate(Math.PI / 2); }
    if (op === 'fliph') { ctx.translate(W, 0); ctx.scale(-1, 1); }
    if (op === 'flipv') { ctx.translate(0, H); ctx.scale(1, -1); }
    ctx.drawImage(source, 0, 0);
    return c;
  }
  function rotateView(op) {
    if (!S.image) { toast('Сначала загрузите снимок.'); return; }
    pushUndo();
    const dw = (op === 'rot1' || op === 'rot2' || op === 'rot3') ? S.H : S.W;
    const dh = (op === 'rot1' || op === 'rot2' || op === 'rot3') ? S.W : S.H;
    const newImageCanvas = transformedCanvas(S.image, op, dw, dh);
    const newMaskCanvas = transformedCanvas(maskCanvas, op, dw, dh);
    S.seed = S.seed ? transformPoint(S.seed, op) : null;
    S.colorPoints = S.colorPoints.map((p) => transformPoint(p, op));
    S.W = dw; S.H = dh;
    initMask(dw, dh);
    maskCtx.drawImage(newMaskCanvas, 0, 0);
    S.baseDataURL = newImageCanvas.toDataURL('image/jpeg', 0.92);
    const img = new Image();
    img.onload = () => { S.image = img; resetView(); };
    img.src = S.baseDataURL;
    S.result = null;
    el.plot.hidden = true; el.plotEmpty.hidden = false;
    setBadge('resultBadge', 'ожидание');
    status('Изображение, маска и створ преобразованы. Пересчитайте D.');
  }

  // ----------------------------------------------------------------- карта
  function tileXY(lon, lat, z) {
    const n = Math.pow(2, z);
    const la = clamp(lat, -85.05112878, 85.05112878) * Math.PI / 180;
    return { x: (lon + 180) / 360 * n, y: (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * n };
  }
  function lonLatFromTile(x, y, z) {
    const n = Math.pow(2, z);
    return { lon: x / n * 360 - 180, lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI };
  }
  const LEAFLET_SOURCES = {
    esri: [
      { url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        credit: 'Снимок: Esri, Maxar, Earthstar Geographics' },
      { url: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        credit: 'Снимок: Esri, Maxar, Earthstar Geographics' },
      { url: 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        credit: 'Снимок: Google Satellite' },
      { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        credit: 'Карта: © OpenStreetMap (резерв)' }
    ],
    topo: [
      { url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        credit: 'Карта: © OpenTopoMap (CC-BY-SA), данные © OpenStreetMap' },
      { url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png',
        credit: 'Карта: © OpenTopoMap (CC-BY-SA), данные © OpenStreetMap' },
      { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        credit: 'Карта: © OpenStreetMap (резерв)' }
    ]
  };
  function viewGeoPixels(lon, lat, z, w, h) {
    const c = tileXY(lon, lat, z);
    return { x0: c.x - w / (2 * 256), y0: c.y - h / (2 * 256), z, w, h };
  }
  function setLeafletLayer(index) {
    if (!S.map.leaflet || !window.L) return;
    const list = LEAFLET_SOURCES[S.map.source] || LEAFLET_SOURCES.esri;
    S.map.layerIndex = clamp(index, 0, list.length - 1);
    S.map.tileErrors = 0;
    const src = list[S.map.layerIndex];
    if (S.map.tileLayer) S.map.leaflet.removeLayer(S.map.tileLayer);
    S.map.tileLayer = L.tileLayer(src.url, {
      maxZoom: 19, minZoom: 2, subdomains: 'abc',
      attribution: src.credit
    });
    S.map.tileLayer.on('tileload', () => { S.map.tileErrors = 0; });
    S.map.tileLayer.on('tileerror', () => {
      S.map.tileErrors++;
      if (S.map.tileErrors >= 3 && S.map.layerIndex < list.length - 1) {
        setLeafletLayer(S.map.layerIndex + 1);
        status(`Основной источник тайлов недоступен — включён резерв: ${src.credit}.`);
      }
    });
    S.map.tileLayer.addTo(S.map.leaflet);
    S.map.leafletCredit = src.credit;
    renderMap();
  }
  function initLeaflet() {
    if (!window.L || !el.leafletWrap || S.map.leaflet) return;
    const map = L.map(el.leafletWrap, {
      center: [S.map.lat, S.map.lon], zoom: S.map.zoom,
      zoomControl: false, attributionControl: true,
      preferCanvas: false, worldCopyJump: true
    });
    S.map.leaflet = map;
    el.mapWrap.classList.add('leaflet-mode');
    el.mapPlaceholder.hidden = true;
    setLeafletLayer(0);
    const sync = () => {
      const c = map.getCenter();
      S.map.lat = c.lat; S.map.lon = c.lng; S.map.zoom = map.getZoom();
      updateMapCoords();
      renderMap();
      clearTimeout(S.map.moveTimer);
      S.map.moveTimer = setTimeout(() => loadMapView(true), 180);
      if (S.map.minimapVisible) loadMapMinimap();
    };
    map.on('moveend zoomend', sync);
    map.on('click', (e) => {
      if (S.map.markMode) {
        addMapMark(e.latlng.lat, e.latlng.lng);
        return;
      }
      S.map.outlet = { lon: e.latlng.lng, lat: e.latlng.lat };
      renderMap();
      status(`Створ установлен: ${fmt(e.latlng.lat, 5)}° N, ` +
        `${fmt(e.latlng.lng, 5)}° E. Нажмите «Построить водосбор».`);
    });
    setTimeout(() => { map.invalidateSize(); sync(); }, 0);
  }
  function centerMapAt(lat, lon, zoom) {
    const z = zoom === undefined ? S.map.zoom : zoom;
    if (S.map.leaflet) {
      S.map.leaflet.setView([lat, lon], z);
    } else {
      S.map.lat = lat; S.map.lon = lon; S.map.zoom = z;
      S.map.panDx = S.map.panDy = 0;
      updateMapCoords();
      loadMapView(true);
    }
  }
  function projectOverlay(ctx, img, srcGeo, dstGeo, w, h, alpha) {
    if (!img || !srcGeo || !dstGeo) return;
    const k = Math.pow(2, dstGeo.z - srcGeo.z);
    const dx = (srcGeo.x0 * k - dstGeo.x0) * 256;
    const dy = (srcGeo.y0 * k - dstGeo.y0) * 256;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.drawImage(img, dx, dy, srcGeo.w * k, srcGeo.h * k);
    ctx.restore();
  }
  function mapGeoAt(sx, sy) {
    const geo = S.map.geo;
    if (!geo) return { lat: S.map.lat, lon: S.map.lon };
    const rect = el.mapCanvas.getBoundingClientRect();
    const px = (sx - S.map.panDx) * geo.w / rect.width;
    const py = (sy - S.map.panDy) * geo.h / rect.height;
    return lonLatFromTile(geo.x0 + px / 256, geo.y0 + py / 256, geo.z);
  }
  function addMapMark(lat, lon) {
    const raw = (el.mapMarkText && el.mapMarkText.value || '').trim();
    const label = raw || `Метка ${S.map.marks.length + 1}`;
    S.map.marks.push({ lat, lon, label });
    if (el.mapMarkText) el.mapMarkText.value = '';
    renderMap();
    status(`Метка «${label}» поставлена: ${fmt(lat, 5)}° N, ${fmt(lon, 5)}° E.`);
  }
  function toggleMapMark() {
    S.map.markMode = !S.map.markMode;
    $('btnMapMark').classList.toggle('selected-accent', S.map.markMode);
    status(S.map.markMode
      ? 'Режим меток включён: кликайте по карте, чтобы отмечать места. Повторное нажатие вернёт установку створа.'
      : 'Режим меток выключен. Клик по карте снова ставит створ.');
  }
  function clearMapMarks() {
    const n = S.map.marks.length;
    S.map.marks.length = 0;
    renderMap();
    status(n ? 'Все метки удалены.' : 'Меток пока нет.');
  }
  function drawMapMarks(ctx, geo, useLeaflet) {
    if (!S.map.marks.length) return;
    S.map.marks.forEach((m, i) => {
      let px, py;
      if (useLeaflet && S.map.leaflet) {
        const p = S.map.leaflet.latLngToContainerPoint([m.lat, m.lon]);
        px = p.x; py = p.y;
      } else if (geo) {
        const t = tileXY(m.lon, m.lat, geo.z);
        px = ((t.x - geo.x0) * 256) * el.mapCanvas.clientWidth / geo.w + S.map.panDx;
        py = ((t.y - geo.y0) * 256) * el.mapCanvas.clientHeight / geo.h + S.map.panDy;
      } else return;
      ctx.save();
      ctx.fillStyle = '#5F0001'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 10, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 11px Segoe UI, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(String(i + 2), px, py + 0.5);
      if (m.label) {
        ctx.font = '12px Segoe UI, sans-serif';
        ctx.fillStyle = '#1F1A17'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.fillText(m.label, px + 13, py - 7);
      }
      ctx.restore();
    });
  }
  function drawOutletMarker(ctx, px, py, label) {
    ctx.save();
    ctx.strokeStyle = '#ff3c3c'; ctx.fillStyle = '#ff3c3c'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(px, py, 9, 0, 2 * Math.PI); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(px - 15, py); ctx.lineTo(px + 15, py);
    ctx.moveTo(px, py - 15); ctx.lineTo(px, py + 15);
    ctx.stroke();
    if (label !== false) {
      ctx.font = 'bold 13px Segoe UI, sans-serif';
      ctx.fillText('1', px + 13, py - 11);
    }
    ctx.restore();
  }
  function renderMap() {
    const { ctx, w, h } = prepCanvas(el.mapCanvas);
    el.mapPlaceholder.hidden = !!S.map.img || !!S.map.leaflet;
    if (S.map.leaflet) {
      // Leaflet рисует подложку; на прозрачном холсте — только расчётные слои.
      const geo = viewGeoPixels(S.map.lon, S.map.lat, S.map.zoom, w, h);
      projectOverlay(ctx, S.map.reliefImg, S.map.reliefGeo, geo, w, h, 0.55);
      projectOverlay(ctx, S.map.overlayImg, S.map.overlayGeo, geo, w, h, 1);
      if (S.map.outlet) {
        const p = S.map.leaflet.latLngToContainerPoint(
          [S.map.outlet.lat, S.map.outlet.lon]);
        drawOutletMarker(ctx, p.x, p.y, true);
      }
      drawMapMarks(ctx, geo, true);
      el.mapCredit.textContent = S.map.leafletCredit +
        ' · Рельеф: Mapzen / AWS Terrain Tiles' +
        (S.map.demo ? ' · демо-рельеф (нет сети)' : '');
      el.mapZoom.textContent = `z${S.map.zoom} · ${fmt(S.map.cell, 1)} м/пиксель`;
      if (S.map.minimapVisible) renderMapMinimap();
      return;
    }
    if (!S.map.img) return;
    ctx.drawImage(S.map.img, S.map.panDx, S.map.panDy, w, h);
    const geo = S.map.geo;
    if (geo) {
      const sx = w / geo.w, sy = h / geo.h;
      // настоящие спутниковые/топо-тайлы: <img> загружаются без CORS
      (S.map.tiles || []).forEach((t) => {
        ctx.drawImage(t.img, S.map.panDx + t.px * sx, S.map.panDy + t.py * sy,
          256 * sx, 256 * sy);
      });
      if (S.map.reliefImg) {
        ctx.globalAlpha = 0.55;
        ctx.drawImage(S.map.reliefImg, S.map.panDx, S.map.panDy, w, h);
        ctx.globalAlpha = 1;
      }
      if (S.map.overlayImg) {
        ctx.drawImage(S.map.overlayImg, S.map.panDx, S.map.panDy, w, h);
      }
    }
    if (geo && S.map.outlet) {
      const t = tileXY(S.map.outlet.lon, S.map.outlet.lat, geo.z);
      const px = ((t.x - geo.x0) * 256) * el.mapCanvas.clientWidth / geo.w + S.map.panDx;
      const py = ((t.y - geo.y0) * 256) * el.mapCanvas.clientHeight / geo.h + S.map.panDy;
      drawOutletMarker(ctx, px, py, true);
    }
    drawMapMarks(ctx, geo, false);
    el.mapCredit.textContent = S.map.credit + (S.map.demo ? ' · демо-рельеф (нет сети)' : '');
    el.mapZoom.textContent = `z${S.map.zoom} · ${fmt(S.map.cell, 1)} м/пиксель`;
    if (S.map.minimapVisible) renderMapMinimap();
  }
  function mapParams() {
    const rect = el.mapCanvas.getBoundingClientRect();
    return {
      lon: S.map.lon, lat: S.map.lat, zoom: S.map.zoom,
      width: Math.max(240, Math.round(rect.width)), height: Math.max(180, Math.round(rect.height)),
      source: S.map.source, relief: S.map.relief,
      skip_tiles: !!S.map.leaflet
    };
  }
  async function loadMapView(quiet) {
    if (S.map.loading) return;
    S.map.loading = true;
    if (!quiet) status('Загрузка карты…');
    try {
      const resp = await api('/api/map/view', mapParams());
      const img = await loadImage(resp.image);
      S.map.img = img;
      S.map.geo = resp.geo;
      S.map.credit = resp.credit;
      S.map.cell = resp.cell_m;
      S.map.demo = !!resp.demo;
      S.map.tiles = resp.tiles || [];
      S.map.panDx = S.map.panDy = 0;
      if (resp.relief) {
        loadImage(resp.relief).then((relief) => {
          S.map.reliefImg = relief;
          S.map.reliefGeo = resp.geo;
          renderMap();
        });
      } else if (!S.map.leaflet) {
        S.map.reliefImg = null;
        S.map.reliefGeo = null;
      }
      el.mapPlaceholder.hidden = true;
      renderMap();
      updateMapCoords();
      if (S.map.minimapVisible) loadMapMinimap();
      if (!quiet) {
        status(S.map.leaflet
          ? 'Подложка Leaflet загружена. Кликните по руслу, чтобы поставить створ.'
          : (resp.demo
            ? 'Внешние тайлы недоступны — показана демо-подложка. Кликните по руслу реки.'
            : 'Карта обновлена. Кликните по руслу реки, чтобы поставить створ.'));
      }
    } catch (e) {
      status(e.message, true); toast(e.message);
    } finally { S.map.loading = false; }
  }
  function updateMapCoords(lat, lon) {
    const la = lat === undefined ? S.map.lat : lat;
    const lo = lon === undefined ? S.map.lon : lon;
    el.mapCoords.textContent = `${Math.abs(lo).toFixed(5)}° ${lo >= 0 ? 'E' : 'W'}, ` +
      `${Math.abs(la).toFixed(5)}° ${la >= 0 ? 'N' : 'S'}`;
    if (el.mapLat) el.mapLat.value = la.toFixed(5);
    if (el.mapLon) el.mapLon.value = lo.toFixed(5);
  }
  function mapZoomBy(delta) {
    if (!S.map.geo && !S.map.leaflet) { toast('Карта ещё загружается.'); return; }
    const z = clamp(S.map.zoom + delta, 2, 18);
    if (z === S.map.zoom) return;
    if (S.map.leaflet) {
      S.map.leaflet.setZoom(z);
    } else {
      S.map.zoom = z;
      loadMapView(true);
    }
    status(`Масштаб карты: z${z}.`);
  }
  function searchMapCoords() {
    const lat = Number(el.mapLat.value), lon = Number(el.mapLon.value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) ||
        Math.abs(lat) > 85 || Math.abs(lon) > 180) {
      toast('Введите координаты: широта −85…85, долгота −180…180.');
      return;
    }
    // Поиск центра: створ НЕ ставим и гидрологию не запускаем.
    centerMapAt(lat, lon);
    status(`Карта центрирована: ${fmt(lat, 5)}° N, ${fmt(lon, 5)}° E. Створ не изменён.`);
  }
  async function loadMapMinimap() {
    if (!S.map.minimapVisible || !S.map.geo) return;
    const mz = clamp(S.map.zoom - 4, 0, 12);
    const t = tileXY(S.map.lon, S.map.lat, mz);
    const key = `${S.map.source}/${mz}/${Math.floor(t.x)}/${Math.floor(t.y)}`;
    if (key === S.map.miniKey && S.map.miniResp) { renderMapMinimap(); return; }
    S.map.miniKey = key;
    try {
      const resp = await api('/api/map/view', {
        lon: S.map.lon, lat: S.map.lat, zoom: mz,
        width: 320, height: 220, source: S.map.source, relief: false
      });
      const img = await loadImage(resp.image);
      S.map.miniResp = Object.assign({}, resp, { img: img });
      renderMapMinimap();
    } catch (e) { /* мини-карта необязательна при отсутствии сети */ }
  }
  function renderMapMinimap() {
    if (!S.map.minimapVisible || !el.mapMinimapBox || el.mapMinimapBox.hidden) return;
    const c = el.mapMinimapCanvas;
    if (!c) return;
    const ctx = c.getContext('2d');
    const w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    const mini = S.map.miniResp, geo = S.map.geo;
    if (!mini || !mini.img || !mini.geo || !geo) {
      ctx.fillStyle = '#eee'; ctx.fillRect(0, 0, w, h);
      return;
    }
    const sx = w / mini.geo.w, sy = h / mini.geo.h;
    ctx.drawImage(mini.img, 0, 0, w, h);
    (mini.tiles || []).forEach((t) => {
      ctx.drawImage(t.img, t.px * sx, t.py * sy, 256 * sx, 256 * sy);
    });
    const k = Math.pow(2, mini.geo.z - geo.z);
    const x0 = (geo.x0 * k - mini.geo.x0) * 256 * sx;
    const y0 = (geo.y0 * k - mini.geo.y0) * 256 * sy;
    const vw = Math.max(3, geo.w * k * sx);
    const vh = Math.max(3, geo.h * k * sy);
    ctx.strokeStyle = '#733933'; ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, vw, vh);
    const mx = ((tileXY(S.map.lon, S.map.lat, mini.geo.z).x - mini.geo.x0) * 256) * sx;
    const my = ((tileXY(S.map.lon, S.map.lat, mini.geo.z).y - mini.geo.y0) * 256) * sy;
    ctx.fillStyle = '#ff3c3c';
    ctx.beginPath(); ctx.arc(mx, my, 3, 0, 2 * Math.PI); ctx.fill();
  }
  function toggleMapMinimap() {
    S.map.minimapVisible = !S.map.minimapVisible;
    el.mapMinimapBox.hidden = !S.map.minimapVisible;
    $('btnMapMinimap').classList.toggle('selected', S.map.minimapVisible);
    status(S.map.minimapVisible ? 'Мини-карта открыта.' : 'Мини-карта скрыта.');
    if (S.map.minimapVisible) loadMapMinimap();
  }
  function showMapResult(resp) {
    S.map.info = resp.map;
    S.map.result = resp.result;
    const m = resp.map || {};
    const r = resp.result || {};
    const st = resp.stream || r.stream || {};
    const lines = [
      'ВОДОСБОР И ФРАКТАЛЬНАЯ РАЗМЕРНОСТЬ РУСЛА',
      '============================================',
      'Створ: ' + fmt(m.outlet_lat, 5) + '° N, ' + fmt(m.outlet_lon, 5) + '° E',
      'Метод: ' + (r.method || 'Кантор (квадраты), D = 1 + h/2'),
      '',
      'МОРФОМЕТРИЯ ВОДОСБОРА',
      '  Площадь водосбора .... ' + fmt(m.area_km2, 3) + ' км²',
      '  Длина главного русла .. ' + fmt(m.channel_km, 3) + ' км',
      '  Ячеек водосбора ....... ' + fmt(m.cells, 0),
      '  Ячеек русловой сети ... ' + fmt(m.network_cells, 0),
      '  Порядок Стралера ...... ' + fmt(m.strahler, 0),
      '  Разрешение рельефа .... ' + fmt(m.cell_m, 1) + ' м/ячейку (z' + m.dem_zoom + ')',
      '',
      'ФРАКТАЛЬНАЯ РАЗМЕРНОСТЬ ПО ГЛАВНОМУ РУСЛУ',
      '  D  = ' + fmt(r.D, 6) + ' ± ' + fmt(r.dD, 6),
      '  h  = ' + fmt(r.h, 6) + ' ± ' + fmt(r.dh, 6),
      '  R² = ' + fmt(r.r2, 6),
      '',
      'ХАРАКТЕРИСТИКИ СТОКА (оценка по D)',
      '  Qср = ' + fmt(st.Q_mean, 2) + ' м³/с',
      '  Cv  = ' + fmt(st.Cv, 4),
      '  Cs  = ' + fmt(st.Cs, 4)
    ];
    el.mapReport.textContent = lines.join('\n');
    if (r.plot) { el.mapPlot.src = r.plot; el.mapPlot.hidden = false; el.mapPlotEmpty.hidden = true; }
    buildTable(r.table || [], el.mapTableWrap, ['n', 'ε, px', 'N(ε)']);
    setBadge('mapBadge', 'готово', 'ok');
  }
  async function mapAnalyze() {
    if (!mapParamsReady()) return;
    if (!S.map.outlet) {
      S.map.outlet = { lon: S.map.lon, lat: S.map.lat };
      status('Створ не задан — используется центр карты.');
    }
    busy(true, 'Гидрологический анализ рельефа…');
    try {
      const resp = await api('/api/map/analyze', {
        ...mapParams(),
        outlet_lon: S.map.outlet.lon, outlet_lat: S.map.outlet.lat
      });
      S.map.credit = resp.credit;
      S.map.demo = !!resp.demo;
      S.map.tiles = resp.tiles || S.map.tiles;
      S.map.reportImage = resp.image;
      S.map.mask = resp.mask || null;
      S.map.width = resp.width || 0;
      S.map.height = resp.height || 0;
      if (resp.relief && !S.map.reliefImg) {
        S.map.reliefImg = await loadImage(resp.relief);
      }
      S.map.overlayImg = resp.overlay ? await loadImage(resp.overlay) : null;
      S.map.overlayGeo = S.map.overlayImg ? S.map.geo : null;
      showMapResult(resp);
      renderMap();
      status(`Водосбор построен: ${fmt(resp.map.area_km2, 2)} км², D = ${fmt(resp.result.D, 4)}.`);
      toast('Анализ карты завершён');
    } catch (e) {
      setBadge('mapBadge', 'ошибка', 'err');
      status(e.message, true); toast(e.message);
    } finally { busy(false); }
  }
  function mapParamsReady() {
    if (!S.map.geo) { toast('Карта ещё загружается.'); return false; }
    return true;
  }
  async function mapSavePdf() {
    if (!S.map.result) { toast('Сначала постройте водосбор и рассчитайте D.'); return; }
    const r = S.map.result, m = S.map.info || {};
    busy(true, 'Формирование PDF-отчёта по карте…');
    try {
      await download('/api/report', {
        title: 'Анализ реки по карте и рельефу',
        source_name: 'карта и водосбор', method: 'color', tol: 0,
        object: 'skeleton', max_divs: 60, color_pts: [], mask_touched: false,
        width: S.map.width || undefined, height: S.map.height || undefined,
        mask: S.map.mask,
        params: [
          ['Источник карты', S.map.source === 'esri' ? 'Esri World Imagery' : 'OpenTopoMap'],
          ['Рельеф', S.map.relief ? 'отмывка включена' : 'не показывалась'],
          ['Центр карты', fmt(S.map.lat, 5) + '° N, ' + fmt(S.map.lon, 5) + '° E'],
          ['Масштаб карты', 'z' + S.map.zoom],
          ['Створ', fmt(m.outlet_lat, 5) + '° N, ' + fmt(m.outlet_lon, 5) + '° E'],
          ['Площадь водосбора', fmt(m.area_km2, 3) + ' км²'],
          ['Длина главного русла', fmt(m.channel_km, 3) + ' км'],
          ['Разрешение рельефа', fmt(m.cell_m, 1) + ' м/ячейку']
        ],
        result: r, table: r.table || [], stream: r.stream || {},
        plot: r.plot, image: S.map.reportImage || (S.map.img ? S.map.img.src : null),
        marks: S.map.marks.map((m) => ({ lat: m.lat, lon: m.lon, label: m.label }))
      }, 'gidrofraktal-map-report.pdf');
      status('PDF-отчёт по карте сохранён.');
    } catch (e) { status(e.message, true); toast(e.message); }
    finally { busy(false); }
  }
  function switchTab(name) {
    S.activeTab = name;
    document.querySelectorAll('.tab').forEach((b) => {
      const active = b.dataset.tab === name;
      b.classList.toggle('active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $('panel-photo').classList.toggle('active', name === 'photo');
    $('panel-map').classList.toggle('active', name === 'map');
    if (name === 'photo') setTimeout(renderPhoto, 0);
    if (name === 'map') {
      if (!S.mapTabLoaded) {
        S.mapTabLoaded = true;
        setTimeout(() => { initLeaflet(); loadMapView(true); }, 0);
      } else {
        setTimeout(() => {
          if (S.map.leaflet) S.map.leaflet.invalidateSize();
          renderMap();
        }, 0);
      }
    }
  }

  // ------------------------------------------------------------- события UI
  function setStatusForTool() {
    const hints = {
      point: 'Кликните по руслу — это точка расхода (створ): относительно неё считается D.',
      colorpoint: 'Кликните по участку воды другого оттенка — его цвет станет дополнительным эталоном.',
      pan: 'Перетащите снимок ЛКМ. Колесо мыши — масштаб к курсору.',
      eraser: 'Ведите ластиком по зелёным областям. Сотрите ВСЁ ниже створа — в расчёте должна остаться только часть ВЫШЕ створа.',
      brush: 'Ведите кистью, чтобы дорисовать воду в маску. После правки пересчитайте D.'
    };
    status(hints[S.tool]);
    el.statusRight.textContent = 'Инструмент: ' + $('tool').selectedOptions[0].text;
    el.photoWrap.className = 'canvas-wrap tool-' + S.tool;
  }
  function bindEvents() {
    $('btnLoad').addEventListener('click', () => el.fileInput.click());
    $('btnLoadBig').addEventListener('click', () => el.fileInput.click());
    $('btnDemoImage').addEventListener('click', () => loadRawImage(generateDemoImage(), 'demo-river.png'));
    el.fileInput.addEventListener('change', (e) => {
      loadFile(e.target.files[0]);
      e.target.value = '';
    });
    $('btnSegment').addEventListener('click', segment);
    $('btnAnalyze').addEventListener('click', analyze);
    $('btnSaveMask').addEventListener('click', saveMask);
    $('btnSaveReport').addEventListener('click', saveReport);
    $('btnUndo').addEventListener('click', undo);
    $('btnRedo').addEventListener('click', redo);

    $('tol').addEventListener('input', (e) => { $('tolNum').value = e.target.value; });
    $('tolNum').addEventListener('input', (e) => { $('tol').value = clamp(Number(e.target.value) || 10, 10, 160); });
    $('brush').addEventListener('input', (e) => { $('brushNum').value = e.target.value; });
    $('brushNum').addEventListener('input', (e) => { $('brush').value = clamp(Number(e.target.value) || 2, 2, 80); });
    $('maxDivs').addEventListener('input', (e) => { $('maxDivsNum').value = e.target.value; });
    $('maxDivsNum').addEventListener('input', (e) => { $('maxDivs').value = clamp(Number(e.target.value) || 10, 10, 120); });

    $('tool').addEventListener('change', (e) => { S.tool = e.target.value; setStatusForTool(); });
    $('viewMode').addEventListener('change', (e) => { S.view = e.target.value; renderPhoto(); });
    $('btnZoomIn').addEventListener('click', () => zoomAt(1.25));
    $('btnZoomOut').addEventListener('click', () => zoomAt(1 / 1.25));
    $('btnZoomFit').addEventListener('click', resetView);
    $('btnMinimap').addEventListener('click', toggleMinimap);
    $('btnCrop').addEventListener('click', toggleCrop);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && S.crop.active) toggleCrop();
    });
    document.querySelectorAll('[data-rotate]').forEach((b) =>
      b.addEventListener('click', () => rotateView(b.dataset.rotate)));

    // Холст снимка
    el.photoCanvas.addEventListener('pointerdown', (e) => {
      if (!S.image) return;
      const rect = el.photoCanvas.getBoundingClientRect();
      if (S.crop.active) {
        const pt = screenToImage(e.clientX - rect.left, e.clientY - rect.top, rect.width, rect.height);
        S.crop.start = { x: clamp(pt.x, 0, S.W), y: clamp(pt.y, 0, S.H) };
        S.crop.end = { ...S.crop.start };
        el.photoCanvas.setPointerCapture(e.pointerId);
        renderPhoto();
        return;
      }
      const px = e.clientX - rect.left, py = e.clientY - rect.top;
      const pt = screenToImage(px, py, rect.width, rect.height);
      if (S.tool === 'pan') {
        S.panning = true; S.lastPointer = { x: px, y: py };
        el.photoWrap.classList.add('panning');
        el.photoCanvas.setPointerCapture(e.pointerId);
      } else if (S.tool === 'brush' || S.tool === 'eraser') {
        if (pt.x < 0 || pt.y < 0 || pt.x >= S.W || pt.y >= S.H) return;
        pushUndo();
        S.painting = true; S.lastPaint = { x: pt.x, y: pt.y };
        paintBrush(pt);
        el.photoCanvas.setPointerCapture(e.pointerId);
      } else if (pt.x >= 0 && pt.y >= 0 && pt.x < S.W && pt.y < S.H) {
        pushUndo();
        if (S.tool === 'colorpoint') S.colorPoints.push({ x: pt.x, y: pt.y });
        else { S.seed = { x: pt.x, y: pt.y }; S.colorPoints = []; }
        renderPhoto();
        status(S.tool === 'point'
          ? `Створ: x=${Math.round(pt.x)}, y=${Math.round(pt.y)}. Нажмите «Выделить реку».`
          : `Добавлена точка эталона цвета: x=${Math.round(pt.x)}, y=${Math.round(pt.y)}.`);
      }
    });
    el.photoCanvas.addEventListener('pointermove', (e) => {
      const rect = el.photoCanvas.getBoundingClientRect();
      const px = e.clientX - rect.left, py = e.clientY - rect.top;
      if (S.crop.active) {
        if (S.crop.start) {
          const pt = screenToImage(px, py, rect.width, rect.height);
          S.crop.end = { x: clamp(pt.x, 0, S.W), y: clamp(pt.y, 0, S.H) };
          renderPhoto();
        }
        el.cursorInfo.textContent = `x: ${Math.round(S.crop.end ? S.crop.end.x : 0)}, y: ${Math.round(S.crop.end ? S.crop.end.y : 0)}`;
        return;
      }
      if (S.image) {
        const pt = screenToImage(px, py, rect.width, rect.height);
        el.cursorInfo.textContent = `x: ${Math.round(pt.x)}, y: ${Math.round(pt.y)}`;
      }
      if (S.panning && S.lastPointer) {
        const scale = S.fit * S.zoom;
        S.cx -= (px - S.lastPointer.x) / scale;
        S.cy -= (py - S.lastPointer.y) / scale;
        S.lastPointer = { x: px, y: py };
        clampView(); renderPhoto();
      } else if (S.painting) {
        const pt = screenToImage(px, py, rect.width, rect.height);
        paintLine(S.lastPaint || pt, pt);
        S.lastPaint = { x: pt.x, y: pt.y };
        renderPhoto();
      }
    });
    const endPhotoPointer = () => {
      if (S.crop.active && S.crop.start) { finishCrop(); return; }
      S.painting = false; S.panning = false; S.lastPaint = null; S.lastPointer = null;
      el.photoWrap.classList.remove('panning');
    };
    el.photoCanvas.addEventListener('pointerup', endPhotoPointer);
    el.photoCanvas.addEventListener('pointercancel', endPhotoPointer);
    el.photoCanvas.addEventListener('wheel', (e) => {
      if (!S.image) return;
      e.preventDefault();
      const rect = el.photoCanvas.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.16 : 1 / 1.16, e.clientX - rect.left, e.clientY - rect.top);
    }, { passive: false });

    // Мини-карта
    el.minimapCanvas.addEventListener('pointerdown', (e) => {
      if (!S.image) return;
      const rect = el.minimapCanvas.getBoundingClientRect();
      const s = Math.min((rect.width - 4) / S.W, (rect.height - 4) / S.H);
      const ox = (rect.width - S.W * s) / 2, oy = (rect.height - S.H * s) / 2;
      S.cx = ((e.clientX - rect.left) - ox) / s;
      S.cy = ((e.clientY - rect.top) - oy) / s;
      clampView(); renderPhoto();
    });

    // Вкладки
    document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));

    // Карта
    $('mapSource').addEventListener('change', (e) => {
      S.map.source = e.target.value;
      if (S.map.leaflet) setLeafletLayer(0);
      loadMapView(true);
    });
    $('mapRelief').addEventListener('change', (e) => {
      S.map.relief = e.target.checked;
      if (!S.map.relief) { S.map.reliefImg = null; S.map.reliefGeo = null; renderMap(); }
      loadMapView(true);
    });
    $('btnMapHome').addEventListener('click', () => {
      centerMapAt(59.93428, 30.33510, 11);
      status('Центр карты — Санкт-Петербург. Створ не изменён.');
    });
    $('btnMapSearch').addEventListener('click', searchMapCoords);
    $('btnMapZoomIn').addEventListener('click', () => mapZoomBy(1));
    $('btnMapZoomOut').addEventListener('click', () => mapZoomBy(-1));
    $('btnMapMinimap').addEventListener('click', toggleMapMinimap);
    $('btnMapMark').addEventListener('click', toggleMapMark);
    $('btnMapClearMarks').addEventListener('click', clearMapMarks);
    $('btnMapCatch').addEventListener('click', mapAnalyze);
    $('btnMapDim').addEventListener('click', mapAnalyze);
    $('btnMapPdf').addEventListener('click', mapSavePdf);

    el.mapMinimapCanvas.addEventListener('pointerdown', (e) => {
      const mini = S.map.miniResp;
      if (!mini || !mini.geo) return;
      const rect = el.mapMinimapCanvas.getBoundingClientRect();
      const px = (e.clientX - rect.left) * el.mapMinimapCanvas.width / rect.width;
      const py = (e.clientY - rect.top) * el.mapMinimapCanvas.height / rect.height;
      const sx = el.mapMinimapCanvas.width / mini.geo.w;
      const sy = el.mapMinimapCanvas.height / mini.geo.h;
      const ll = lonLatFromTile(mini.geo.x0 + (px / sx) / 256,
        mini.geo.y0 + (py / sy) / 256, mini.geo.z);
      centerMapAt(ll.lat, ll.lon);
      status('Карта перемещена по мини-карте. Створ не изменён.');
    });

    el.mapCanvas.addEventListener('pointerdown', (e) => {
      if (S.map.leaflet || !S.map.geo) return;
      const rect = el.mapCanvas.getBoundingClientRect();
      S.map.dragStart = { x: e.clientX, y: e.clientY, px: e.clientX - rect.left, py: e.clientY - rect.top };
      S.map.moved = false;
      el.mapCanvas.setPointerCapture(e.pointerId);
    });
    el.mapCanvas.addEventListener('pointermove', (e) => {
      if (S.map.leaflet) return;
      const rect = el.mapCanvas.getBoundingClientRect();
      if (S.map.dragStart) {
        const dx = e.clientX - S.map.dragStart.x, dy = e.clientY - S.map.dragStart.y;
        if (Math.hypot(dx, dy) > 4) S.map.moved = true;
        if (S.map.moved) {
          S.map.panDx = dx; S.map.panDy = dy;
          renderMap();
        }
      } else {
        const g = mapGeoAt(e.clientX - rect.left, e.clientY - rect.top);
        updateMapCoords(g.lat, g.lon);
      }
    });
    el.mapCanvas.addEventListener('pointerup', (e) => {
      if (S.map.leaflet) return;
      const st = S.map.dragStart;
      S.map.dragStart = null;
      if (!st || !S.map.geo) return;
      if (S.map.moved) {
        const rect = el.mapCanvas.getBoundingClientRect();
        const t = tileXY(S.map.lon, S.map.lat, S.map.zoom);
        const ll = lonLatFromTile(t.x - (e.clientX - st.x) * S.map.geo.w / (256 * rect.width),
          t.y - (e.clientY - st.y) * S.map.geo.h / (256 * rect.height), S.map.zoom);
        S.map.lon = ll.lon; S.map.lat = ll.lat;
        S.map.panDx = S.map.panDy = 0;
        updateMapCoords();
        loadMapView(true);
      } else {
        const rect = el.mapCanvas.getBoundingClientRect();
        const g = mapGeoAt(e.clientX - rect.left, e.clientY - rect.top);
        if (S.map.markMode) { addMapMark(g.lat, g.lon); return; }
        S.map.outlet = { lon: g.lon, lat: g.lat };
        renderMap();
        status(`Створ установлен: ${fmt(g.lat, 5)}° N, ${fmt(g.lon, 5)}° E. Нажмите «Построить водосбор».`);
      }
    });
    el.mapCanvas.addEventListener('wheel', (e) => {
      if (S.map.leaflet || !S.map.geo) return;
      e.preventDefault();
      const rect = el.mapCanvas.getBoundingClientRect();
      const g = mapGeoAt(e.clientX - rect.left, e.clientY - rect.top);
      const oldZoom = S.map.zoom;
      S.map.zoom = clamp(oldZoom + (e.deltaY < 0 ? 1 : -1), 3, 16);
      if (S.map.zoom === oldZoom) return;
      const t = tileXY(g.lon, g.lat, oldZoom);
      const px = (e.clientX - rect.left) / rect.width * S.map.geo.w / 256;
      const py = (e.clientY - rect.top) / rect.height * S.map.geo.h / 256;
      const ll = lonLatFromTile(t.x + px, t.y + py, S.map.zoom);
      S.map.lon = ll.lon; S.map.lat = ll.lat;
      updateMapCoords();
      loadMapView(true);
    }, { passive: false });

    // Меню
    document.querySelectorAll('.menu-trigger').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const open = btn.classList.contains('open');
        closeMenus();
        if (!open) { btn.classList.add('open'); $('menu-' + btn.dataset.menu).classList.add('open'); }
      });
    });
    document.querySelectorAll('.menu-dropdown button').forEach((btn) => {
      btn.addEventListener('click', () => { closeMenus(); menuAction(btn.dataset.act); });
    });
    document.addEventListener('click', closeMenus);

    $('modalClose').addEventListener('click', closeModal);
    $('modalOk').addEventListener('click', closeModal);
    $('btnHelpPdf').addEventListener('click', downloadInstructionPdf);
    el.modal.addEventListener('click', (e) => { if (e.target === el.modal) closeModal(); });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { closeModal(); closeMenus(); return; }
      const ctrl = e.ctrlKey || e.metaKey;
      if (!ctrl) return;
      const k = e.key.toLowerCase();
      if (k === 'z') { e.preventDefault(); undo(); }
      if (k === 'y') { e.preventDefault(); redo(); }
      if (k === 'o') { e.preventDefault(); el.fileInput.click(); }
    });

    if (window.ResizeObserver) {
      new ResizeObserver(() => { renderPhoto(); renderMap(); }).observe(el.photoWrap);
      new ResizeObserver(() => renderMap()).observe(el.mapWrap);
    } else window.addEventListener('resize', () => { renderPhoto(); renderMap(); });
  }
  function closeMenus() {
    document.querySelectorAll('.menu-trigger').forEach((b) => b.classList.remove('open'));
    document.querySelectorAll('.menu-dropdown').forEach((d) => d.classList.remove('open'));
  }
  function toggleMinimap() {
    S.minimapVisible = !S.minimapVisible;
    el.minimapBox.hidden = !S.minimapVisible;
    $('btnMinimap').classList.toggle('selected', S.minimapVisible);
    renderMinimap();
    status(S.minimapVisible ? 'Карта просмотра открыта.' : 'Карта просмотра скрыта.');
  }
  function escHtml(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  const TIP_LABELS = {
    'open': 'Файл → Загрузить снимок', 'close': 'Файл → Закрыть снимок',
    'save-mask': 'Файл → Сохранить маску (PNG)', 'save-report': 'Файл → Сохранить отчёт (PDF)',
    'undo': 'Правка → Отменить', 'redo': 'Правка → Повторить',
    'clear-mask': 'Правка → Очистить маску', 'reset-view': 'Правка → Сбросить масштаб',
    'view-overlay': 'Вид → Снимок + маска', 'view-image': 'Вид → Только снимок',
    'view-mask': 'Вид → Только маска', 'toggle-minimap': 'Вид → Карта просмотра',
    'zoom-fit': 'Вид → Показать всё', 'tab-photo': 'Переход → Фотоснимок',
    'tab-map': 'Переход → Карта и водосбор', 'help': 'Справка → Инструкция',
    'about': 'Справка → О программе',
    'rot1': '⟲ 90°', 'rot3': '⟳ 90°', 'rot2': '180°', 'fliph': '⇋ отразить', 'flipv': '⇵ отразить',
    'btnLoad': '📂 Загрузить снимок', 'btnLoadBig': '📂 Выбрать файл',
    'btnDemoImage': 'Попробовать на примере', 'btnCrop': '✂ Обрезать снимок',
    'btnSegment': '🌊 Выделить реку', 'btnAnalyze': '📐 Рассчитать D',
    'btnSaveMask': '💾 Сохранить маску (PNG)', 'btnSaveReport': '📄 Сохранить отчёт (PDF)',
    'btnUndo': '↶ Назад', 'btnRedo': '↷ Вперёд', 'btnZoomIn': '🔍+ (снимок)',
    'btnZoomOut': '🔍− (снимок)', 'btnZoomFit': '⛶ Всё', 'btnMinimap': '🗺 Карта (снимок)',
    'photo': 'Вкладка «Фотоснимок»', 'map': 'Вкладка «Карта и водосбор»',
    'btnMapSearch': '🔎 Найти', 'btnMapHome': '⌂', 'btnMapZoomIn': '🔍+ (карта)',
    'btnMapZoomOut': '🔍− (карта)', 'btnMapMinimap': '🗺 Мини-карта',
    'btnMapMark': '📌 Метка', 'btnMapClearMarks': '🗑 Метки',
    'btnMapCatch': '🌊 Построить водосбор', 'btnMapDim': '📐 Рассчитать D (карта)',
    'btnMapPdf': '💾 Отчёт PDF (карта)', 'btnHelpPdf': '📄 Скачать инструкцию (PDF)',
    'modalClose': '✕', 'modalOk': 'Понятно',
    'method': 'Способ выделения', 'tol': 'Допуск по цвету', 'tolNum': 'Допуск (число)',
    'largest': 'Только крупнейшая область', 'tool': 'Инструмент мыши',
    'brush': 'Размер ластика/кисти', 'brushNum': 'Размер (число)',
    'object': 'Объект расчёта', 'viewMode': 'Вид', 'maxDivs': 'Число делений сетки',
    'maxDivsNum': 'Число делений (число)', 'scaleText': 'Масштаб, м/пиксель',
    'mapSource': 'Слой карты', 'mapRelief': 'Рельеф',
    'mapLat': 'Широта', 'mapLon': 'Долгота', 'mapMarkText': 'Подпись метки'
  };
  function nl2br(text) {
    return escHtml(text).replace(/\n/g, '<br>');
  }
  function instructionHtml() {
    const buttonRows = Object.keys(TIPS).map((k) =>
      `<tr><td>${escHtml(TIP_LABELS[k] || k)}</td><td>${nl2br(TIPS[k])}</td></tr>`).join('');
    const fieldRows = Object.keys(FIELD_TIPS).map((k) =>
      `<tr><td>${escHtml(TIP_LABELS[k] || k)}</td><td>${nl2br(FIELD_TIPS[k])}</td></tr>`).join('');
    return `
      <h2>1. Что делает Гидрофрактал</h2>
      <p>Программа оценивает фрактальную размерность реки по спутниковому снимку или по карте
      и рельефу. Снимок разбивается квадратной сеткой n×n; сторона ячейки ε = side/n,
      N(ε) — число клеток, через которые проходит линия реки. Точки (log 1/ε, log N)
      ложатся на прямую, её наклон — размерность блуждания h, а итоговая размерность
      <b>D = 1 + h/2</b>. По D оцениваются средний многолетний расход Qср, коэффициенты
      вариации Cv и асимметрии Cs и кривая обеспеченности Пирсона III типа.</p>
      <h2>2. Работа со снимком</h2>
      <ol>
        <li><b>Загрузите снимок</b> кнопкой «📂 Загрузить снимок» или перетащите файл.
          Поддерживаются JPG, PNG, TIFF и BMP, включая 16-битные TIFF — они нормализуются автоматически.</li>
        <li>Инструментом «🖱 Точка расхода (створ)» кликните <b>по руслу</b>. Цвет точки становится
          эталоном воды, а сама точка — створом: выше неё должна остаться измеряемая часть реки.</li>
        <li>Подберите «Допуск по цвету» (обычно 50–80) и нажмите «🌊 Выделить реку».
          Зелёным покажется маска воды.</li>
        <li><b>Важно.</b> Ластиком сотрите всё, что ниже створа. В расчёте должна остаться
          только область <b>выше</b> створа; иначе D будет неверным.</li>
        <li>Если снимок нужно обрезать, нажмите «✂ Обрезать снимок», выделите прямоугольник ЛКМ.
          Изображение и маска обрежутся вместе; створ и доп. точки сдвинутся. D придётся пересчитать.</li>
        <li>Нажмите «📐 Рассчитать D». Появятся D = 1 + h/2, R², таблица n/ε/N, график log–log
          и оценка Qср, Cv, Cs.</li>
        <li>«💾 Сохранить маску (PNG)» — чёрная река на белом фоне с метаданными
          (размер, 300 dpi, масштаб, источник, дата). «📄 Сохранить отчёт (PDF)» — полный отчёт.</li>
        <li>После любой правки маски нажмите «Рассчитать D» заново.</li>
      </ol>
      <h2>3. Параметры и их влияние</h2>
      <ul>
        <li><b>Способ выделения.</b> «По цвету точки (HSV)» сравнивает тон, насыщенность и яркость
          с эталонной точкой; «Тёмная вода» берёт всё темнее точки по каналу V; «Комбинация»
          объединяет правила (ИЛИ) — воды больше, но риск захватить тени выше.</li>
        <li><b>Допуск по цвету.</b> 20–40 — узкая чистая маска, но русло может разорваться;
          90–130 — сплошное русло, но захватываются тени и крыши. Разрывы завышают N(ε)
          на мелких ячейках и «плывёт» наклон прямой.</li>
        <li><b>Только крупнейшая область.</b> Отсекает случайные тёмные пятна; без галочки
          посторонние островки раздувают N(ε) и завышают D.</li>
        <li><b>Инструменты.</b> Точка — створ и эталон цвета; ластик — удалить лишнее и убрать
          всё ниже створа; кисть — дорисовать пропущенную воду; «Двигать» — панорамирование.</li>
        <li><b>Размер кисти/ластика</b> задаётся в пикселях исходного снимка: 10–20 — тонкая работа,
          40–80 — быстрая зачистка больших пятен.</li>
        <li><b>Объект расчёта.</b> Скелет — ось реки, самая честная оценка D; граница — контур маски,
          D чуть выше; заполненная маска даёт D→2, это размерность области, а не линии.</li>
        <li><b>Число делений сетки.</b> По умолчанию 60, шаг n += 1; 40–80 — разумный диапазон.
          Слишком много делений упирается в число пикселей реки и слегка занижает наклон.</li>
        <li><b>Колесо мыши</b> масштабирует холст до 12× с привязкой к курсору; Ctrl+Z / Ctrl+Y —
          отмена и повтор; кнопки ориентации поворачивают снимок вместе с маской и точками.</li>
      </ul>
      <h2>4. Карта и водосбор</h2>
      <ol>
        <li>Откройте вкладку «🗺 Карта и водосбор». Подложка загружается через Leaflet:
          Esri, при недоступности — Google Satellite и OpenStreetMap; для топо — OpenTopoMap.</li>
        <li>Панорамируйте карту мышью, масштабируйте колесом или кнопками 🔍+/🔍−.
          Кнопка «⌂» возвращает к Санкт-Петербургу.</li>
        <li>Поля «Широта» / «Долгота» и кнопка «🔎 Найти» <b>только центрируют карту</b>,
          створ не ставят. Чтобы задать створ, кликните по руслу.</li>
        <li>Кнопка «🌊 Построить водосбор» строит: синий — предварительная область,
          оливковый — уточнённый водосбор, коричневый — речная сеть, бордовый — главное русло.
          Дополнительно показывается мини-карта и порядок реки Стралера.</li>
        <li>В режиме «📌 Метка» клики по подложке ставят пронумерованные заметки с подписью
          из поля «Подпись метки»; «🗑 Метки» удаляет их. Метки попадают в PDF-отчёт.</li>
        <li>«📐 Рассчитать D» считает D по главному руслу. «💾 Отчёт PDF» формирует сводный отчёт.</li>
      </ol>
      <h2>5. Отчёт</h2>
      <p>PDF повторяет эталон: титул, разделы I–VII, таблицы 1–5, рисунки 1–4, формулы (1)–(11)
      с пояснениями к каждому символу, серые пояснения под таблицами и альбомная страница
      с вероятностной клетчаткой. Формат A4, Times New Roman, нумерация страниц.
      На GitHub Pages «Сохранить отчёт» открывает окно печати браузера — выберите
      «Сохранить как PDF».</p>
      <h2>6. Что именно делает каждая кнопка и поле</h2>
      <table>
        <thead><tr><th>Элемент</th><th>Действие и влияние</th></tr></thead>
        <tbody>${buttonRows}${fieldRows}</tbody>
      </table>`;
  }
  function downloadInstructionPdf() {
    const win = window.open('', '_blank');
    if (!win) { toast('Разрешите всплывающие окна для сохранения инструкции.'); return; }
    win.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8">
      <title>Инструкция — Гидрофрактал</title><style>
      @page { size: A4; margin: 2cm; @bottom-center { content: counter(page); font-family: "Times New Roman"; } }
      body { font-family: "Times New Roman", Times, serif; font-size: 12pt; line-height: 1.4; color: #000; }
      h1 { font-size: 18pt; text-align: center; color: #5F0001; }
      h2 { font-size: 14pt; color: #5F0001; margin-top: 16pt; }
      p, li { text-align: justify; }
      table { border-collapse: collapse; width: 100%; font-size: 9pt; margin-top: 8pt; }
      th, td { border: 1px solid #666; padding: 3pt 5pt; vertical-align: top; }
      th { background: #F4DDCF; }
      @media screen { body { max-width: 21cm; margin: 1cm auto; } }
      </style></head><body><h1>Как работать с Гидрофракталом</h1>${instructionHtml()}</body></html>`);
    win.document.close();
    setTimeout(() => { try { win.focus(); win.print(); } catch (e) { /* ignore */ } }, 500);
  }

  function menuAction(act) {
    const actions = {
      open: () => el.fileInput.click(),
      close: closePhoto,
      'save-mask': saveMask,
      'save-report': saveReport,
      undo, redo,
      'clear-mask': clearMask,
      'reset-view': resetView,
      'view-overlay': () => { S.view = 'overlay'; $('viewMode').value = 'overlay'; renderPhoto(); },
      'view-image': () => { S.view = 'image'; $('viewMode').value = 'image'; renderPhoto(); },
      'view-mask': () => { S.view = 'mask'; $('viewMode').value = 'mask'; renderPhoto(); },
      'toggle-minimap': toggleMinimap,
      'zoom-fit': resetView,
      'tab-photo': () => switchTab('photo'),
      'tab-map': () => switchTab('map'),
      help: () => openModal('Как работать с Гидрофракталом', instructionHtml()),
      about: () => openModal('О программе', `
        <p><b>Гидрофрактал</b> — веб-версия настольного приложения для оценки фрактальной размерности рек.</p>
        <p>Сегментация воды в HSV, скелет/контур маски, канторовский метод (D = 1 + h/2), оценка Cv, Cs и кривой обеспеченности по Пирсону III типа — все алгоритмы перенесены из десктопного приложения без изменений.</p>
        <p>Карта использует Esri World Imagery / OpenTopoMap и высоты SRTM (AWS Terrain Tiles).
        Если сервер запущен без доступа к сети, показывается демо-местность.</p>`)
    };
    if (actions[act]) actions[act]();
  }

  // ---------------------------------------------------------------- подсказки
  const TIPS = {
    // Меню
    'Файл': 'Загрузка снимка, сохранение маски и отчёта',
    'Правка': 'Отмена/повтор, очистка маски и сброс масштаба',
    'Вид': 'Переключение вида снимка и карты просмотра',
    'Переход': 'Переключение между вкладками «Фотоснимок» и «Карта»',
    'Справка': 'Инструкция и сведения о программе',
    // Действия меню
    'open': `Загружает снимок (JPG, PNG, TIFF…).
16-битные TIFF нормализуются автоматически.
После загрузки кликните по руслу реки инструментом «Точка».`,
    'close': `Прекращает работу с текущим снимком:
снимок, маска, точки и результаты удаляются с экрана.
Сначала показывается предупреждение — подтверждайте,
только если точно хотите закрыть снимок
(несохранённые результаты будут утеряны).`,
    'save-mask': `Сохраняет маску реки как чёрно-белое PNG:
белый = вода, чёрный = фон. Можно использовать как
исходные данные в другой программе (QGIS и т.п.).`,
    'save-report': 'Формирует сводный отчёт в PDF.',
    'undo': 'Отменить последнее изменение маски (Ctrl+Z).',
    'redo': 'Повторить отменённое изменение маски (Ctrl+Y).',
    'clear-mask': 'Полностью очистить выделение воды. После этого нужно заново выделить реку.',
    'reset-view': 'Вернуть масштаб и положение снимка к исходным («вся картинка»).',
    'view-overlay': 'Снимок с полупрозрачной зелёной подсветкой выделенной воды.',
    'view-image': 'Только исходный снимок без подсветки маски.',
    'view-mask': 'Белая река на чёрном фоне — удобно проверить, что выделилось ровно русло. На D выбор вида не влияет.',
    'toggle-minimap': `Открыть/закрыть мини-окно «🗺 Карта просмотра»:
вся картинка целиком с красной рамкой текущего вида.
Клик или перетаскивание по мини-карте — перейти
к этому месту на основном холсте.`,
    'zoom-fit': 'Вернуться к масштабу «вся картинка» и центру.',
    'tab-photo': 'Перейти к работе со спутниковым снимком: HSV-сегментация, маска и D.',
    'tab-map': 'Перейти к карте: рельеф, водосбор, главное русло, Стралер и D.',
    'help': 'Открыть краткую инструкцию по работе.',
    'about': 'Сведения о HydroFractal и алгоритмах.',
    // Кнопки снимка — тексты из настольной программы
    'btnLoad': `Загружает снимок (JPG, PNG, TIFF…).
16-битные TIFF нормализуются автоматически.
После загрузки кликните по руслу реки инструментом «Точка».`,
    'btnLoadBig': `Загружает снимок (JPG, PNG, TIFF…).
16-битные TIFF нормализуются автоматически.`,
    'btnCrop': `Режим обрезки снимка.
Нажмите кнопку, затем выделите прямоугольник ЛКМ на снимке —
обрезке подвергаются и изображение, и текущая маска.
Точка створа и доп. точки сдвигаются вместе с областью.
D после обрезки нужно пересчитать заново.`,
    'btnDemoImage': `Загрузить демонстрационный снимок реки.
Удобно попробовать все этапы без поиска файла:
створ → сегментация → ластик → расчёт D.`,
    'btnSegment': `Пересоздаёт маску воды от точки-эталона с текущими
«Способом выделения», «Допуском» и флажком «Только крупнейшая
область».
Внимание: ручные правки ластиком/кистью при этом теряются.`,
    'btnAnalyze': `Метод Кантора (квадраты) (Новикова, Булякова,
2024; обоснование — Балханов В.К., 2013, гл. 2 § 2).
Изображение покрывается сеткой n×n, n увеличивается
на 1 за шаг; ε = side/n. N(ε) — число клеток, по которым
идёт линия реки. Прямая по точкам (log 1/ε, log N),
её наклон — размерность блуждания h. Итог: D = 1 + h/2.
Считается по «Объект расчёта» (по умолчанию — скелет).
Ориентир: D ≈ 1.6 — как у дельт Волги/Лены по публикациям
(1.56–1.63). Для одиночного неразветвлённого русла метод
завышает D — там правильнее клеточный box-counting.`,
    'btnSaveMask': `Сохраняет маску реки как чёрно-белое PNG:
белый = вода, чёрный = фон. Можно использовать как
исходные данные в другой программе (QGIS и т.п.).`,
    'btnSaveReport': 'Формирует сводный отчёт в PDF.',
    'btnUndo': 'Отменить последнее движение кисти или ластика (Ctrl+Z).',
    'btnRedo': 'Повторить отменённое действие (Ctrl+Y).',
    'btnZoomIn': `Увеличить масштаб (×1.25) с привязкой к центру.
Точная привязка — колесом мыши над холстом:
точка под курсором остаётся на месте.
Максимум — 12×.`,
    'btnZoomOut': 'Уменьшить масштаб (÷1.25). При 100% видна вся картинка.',
    'btnZoomFit': 'Вернуться к масштабу «вся картинка» и центру.',
    'btnMinimap': `Открыть/закрыть мини-окно «🗺 Карта просмотра»:
вся картинка целиком с красной рамкой текущего вида.
Клик по мини-карте — перейти к этому месту на холсте.`,
    'rot1': `Поворот снимка на 90° ПРОТИВ часовой стрелки.
Поворачивается всё: снимок, маска и обе отмеченные точки.
На D поворот не влияет (форма не меняется) — это удобство обзора.`,
    'rot3': `Поворот снимка на 90° ПО часовой стрелке.
Поворачивается всё: снимок, маска и обе отмеченные точки. На D не влияет.`,
    'rot2': `Поворот снимка на 180°.
Поворачивается всё: снимок, маска и обе отмеченные точки. На D не влияет.`,
    'fliph': `Зеркальное отражение слева направо (как перевернуть страницу).
Отражаются снимок, маска и точки. На D не влияет.`,
    'flipv': `Зеркальное отражение сверху вниз.
Отражаются снимок, маска и точки. На D не влияет.`,
    'photo': 'Вкладка анализа спутникового снимка.',
    'map': 'Вкладка карты и водосбора.',
    // Кнопки карты
    'btnMapMark': `Режим заметок на карте: включите его и кликайте по подложке,
чтобы поставить пронумерованные метки. Подпись берется из поля
«Подпись метки». Повторное нажатие выключает режим — после этого
клик по карте снова ставит створ.`,
    'btnMapClearMarks': 'Удаляет все проставленные на карте метки. Створ и водосбор не трогает.',
    'btnHelpPdf': 'Открывает окно печати: выберите «Сохранить как PDF», чтобы скачать полную инструкцию.',
    'btnMapSearch': `Ищет место по введённым координатам и центрирует карту.
Это только ПЕРЕХОД к месту: маркер створа не ставится,
водосбор и D не пересчитываются. Чтобы задать створ,
кликните по руслу на карте.`,
    'btnMapHome': `Возвращает карту к центру — Санкт-Петербург
(59.93428° N, 30.33510° E), масштаб z11. Створ не меняется.`,
    'btnMapZoomIn': `Приблизить карту на один уровень (z + 1).
Географические координаты створа при этом не меняются.`,
    'btnMapZoomOut': `Отдалить карту на один уровень (z − 1).
Географические координаты створа при этом не меняются.`,
    'btnMapMinimap': `Показать/скрыть мини-карту с видом всего района.
Клик по мини-карте центрирует основной холст в этом месте;
створ при этом не ставится.`,
    'btnMapCatch': `Строит предварительную область водосбора (синий контур),
уточнённый водосбор (оливковый), речную сеть (коричневый)
и главное русло (бордовый) по рельефу D8.
Створ задаётся кликом по руслу; если его нет, используется центр карты.`,
    'btnMapDim': `Считает D канторовским методом по главному руслу
построенного водосбора. Таблица n/ε/N и график log–log
появляются справа; по D оцениваются Qср, Cv и Cs.`,
    'btnMapPdf': 'Формирует сводный отчёт в PDF.',
    'modalClose': 'Закрыть окно.',
    'modalOk': 'Понятно, закрыть окно.'
  };
  const FIELD_TIPS = {
    method: `Как программа отличает воду от берега.
• «По цвету точки (HSV)» — пиксель считается водой, если его цвет
  ближе, чем «допуск», к цвету кликнутой точки (с учётом тона,
  насыщенности и яркости).
• «Тёмная вода (яркость)» — водой считается всё, что ТЕМНЕЕ точки
  клика (канал V) + допуск. Удобно для почти серых снимков.
• «Комбинация признаков» — объединение правил (ИЛИ): выделяется
  больше воды, но выше риск захватить тени.
Влияние на расчёт: более широкое правило → более широкая река
в маске → мельче детали русла на мелкой ε-сетке.`,
    tol: `Порог «похожести на воду» (в единицах HSV-расстояния, 10…160).
Меньше (20–40) — выделяются только пиксели почти цвета точки:
маска узкая и чистая, но русло может разорваться.
Больше (90–130) — русло сплошное и широкое, но захватываются
тени, тёмные крыши и дороги.
Для D это важно так: разрывы маски порождают много мелких
компонентов, из-за чего N(ε) на малых ε завышается и наклон
прямой в log–log «плывёт». Ориентир: двигать допуск, пока
зелёная подсветка не покроет русло без разрывов и без луж
за его пределами; обычно это 50–80.`,
    tolNum: 'То же, что ползунок «Допуск по цвету»: HSV-расстояние до эталонного цвета воды.',
    largest: `Оставляет в маске только самую БОЛЬШУЮ связную область воды,
всё остальное удаляется.
Зачем: отсекает случайные тёмные пятна (тени леса, крыши),
которые иначе попадут в подсчёт ячеек.
Влияние на расчёт: без галочки посторонние «островки» раздувают
N(ε) на малых размерах ячеек и завышают D.
Снимите галочку, если нужно считать и основное русло,
и протоки/старицы как единое целое.`,
    tool: `Что делает левая кнопка мыши на снимке:
• «Точка расхода (створ)» — отмечает створ (красный маркер 1):
  цвет под курсором становится эталоном воды, а сама точка —
  опорой для расчёта D;
• «Ластик» — удаляет ошибочно выделенные области. ИМ ЖЕ убирают
  всё ниже по течению: в расчёте должна остаться только часть
  реки ВЫШЕ створа;
• «Кисть» — дорисовывает пропущенные участки воды.
Любая правка маски отменяет расчёт: после правки нажмите
«📐 Рассчитать D» заново.`,
    brush: `Радиус ластика/кисти в пикселях ИСХОДНОГО снимка (не экрана).
10–20 — для тонкой работы вдоль береговой линии и проток,
40–80 — чтобы быстро счистить большие тёмные пятна.
На значение D влияет косвенно: радиус определяет, насколько
точно вы повторите береговую линию при ручной правке.`,
    brushNum: 'Радиус кисти/ластика в пикселях исходного снимка.',
    object: `По какому объекту строится зависимость N(ε):
• «Скелет (центр русла)» — осевая однопиксельная линия реки;
  самая честная оценка D хода реки.
• «Граница воды (контур)» — тонкий контур маски; результат
  близок к скелету, но D чуть выше из-за двух берегов сразу.
• «Заполненная маска» — вся площадь воды; N(ε) ≈ A/ε², поэтому
  D завышается к 2 и описывает «заполнение области», а не
  извилистость реки. Не используйте для сравнения рек.
Ожидаемое D для рек: скелет ≈ 1.05–1.35.`,
    viewMode: `Что показывать на холсте:
• «Снимок + маска» — снимок с полупрозрачной зелёной
  подсветкой выделенной воды;
• «Только снимок» — сам снимок без подсветки;
• «Только маска» — белая река на чёрном фоне
  (удобно проверить, что выделилось ровно русло).
На маску и на расчёт D выбор вида не влияет.`,
    maxDivs: `Максимальное число делений сетки n×n по стороне
(по умолчанию 60). Точки (log 1/ε, log N(ε)) берутся
по всем n от 1 до этого значения. Больше — длиннее
ряд и стабильнее наклон, но N упирается в число пикселей
реки (насыщение) и наклон слегка занижается на мелких ε.
40–80 — разумный диапазон.`,
    maxDivsNum: 'То же, что ползунок числа делений сетки: максимальное n для метода Кантора.',
    scaleText: `Реальный масштаб снимка, м/пиксель (необязательно),
например 0.5. Подставляется в метаданные PNG маски
(поле Scale), куда также записываются размер,
разрешение 300 dpi, источник и дата.
Если оставить пустым — будет «not set».`,
    mapSource: 'Подложка карты через Leaflet: спутник Esri/Google или топокарта OpenTopoMap. Leaflet сам переключает резервные источники при ошибках тайлов.',
    mapRelief: 'Показать отмывку рельефа по AWS Terrain Tiles. Она же используется для расчёта водосбора и главного русла.',
    mapMarkText: 'Подпись для следующей метки на карте. Оставьте пустым — будет автоматическая нумерация.',
    mapLat: 'Широта центра карты в градусах. Кнопка «Найти» только центрирует карту, не ставя створ.',
    mapLon: 'Долгота центра карты в градусах. Кнопка «Найти» только центрирует карту, не ставя створ.'
  };
  function initTooltips() {
    document.querySelectorAll('button').forEach((btn) => {
      const key = btn.id || btn.dataset.act || btn.dataset.tab ||
        btn.dataset.rotate || btn.dataset.menu || btn.textContent.trim();
      const tip = TIPS[key];
      if (tip) btn.title = tip;
    });
    Object.keys(FIELD_TIPS).forEach((id) => {
      const node = $(id);
      if (node && !node.title) node.title = FIELD_TIPS[id];
    });
  }

  // ------------------------------------------------------------------- init
  function init() {
    initTooltips();
    setStatusForTool();
    bindEvents();
    renderPhoto();
    updateHistoryButtons();
    if (STATIC_MODE) {
      $('onlineText').textContent = 'расчёты в браузере';
      status('Статический режим: все расчёты выполняются в браузере (GitHub Pages).');
    } else {
      fetch('/api/health').then((r) => r.json()).then((d) => {
        if (d.ok) {
          $('onlineText').textContent = 'сервер готов';
        } else throw new Error('health check');
      }).catch(() => {
        $('onlineDot').classList.add('err');
        $('onlineText').textContent = 'сервер недоступен';
      });
    }
  }
  init();
})();
