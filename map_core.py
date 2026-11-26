# -*- coding: utf-8 -*-
"""
ГИДРОФРАКТАЛ — ядро картографического режима.

Что делает
----------
1. Качает и кэширует тайлы карты (Sentinel-2 L2A через Planetary Computer, Esri).
2. Качает тайлы ЦМР (Copernicus DEM GLO-30 через Planetary Computer / TiTiler)
   и декодирует их в НАСТОЯЩИЕ высоты в метрах.
3. Собирает мозаику под текущее окно карты.
4. Считает гидрологию по ЦМР: заполнение впадин, направления стока D8,
   накопление стока.
5. По клику (створ) строит водосбор и выделяет главное русло.

Зависимости: только numpy и Pillow — никаких GDAL, rasterio и pysheds.
Значит, и на Windows всё ставится одной командой.
"""

from __future__ import annotations

import io
import json
import math
import urllib.parse
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

TILE = 256
MAX_LAT = 85.05112878

# ---------------------------------------------------------------------------
# Источники тайлов
# ---------------------------------------------------------------------------
SOURCES = {
    "esri": {
        "name": "Esri (спутник)",
        "url": ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"),
        "credit": "Снимок: Esri, Maxar, Earthstar Geographics",
        "max_zoom": 18,
    },
    "sentinel": {
        "name": "Sentinel-2 L2A (Planetary Computer)",
        "url": ("https://planetarycomputer.microsoft.com/api/data/v1/item/tiles/"
                "WebMercatorQuad/{z}/{x}/{y}@1x?collection=sentinel-2-l2a"
                "&item={item}&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0"
                "&format=png"),
        "credit": "Sentinel-2 L2A: Copernicus / Planetary Computer",
        "max_zoom": 14,
    },
}

# Copernicus DEM GLO-30 через Planetary Computer (TiTiler / item tiles).
DEM_COLLECTION = "cop-dem-glo-30"
DEM_RESCALE = (-1000.0, 4000.0)
PC_DEM_TILES = ("https://planetarycomputer.microsoft.com/api/data/v1/collections/"
                "cop-dem-glo-30/items/{item}/tiles/WebMercatorQuad/"
                "{z}/{x}/{y}@1x?assets=data&rescale=-1000,4000&format=png")
PC_STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
# NASADEM (SRTM, архив USGS EarthExplorer) — основной источник ЦМР.
# Copernicus DEM GLO-30 остаётся резервом.
NASADEM_TILES = ("https://planetarycomputer.microsoft.com/api/data/v1/collections/"
                 "nasadem/items/{item}/tiles/WebMercatorQuad/"
                 "{z}/{x}/{y}@1x?assets=elevation&rescale=-100,4000&format=png")
# Последний резерв, если оба PC-сервиса DEM недоступны: terrarium-тайлы
# с настоящими высотаМИ (не синтетика). PC остаётся основным источником.
TERRARIUM_URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
TERRAIN_CREDIT = ("ЦМР: USGS EarthExplorer (NASADEM/SRTM), резерв — "
                  "Copernicus DEM GLO-30, Terrarium")

UA = {"User-Agent": "Gidrofraktal/1.0 (river fractal analysis)"}

# ---------------------------------------------------------------------------
# Кэш тайлов на диске
# ---------------------------------------------------------------------------
_CACHE_DIR = None
_cache_lock = threading.Lock()


def set_cache_dir(path):
    """Папка для кэша тайлов."""
    global _CACHE_DIR
    _CACHE_DIR = path
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        _CACHE_DIR = None


def cache_dir():
    if _CACHE_DIR:
        return _CACHE_DIR
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tile_cache")
    set_cache_dir(base)
    return _CACHE_DIR


def _cache_path(source, z, x, y):
    d = cache_dir()
    if not d:
        return None
    sub = os.path.join(d, source, str(z), str(x))
    return os.path.join(sub, f"{y}.png")


# ---------------------------------------------------------------------------
# Загрузка одного тайла
# ---------------------------------------------------------------------------
def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_tile(source, z, x, y, use_cache=True, force=False, item=None):
    """Возвращает bytes PNG или None при ошибке."""
    key = "esri" if source == "esri" else "sentinel"
    cpath = _cache_path(key, z, x, y) if use_cache else None

    if cpath and os.path.exists(cpath) and not force:
        try:
            with open(cpath, "rb") as f:
                data = f.read()
            if len(data) > 100:
                return data
        except Exception:
            pass

    s = SOURCES[key]
    try:
        if key == "sentinel":
            if not item:
                return None
            url = s["url"].format(z=z, x=x, y=y, item=urllib.parse.quote(item, safe=""))
        else:
            url = s["url"].format(z=z, x=x, y=y)
        data = _http_get(url)
    except Exception:
        return None

    if cpath:
        try:
            with _cache_lock:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath, "wb") as f:
                    f.write(data)
        except Exception:
            pass
    return data


