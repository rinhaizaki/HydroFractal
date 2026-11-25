/* HydroFractal — клиентское вычислительное ядро для GitHub Pages.
   Повторяет алгоритмы app.py / core без сервера: сегментация, Кантор,
   PNG-маска с метаданными, D8-гидрология, тайлы и отчёт через печать PDF. */
(function () {
  'use strict';

  const HF = {};
  const TILE = 256;
  const MAX_LAT = 85.05112878;
  const MAJOR_P = [0.1, 0.5, 1, 2, 5, 10, 20, 30, 40, 50,
    60, 70, 80, 90, 95, 98, 99, 99.5, 99.9];
  const D8 = [[-1, 0, 1], [1, 0, 4], [0, -1, 16], [0, 1, 1],
    [-1, -1, 128], [-1, 1, 64], [1, -1, 8], [1, 1, 2]];
  const DY = { 1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1 };
  const DX = { 1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1 };
  const SOURCES = {
    esri: {
      name: 'Esri (спутник)',
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      credit: 'Снимок: Esri, Maxar, Earthstar Geographics'
    },
    sentinel: {
      name: 'Sentinel-2 L2A (Planetary Computer)',
      url: 'https://planetarycomputer.microsoft.com/api/data/v1/item/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?collection=sentinel-2-l2a&item={item}&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png',
      credit: 'Sentinel-2 L2A: Copernicus / Planetary Computer'
    }
  };
  const PC_STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/search';
  const PC_DEM_TILES = 'https://planetarycomputer.microsoft.com/api/data/v1/collections/cop-dem-glo-30/items/{item}/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?assets=data&rescale=-1000,4000&format=png';
  const NASADEM_TILES = 'https://planetarycomputer.microsoft.com/api/data/v1/collections/nasadem/items/{item}/tiles/WebMercatorQuad/{z}/{x}/{y}@1x?assets=elevation&rescale=-100,4000&format=png';
  const TERRARIUM_URL = 'https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png';
  const TERRAIN_CREDIT = 'ЦМР: Planetary Computer (Copernicus DEM GLO-30 / NASADEM), резерв — Terrarium';
  const sentinelItems = new Map();
  function findSentinelItem(lon, lat) {
    const key = Math.round(lon * 4) + ':' + Math.round(lat * 4);
    if (sentinelItems.has(key)) return sentinelItems.get(key);
    const q = new URLSearchParams({
      collections: 'sentinel-2-l2a',
      bbox: `${(lon - 0.16).toFixed(5)},${(lat - 0.16).toFixed(5)},${(lon + 0.16).toFixed(5)},${(lat + 0.16).toFixed(5)}`,
      datetime: '2024-01-01/2026-12-31', limit: '1',
      query: JSON.stringify({ 'eo:cloud_cover': { lt: 25 } })
    });
    const promise = fetch(PC_STAC + '?' + q.toString())
      .then((r) => r.ok ? r.json() : Promise.reject(new Error('STAC недоступен')))
      .then((d) => (d.features && d.features[0] && d.features[0].id) || null)
      .catch(() => null);
    sentinelItems.set(key, promise);
    return promise;
  }
  function tileToLonLat(x, y, z) {
    const n = Math.pow(2, z);
    const lon = x / n * 360 - 180;
    const lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
    return [lon, lat];
  }
  function demItemName(lon, lat) {
    const ilon = Math.floor(lon), ilat = Math.floor(lat);
    return 'Copernicus_DSM_COG_10_' + (ilat >= 0 ? 'N' : 'S') + Math.abs(ilat) +
      '_00_' + (ilon >= 0 ? 'E' : 'W') + String(Math.abs(ilon)).padStart(3, '0') + '_00_DEM';
  }
  function pcDemUrl(z, x, y) {
    const [lon, lat] = tileToLonLat(x + 0.5, y + 0.5, z);
    return PC_DEM_TILES.replace('{item}', demItemName(lon, lat))
      .replace('{z}', z).replace('{x}', x).replace('{y}', y);
  }
  function nasaDemItemName(lon, lat) {
    const ilon = Math.round(lon), ilat = Math.round(lat);
    return 'NASADEM_HGT_' + (ilat >= 0 ? 'n' : 's') + String(Math.abs(ilat)).padStart(2, '0') +
      (ilon >= 0 ? 'e' : 'w') + String(Math.abs(ilon)).padStart(3, '0');
  }
  function nasaDemUrl(z, x, y) {
    const [lon, lat] = tileToLonLat(x + 0.5, y + 0.5, z);
    return NASADEM_TILES.replace('{item}', nasaDemItemName(lon, lat))
      .replace('{z}', z).replace('{x}', x).replace('{y}', y);
  }
  const TILE_CREDITS = {
    esri: [
      'Снимок: Esri, Maxar, Earthstar Geographics',
      'Снимок: Esri, Maxar, Earthstar Geographics',
      'Снимок: Esri, Maxar, Earthstar Geographics',
      'Снимок: Google Satellite',
      'Снимок: Google Satellite',
      'Карта: © OpenStreetMap (резерв)'
    ],
    sentinel: [
      'Sentinel-2 L2A: Copernicus / Planetary Computer',
      'Снимок: Esri, Maxar, Earthstar Geographics',
      'Снимок: Google Satellite'
    ]
  };

  // ------------------------------------------------------------- изображения
  function loadImage(src, timeoutMs) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      let done = false;
      const timer = setTimeout(() => finish(new Error('Таймаут загрузки изображения.')),
        timeoutMs || 12000);
      function finish(err, value) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        img.onload = img.onerror = null;
        if (err) reject(err); else resolve(value);
      }
      img.onload = () => finish(null, img);
      img.onerror = () => finish(new Error('Не удалось прочитать изображение.'));
      img.src = src;
    });
  }
  function loadFirstImage(urls) {
    if (!urls.length) return Promise.reject(new Error('нет источников тайла'));
    return loadImage(urls[0]).then((img) => ({ img, index: 0 }))
      .catch(() => loadFirstImage(urls.slice(1))
        .then((res) => ({ img: res.img, index: res.index + 1 })));
  }
  function dataUrlToBytes(dataURL) {
    const comma = dataURL.indexOf(',');
    return Uint8Array.from(atob(dataURL.slice(comma + 1)), (c) => c.charCodeAt(0));
  }
  function bytesToDataUrl(bytes, mime) {
    let binary = '';
    const step = 8192;
    for (let i = 0; i < bytes.length; i += step) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    }
    return `data:${mime};base64,${btoa(binary)}`;
  }
  function canvasContext(w, h) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    return { canvas: c, ctx: c.getContext('2d', { willReadFrequently: true }) };
  }
  function drawNormalizedImage(dataURL, maxSide) {
    return loadImage(dataURL).then((img) => {
      let w = img.naturalWidth, h = img.naturalHeight;
      if (!w || !h) throw new Error('Пустое изображение.');
      if (Math.max(w, h) > maxSide) {
        const k = maxSide / Math.max(w, h);
        w = Math.max(1, Math.round(w * k));
        h = Math.max(1, Math.round(h * k));
      }
      const { canvas, ctx } = canvasContext(w, h);
      ctx.drawImage(img, 0, 0, w, h);
      return { canvas, ctx, width: w, height: h, data: ctx.getImageData(0, 0, w, h) };
    });
  }
  function median(values) {
    values.sort((a, b) => a - b);
    return values[values.length >> 1];
  }
  function rgbToHsv(data) {
    const n = data.length / 4;
    const hsv = new Float32Array(n * 3);
    for (let i = 0, p = 0; i < n; i++, p += 4) {
      const r = data[p] / 255, g = data[p + 1] / 255, b = data[p + 2] / 255;
      const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
      let h = 0;
      if (d > 0) {
        if (max === r) h = 60 * (((g - b) / d) % 6);
        else if (max === g) h = 60 * ((b - r) / d + 2);
        else h = 60 * ((r - g) / d + 4);
        if (h < 0) h += 360;
        h /= 2; // OpenCV: 0…179
      }
      hsv[i * 3] = h;
      hsv[i * 3 + 1] = max ? (d / max) * 255 : 0;
      hsv[i * 3 + 2] = max * 255;
    }
    return hsv;
  }
  function refHsv(hsv, W, H, cx, cy, rad) {
    cx = Math.max(0, Math.min(W - 1, Math.round(cx)));
    cy = Math.max(0, Math.min(H - 1, Math.round(cy)));
    const hs = [], ss = [], vs = [];
    for (let y = Math.max(0, cy - rad); y < Math.min(H, cy + rad + 1); y++) {
      for (let x = Math.max(0, cx - rad); x < Math.min(W, cx + rad + 1); x++) {
        const i = (y * W + x) * 3;
        hs.push(hsv[i]); ss.push(hsv[i + 1]); vs.push(hsv[i + 2]);
      }
    }
    return [median(hs), median(ss), median(vs)];
  }
  function morphology(src, W, H, mode) {
    const dst = new Uint8Array(src.length);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        let any = false, all = true;
        for (let dy = -1; dy <= 1 && all; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const ny = y + dy, nx = x + dx;
            const v = (ny >= 0 && ny < H && nx >= 0 && nx < W) ? src[ny * W + nx] : 0;
            if (v) any = true; else all = false;
          }
        }
        dst[y * W + x] = mode === 'erode' ? (all ? 1 : 0) : (any ? 1 : 0);
      }
    }
    return dst;
  }
  function keepLargest(mask, W, H) {
    const labels = new Int32Array(W * H);
    const sizes = [0];
    let label = 0;
    const stack = [];
    for (let i = 0; i < mask.length; i++) {
      if (!mask[i] || labels[i]) continue;
      label++;
      let size = 0;
      labels[i] = label; stack.push(i);
      while (stack.length) {
        const cur = stack.pop();
        size++;
        const y = (cur / W) | 0, x = cur - y * W;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const ny = y + dy, nx = x + dx;
            if (dy === 0 && dx === 0 || ny < 0 || ny >= H || nx < 0 || nx >= W) continue;
            const ni = ny * W + nx;
            if (mask[ni] && !labels[ni]) { labels[ni] = label; stack.push(ni); }
          }
        }
      }
      sizes[label] = size;
    }
    if (label <= 1) return mask;
    let best = 1;
    for (let i = 2; i <= label; i++) if (sizes[i] > sizes[best]) best = i;
    const out = new Uint8Array(mask.length);
    for (let i = 0; i < mask.length; i++) out[i] = labels[i] === best ? 1 : 0;
    return out;
  }
  function segmentWater(rgbData, seed, opts) {
    const W = rgbData.width, H = rgbData.height;
    const hsv = rgbToHsv(rgbData.data.data);
    const seeds = [refHsv(hsv, W, H, seed.x, seed.y, 4)];
    (opts.extras || []).forEach((p) => seeds.push(refHsv(hsv, W, H, p.x, p.y, 4)));
    const tol = Math.max(1, Math.min(180, Number(opts.tol) || 60));
    let mask = new Uint8Array(W * H);
    if (opts.method === 'color' || opts.method === 'hybrid') {
      for (let i = 0; i < W * H; i++) {
        for (let s = 0; s < seeds.length; s++) {
          const ref = seeds[s];
          let dh = Math.abs(hsv[i * 3] - ref[0]);
          dh = Math.min(dh, 180 - dh) * (255 / 180);
          const ds = hsv[i * 3 + 1] - ref[1];
          const dv = hsv[i * 3 + 2] - ref[2];
          if (Math.sqrt(dh * dh + ds * ds + dv * dv) <= tol) { mask[i] = 1; break; }
        }
      }
    }
    if (opts.method === 'dark' || opts.method === 'hybrid') {
      const vSeed = Math.max.apply(null, seeds.map((s) => s[2]));
      for (let i = 0; i < W * H; i++) if (hsv[i * 3 + 2] <= vSeed + tol) mask[i] = 1;
    }
    mask = morphology(mask, W, H, 'erode');
    mask = morphology(mask, W, H, 'dilate');
    mask = morphology(mask, W, H, 'dilate');
    mask = morphology(mask, W, H, 'erode');
    if (opts.keep_largest !== false) mask = keepLargest(mask, W, H);
    return mask;
  }
  function maskToImageData(mask, W, H, fg, bg) {
    const out = new ImageData(W, H);
    for (let i = 0, p = 0; i < mask.length; i++, p += 4) {
      const c = mask[i] ? fg : bg;
      out.data[p] = c[0]; out.data[p + 1] = c[1]; out.data[p + 2] = c[2]; out.data[p + 3] = c[3];
    }
    return out;
  }
  function maskPngDataUrl(mask, W, H) {
    const { canvas, ctx } = canvasContext(W, H);
    ctx.putImageData(maskToImageData(mask, W, H, [255, 255, 255, 255], [0, 0, 0, 255]), 0, 0);
    return canvas.toDataURL('image/png');
  }
  function maskFromDataUrl(dataURL) {
    return loadImage(dataURL).then((img) => {
      const W = img.naturalWidth, H = img.naturalHeight;
      const { ctx } = canvasContext(W, H);
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, W, H).data;
      const mask = new Uint8Array(W * H);
      for (let i = 0; i < mask.length; i++) mask[i] = d[i * 4] > 127 ? 1 : 0;
      return { mask, W, H };
    });
  }

  // ----------------------------------------------------------- фрактальный D
  function boundaryMask(mask, W, H) {
    const dil = morphology(mask, W, H, 'dilate');
    const ero = morphology(mask, W, H, 'erode');
    const out = new Uint8Array(mask.length);
    for (let i = 0; i < out.length; i++) out[i] = dil[i] && !ero[i] ? 1 : 0;
    return out;
  }
  function skeletonMask(mask, W, H) {
    const cur = Uint8Array.from(mask);
    const marks = new Uint8Array(W * H);
    for (let pass = 0; pass < 200; pass++) {
      let changed = false;
      for (let sub = 0; sub < 2; sub++) {
        marks.fill(0);
        for (let y = 1; y < H - 1; y++) {
          for (let x = 1; x < W - 1; x++) {
            const i = y * W + x;
            if (!cur[i]) continue;
            const p2 = cur[i - W], p3 = cur[i - W + 1], p4 = cur[i + 1],
              p5 = cur[i + W + 1], p6 = cur[i + W], p7 = cur[i + W - 1],
              p8 = cur[i - 1], p9 = cur[i - W - 1];
            const seq = [p2, p3, p4, p5, p6, p7, p8, p9];
            let B = 0, A = 0;
            for (let k = 0; k < 8; k++) {
              B += seq[k];
              if (!seq[k] && seq[(k + 1) % 8]) A++;
            }
            const c1 = sub === 0
              ? (!p2 || !p4 || !p6) && (!p4 || !p6 || !p8)
              : (!p2 || !p4 || !p8) && (!p2 || !p6 || !p8);
            if (B >= 2 && B <= 6 && A === 1 && c1) marks[i] = 1;
          }
        }
        for (let i = 0; i < marks.length; i++) if (marks[i]) { cur[i] = 0; changed = true; }
      }
      if (!changed) break;
    }
    return cur;
  }
  function cantorDimension(mask, W, H, maxDivs) {
    let sum = 0;
    for (let i = 0; i < mask.length; i++) sum += mask[i];
    if (!sum) throw new Error('Маска пуста — нечего считать. Кликните точку на реке и/или увеличьте допуск.');
    const side = Math.max(W, H);
    const divs = Math.max(2, Math.min(Number(maxDivs) || 60, Math.floor(side / 2)));
    const table = [];
    for (let n = 1; n <= divs; n++) {
      const occupied = new Set();
      for (let i = 0; i < mask.length; i++) {
        if (!mask[i]) continue;
        const y = (i / W) | 0, x = i - y * W;
        occupied.add(((y * n / side) | 0) * n + ((x * n / side) | 0));
      }
      table.push([n, side / n, occupied.size]);
    }
    const fitRows = table.filter((r) => r[2] >= 2);
    if (fitRows.length < 3) throw new Error('Слишком мало точек для регрессии — объект слишком мал или плохо выделен.');
    const xs = fitRows.map((r) => Math.log10(1 / r[1]));
    const ys = fitRows.map((r) => Math.log10(r[2]));
    const n = xs.length;
    const mx = xs.reduce((a, b) => a + b, 0) / n;
    const my = ys.reduce((a, b) => a + b, 0) / n;
    let sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) { sxx += (xs[i] - mx) ** 2; sxy += (xs[i] - mx) * (ys[i] - my); }
    const h = sxy / sxx;
    const intercept = my - h * mx;
    let ssRes = 0, ssTot = 0;
    for (let i = 0; i < n; i++) {
      ssRes += (ys[i] - (h * xs[i] + intercept)) ** 2;
      ssTot += (ys[i] - my) ** 2;
    }
    const r2 = ssTot > 0 ? 1 - ssRes / ssTot : 1;
    const dh = Math.sqrt((ssRes / Math.max(n - 2, 1)) / sxx);
    return {
      D: 1 + h / 2, h, dh, dD: dh / 2, r2, intercept,
      table, fit_rows: fitRows, n_divs_used: divs,
      water_pixels: sum
    };
  }

  function normInv(p) {
    // Approximating the normal quantile (Acklam's rational approximation)
    const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
    const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01];
    const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
    const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00];
    const plow = 0.02425;
    if (p < plow) {
      const q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - plow) return -normInv(1 - p);
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const SP33_CS_CV_RATIOS = [0, 0.5, 1, 1.5, 2, 3];
  function sp33KpTable(cv) {
    return MAJOR_P.map((p) => {
      const row = [p];
      SP33_CS_CV_RATIOS.forEach((ratio) => {
        const cs = ratio * cv;
        const z = normInv(1 - p / 100);
        row.push(1 + (z + (cs / 6) * (z * z - 1)) * cv);
      });
      return row;
    });
  }
  function streamStats(D, dD) {
    const qMean = 100;
    const cv = Math.max(0.10, Math.min(0.80, 2 * (D - 1)));
    const cs = 2 * cv;
    const rel = 100 * (dD / Math.max(D - 1, 1e-9));
    const kp = {}, qp = {};
    MAJOR_P.forEach((p) => {
      const z = normInv(1 - p / 100);
      const k = 1 + (z + (cs / 6) * (z * z - 1)) * cv;
      kp[p] = k; qp[p] = k * qMean;
    });
    return {
      Q_mean: qMean, Cv: cv, Cs: cs,
      rel_err_Q: rel, rel_err_Cv: rel, rel_err_Cs: rel * 1.5,
      kp_by_p: kp, qp_by_p: qp, sp33: sp33KpTable(cv),
      qp: MAJOR_P.map((p) => ({ p, k: kp[p], q: qp[p] }))
    };
  }
  function makePlot(result) {
    const { canvas, ctx } = canvasContext(720, 380);
    const W = canvas.width, H = canvas.height;
    ctx.fillStyle = '#FFFFFF'; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#FFFFFF'; ctx.fillRect(48, 18, W - 66, H - 68);
    const rows = result.fit_rows;
    const xs = rows.map((r) => Math.log10(1 / r[1]));
    const ys = rows.map((r) => Math.log10(r[2]));
    if (!xs.length) return canvas.toDataURL('image/png');
    const x0 = Math.min.apply(null, xs) - 0.08, x1 = Math.max.apply(null, xs) + 0.08;
    const y0 = Math.min.apply(null, ys) - 0.08, y1 = Math.max.apply(null, ys) + 0.08;
    const px = (x) => 48 + (x - x0) / (x1 - x0) * (W - 66);
    const py = (y) => 18 + (H - 68) - (y - y0) / (y1 - y0) * (H - 68);
    ctx.strokeStyle = '#DDDDDD'; ctx.lineWidth = 1;
    for (let i = 0; i <= 6; i++) {
      const x = 48 + i * (W - 66) / 6, y = 18 + i * (H - 68) / 6;
      ctx.beginPath(); ctx.moveTo(x, 18); ctx.lineTo(x, H - 50); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(48, y); ctx.lineTo(W - 18, y); ctx.stroke();
    }
    ctx.fillStyle = '#333333'; ctx.font = '12px "Times New Roman", Times, serif';
    ctx.fillText('log₁₀(1/ε)', W / 2 - 34, H - 16);
    ctx.save(); ctx.translate(14, H / 2 + 40); ctx.rotate(-Math.PI / 2);
    ctx.fillText('log₁₀ N(ε)', 0, 0); ctx.restore();
    ctx.beginPath(); ctx.moveTo(px(x0), py(result.h * x0 + result.intercept));
    ctx.lineTo(px(x1), py(result.h * x1 + result.intercept));
    ctx.strokeStyle = '#733933'; ctx.lineWidth = 2; ctx.stroke();
    rows.forEach((r) => {
      ctx.beginPath(); ctx.arc(px(Math.log10(1 / r[1])), py(Math.log10(r[2])), 3.2, 0, 2 * Math.PI);
      ctx.fillStyle = '#9CA75A'; ctx.fill();
      ctx.strokeStyle = '#8B6431'; ctx.lineWidth = 0.8; ctx.stroke();
    });
    ctx.fillStyle = '#733933'; ctx.font = 'bold 13px "Times New Roman", Times, serif';
    ctx.fillText('Канторовский метод: log N(ε) от log(1/ε)', 58, 12);
    return canvas.toDataURL('image/png');
  }
  function cleanResult(r, object) {
    const stream = streamStats(r.D, r.dD);
    return {
      D: r.D, h: r.h, dh: r.dh, dD: r.dD, r2: r.r2, intercept: r.intercept,
      water_pixels: r.water_pixels, object: object || 'skeleton',
      table: r.table.map((row) => [row[0], Math.round(row[1] * 1000) / 1000, row[2]]),
      fit_rows: r.fit_rows, n_divs_used: r.n_divs_used,
      method: 'Кантор (квадраты), D = 1 + h/2', plot: makePlot(r), stream: stream,
      qp: MAJOR_P.map((p) => ({ p, k: stream.kp_by_p[p], q: stream.qp_by_p[p] }))
    };
  }

  // ------------------------------------------------------------------ PNG/meta
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function pngWithMetadata(dataURL, texts) {
    const src = dataUrlToBytes(dataURL);
    let offset = 8, iend = -1;
    while (offset + 12 <= src.length) {
      const len = (src[offset] << 24) | (src[offset + 1] << 16) | (src[offset + 2] << 8) | src[offset + 3];
      const type = String.fromCharCode(src[offset + 4], src[offset + 5], src[offset + 6], src[offset + 7]);
      if (type === 'IEND') { iend = offset; break; }
      offset += 12 + len;
    }
    if (iend < 0) return dataURL;
    const extra = [];
    Object.keys(texts).forEach((key) => {
      const value = String(texts[key] === undefined || texts[key] === null ? '' : texts[key]);
      const raw = new TextEncoder().encode('tEXt' + key + '\0' + value);
      const chunk = new Uint8Array(12 + raw.length);
      const view = new DataView(chunk.buffer);
      view.setUint32(0, raw.length - 4);
      chunk.set(raw.subarray(0, 4), 4);
      chunk.set(raw.subarray(4), 8);
      for (let i = 0; i < 4; i++) chunk[chunk.length - 4 + i] = 0;
      view.setUint32(chunk.length - 4, crc32(raw));
      extra.push(chunk);
    });
    const total = iend + extra.reduce((a, c) => a + c.length, 0);
    const out = new Uint8Array(total);
    out.set(src.subarray(0, iend));
    let pos = iend;
    extra.forEach((c) => { out.set(c, pos); pos += c.length; });
    out.set(src.subarray(iend));
    return bytesToDataUrl(out, 'image/png');
  }

  // --------------------------------------------------------------------- карта
  function lonlatToTile(lon, lat, z) {
    const n = Math.pow(2, z);
    const la = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI / 180;
    return {
      x: (lon + 180) / 360 * n,
      y: (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * n
    };
  }
  function tileToLonlat(x, y, z) {
    const n = Math.pow(2, z);
    return {
      lon: x / n * 360 - 180,
      lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI
    };
  }
  function resolutionM(lat, z) {
    return 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, z);
  }
  function viewGeometry(lon, lat, zoom, width, height) {
    const c = lonlatToTile(lon, lat, zoom);
    return {
      x0: c.x - width / (2 * TILE), y0: c.y - height / (2 * TILE),
      z: zoom, w: width, h: height, center_lon: lon, center_lat: lat
    };
  }
  function tileRange(x0, y0, x1, y1) {
    const out = [];
    for (let y = Math.floor(y0); y <= Math.floor(y1); y++) {
      for (let x = Math.floor(x0); x <= Math.floor(x1); x++) out.push([x, y]);
    }
    return out;
  }
  // Обычные <img> показывают тайлы без CORS (canvas при этом «загрязняется»,
  // поэтому данные для отчёта берём из отдельного синтетического холста).
  function fetchImage(urls) { return loadFirstImage(Array.isArray(urls) ? urls : [urls]); }
  function fetchCorsOnce(url) {
    return fetch(url, { mode: 'cors' }).then((r) => {
      if (!r.ok) throw new Error('tile');
      return r.blob();
    }).then((blob) => {
      const objectUrl = URL.createObjectURL(blob);
      return loadImage(objectUrl).then((img) => {
        URL.revokeObjectURL(objectUrl);
        return img;
      });
    });
  }
  // Для чтения высот нужен CORS. Основной хост S3 — виртуальный; если он
  // недоступен, пробуем публичный CORS-прокси, иначе включаем демо-рельеф.
  function fetchImageCors(url) {
    return fetchCorsOnce(url).catch(() => fetchCorsOnce(
      'https://api.allorigins.win/raw?url=' + encodeURIComponent(url)));
  }
  function valleyCenter(v) {
    return 0.5 + 0.045 * Math.sin(2 * Math.PI * (v - 0.5))
      + 0.018 * Math.sin(4 * Math.PI * (v - 0.5));
  }
  function terrainField(u, v) {
    const d = (u - valleyCenter(v)) / 0.09;
    const valley = Math.exp(-d * d);
    const ridges = 0.55 * Math.sin(2 * Math.PI * (2.3 * u + 1.1 * v) + 0.4)
      + 0.30 * Math.sin(2 * Math.PI * (4.7 * u - 0.8 * v) + 1.7)
      + 0.15 * Math.sin(2 * Math.PI * (9.1 * u + 3.3 * v));
    const small = 0.35 * Math.sin(2 * Math.PI * (17 * u + 5 * v) + 2.1);
    return -1200 * v + 120 * ridges * (1 - valley) + 25 * small * (1 - valley) - 400 * valley;
  }
  function syntheticDem(geo, demZoom, margin) {
    const k = Math.pow(2, demZoom - geo.z);
    const tx0 = Math.floor(geo.x0 * k - margin), ty0 = Math.floor(geo.y0 * k - margin);
    const tx1 = Math.floor((geo.x0 + geo.w / TILE) * k + margin);
    const ty1 = Math.floor((geo.y0 + geo.h / TILE) * k + margin);
    const nx = Math.max(1, tx1 - tx0 + 1), ny = Math.max(1, ty1 - ty0 + 1);
    const H = ny * TILE, W = nx * TILE;
    const dem = new Float32Array(H * W);
    for (let y = 0; y < H; y++) {
      const ty = (ty0 + (y + 0.5) / TILE) / k;
      const v = (ty - geo.y0) * TILE / geo.h;
      for (let x = 0; x < W; x++) {
        const tx = (tx0 + (x + 0.5) / TILE) / k;
        const u = (tx - geo.x0) * TILE / geo.w;
        dem[y * W + x] = terrainField(u, v);
      }
    }
    return { dem, W, H, dgeo: { x0: tx0, y0: ty0, z: demZoom, w: W, h: H, synthetic: true } };
  }
  function syntheticBase(geo, source) {
    const W = geo.w, H = geo.h;
    const { canvas, ctx } = canvasContext(W, H);
    const img = ctx.createImageData(W, H);
    let lo = Infinity, hi = -Infinity;
    const vals = new Float32Array(W * H);
    for (let y = 0; y < H; y++) {
      const v = (y + 0.5) / H;
      for (let x = 0; x < W; x++) vals[y * W + x] = terrainField((x + 0.5) / W, v);
    }
    for (let i = 0; i < vals.length; i++) { if (vals[i] < lo) lo = vals[i]; if (vals[i] > hi) hi = vals[i]; }
    const topo = source === 'topo';
    const low = topo ? [206, 214, 178] : [63, 96, 63];
    const mid = topo ? [174, 190, 141] : [104, 123, 70];
    const high = topo ? [214, 198, 166] : [149, 132, 101];
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        const z = Math.max(0, Math.min(1, (vals[i] - lo) / Math.max(hi - lo, 1e-6)));
        const dx = (vals[i + W] !== undefined && vals[i - W] !== undefined)
          ? (vals[i + W] - vals[i - W]) / (hi - lo) : 0;
        const dy = (vals[i + 1] !== undefined && vals[i - 1] !== undefined)
          ? (vals[i + 1] - vals[i - 1]) / (hi - lo) : 0;
        const norm = Math.sqrt(dx * dx + dy * dy + 0.015);
        const shade = Math.max(0.35, Math.min(1.15, 0.72 + 0.45 * (-dx * 0.7 - dy * 0.7 + 0.7) / norm));
        const t = Math.min(1, z * 2), t2 = Math.max(0, Math.min(1, (z - 0.5) * 2));
        const p = i * 4;
        for (let c = 0; c < 3; c++) {
          let color = low[c] * (1 - t) + mid[c] * t;
          color = color * (1 - t2) + high[c] * t2;
          img.data[p + c] = Math.max(0, Math.min(255, color * shade));
        }
        img.data[p + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    ctx.lineCap = 'round';
    const width = Math.max(2, Math.round(Math.min(W, H) / 260));
    for (const [color, w] of [['rgba(63,97,116,.4)', width + 5], ['rgba(58,116,152,.86)', width]]) {
      ctx.strokeStyle = color; ctx.lineWidth = w; ctx.beginPath();
      for (let y = 0; y < H; y++) {
        const x = valleyCenter((y + 0.5) / H) * W;
        if (y === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    return canvas;
  }
  function blendRelief(canvas, dem, W, H) {
    const { ctx } = canvasContext(W, H);
    const img = ctx.createImageData(W, H);
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < dem.length; i++) { if (dem[i] < lo) lo = dem[i]; if (dem[i] > hi) hi = dem[i]; }
    const range = Math.max(hi - lo, 1e-6);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const sx = Math.min(dem.W - 1, Math.floor(x / W * dem.W));
        const sy = Math.min(dem.H - 1, Math.floor(y / H * dem.H));
        const i = sy * dem.W + sx;
        const zx = Math.min(dem.W - 1, sx + 1), zy = Math.min(dem.H - 1, sy + 1);
        const dx = (dem[sy * dem.W + zx] - dem[i]) / range;
        const dy = (dem[zy * dem.W + sx] - dem[i]) / range;
        const norm = Math.sqrt(dx * dx + dy * dy + 0.02);
        const shade = Math.max(0.4, Math.min(1, (-dx * 0.6 - dy * 0.6 + 0.8) / norm));
        const p = (y * W + x) * 4;
        img.data[p] = img.data[p + 1] = img.data[p + 2] = shade * 255;
        img.data[p + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    const base = canvasContext(W, H);
    base.ctx.drawImage(canvas, 0, 0);
    base.ctx.globalAlpha = 0.55;
    base.ctx.drawImage(ctx.canvas, 0, 0);
    return base.canvas;
  }

  function loadTerrain(geo, demZoom, margin) {
    const k = Math.pow(2, demZoom - geo.z);
    const tx0 = Math.floor(geo.x0 * k - margin), ty0 = Math.floor(geo.y0 * k - margin);
    const tx1 = Math.floor((geo.x0 + geo.w / TILE) * k + margin);
    const ty1 = Math.floor((geo.y0 + geo.h / TILE) * k + margin);
    const nx = Math.max(1, tx1 - tx0 + 1), ny = Math.max(1, ty1 - ty0 + 1);
    const W = nx * TILE, H = ny * TILE;
    const tiles = tileRange(tx0, ty0, tx1, ty1);
    const decode = (img, lo, hi, source, terrarium) => {
      const c = canvasContext(TILE, TILE);
      c.ctx.drawImage(img, 0, 0);
      const d = c.ctx.getImageData(0, 0, TILE, TILE).data;
      const heights = new Float32Array(TILE * TILE);
      for (let i = 0; i < heights.length; i++) {
        const q = i * 4;
        heights[i] = terrarium
          ? d[q] * 256 + d[q + 1] + d[q + 2] / 256 - 32768
          : (d[q + 3] < 128 ? NaN : d[q] / 255 * (hi - lo) + lo);
      }
      return { tx, ty, heights, source };
    };
    const jobs = tiles.map(([tx, ty]) => {
      const terrainUrl = TERRARIUM_URL.replace('{z}', demZoom).replace('{x}', tx).replace('{y}', ty);
      return fetchImageCors(pcDemUrl(demZoom, tx, ty))
        .then((img) => decode(img, -1000, 4000, 'cop-dem-glo-30', false))
        .catch(() => fetchImageCors(nasaDemUrl(demZoom, tx, ty))
          .then((img) => decode(img, -100, 4000, 'nasadem', false)))
        .catch(() => fetchImageCors(terrainUrl)
          .then((img) => decode(img, 0, 1, 'terrarium', true)))
        .catch(() => null);
    });
    return Promise.all(jobs).then((parts) => {
      if (parts.every((p) => !p)) return null;
      const dem = new Float32Array(W * H);
      dem.fill(NaN);
      parts.forEach((p) => {
        if (!p) return;
        const i = tiles.findIndex(([x, y]) => x === p.tx && y === p.ty);
        const ox = (tiles[i][0] - tx0) * TILE, oy = (tiles[i][1] - ty0) * TILE;
        for (let y = 0; y < TILE; y++) {
          dem.set(p.heights.subarray(y * TILE, y * TILE + TILE), (oy + y) * W + ox);
        }
      });
      const finite = [];
      for (let i = 0; i < dem.length; i++) if (Number.isFinite(dem[i])) finite.push(dem[i]);
      const med = median(finite) || 0;
      for (let i = 0; i < dem.length; i++) if (!Number.isFinite(dem[i])) dem[i] = med;
      const sources = {};
      parts.forEach((p) => { if (p && p.source) sources[p.source] = (sources[p.source] || 0) + 1; });
      const demSource = Object.keys(sources).sort((a, b) => sources[b] - sources[a])[0] || 'synthetic';
      return { dem, W, H, source: demSource, dgeo: { x0: tx0, y0: ty0, z: demZoom, w: W, h: H } };
    });
  }
  function sampleDemToView(info, geo, W, H) {
    const k = Math.pow(2, info.dgeo.z - geo.z);
    const out = new Float32Array(W * H);
    for (let y = 0; y < H; y++) {
      const ty = (geo.y0 + (y + 0.5) / TILE) * k - info.dgeo.y0;
      const sy = Math.max(0, Math.min(info.H - 1, Math.floor(ty * TILE)));
      for (let x = 0; x < W; x++) {
        const tx = (geo.x0 + (x + 0.5) / TILE) * k - info.dgeo.x0;
        const sx = Math.max(0, Math.min(info.W - 1, Math.floor(tx * TILE)));
        out[y * W + x] = info.dem[sy * info.W + sx];
      }
    }
    return { dem: out, W, H };
  }

  function hillshadeOverlay(info, geo, W, H) {
    const sampled = sampleDemToView(info, geo, W, H);
    const dem = sampled.dem;
    const { canvas, ctx } = canvasContext(W, H);
    const img = ctx.createImageData(W, H);
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < dem.length; i++) {
      if (dem[i] < lo) lo = dem[i];
      if (dem[i] > hi) hi = dem[i];
    }
    const range = Math.max(hi - lo, 1e-6);
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        const i = y * W + x;
        const x1 = Math.min(W - 1, x + 1), y1 = Math.min(H - 1, y + 1);
        const dx = (dem[y * W + x1] - dem[i]) / range;
        const dy = (dem[y1 * W + x] - dem[i]) / range;
        const norm = Math.sqrt(dx * dx + dy * dy + 0.02);
        const shade = Math.max(0.25, Math.min(1, (-dx * 0.6 - dy * 0.6 + 0.85) / norm));
        const p = i * 4;
        img.data[p] = img.data[p + 1] = img.data[p + 2] = Math.round(shade * 255);
        img.data[p + 3] = 140;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas;
  }

  function mapView(params) {
    const source = SOURCES[params.source] ? params.source : 'esri';
    return (source === 'sentinel'
      ? findSentinelItem(Number(params.lon), Number(params.lat))
      : Promise.resolve(null))
      .then((item) => mapViewCore(params, item));
  }

  function mapViewCore(params, sentinelItem) {
    const lon = Number(params.lon), lat = Number(params.lat), z = Number(params.zoom);
    const W = Math.max(240, Math.min(1100, Number(params.width) || 900));
    const H = Math.max(180, Math.min(760, Number(params.height) || 580));
    const source = SOURCES[params.source] ? params.source : 'esri';
    const geo = viewGeometry(lon, lat, z, W, H);
    const coords = tileRange(geo.x0, geo.y0, geo.x0 + W / TILE, geo.y0 + H / TILE)
      .filter(([x, y]) => x >= 0 && y >= 0 && x < Math.pow(2, z) && y < Math.pow(2, z));
    // Одна и та же локальная подложка используется, если тайлы не пришли,
    // и как «чистая» копия для PDF (оригинальные тайлы загрязняют canvas).
    const safe = syntheticBase(geo, source);
    const skipTiles = !!params.skip_tiles;   // подложку грузит Leaflet
    const sub = ['a', 'b', 'c'];
    const jobs = skipTiles ? [] : coords.map(([x, y]) => {
      const template = SOURCES[source].url.replace('{item}',
        encodeURIComponent(sentinelItem || ''));
      const urls = [template];
      urls.push('https://services.arcgisonline.com/ArcGIS/rest/services/' +
        'World_Imagery/MapServer/tile/{z}/{y}/{x}');
      urls.push('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}');
      urls.push('https://mt2.google.com/vt/lyrs=s&x={x}&y={y}&z={z}');
      const candidates = urls.map((u) => u
        .replace('{s}', sub[(x + y) % 3])
        .replace('{z}', z).replace('{x}', x).replace('{y}', y));
      return fetchImage(candidates).then(({ img, index }) => ({
        img, sourceIndex: index,
        px: (x - geo.x0) * TILE, py: (y - geo.y0) * TILE
      })).catch(() => null);
    });
    return Promise.all(jobs).then((results) => {
      const tiles = results.filter(Boolean);
      const demo = !skipTiles && tiles.length === 0;
      const used = {};
      tiles.forEach((t) => { used[t.sourceIndex] = (used[t.sourceIndex] || 0) + 1; });
      const mainSource = Object.keys(used)
        .sort((a, b) => used[b] - used[a])
        .map(Number)[0];
      const creditBase = (TILE_CREDITS[source] || [SOURCES[source].credit])[mainSource]
        || SOURCES[source].credit;
      const answer = (relief) => ({
        ok: true,
        image: safe.toDataURL('image/jpeg', 0.88),
        tiles, relief: relief ? relief.toDataURL('image/png') : null,
        credit: creditBase + ' · ' + TERRAIN_CREDIT + (demo ? ' (демо-карта)' : ''),
        demo, source_used: mainSource,
        cell_m: Math.round(resolutionM(lat, z) * 100) / 100, geo
      });
      if (!params.relief) return answer(null);
      const dz = Math.min(z, 12);
      return loadTerrain(geo, dz, 0).then((real) => {
        const info = real || syntheticDem(geo, Math.min(z, 10), 0);
        return answer(hillshadeOverlay(info, geo, W, H));
      });
    });
  }

  // --------------------------------------------------------------- гидрология
  function fillDepressions(dem, W, H, eps) {
    const filled = Float64Array.from(dem);
    const visited = new Uint8Array(W * H);
    const heapZ = new Float64Array(W * H + 4);
    const heapI = new Int32Array(W * H + 4);
    let size = 0;
    const push = (z, i) => {
      let p = size++;
      heapZ[p] = z; heapI[p] = i;
      while (p > 0) {
        const parent = (p - 1) >> 1;
        if (heapZ[parent] <= heapZ[p]) break;
        const tz = heapZ[parent], ti = heapI[parent];
        heapZ[parent] = heapZ[p]; heapI[parent] = heapI[p];
        heapZ[p] = tz; heapI[p] = ti;
        p = parent;
      }
    };
    const pop = () => {
      const rz = heapZ[0], ri = heapI[0];
      size--;
      if (size > 0) {
        heapZ[0] = heapZ[size]; heapI[0] = heapI[size];
        let p = 0;
        for (;;) {
          const l = 2 * p + 1, r = l + 1;
          let m = p;
          if (l < size && heapZ[l] < heapZ[m]) m = l;
          if (r < size && heapZ[r] < heapZ[m]) m = r;
          if (m === p) break;
          const tz = heapZ[m], ti = heapI[m];
          heapZ[m] = heapZ[p]; heapI[m] = heapI[p];
          heapZ[p] = tz; heapI[p] = ti;
          p = m;
        }
      }
      return [rz, ri];
    };
    for (let x = 0; x < W; x++) {
      [0, H - 1].forEach((y) => {
        const i = y * W + x;
        if (!visited[i]) { visited[i] = 1; push(filled[i], i); }
      });
    }
    for (let y = 0; y < H; y++) {
      [0, W - 1].forEach((x) => {
        const i = y * W + x;
        if (!visited[i]) { visited[i] = 1; push(filled[i], i); }
      });
    }
    while (size) {
      const [z, idx] = pop();
      const y = (idx / W) | 0, x = idx - y * W;
      for (let d = 0; d < D8.length; d++) {
        const ny = y + D8[d][0], nx = x + D8[d][1];
        if (ny < 0 || ny >= H || nx < 0 || nx >= W) continue;
        const ni = ny * W + nx;
        if (visited[ni]) continue;
        visited[ni] = 1;
        if (filled[ni] <= z) filled[ni] = z + eps;
        push(filled[ni], ni);
      }
    }
    return filled;
  }
  function flowDirections(filled, W, H, cell) {
    const best = new Float32Array(W * H);
    const fdir = new Uint8Array(W * H);
    D8.forEach(([dy, dx, code]) => {
      const dist = Math.hypot(dy, dx) * cell;
      const ys0 = Math.max(0, -dy), ys1 = Math.min(H, H - dy);
      const xs0 = Math.max(0, -dx), xs1 = Math.min(W, W - dx);
      for (let y = ys0; y < ys1; y++) {
        for (let x = xs0; x < xs1; x++) {
          const i = y * W + x, ni = (y + dy) * W + (x + dx);
          const slope = (filled[i] - filled[ni]) / dist;
          if (slope > best[i]) { best[i] = slope; fdir[i] = code; }
        }
      }
    });
    return fdir;
  }
  function flowAccumulation(filled, fdir, W, H) {
    const acc = new Float64Array(W * H).fill(1);
    const order = new Int32Array(W * H);
    for (let i = 0; i < order.length; i++) order[i] = i;
    order.sort((a, b) => filled[b] - filled[a]);
    for (let k = 0; k < order.length; k++) {
      const idx = order[k], d = fdir[idx];
      if (!d) continue;
      const y = (idx / W) | 0, x = idx - y * W;
      const ny = y + DY[d], nx = x + DX[d];
      if (ny >= 0 && ny < H && nx >= 0 && nx < W) acc[ny * W + nx] += acc[idx];
    }
    return acc;
  }
  function catchmentUpstream(fdir, W, H, oy, ox) {
    if (oy < 0 || oy >= H || ox < 0 || ox >= W) throw new Error('Створ за пределами рельефа.');
    const seen = new Uint8Array(W * H);
    const stack = [oy * W + ox];
    seen[stack[0]] = 1;
    let count = 1;
    while (stack.length) {
      const cur = stack.pop(), y = (cur / W) | 0, x = cur - y * W;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dy && !dx) continue;
          const ny = y + dy, nx = x + dx;
          if (ny < 0 || ny >= H || nx < 0 || nx >= W) continue;
          const ni = ny * W + nx;
          if (seen[ni]) continue;
          const d = fdir[ni];
          if (DY[d] === -dy && DX[d] === -dx) { seen[ni] = 1; count++; stack.push(ni); }
        }
      }
    }
    return { seen, count };
  }
  function mainChannel(fdir, acc, catchMask, W, H, oy, ox) {
    const line = new Uint8Array(W * H);
    if (!catchMask[oy * W + ox]) return { line, count: 0 };
    line[oy * W + ox] = 1;
    let cy = oy, cx = ox, count = 1;
    const minAcc = Math.max(2, 0.02 * acc[oy * W + ox]);
    for (let step = 0; step < W * H; step++) {
      let best = -1, bestIdx = -1;
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (!dy && !dx) continue;
          const ny = cy + dy, nx = cx + dx;
          if (ny < 0 || ny >= H || nx < 0 || nx >= W) continue;
          const ni = ny * W + nx;
          if (!catchMask[ni] || line[ni]) continue;
          const d = fdir[ni];
          if (DY[d] !== -dy || DX[d] !== -dx) continue;
          if (acc[ni] > best) { best = acc[ni]; bestIdx = ni; }
        }
      }
      if (bestIdx < 0 || best < minAcc) break;
      cy = (bestIdx / W) | 0; cx = bestIdx - cy * W;
      line[bestIdx] = 1; count++;
    }
    if (count < 5) {
      const cut = 0.6 * acc[oy * W + ox];
      for (let i = 0; i < line.length; i++) line[i] = catchMask[i] && acc[i] >= cut ? 1 : 0;
      count = line.reduce((a, b) => a + b, 0);
    }
    return { line, count };
  }
  function strahlerOrder(fdir, network, acc, W, H) {
    const cells = [];
    for (let i = 0; i < network.length; i++) if (network[i]) cells.push(i);
    if (!cells.length) return 1;
    cells.sort((a, b) => acc[a] - acc[b]);
    const best = new Int16Array(W * H), eq = new Int16Array(W * H);
    let result = 1;
    cells.forEach((i) => {
      const y = (i / W) | 0, x = i - y * W;
      const top = best[i], cnt = eq[i];
      const st = top === 0 ? 1 : (cnt >= 2 ? top + 1 : top);
      const d = fdir[i];
      const ny = y + (DY[d] || 0), nx = x + (DX[d] || 0);
      if (ny < 0 || ny >= H || nx < 0 || nx >= W) return;
      const ni = ny * W + nx;
      if (!network[ni]) return;
      if (st > best[ni]) { best[ni] = st; eq[ni] = 1; }
      else if (st === best[ni]) eq[ni]++;
      if (st > result) result = st;
    });
    return result;
  }
  function demAtScreen(geo, dgeo, row, col) {
    const lonlat = tileToLonlat(dgeo.x0 + (col + 0.5) / TILE, dgeo.y0 + (row + 0.5) / TILE, dgeo.z);
    const t = lonlatToTile(lonlat.lon, lonlat.lat, geo.z);
    return [(t.x - geo.x0) * TILE, (t.y - geo.y0) * TILE];
  }
  function dilateMask(mask, W, H, radius) {
    let cur = mask;
    for (let r = 0; r < (radius || 1); r++) {
      const out = new Uint8Array(W * H);
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          let v = 0;
          for (let dy = -1; dy <= 1 && !v; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              const ny = y + dy, nx = x + dx;
              if (ny >= 0 && ny < H && nx >= 0 && nx < W && cur[ny * W + nx]) { v = 1; break; }
            }
          }
          out[y * W + x] = v;
        }
      }
      cur = out;
    }
    return cur;
  }
  function overlayMap(baseCanvas, geo, dgeo, catchment, network, line, outletPx, preview) {
    const ctx = baseCanvas.getContext('2d');
    const W = baseCanvas.width, H = baseCanvas.height;
    ctx.save();
    const cellSize = Math.max(1.4, TILE / Math.pow(2, geo.z - dgeo.z));
    if (preview) {
      ctx.fillStyle = 'rgba(70,130,200,.24)';
      for (let i = 0; i < preview.length; i++) {
        if (!preview[i]) continue;
        const [px, py] = demAtScreen(geo, dgeo, (i / dgeo.w) | 0, i % dgeo.w);
        if (px < -8 || py < -8 || px > W + 8 || py > H + 8) continue;
        ctx.fillRect(px, py, cellSize, cellSize);
      }
    }
    ctx.fillStyle = 'rgba(156,167,90,.30)';
    for (let i = 0; i < catchment.length; i++) {
      if (!catchment[i]) continue;
      const [px, py] = demAtScreen(geo, dgeo, (i / dgeo.w) | 0, i % dgeo.w);
      if (px < -8 || py < -8 || px > W + 8 || py > H + 8) continue;
      ctx.fillRect(px, py, cellSize, cellSize);
    }
    ctx.fillStyle = 'rgba(139,100,49,.75)';
    for (let i = 0; i < network.length; i++) {
      if (!network[i]) continue;
      const [px, py] = demAtScreen(geo, dgeo, (i / dgeo.w) | 0, i % dgeo.w);
      if (px >= 0 && py >= 0 && px <= W && py <= H) ctx.fillRect(px, py, 1.4, 1.4);
    }
    ctx.fillStyle = 'rgba(115,57,51,.95)';
    for (let i = 0; i < line.length; i++) {
      if (!line[i]) continue;
      const [px, py] = demAtScreen(geo, dgeo, (i / dgeo.w) | 0, i % dgeo.w);
      if (px >= 0 && py >= 0 && px <= W && py <= H) ctx.fillRect(px - 0.8, py - 0.8, 2.2, 2.2);
    }
    ctx.strokeStyle = '#ff3c3c'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(outletPx[0], outletPx[1], 9, 0, 2 * Math.PI); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(outletPx[0] - 15, outletPx[1]); ctx.lineTo(outletPx[0] + 15, outletPx[1]);
    ctx.moveTo(outletPx[0], outletPx[1] - 15); ctx.lineTo(outletPx[0], outletPx[1] + 15);
    ctx.stroke();
    ctx.restore();
    return baseCanvas.toDataURL('image/png');
  }

  function mapAnalyze(params) {
    const lon = Number(params.lon), lat = Number(params.lat), z = Number(params.zoom);
    const W = Math.max(240, Math.min(1100, Number(params.width) || 900));
    const H = Math.max(180, Math.min(760, Number(params.height) || 580));
    const source = SOURCES[params.source] ? params.source : 'esri';
    const outletLon = Number(params.outlet_lon), outletLat = Number(params.outlet_lat);
    const geo = viewGeometry(lon, lat, z, W, H);
    const view = mapView({ ...params, relief: false });
    const demZoom = Math.min(z, 10);
    const demPromise = loadTerrain(geo, demZoom, 1)
      .then((real) => real || syntheticDem(geo, demZoom, 1));
    return Promise.all([view, demPromise]).then(([viewResult, demInfo]) => {
      const dem = demInfo.dem, dW = demInfo.W, dH = demInfo.H, dgeo = demInfo.dgeo;
      const cell = resolutionM(lat, dgeo.z);
      const filled = fillDepressions(dem, dW, dH, 0.05);
      const fdir = flowDirections(filled, dW, dH, cell);
      const acc = flowAccumulation(filled, fdir, dW, dH);
      const op = lonlatToTile(outletLon, outletLat, demZoom);
      const oy = Math.round((op.y - dgeo.y0) * TILE), ox = Math.round((op.x - dgeo.x0) * TILE);
      if (oy < 0 || oy >= dH || ox < 0 || ox >= dW) throw new Error('Створ за пределами загруженного рельефа.');
      const catchResult = catchmentUpstream(fdir, dW, dH, oy, ox);
      if (catchResult.count < 3) throw new Error('Створ попал на водораздел или в бессточную впадину. Кликните по видимому руслу реки.');
      const catchMask = catchResult.seen;
      let maxAcc = 0;
      for (let i = 0; i < catchMask.length; i++) if (catchMask[i] && acc[i] > maxAcc) maxAcc = acc[i];
      const threshold = Math.max(3, 0.01 * maxAcc);
      const net = new Uint8Array(catchMask.length);
      let netCount = 0;
      for (let i = 0; i < net.length; i++) if (catchMask[i] && acc[i] >= threshold) { net[i] = 1; netCount++; }
      const ch = mainChannel(fdir, acc, catchMask, dW, dH, oy, ox);
      if (ch.count < 10) throw new Error('Главное русло слишком короткое для расчёта D. Попробуйте кликнуть ниже по течению.');
      const strahler = strahlerOrder(fdir, net, acc, dW, dH);
      const r = cantorDimension(ch.line, dW, dH, 60);
      const result = cleanResult(r, 'skeleton');
      const tp = lonlatToTile(outletLon, outletLat, geo.z);
      const overlayCanvas = canvasContext(W, H);
      const previewMask = dilateMask(catchMask, dW, dH, 2);
      const overlay = overlayMap(overlayCanvas.canvas, geo, dgeo, catchMask, net, ch.line,
        [(tp.x - geo.x0) * TILE, (tp.y - geo.y0) * TILE], previewMask);
      const reportCanvas = canvasContext(W, H);
      const channelMask = canvasContext(dW, dH);
      const maskPixels = channelMask.ctx.createImageData(dW, dH);
      for (let i = 0; i < ch.line.length; i++) {
        if (!ch.line[i]) continue;
        const q = i * 4;
        maskPixels.data[q] = maskPixels.data[q + 1] = maskPixels.data[q + 2] = 255;
        maskPixels.data[q + 3] = 255;
      }
      channelMask.ctx.putImageData(maskPixels, 0, 0);
      const mask = channelMask.canvas.toDataURL('image/png');
      return Promise.all([loadImage(viewResult.image), loadImage(overlay)]).then(([baseImg, overImg]) => {
        reportCanvas.ctx.drawImage(baseImg, 0, 0, W, H);
        reportCanvas.ctx.drawImage(overImg, 0, 0, W, H);
        const image = reportCanvas.canvas.toDataURL('image/png');
        return {
          ok: true, image, overlay, mask, width: W, height: H,
          tiles: viewResult.tiles, relief: viewResult.relief,
          demo: !!viewResult.demo,
          credit: viewResult.credit,
          map: {
            area_km2: Math.round(catchResult.count * cell * cell / 1e6 * 1000) / 1000,
            channel_km: Math.round(ch.count * cell / 1000 * 1000) / 1000,
            cells: catchResult.count, line_cells: ch.count, network_cells: netCount,
            preview_cells: previewMask.reduce((a, b) => a + b, 0),
            threshold: Math.round(threshold * 100) / 100, strahler,
            cell_m: Math.round(cell * 100) / 100, dem_zoom: dgeo.z,
            outlet_lat: Math.round(outletLat * 1e5) / 1e5,
            outlet_lon: Math.round(outletLon * 1e5) / 1e5
          },
          result
        };
      });
    });
  }

  // -------------------------------------------------------------------- отчёт
  function escapeHtml(value) {
    return String(value === undefined || value === null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function tableHtml(rows, head) {
    if (!rows || !rows.length) return '';
    return '<table><thead><tr>' + head.map((h) => `<th>${escapeHtml(h)}</th>`).join('') +
      '</tr></thead><tbody>' + rows.map((row) => '<tr>' +
        row.map((c) => `<td>${escapeHtml(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
  }
  function invertMaskDataUrl(dataURL) {
    if (!dataURL) return Promise.resolve(null);
    return loadImage(dataURL).then((img) => {
      const { canvas, ctx } = canvasContext(img.naturalWidth, img.naturalHeight);
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, canvas.width, canvas.height);
      for (let i = 0; i < d.data.length; i += 4) {
        const v = d.data[i] > 127 ? 0 : 255;
        d.data[i] = d.data[i + 1] = d.data[i + 2] = v;
        d.data[i + 3] = 255;
      }
      ctx.putImageData(d, 0, 0);
      return canvas.toDataURL('image/png');
    }).catch(() => null);
  }
  function probabilityGrid() {
    const W = 900, H = 470, x0 = 78, x1 = W - 24, y0 = 24, y1 = H - 52;
    const zmin = normInv(0.001), zmax = normInv(0.999);
    const xp = (p) => x0 + (normInv(p / 100) - zmin) / (zmax - zmin) * (x1 - x0);
    const yp = (k) => y1 - k / 5.5 * (y1 - y0);
    let out = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="white" stroke="black" stroke-width="1"/>`;
    for (let k = 0.5; k <= 5.4; k += 0.5) {
      const major = Math.abs(k - Math.round(k)) < 1e-6;
      const y = yp(k);
      out += `<line x1="${x0}" y1="${y}" x2="${x1}" y2="${y}" stroke="${major ? 'black' : '#b8b8b8'}" stroke-width="${major ? 0.8 : 0.35}"/>`;
      if (major) {
        out += `<line x1="${x0 - 6}" y1="${y}" x2="${x0}" y2="${y}" stroke="black" stroke-width="0.5"/>`;
        out += `<text x="${x0 - 10}" y="${y + 4}" text-anchor="end" font-size="13" font-family="Times New Roman">${k}</text>`;
      }
    }
    const MINOR_P = [1.5, 3, 6, 15, 25, 35, 45, 65, 85, 97];
    MINOR_P.forEach((p) => {
      const x = xp(p);
      out += `<line x1="${x}" y1="${y0}" x2="${x}" y2="${y1}" stroke="#b8b8b8" stroke-width="0.35"/>`;
    });
    MAJOR_P.forEach((p, i) => {
      const x = xp(p);
      out += `<line x1="${x}" y1="${y0}" x2="${x}" y2="${y1}" stroke="black" stroke-width="${i === 0 || i === MAJOR_P.length - 1 ? 0.8 : 0.5}"/>`;
      out += `<text x="${x}" y="${y1 + 14}" text-anchor="middle" font-size="11" font-family="Times New Roman">${String(p).replace('.', ',')}</text>`;
    });
    out += `<text x="${(x0 + x1) / 2}" y="${H - 8}" text-anchor="middle" font-size="14" font-family="Times New Roman">Обеспеченность P, %</text>
      <text transform="translate(20,${(y0 + y1) / 2}) rotate(-90)" text-anchor="middle" font-size="14" font-family="Times New Roman">Модульный коэффициент k<tspan baseline-shift="sub" font-size="10">p</tspan></text>
      </svg>`;
    return out;
  }
  function report(payload) {
    const r = payload.result || {};
    const stream = payload.stream || r.stream || streamStats(r.D || 1, r.dD || 0);
    const fromParams = (label, fallback) => {
      const row = (payload.params || []).find((p) => p[0] === label);
      return row ? row[1] : fallback;
    };
    const ru = (v, n) => (v === undefined || v === null || Number.isNaN(Number(v))
      ? '—' : Number(v).toFixed(n === undefined ? 3 : n).replace('.', ','));
    const w = payload.width || fromParams('Размер снимка', '—');
    const seed = payload.seed;
    const seedText = seed
      ? `x = ${Math.round(seed.x)}, y = ${Math.round(seed.y)}` +
        (payload.seed_rgb ? ` (RGB = ${payload.seed_rgb.join(', ')})` : '')
      : 'не отмечена';
    const extras = payload.color_pts || [];
    const methodText = { color: 'по цвету точки (HSV)', dark: 'тёмная вода (яркость)',
      hybrid: 'комбинация признаков' }[payload.method] || 'по цвету точки (HSV)';
    const objectText = { skeleton: 'скелет (центр русла)', boundary: 'граница воды (контур)',
      mask: 'заполненная маска' }[payload.object] || 'скелет (центр русла)';
    const water = r.water_pixels || 0;
    const waterPct = (payload.width && payload.height)
      ? 100 * water / (payload.width * payload.height) : 0;
    const table1 = [
      ['Файл', payload.source_name || fromParams('Источник', '—')],
      ['Размер снимка', `${w} px`],
      ['Точка расхода (створ)', seedText],
      ['Доп. точки цвета', extras.length ? `${extras.length} шт.: ` +
        extras.map((p) => `x=${Math.round(p.x)}, y=${Math.round(p.y)}`).join(', ') : 'нет'],
      ['Способ выделения', `${methodText}; допуск = ${payload.tol === undefined ? '—' : payload.tol}`],
      ['Объект расчёта', objectText],
      ['Максимальное число делений сетки', `${payload.max_divs || r.n_divs_used || '—'} (шаг n += 1)`],
      ['Пикселей воды', `${water} (${ru(waterPct, 2)} % кадра)`],
      ['Маска', payload.mask_touched ? 'отредактирована вручную (ластик/кисть)' : 'автоматическая сегментация']
    ];
    const r2 = Number(r.r2 || 0), corr = Math.sqrt(r2);
    const rows3 = (r.table || []).map((row) => [
      row[0], ru(row[1], 1), String(row[2]),
      ru(Math.log10(1 / Number(row[1])), 3), ru(Math.log10(Number(row[2])), 3)
    ]);
    const relQ = stream.rel_err_Q || 0, relCv = stream.rel_err_Cv || 0, relCs = stream.rel_err_Cs || 0;
    const rows4 = [
      ['Средний многолетний расход воды, м³/с', 'Qср', ru(stream.Q_mean, 2), ru(relQ, 1), '± ' + ru(stream.Q_mean * relQ / 100, 2)],
      ['Коэффициент вариации', 'Cv', ru(stream.Cv, 3), ru(relCv, 1), '± ' + ru(stream.Cv * relCv / 100, 3)],
      ['Коэффициент асимметрии', 'Cs', ru(stream.Cs, 3), ru(relCs, 1), '± ' + ru(stream.Cs * relCs / 100, 3)]
    ];
    const rows5 = (stream.qp || []).map((p) => [
      String(p.p).replace('.', ','), ru(p.k, 2), ru(p.q, 1)
    ]);
    const spTable = stream.sp33 || sp33KpTable(stream.Cv || 0.3);
    const ratios = [0, 0.5, 1, 1.5, 2, 3];
    const rowsSp = spTable.map((row) => [
      String(row[0]).replace('.', ','), ...row.slice(1).map((v) => ru(v, 2))
    ]);
    const tbl = (caption, head, rows, cls) => `<div class="tbl-cap">${escapeHtml(caption)}</div>
      <table class="${cls || ''}"><thead><tr>${head.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((row) => '<tr>' + row.map((c) => `<td>${escapeHtml(c)}</td>`).join('') + '</tr>').join('')}</tbody></table>`;
    const mapReport = (payload.source_name === 'карта и водосбор' ||
      /карте/i.test(payload.title || ''));
    // Легенда и координатная метка для рисунка 2.
    const geo = payload.geo || {};
    const center = geo.center || {}, outlet = geo.outlet || {};
    const coordLines = mapReport ? [
      (Number.isFinite(Number(outlet.lat)) && Number.isFinite(Number(outlet.lon)))
        ? `Створ: ${Number(outlet.lat).toFixed(5)}° N, ${Number(outlet.lon).toFixed(5)}° E`
        : (fromParams('Створ', '') ? `Створ: ${fromParams('Створ', '')}` : ''),
      (Number.isFinite(Number(center.lat)) && Number.isFinite(Number(center.lon)))
        ? `Центр: ${Number(center.lat).toFixed(5)}° N, ${Number(center.lon).toFixed(5)}° E`
        : (fromParams('Центр карты', '') ? `Центр: ${fromParams('Центр карты', '')}` : ''),
      geo.zoom ? `z${geo.zoom}${geo.m_per_px ? ' · ' + ru(geo.m_per_px, 1) + ' м/пиксель' : ''}`
        : fromParams('Масштаб карты', '')
    ].filter(Boolean) : [];
    const reportMarks = mapReport ? (payload.marks || []) : (payload.photo_marks || []);
    const legendItems = [
      { color: '#FF3C3C', label: 'маркер «1» — створ', kind: 'dot' },
      ...reportMarks.map((m, i) => ({
        color: m.color || '#5F0001',
        label: `${mapReport ? i + 2 : 'M' + (i + 1)} — ${m.label || 'без подписи'}`,
        kind: 'dot'
      })),
      { color: '#28DC50', label: 'линия маски реки', kind: 'line' }
    ];
    const legendHtml = '<div class="fig-legend">' + legendItems.map((it) =>
      `<span><i class="${it.kind}" style="background:${it.color}"></i>${escapeHtml(it.label)}</span>`
    ).join('') + '</div>';
    const coordHtml = coordLines.length
      ? `<p class="note coord-note">${escapeHtml(coordLines.join(' · '))}</p>` : '';
    const stampImage = (src, lines) => {
      if (!src || !lines.length) return Promise.resolve(src);
      return loadImage(src).then((img) => {
        const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
        const c = canvasContext(w, h);
        c.ctx.drawImage(img, 0, 0);
        const fs = Math.max(12, Math.round(w / 72));
        c.ctx.font = `${fs}px "Times New Roman", serif`;
        const lh = fs + 5, pad = 8;
        const tw = Math.max(...lines.map((line) => c.ctx.measureText(line).width));
        const bw = Math.min(w - 12, tw + 2 * pad);
        const bh = lines.length * lh + pad;
        const bx = 6, by = Math.max(6, h - bh - 6);
        c.ctx.fillStyle = 'rgba(255,255,255,0.86)';
        c.ctx.fillRect(bx, by, bw, bh);
        c.ctx.strokeStyle = '#733933'; c.ctx.lineWidth = 1;
        c.ctx.strokeRect(bx, by, bw, bh);
        c.ctx.fillStyle = '#000';
        lines.forEach((line, i) => c.ctx.fillText(line, bx + pad, by + pad + i * lh + fs));
        // Стрелка севера — обязательный элемент координатной метки снимка.
        c.ctx.fillStyle = 'rgba(255,255,255,0.86)';
        c.ctx.fillRect(w - 44, 6, 38, 46);
        c.ctx.strokeRect(w - 44, 6, 38, 46);
        c.ctx.fillStyle = '#733933';
        c.ctx.beginPath(); c.ctx.moveTo(w - 25, 12); c.ctx.lineTo(w - 32, 32);
        c.ctx.lineTo(w - 25, 27); c.ctx.lineTo(w - 18, 32); c.ctx.closePath(); c.ctx.fill();
        c.ctx.font = `bold ${fs}px "Times New Roman", serif`;
        c.ctx.fillText('N', w - 31, 46);
        return c.canvas.toDataURL('image/png');
      }).catch(() => src);
    };
    return Promise.all([invertMaskDataUrl(payload.mask), stampImage(payload.image, coordLines)]).then(([maskImg, sceneImg]) => {
      const win = window.open('', '_blank');
      if (!win) throw new Error('Разрешите всплывающие окна для сохранения отчёта.');
      const img = (src, cap) => src ? `<div class="figure"><img src="${src}" alt=""><div class="fig-cap">${cap}</div></div>` : '';
      win.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8">
        <title>Отчёт Гидрофрактал</title><style>
        @page { size: A4; margin: 2cm 1.5cm 2cm 3cm; @bottom-center { content: counter(page); font-family: "Times New Roman"; font-size: 12pt; } }
        @page wide { size: A4 landscape; margin: 2cm; }
        body { font-family: "Times New Roman", Times, serif; font-size: 14pt; line-height: 1.5; color: #000; margin: 0; }
        h1 { font-size: 16pt; line-height: 1.35; text-align: center; margin: 0 0 6pt; font-weight: bold; }
        .sub { font-size: 10pt; color: #555; text-align: center; margin-bottom: 12pt; }
        h2 { font-size: 14pt; margin: 10pt 0 8pt; font-weight: bold; }
        p { text-align: justify; text-indent: 1.25cm; margin: 0 0 8pt; }
        p.noind { text-indent: 0; }
        .formula { text-align: center; text-indent: 0; margin: 2pt 0; }
        .num { float: right; }
        .tbl-cap { text-align: right; font-size: 14pt; margin: 4pt 0; }
        table { border-collapse: collapse; width: 100%; font-size: 12pt; margin-bottom: 8pt; }
        th, td { border: 1px solid #000; padding: 3pt 6pt; vertical-align: middle; }
        th { background: #eee; font-weight: bold; }
        td { text-align: center; }
        table.t1 td:first-child, table.t4 td:first-child { text-align: left; }
        .note { font-size: 10pt; color: #555; text-align: justify; text-indent: 0; }
        .figure { text-align: center; margin: 6pt 0; }
        .figure img { max-width: 100%; max-height: 15cm; }
        .fig-cap { text-align: center; margin-top: 4pt; font-size: 14pt; }
        .fig-legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 3pt 12pt;
          font-size: 10pt; text-indent: 0; margin: 4pt 0 2pt; }
        .fig-legend span { white-space: nowrap; }
        .fig-legend i { display: inline-block; width: 10pt; height: 10pt; margin-right: 4pt;
          border: 1px solid #000; vertical-align: -1pt; }
        .fig-legend i.dot { border-radius: 50%; }
        .fig-legend i.line { width: 16pt; height: 2pt; border: 0; vertical-align: 3pt; }
        .coord-note { text-align: center; font-weight: bold; }
        .page { page-break-after: always; }
        .page:last-child { page-break-after: auto; }
        .wide { page: wide; page-break-before: always; }
        .wide svg { width: 100%; height: auto; }
        @media screen { body { max-width: 21cm; margin: 1cm auto; } .page { border-bottom: 1px dashed #bbb; padding-bottom: 12pt; } }
        </style></head><body>
        <div class="page">
          <h1>Отчёт о значениях фрактальной размерности, среднего многолетнего расхода воды,
          коэффициента вариации, коэффициента асимметрии и кривой обеспеченности для выбранного створа реки</h1>
          <div class="sub">Метод Кантора (квадраты) &nbsp;·&nbsp; создан ${new Date().toLocaleString('ru-RU')}</div>
          <p>В отчёте приведены результаты измерения фрактальной размерности реки по спутниковому снимку
          «${escapeHtml(payload.source_name || fromParams('Источник', '—'))}». Измерение выполнено методом Кантора (квадраты);
          связь размерности блуждания h с фрактальной размерностью D задаётся формулой:</p>
          <p class="formula">N ~ (1/ε)<sup>h</sup> <span class="num">(1)</span></p>
          <p class="note">где ε — сторона ячейки сетки, px; N(ε) — число ячеек, через которые проходит
          линия реки; h — показатель степени (размерность блуждания), равный наклону прямой.</p>
          <p class="formula">h = 2(D − 1), &nbsp;&nbsp; D = 1 + h/2 <span class="num">(2)</span></p>
          <p class="note">где h — размерность блуждания (наклон прямой); D — фрактальная размерность
          линии реки; 1 — размерность точки.</p>
          <p>Наклон прямой в координатах «log<sub>10</sub> N(ε) — log<sub>10</sub> (1/ε)» оценивается
          методом наименьших квадратов по всем делениям сетки от 1 до максимального.</p>
          <h2>I. Исходные данные и параметры расчёта</h2>
          ${tbl('Таблица 1 — Параметры расчёта', ['Параметр', 'Значение'], table1, 't1')}
          <p class="note">Пояснение: файл — имя снимка; створ — точка, выше которой измеряется русло;
          допуск — порог HSV-расстояния; объект — что обмеряется сеткой; пиксели воды — площадь маски.</p>
        </div>
        <div class="page">
          <h2>II. Результаты измерения фрактальной размерности</h2>
          ${tbl('Таблица 2 — Результаты измерения', ['Показатель', 'Значение'], [
            ['Размерность блуждания', `h = ${ru(r.h, 4)} ± ${ru(r.dh, 4)}`],
            ['Фрактальная размерность', `D = 1 + h/2 = ${ru(r.D, 4)} ± ${ru(r.dD, 4)}`],
            ['R² (коэффициент детерминации)', `R² = ${ru(r2, 10)}`],
            ['Коэффициент корреляции (r = √R²)', `r = ${ru(corr, 10)}`]
          ])}
          <p class="note">Пояснение: R² = 1,0 соответствует идеальной прямой в логарифмических координатах;
          погрешность D получена из ошибки наклона h (метод наименьших квадратов).</p>
          ${img(payload.plot || r.plot, 'Рисунок 1 — Зависимость log<sub>10</sub> N(ε) от log<sub>10</sub> (1/ε)')}
          <p class="noind" style="text-align:center;text-indent:0">h = ${ru(r.h, 4)}, &nbsp; D = ${ru(r.D, 4)}, &nbsp; R² = ${ru(r2, 10)}</p>
        </div>
        <div class="page">
          <h2>III. Полная таблица измерений</h2>
          <p>Ниже представлены результаты обмера маски реки сеткой: для каждого деления сетки указаны
          сторона ячейки ε в пикселях, число ячеек N(ε), через которые проходит линия реки, и их
          десятичные логарифмы, по которым строится прямая рисунка 1.</p>
          ${tbl('Таблица 3 — Полная таблица измерений', ['n', 'ε, px', 'N(ε)', 'log<sub>10</sub> (1/ε)', 'log<sub>10</sub> N(ε)'], rows3)}
          <p class="note">Пояснение: n — номер деления сетки; ε — сторона ячейки, px; N(ε) — число ячеек,
          через которые проходит линия реки; log<sub>10</sub>(1/ε) и log<sub>10</sub> N(ε) — десятичные логарифмы.</p>
        </div>
        <div class="page">
          <h2>IV. Снимок с выделенной маской и маска реки</h2>
          ${img(sceneImg, mapReport
            ? 'Рисунок 2 — Карта с водосбором, речной сетью и главным руслом'
            : 'Рисунок 2 — Снимок с выделенной маской воды (зелёный) и точкой расхода (створ, маркер «1»)')}
          ${legendHtml}
          ${coordHtml}
        </div>
        <div class="page">
          ${img(maskImg, 'Рисунок 3 — Маска реки (чёрный — вода, белый — фон)')}
        </div>
        <div class="page">
          <h2>V. Статистические характеристики стока</h2>
          <p>В таблице ниже представлены статистические характеристики стока для данного створа,
          определённые по фрактальной размерности.</p>
          ${tbl('Таблица 4 — Статистические характеристики стока',
            ['Характеристика', 'Обозначение', 'Значение', 'Относительная погрешность', 'Абсолютная погрешность'], rows4, 't4')}
          <p class="note">Пояснение: Qср — средний многолетний расход воды (норма стока), м³/с;
          Cv — коэффициент вариации; Cs — коэффициент асимметрии. Характеристики определены по
          фрактальной размерности D (калибровочная связь); относительная погрешность указана в
          долях процента, абсолютная — в единицах измерения характеристики.</p>
          <p class="noind">а) абсолютные погрешности</p>
          <p class="noind">• для среднего значения</p>
          <p class="formula">ε<sub>Q</sub> = σ<sub>Q</sub> / n<sup>1/2</sup> <span class="num">(3)</span></p>
          <p class="note">где ε<sub>Q</sub> — абсолютная погрешность среднего расхода; σ<sub>Q</sub> —
          среднеквадратическое отклонение расхода воды, м³/с; n — число членов ряда наблюдений.</p>
          <p class="noind">• для коэффициента вариации</p>
          <p class="formula">ε<sub>Cv</sub> = Cv / n · ((n + 4Cv²) / (2(1 + Cv²)))<sup>1/2</sup> <span class="num">(4)</span></p>
          <p class="note">где ε<sub>Cv</sub> — абсолютная погрешность коэффициента вариации; Cv —
          коэффициент вариации; n — число членов ряда наблюдений.</p>
          <p class="noind">• для коэффициента асимметрии</p>
          <p class="formula">ε<sub>Cs</sub> = (6/n)<sup>1/2</sup>(1 + 6Cv² + 5Cv<sup>4</sup>)<sup>1/2</sup> <span class="num">(5)</span></p>
          <p class="note">где ε<sub>Cs</sub> — абсолютная погрешность коэффициента асимметрии; Cv —
          коэффициент вариации; n — число членов ряда наблюдений.</p>
          <p class="noind">б) относительные погрешности</p>
          <p class="noind">• для среднего значения</p>
          <p class="formula">ε<sub>Q, %</sub> = Cv / n<sup>1/2</sup> · 100 % <span class="num">(6)</span></p>
          <p class="note">где ε<sub>Q, %</sub> — относительная погрешность среднего расхода, %; Cv —
          коэффициент вариации; n — число членов ряда наблюдений.</p>
          <p class="noind">• для коэффициента вариации</p>
          <p class="formula">ε<sub>Cv, %</sub> = 1/n · ((n + 4Cv²) / (2(1 + Cv²)))<sup>1/2</sup> · 100 % <span class="num">(7)</span></p>
          <p class="note">где ε<sub>Cv, %</sub> — относительная погрешность коэффициента вариации, %;
          Cv — коэффициент вариации; n — число членов ряда наблюдений.</p>
          <p class="noind">• для коэффициента асимметрии</p>
          <p class="formula">ε<sub>Cs, %</sub> = (1/Cs)(6/n)<sup>1/2</sup>(1 + 6Cv² + 5Cv<sup>4</sup>)<sup>1/2</sup> · 100 % <span class="num">(8)</span></p>
          <p class="note">где ε<sub>Cs, %</sub> — относительная погрешность коэффициента асимметрии, %;
          Cs — коэффициент асимметрии; Cv — коэффициент вариации; n — число членов ряда.</p>
        </div>
        <div class="page wide">
          <h2>VI. Теоретическая кривая обеспеченности (Пирсона III типа)</h2>
          <div class="figure">${probabilityGrid()}
          <div class="fig-cap">Рисунок 4 — Теоретическая кривая обеспеченности (Пирсона III типа):
          P, % — модульный коэффициент k<sub>p</sub></div></div>
        </div>
        <div class="page">
          <h2>VII. Расчёт ординат теоретической кривой обеспеченности</h2>
          <p>В таблице 5 приведены ординаты теоретической кривой: обеспеченность P, модульные
          коэффициенты k<sub>p</sub> и соответствующие расходы воды Q<sub>P</sub>.</p>
          ${tbl('Таблица 5 — Ординаты теоретической кривой',
            ['Обеспеченность P, %', 'Модульный коэффициент k<sub>p</sub>', 'Расход воды Q<sub>P</sub>, м³/с'], rows5)}
          <p class="note">Пояснение: P — обеспеченность (вероятность превышения), %; k<sub>p</sub> —
          модульный коэффициент; Q<sub>P</sub> = k<sub>p</sub>·Q<sub>ср</sub> — расход воды заданной
          обеспеченности, м³/с. Строки соответствуют рисунку 4.</p>
          <p>Методика СП 33-101-2003 (приложение Ж): для заданных C<sub>v</sub> и
          C<sub>s</sub>/C<sub>v</sub> выбираются модульные коэффициенты
          k<sub>p</sub>, затем Q<sub>P</sub> = k<sub>p</sub>·Q<sub>ср</sub>.
          Ниже приведены расчётные ординаты для стандартных отношений
          C<sub>s</sub>/C<sub>v</sub>; промежуточные значения интерполируются.</p>
          ${tbl('Таблица 6 — k<sub>p</sub> по СП 33-101-2003 (приложение Ж)',
            ['P, %', ...ratios.map((r) => 'Cs/Cv = ' + String(r).replace('.', ','))], rowsSp)}
        </div>
        <div class="page">
          <h2>Порядок вычисления</h2>
          <p>Теоретическая кривая строится по трём характеристикам стока — Q<sub>ср</sub>, C<sub>v</sub> и C<sub>s</sub>.
          Расход воды обеспеченности P вычисляется по формуле</p>
          <p class="formula">Q<sub>P</sub> = (Φ<sub>P</sub>·C<sub>v</sub> + 1)·Q<sub>ср</sub> = k<sub>p</sub>·Q<sub>ср</sub> <span class="num">(9)</span></p>
          <p class="note">где Q<sub>P</sub> — расход воды обеспеченности P, м³/с; Φ<sub>P</sub> — коэффициент
          Фостера–Рыбкина; C<sub>v</sub> — коэффициент вариации; Q<sub>ср</sub> — средний многолетний
          расход; k<sub>p</sub> — модульный коэффициент.</p>
          <p class="formula">Φ<sub>P</sub> = z<sub>P</sub> + (C<sub>s</sub>/6)·(z<sub>P</sub>² − 1) <span class="num">(10)</span></p>
          <p class="note">где Φ<sub>P</sub> — коэффициент Фостера–Рыбкина; z<sub>P</sub> — квантиль
          стандартного нормального распределения для обеспеченности P; C<sub>s</sub> — коэффициент
          асимметрии.</p>
          <p class="formula">k<sub>p</sub> = Φ<sub>P</sub>·C<sub>v</sub> + 1 <span class="num">(11)</span></p>
          <p class="note">где k<sub>p</sub> — модульный коэффициент, показывающий, во сколько раз расход
          обеспеченности P отличается от Q<sub>ср</sub>; Φ<sub>P</sub> — коэффициент Фостера–Рыбкина;
          C<sub>v</sub> — коэффициент вариации.</p>
          <p class="note">В формулах (10) и (11) z<sub>P</sub> — квантиль стандартного нормального
          распределения для обеспеченности P; значения Φ<sub>P</sub> определяются по стандартным
          таблицам СП 33-101-2003 (приложение Ж).</p>
        </div>
        </body></html>`);
      win.document.close();
      setTimeout(() => { try { win.focus(); win.print(); } catch (e) { /* ignore */ } }, 600);
      return { ok: true, printed: true };
    });
  }

  // ------------------------------------------------------------------ API-шлюз
  HF.dispatch = function (path, payload) {
    const p = payload || {};
    switch (path) {
      case '/api/health':
        return Promise.resolve({ ok: true, service: 'HydroFractal Web (static)' });
      case '/api/upload':
        return drawNormalizedImage(p.image, 1600).then((img) => ({
          ok: true, image: img.canvas.toDataURL('image/jpeg', 0.88),
          width: img.width, height: img.height
        }));
      case '/api/segment':
        return drawNormalizedImage(p.image, 1600).then((rgb) => {
          const seed = p.seed || {};
          if (seed.x === undefined || seed.y === undefined) throw new Error('Сначала отметьте точку на реке.');
          const mask = segmentWater(rgb, { x: Number(seed.x), y: Number(seed.y) }, p);
          const W = rgb.width, H = rgb.height;
          let count = 0;
          for (let i = 0; i < mask.length; i++) count += mask[i];
          const maskDataUrl = maskPngDataUrl(mask, W, H);
          const { canvas, ctx } = canvasContext(W, H);
          ctx.drawImage(rgb.canvas, 0, 0);
          const tint = maskToImageData(mask, W, H, [40, 220, 80, 122], [0, 0, 0, 0]);
          const layer = canvasContext(W, H);
          layer.ctx.putImageData(tint, 0, 0);
          ctx.drawImage(layer.canvas, 0, 0);
          [[p.seed, '#FF3C3C'], ...(p.extras || []).map((x) => [x, '#F5CD46'])].forEach(([pt, color]) => {
            if (!pt) return;
            ctx.strokeStyle = color; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(Number(pt.x), Number(pt.y), 9, 0, 2 * Math.PI); ctx.stroke();
          });
          return {
            ok: true, image: rgb.canvas.toDataURL('image/jpeg', 0.88),
            overlay: canvas.toDataURL('image/jpeg', 0.88), mask: maskDataUrl,
            width: W, height: H, water_pixels: count,
            water_share: Math.round(count / mask.length * 100000) / 1000
          };
        });
      case '/api/analyze':
        return maskFromDataUrl(p.mask).then(({ mask, W, H }) => {
          let object = p.object || 'skeleton';
          let working = mask;
          if (object === 'skeleton') working = skeletonMask(mask, W, H);
          else if (object === 'boundary') working = boundaryMask(mask, W, H);
          const r = cantorDimension(working, W, H, p.max_divs || 60);
          r.water_pixels = mask.reduce((a, b) => a + b, 0);
          return { ok: true, result: cleanResult(r, object) };
        });
      case '/api/map/view':
        return mapView(p);
      case '/api/map/analyze':
        return mapAnalyze(p);
      default:
        return Promise.reject(new Error('Неизвестный запрос: ' + path));
    }
  };
  HF.download = function (path, payload, filename) {
    const p = payload || {};
    if (path === '/api/report') return report(p);
    if (path === '/api/mask/png') {
      return maskFromDataUrl(p.mask).then(({ mask, W, H }) => {
        const seed = p.seed ? `${Math.round(p.seed.x)}, ${Math.round(p.seed.y)}` : 'not set';
        const water = mask.reduce((a, b) => a + b, 0);
        const { canvas: out, ctx: outCtx } = canvasContext(W, H);
        outCtx.putImageData(maskToImageData(mask, W, H, [0, 0, 0, 255], [255, 255, 255, 255]), 0, 0);
        const base = out.toDataURL('image/png');
        const meta = {
          Title: 'River mask', Dimensions: `${W} x ${H} px`, Resolution: '300 dpi',
          Scale: p.scale_text ? `${p.scale_text} m/px` : 'not set',
          Source: String(p.source_name || 'unknown'), 'Water pixels': String(water),
          'Water share, pct': (100 * water / mask.length).toFixed(2),
          'Seed point': seed, Created: new Date().toISOString(),
          Software: 'HydroFractal Web (static)', Description: 'Black = water, white = background'
        };
        const url = pngWithMetadata(base, meta);
        const a = document.createElement('a');
        a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
        return { ok: true };
      });
    }
    return Promise.reject(new Error('Скачивание недоступно в статическом режиме.'));
  };

  window.HFClient = HF;
})();