def _dem_item_name(lon, lat):
    """Имя 1°×1° тайла Copernicus DEM GLO-30 в Planetary Computer."""
    ilon = int(math.floor(lon))
    ilat = int(math.floor(lat))
    return ("Copernicus_DSM_COG_10_{latdir}{lat}_00_{londir}{lon:03d}_00_DEM"
            .format(lat=abs(ilat), latdir="N" if ilat >= 0 else "S",
                    lon=abs(ilon), londir="E" if ilon >= 0 else "W"))


def _pc_dem_url(z, x, y):
    lon, lat = tile_to_lonlat(x + 0.5, y + 0.5, z)
    item = _dem_item_name(lon, lat)
    return PC_DEM_TILES.format(item=item, z=z, x=x, y=y)


def _nasa_dem_item_name(lon, lat):
    """Имя 1° тайла NASADEM (широта/долгота округляются до центра тайла)."""
    ilon, ilat = int(round(lon)), int(round(lat))
    return ("NASADEM_HGT_{latdir}{lat:02d}{londir}{lon:03d}"
            .format(lat=abs(ilat), latdir="n" if ilat >= 0 else "s",
                    lon=abs(ilon), londir="e" if ilon >= 0 else "w"))


def _nasa_dem_url(z, x, y):
    lon, lat = tile_to_lonlat(x + 0.5, y + 0.5, z)
    return NASADEM_TILES.format(item=_nasa_dem_item_name(lon, lat),
                                z=z, x=x, y=y)


def _decode_dem_png(data, lo, hi=4000.0):
    """TiTiler: одноканальная ЦМР кодируется в R по линейной шкале."""
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    a = np.asarray(im).astype(np.float32)
    heights = a[..., 0] / 255.0 * (hi - lo) + lo
    heights[a[..., 3] < 128] = np.nan  # вне покрытия тайла
    return heights


def fetch_terrain_tile(z, x, y, use_cache=True):
    """Тайл ЦМР USGS EarthExplorer / NASADEM → высоты в метрах (256×256) или None."""
    cpath = _cache_path("dem-pc", z, x, y) if use_cache else None
    meta_path = cpath + ".json" if cpath else None
    data, lo, terrarium = None, -100.0, False
    if cpath and os.path.exists(cpath):
        try:
            with open(cpath, "rb") as f:
                data = f.read()
            if meta_path and os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                lo = float(meta.get("lo", lo))
                terrarium = bool(meta.get("terrarium", False))
        except Exception:
            data = None
    if data is None:
        lo, terrarium = -100.0, False
        for url, low, terr in ((_nasa_dem_url(z, x, y), -100.0, False),
                               (_pc_dem_url(z, x, y), DEM_RESCALE[0], False),
                               (TERRARIUM_URL.format(z=z, x=x, y=y), 0.0, True)):
            try:
                data = _http_get(url)
                lo, terrarium = low, terr
                break
            except Exception:
                continue
        if data is None:
            return None
        if cpath:
            try:
                with _cache_lock:
                    os.makedirs(os.path.dirname(cpath), exist_ok=True)
                    with open(cpath, "wb") as f:
                        f.write(data)
                    if meta_path:
                        with open(meta_path, "w", encoding="utf-8") as f:
                            json.dump({"lo": lo, "terrarium": terrarium}, f)
            except Exception:
                pass
    try:
        if terrarium:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            a = np.asarray(im).astype(np.float32)
            return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0
        return _decode_dem_png(data, lo)
    except Exception:
        return None


def find_sentinel_item(lon, lat, radius=0.16, max_cloud=25):
    """Ищем свежую сцену Sentinel-2 L2A через STAC Planetary Computer."""
    params = urllib.parse.urlencode({
        "collections": "sentinel-2-l2a",
        "bbox": f"{lon-radius},{lat-radius},{lon+radius},{lat+radius}",
        "datetime": "2024-01-01/2026-12-31",
        "limit": "1",
        "query": json.dumps({"eo:cloud_cover": {"lt": max_cloud}}),
    })
    data = json.loads(_http_get(PC_STAC_SEARCH + "?" + params).decode("utf-8"))
    feats = data.get("features") or []
    return feats[0]["id"] if feats else None


def sentinel_item_url(item, z, x, y):
    """XYZ-тайл выбранной сцены Sentinel-2 L2A через TiTiler."""
    return ("https://planetarycomputer.microsoft.com/api/data/v1/item/tiles/"
            "WebMercatorQuad/{z}/{x}/{y}@1x?collection=sentinel-2-l2a&item={item}"
            "&assets=visual&asset_bidx=visual%7C1%2C2%2C3&nodata=0&format=png"
            .format(item=urllib.parse.quote(item, safe=""), z=z, x=x, y=y))


# ---------------------------------------------------------------------------
# Геометрия «скользящей карты» (Web Mercator, схема z/x/y)
# ---------------------------------------------------------------------------
def lonlat_to_tile(lon, lat, z):
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lonlat(x, y, z):
    n = 2.0 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def resolution_m(lat, z):
    """Метров на пиксель на данной широте."""
    return 156543.03392 * math.cos(math.radians(lat)) / (2.0 ** z)


def tile_range(x0, y0, x1, y1):
    """Список (tx, ty) тайлов, покрывающих прямоугольник в координатах тайлов."""
    out = []
    for ty in range(int(math.floor(y0)), int(math.floor(y1)) + 1):
        for tx in range(int(math.floor(x0)), int(math.floor(x1)) + 1):
            out.append((tx, ty))
    return out


# ---------------------------------------------------------------------------
# Сборка вида карты под окно программы
# ---------------------------------------------------------------------------
def render_view(center_lon, center_lat, zoom, width, height,
                source="esri", use_cache=True, progress=None):
    """Мозаика тайлов под окно. Возвращает (PIL.Image, geo)."""
    width = max(64, int(width))
    height = max(64, int(height))
    cx, cy = lonlat_to_tile(center_lon, center_lat, zoom)

    x0 = cx - width / (2.0 * TILE)
    y0 = cy - height / (2.0 * TILE)
    x1 = x0 + width / (2.0 * TILE) * 2.0 - width / (2.0 * TILE)
    x1 = x0 + width / float(TILE)
    y1 = y0 + height / float(TILE)

    coords = tile_range(x0, y0, x1, y1)
    max_n = 2 ** zoom
    coords = [(tx, ty) for (tx, ty) in coords if 0 <= tx < max_n and 0 <= ty < max_n]

    sentinel_item = None
    fetch_source = source
    if source == "sentinel":
        try:
            sentinel_item = find_sentinel_item(center_lon, center_lat)
        except Exception:
            sentinel_item = None
        if not sentinel_item:
            fetch_source = "esri"  # резерв, если STAC недоступен
            if progress:
                progress("Sentinel-2 недоступен — используется резервный спутниковый снимок.")

    if progress:
        progress(f"Загрузка карты: тайлов {len(coords)}…")

    results = {}
    def job(c):
        tx, ty = c
        results[c] = fetch_tile(fetch_source, zoom, tx, ty,
                                use_cache=use_cache, item=sentinel_item)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(job, coords))

    img = Image.new("RGB", (width, height), (237, 228, 214))
    for (tx, ty) in coords:
        data = results.get((tx, ty))
        if not data:
            continue
        try:
            t = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception:
            continue
        px = int(round((tx - x0) * TILE))
        py = int(round((ty - y0) * TILE))
        img.paste(t, (px, py))

    geo = {"x0": x0, "y0": y0, "z": zoom,
           "w": width, "h": height,
           "center_lon": center_lon, "center_lat": center_lat}
    return img, geo


def pixel_to_lonlat(geo, px, py):
    """Пиксель окна → (широта, долгота)."""
    tx = geo["x0"] + px / float(TILE)
    ty = geo["y0"] + py / float(TILE)
    lon, lat = tile_to_lonlat(tx, ty, geo["z"])
    return lat, lon


# ---------------------------------------------------------------------------
# Рельеф под окно
# ---------------------------------------------------------------------------
def fetch_dem(center_lon, center_lat, zoom, span_x=2, span_y=2,
              use_cache=True, progress=None):
    """Мозаика рельефа. Возвращает (z_array, geo) или (None, None)."""
    zoom = int(max(1, min(15, zoom)))
    cx, cy = lonlat_to_tile(center_lon, center_lat, zoom)
    x0 = int(math.floor(cx)) - span_x // 2
    y0 = int(math.floor(cy)) - span_y // 2

    max_n = 2 ** zoom
    coords = []
    for j in range(span_y):
        for i in range(span_x):
            tx, ty = x0 + i, y0 + j
            if 0 <= tx < max_n and 0 <= ty < max_n:
                coords.append((tx, ty))

    if progress:
        progress(f"Загрузка рельефа: тайлов {len(coords)}…")

    arr = np.full((span_y * TILE, span_x * TILE), np.nan, np.float32)
    got = 0

    def job(c):
        tx, ty = c
        return c, fetch_terrain_tile(zoom, tx, ty, use_cache=use_cache)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for (tx, ty), z in ex.map(job, coords):
            if z is None:
                continue
            i = tx - x0
            j = ty - y0
            arr[j*TILE:(j+1)*TILE, i*TILE:(i+1)*TILE] = z
            got += 1

    if got == 0:
        return None, None

    # дыры (если часть тайлов не пришла) — заполняем медианой
    if not np.isfinite(arr).all():
        med = float(np.nanmedian(arr))
        arr = np.where(np.isfinite(arr), arr, med)

    geo = {"x0": x0, "y0": y0, "z": zoom,
           "w": span_x * TILE, "h": span_y * TILE,
           "center_lon": center_lon, "center_lat": center_lat,
           "tiles_ok": got, "tiles_all": len(coords)}
    return arr, geo


NATIVE_DEM_ZOOM = 12      # ~30 м/пиксель — родное разрешение Copernicus DEM GLO-30


def best_dem_zoom(view_zoom, lat):
    """Зум рельефа: не выше родного разрешения данных (~30 м).

    Тайлы рельефа — Copernicus DEM GLO-30, разложенный по уровням. На z13+ он
    просто интерполируется: деталей больше не становится, зато D8
    начинает «видеть» шум интерполяции и поток рассыпается.
    Поэтому выше z12 не поднимаемся.
    """
    return int(max(1, min(NATIVE_DEM_ZOOM, view_zoom)))


def fetch_dem_for_view(geo, dem_zoom, margin=1, use_cache=True, progress=None):
    """Рельеф, покрывающий всё видимое окно карты (плюс запас)."""
    dem_zoom = int(dem_zoom)
    k = 2.0 ** (dem_zoom - geo["z"])
    x0 = geo["x0"] * k - margin
    y0 = geo["y0"] * k - margin
    x1 = (geo["x0"] + geo["w"] / float(TILE)) * k + margin
    y1 = (geo["y0"] + geo["h"] / float(TILE)) * k + margin

    tx0 = int(math.floor(x0))
    ty0 = int(math.floor(y0))
    tx1 = int(math.floor(x1))
    ty1 = int(math.floor(y1))
    nx = max(1, tx1 - tx0 + 1)
    ny = max(1, ty1 - ty0 + 1)

    max_n = 2 ** dem_zoom
    arr = np.full((ny * TILE, nx * TILE), np.nan, np.float32)
    coords = []
    for j in range(ny):
        for i in range(nx):
            tx, ty = tx0 + i, ty0 + j
            if 0 <= tx < max_n and 0 <= ty < max_n:
                coords.append((i, j, tx, ty))

    if progress:
        progress(f"Загрузка рельефа: тайлов {len(coords)}…")

    got = 0
    def job(c):
        i, j, tx, ty = c
        return (i, j), fetch_terrain_tile(dem_zoom, tx, ty, use_cache=use_cache)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for (i, j), z in ex.map(job, coords):
            if z is None:
                continue
            arr[j*TILE:(j+1)*TILE, i*TILE:(i+1)*TILE] = z
            got += 1

    if got == 0:
        return None, None
    if not np.isfinite(arr).all():
        med = float(np.nanmedian(arr))
        arr = np.where(np.isfinite(arr), arr, med)

    dgeo = {"x0": tx0, "y0": ty0, "z": dem_zoom,
            "w": nx * TILE, "h": ny * TILE,
            "view_x0": geo["x0"], "view_y0": geo["y0"], "view_z": geo["z"],
            "tiles_ok": got, "tiles_all": len(coords)}
    return arr, dgeo



def resample_mask_to_view(mask, dgeo, geo, width, height):
    """Маска на сетке DEM → булева маска размером с видимое окно карты."""
    import numpy as np
    src = np.asarray(mask, dtype=bool)
    H, W = int(height), int(width)
    out = np.zeros((H, W), dtype=bool)
    if not src.size or not src.shape[0] or not src.shape[1]:
        return out
    k = 2.0 ** (float(dgeo["z"]) - float(geo["z"]))
    fy = (float(geo["y0"]) * k - float(dgeo["y0"])) * TILE
    fx = (float(geo["x0"]) * k - float(dgeo["x0"])) * TILE
    ys = np.floor(fy + (np.arange(H) + 0.5) * k).astype(int)
    xs = np.floor(fx + (np.arange(W) + 0.5) * k).astype(int)
    vy = (ys >= 0) & (ys < src.shape[0])
    vx = (xs >= 0) & (xs < src.shape[1])
    if not vy.any() or not vx.any():
        return out
    yy = np.clip(ys, 0, src.shape[0] - 1)
    xx = np.clip(xs, 0, src.shape[1] - 1)
    out = src[np.ix_(yy, xx)] & vy[:, None] & vx[None, :]
    return out

def lonlat_to_dem_pixel(dgeo, lon, lat):
    """(широта, долгота) → (строка, столбец) в массиве рельефа."""
    tx, ty = lonlat_to_tile(lon, lat, dgeo["z"])
    col = (tx - dgeo["x0"]) * TILE
    row = (ty - dgeo["y0"]) * TILE
    return row, col


# ---------------------------------------------------------------------------
# ГИДРОЛОГИЯ: заполнение впадин, D8, накопление
# ---------------------------------------------------------------------------
_D8 = [(-1, 0, 1), (1, 0, 4), (0, -1, 16), (0, 1, 1),
       (-1, -1, 128), (-1, 1, 64), (1, -1, 8), (1, 1, 2)]
# направление → смещение (ESRI: 1=В, 2=ЮВ, 4=Ю, 8=ЮЗ, 16=З, 32=СЗ, 64=С, 128=СВ)
_D8_DY = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
_D8_DX = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}


def fill_depressions(dem, eps=1e-3):
    """Заполнение впадин методом Priority-Flood (Barnes et al.)."""
    import heapq

    H, W = dem.shape
    filled = np.array(dem, dtype=np.float64, copy=True)
    visited = np.zeros((H, W), bool)
    heap = []

    for x in range(W):
        for y in (0, H - 1):
            if 0 <= y < H:
                heapq.heappush(heap, (filled[y, x], y, x))
                visited[y, x] = True
    for y in range(H):
        for x in (0, W - 1):
            if not visited[y, x]:
                heapq.heappush(heap, (filled[y, x], y, x))
                visited[y, x] = True

    while heap:
        z, y, x = heapq.heappop(heap)
        for dy, dx, _ in _D8:
            ny, nx = y + dy, x + dx
            if ny < 0 or ny >= H or nx < 0 or nx >= W or visited[ny, nx]:
                continue
            visited[ny, nx] = True
            if filled[ny, nx] <= z:
                filled[ny, nx] = z + eps
            heapq.heappush(heap, (filled[ny, nx], ny, nx))
    return filled


def flow_directions(filled, cell=1.0):
    """Направления стока D8 (ESRI-коды). 0 — сток за пределы области."""
    H, W = filled.shape
    best = np.zeros((H, W), np.float64)
    fdir = np.zeros((H, W), np.uint8)

    for dy, dx, code in _D8:
        dist = math.hypot(dy, dx) * cell
        # сдвинутые массивы
        ys0, ys1 = max(0, -dy), min(H, H - dy)
        xs0, xs1 = max(0, -dx), min(W, W - dx)
        if ys0 >= ys1 or xs0 >= xs1:
            continue
        here = filled[ys0:ys1, xs0:xs1]
        there = filled[ys0+dy:ys1+dy, xs0+dx:xs1+dx]
        slope = (here - there) / dist
        better = slope > best[ys0:ys1, xs0:xs1]
        best[ys0:ys1, xs0:xs1] = np.where(better, slope, best[ys0:ys1, xs0:xs1])
        fdir[ys0:ys1, xs0:xs1] = np.where(better, code, fdir[ys0:ys1, xs0:xs1])
    return fdir


def flow_accumulation(filled, fdir):
    """Накопление стока (число клеток, включая собственную)."""
    H, W = filled.shape
    acc = np.ones((H, W), np.float64)

    # порядок обработки: от самых высоких клеток к самым низким
    order = np.argsort(-filled.ravel(), kind="stable")
    flat_acc = acc.ravel()
    flat_fdir = fdir.ravel()

    for idx in order:
        d = int(flat_fdir[idx])
        if d == 0:
            continue
        y, x = divmod(int(idx), W)
        ny, nx = y + _D8_DY[d], x + _D8_DX[d]
        if 0 <= ny < H and 0 <= nx < W:
            flat_acc[ny * W + nx] += flat_acc[idx]

    return flat_acc.reshape(H, W)


# ---------------------------------------------------------------------------
# Водосбор и главное русло
# ---------------------------------------------------------------------------
def catchment_upstream(fdir, oy, ox):
    """Все клетки, дренирующиеся в створ (обход вверх по склону)."""
    fdir = np.asarray(fdir)
    H, W = fdir.shape
    if not (0 <= oy < H and 0 <= ox < W):
        raise ValueError("Створ вне пределов рельефа.")

    seen = np.zeros((H, W), bool)
    seen[oy, ox] = True
    stack = [(int(oy), int(ox))]
    while stack:
        cy, cx = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cy + dy, cx + dx
                if ny < 0 or ny >= H or nx < 0 or nx >= W or seen[ny, nx]:
                    continue
                d = int(fdir[ny, nx])
                if _D8_DY.get(d, 99) == -dy and _D8_DX.get(d, 99) == -dx:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return seen


def main_channel(fdir, acc, catchment, oy, ox, min_frac=0.02):
    """Линия главного русла: вверх от створа, каждый раз по притоку
    с наибольшим накоплением."""
    fdir = np.asarray(fdir)
    acc = np.asarray(acc, np.float64)
    H, W = fdir.shape
    if not catchment[oy, ox]:
        return np.zeros((H, W), bool)

    line = np.zeros((H, W), bool)
    line[oy, ox] = True
    cy, cx = int(oy), int(ox)
    min_acc = max(2.0, min_frac * float(acc[oy, ox]))

    for _ in range(H * W):
        best, best_acc = None, -1.0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cy + dy, cx + dx
                if ny < 0 or ny >= H or nx < 0 or nx >= W:
                    continue
                if not catchment[ny, nx] or line[ny, nx]:
                    continue
                d = int(fdir[ny, nx])
                if _D8_DY.get(d, 99) != -dy or _D8_DX.get(d, 99) != -dx:
                    continue
                a = float(acc[ny, nx])
                if a > best_acc:
                    best_acc, best = a, (ny, nx)
        if best is None or best_acc < min_acc:
            break
        cy, cx = best
        line[cy, cx] = True

    if line.sum() < 5:
        cut = 0.60 * float(acc[oy, ox])
        line = catchment & (acc >= cut)
    return line


def strahler_order(fdir, network, acc):
    """Порядок Стралера русловой сети (обход по возрастанию накопления)."""
    fdir = np.asarray(fdir)
    net = np.asarray(network, bool)
    H, W = net.shape
    ys, xs = np.nonzero(net)
    if ys.size == 0:
        return 1
    order = np.argsort(acc[ys, xs])
    ys, xs = ys[order], xs[order]

    best = np.zeros((H, W), np.int16)
    nb_eq = np.zeros((H, W), np.int16)
    for y, x in zip(ys, xs):
        top, cnt = int(best[y, x]), int(nb_eq[y, x])
        if top == 0:
            st = 1
        elif cnt >= 2:
            st = top + 1
        else:
            st = top
        d = int(fdir[y, x])
        dy, dx = _D8_DY.get(d, 0), _D8_DX.get(d, 0)
        if dy == 0 and dx == 0:
            continue
        ny, nx = y + dy, x + dx
        if ny < 0 or ny >= H or nx < 0 or nx >= W or not net[ny, nx]:
            continue
        if st > best[ny, nx]:
            best[ny, nx] = st
            nb_eq[ny, nx] = 1
        elif st == best[ny, nx]:
            nb_eq[ny, nx] += 1
    return int(best[net].max()) if net.any() else 1


# ---------------------------------------------------------------------------
# Полный расчёт по карте
# ---------------------------------------------------------------------------
def analyse_map(view_geo, outlet_lon, outlet_lat,
                threshold_frac=0.01, use_cache=True, progress=None):
    """Полный конвейер по видимому окну карты.

    view_geo — словарь от render_view (x0, y0, z, w, h);
    рельеф подбирается так, чтобы покрыть ВСЁ окно, но не мельче
    родного разрешения данных (~30 м).
    """
    def tick(msg):
        if progress:
            progress(msg)

    dem_zoom = best_dem_zoom(view_geo["z"], view_geo["center_lat"])

    tick("Загрузка рельефа…")
    dem, dgeo = fetch_dem_for_view(view_geo, dem_zoom, margin=1,
                                   use_cache=use_cache, progress=progress)
    if dem is None:
        raise RuntimeError(
            "Не удалось загрузить тайлы рельефа.\n"
            "Проверьте подключение к интернету.")

    cell = resolution_m(view_geo["center_lat"], dem_zoom)

    tick("Заполнение впадин…")
    filled = fill_depressions(dem, eps=0.05)
    tick("Направления стока…")
    fdir = flow_directions(filled, cell)
    tick("Накопление стока…")
    acc = flow_accumulation(filled, fdir)

    row, col = lonlat_to_dem_pixel(dgeo, outlet_lon, outlet_lat)
    H, W = dem.shape
    oy = int(round(row)); ox = int(round(col))
    if not (0 <= oy < H and 0 <= ox < W):
        raise ValueError(
            "Створ за пределами загруженного рельефа.\n"
            "Кликните ближе к центру карты.")

    tick("Построение водосбора…")
    catch = catchment_upstream(fdir, oy, ox)
    if catch.sum() < 3:
        raise ValueError(
            "Створ попал на водораздел или в бессточную впадину.\n"
            "Кликните по видимому руслу реки.")

    try:
        from scipy.ndimage import binary_dilation
        preview = binary_dilation(catch, iterations=2)
    except Exception:
        preview = catch.copy()

    thr = max(3.0, threshold_frac * float(acc[catch].max()))
    net = catch & (acc >= thr)
    line = main_channel(fdir, acc, catch, oy, ox)

    stats = {
        "cells": int(catch.sum()),
        "preview_cells": int(preview.sum()),
        "area_km2": float(catch.sum()) * cell * cell / 1e6,
        "line_cells": int(line.sum()),
        "channel_km": float(line.sum()) * cell / 1000.0,
        "network_cells": int(net.sum()),
        "threshold": float(thr),
        "strahler": strahler_order(fdir, net, acc),
        "cell_m": float(cell),
        "dem_zoom": int(dem_zoom),
    }
    if stats["channel_km"] > 0:
        stats["mean_width_km"] = stats["area_km2"] / stats["channel_km"]

    return {
        "dem": dem, "filled": filled, "fdir": fdir, "acc": acc,
        "catchment": catch, "network": net, "main_line": line,
        "preview": preview,
        "outlet": (ox, oy), "dgeo": dgeo, "stats": stats,
        "outlet_lon": outlet_lon, "outlet_lat": outlet_lat,
    }


# ---------------------------------------------------------------------------
# Отрисовка: снимок + контур водосбора + русло
# ---------------------------------------------------------------------------
def overlay_on_image(base_img, geo, dgeo, catchment=None,
                     main_line=None, network=None, show_relief=False,
                     dem=None, preview=None):
    """Кладёт слои расчёта на картинку карты. Возвращает PIL.Image."""
    img = base_img.convert("RGB").copy()
    if show_relief and dem is not None:
        img = _blend_relief(img, dem, dgeo)

    if catchment is None:
        return img

    W, H = img.size
    # маска водосбора → размер окна
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img, "RGBA")

    ch, cw = catchment.shape
    # найти границы водосбора в пикселях рельефа (включая предварительную область)
    ys, xs = np.nonzero(catchment)
    if preview is not None:
        pys, pxs = np.nonzero(preview)
        if pys.size:
            ys = np.concatenate([ys, pys])
            xs = np.concatenate([xs, pxs])
    if ys.size == 0:
        return img
    r0, r1 = int(ys.min()), int(ys.max())
    c0, c1 = int(xs.min()), int(xs.max())

    def dem_to_screen(row, col):
        # пиксель рельефа → lon/lat → тайл-координаты окна → пиксели окна
        tx = dgeo["x0"] + (col + 0.5) / float(TILE)
        ty = dgeo["y0"] + (row + 0.5) / float(TILE)
        lon, lat = tile_to_lonlat(tx, ty, dgeo["z"])
        vx, vy = lonlat_to_tile(lon, lat, geo["z"])
        px = (vx - geo["x0"]) * TILE
        py = (vy - geo["y0"]) * TILE
        return px, py

    # --- заливка водосбора (полупрозрачная олива) ---
    # размер «квадратика» заливки в пикселях экрана
    px0, py0 = dem_to_screen(r0, c0)
    px1, py1 = dem_to_screen(r0 + 1, c0 + 1)
    cell_px = max(1.0, abs(px1 - px0), abs(py1 - py0))
    step = max(1, int(round(cell_px)))
    # заливаем ровно клетками экрана: соседние прямоугольники стыкуются
    def fill_mask(mask, color):
        for row in range(r0, r1 + 1, step):
            for col in range(c0, c1 + 1, step):
                if row >= mask.shape[0] or col >= mask.shape[1] or not mask[row, col]:
                    continue
                px, py = dem_to_screen(row, col)
                if -step <= px <= W + step and -step <= py <= H + step:
                    draw.rectangle([px, py, px + cell_px + 0.6, py + cell_px + 0.6],
                                   fill=color)

    # синий — предварительная (расширенная) область водосбора
    if preview is not None:
        fill_mask(preview, (70, 130, 200, 55))
    # оливковый — уточнённый водосбор
    fill_mask(catchment, (156, 167, 90, 78))

    # --- контур водосбора ---
    from scipy.ndimage import binary_erosion
    try:
        edge = catchment & ~binary_erosion(catchment, iterations=1)
    except Exception:
        edge = catchment
    pts = []
    for row, col in zip(*np.nonzero(edge)):
        px, py = dem_to_screen(row, col)
        if -20 <= px <= W + 20 and -20 <= py <= H + 20:
            pts.append((px, py))
    for px, py in pts:
        draw.ellipse([px - 1.6, py - 1.6, px + 1.6, py + 1.6],
                     fill=(115, 57, 51, 235))

    # --- русловая сеть ---
    if network is not None:
        for row, col in zip(*np.nonzero(network)):
            px, py = dem_to_screen(row, col)
            if -4 <= px <= W + 4 and -4 <= py <= H + 4:
                draw.point([px, py], fill=(139, 100, 49, 220))

    # --- главное русло ---
    if main_line is not None:
        for row, col in zip(*np.nonzero(main_line)):
            px, py = dem_to_screen(row, col)
            if -4 <= px <= W + 4 and -4 <= py <= H + 4:
                draw.ellipse([px - 1.5, py - 1.5, px + 1.5, py + 1.5],
                             fill=(115, 57, 51, 255))
    return img


def _blend_relief(img, dem, dgeo, alpha=0.45, view_geo=None):
    """Полупрозрачная отмывка рельефа поверх снимка.

    Если передан view_geo — вырезаем из рельефа ровно видимое окно
    (они могут быть в разных зумах).
    """
    from scipy.ndimage import gaussian_filter
    H, W = img.size[1], img.size[0]
    z = dem.astype(np.float32)
    if view_geo is not None and "view_z" in dgeo:
        try:
            # окно карты → координаты тайлов рельефа
            k = float(dgeo["z"] - view_geo["z"])
            fx0 = view_geo["x0"] * (2.0 ** k) - dgeo["x0"]
            fy0 = view_geo["y0"] * (2.0 ** k) - dgeo["y0"]
            fx1 = (view_geo["x0"] + view_geo["w"] / float(TILE)) * (2.0 ** k) - dgeo["x0"]
            fy1 = (view_geo["y0"] + view_geo["h"] / float(TILE)) * (2.0 ** k) - dgeo["y0"]
            c0 = max(0, int(fx0 * TILE)); r0 = max(0, int(fy0 * TILE))
            c1 = min(z.shape[1], int(fx1 * TILE)); r1 = min(z.shape[0], int(fy1 * TILE))
            if c1 > c0 and r1 > r0:
                z = z[r0:r1, c0:c1]
        except Exception:
            pass
    lo, hi = np.percentile(z, [5, 95])
    zn = np.clip((z - lo) / max(hi - lo, 1e-6), 0, 1)
    zs = gaussian_filter(zn, sigma=1.2)
    gy, gx = np.gradient(zs)
    az, alt = math.radians(315), math.radians(45)
    nx, ny, nz = -gx * 30.0, -gy * 30.0, np.ones_like(zn)
    norm = np.sqrt(nx*nx + ny*ny + nz*nz)
    shade = (nx*math.cos(alt)*math.sin(az)
             + ny*math.cos(alt)*math.cos(az)
             + nz*math.sin(alt)) / norm
    shade = np.clip(shade, 0, 1)
    shade = 0.80 + 0.20 * shade

    shade_img = Image.fromarray((shade * 255).astype(np.uint8)).convert("L")
    shade_img = shade_img.resize((W, H), Image.BILINEAR)
    gray = Image.merge("RGB", (shade_img, shade_img, shade_img))
    return Image.blend(img.convert("RGB"), gray, alpha)


def render_for_tk(width, height, center_lon, center_lat, zoom, source="esri",
                  use_cache=True, progress=None):
    """Мозаика тайлов, подготовленная под окно Tk."""
    return render_view(center_lon, center_lat, zoom,
                       width, height, source=source,
                       use_cache=use_cache, progress=progress)


def draw_outlet(img, px, py, radius=9):
    """Рисует маркер створа на картинке."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.ellipse([px-radius, py-radius, px+radius, py+radius],
              outline=(255, 60, 60), width=3)
    d.line([px-radius-6, py, px+radius+6, py], fill=(255, 60, 60), width=2)
    d.line([px, py-radius-6, px, py+radius+6], fill=(255, 60, 60), width=2)
    return img
