# -*- coding: utf-8 -*-
"""Демонстрационные подложки и рельеф для автономного окружения.

Карта и SRTM-тайлы в обычной работе берутся из сети. Если сеть недоступна
(например, сервер запущен в изолированном preview-окружении), web-версия
показывает детерминированную синтетическую местность с руслом и
выполняет тот же конвейер D8/водосбор/Кантор на этом рельефе. Это позволяет
проверить все функции сайта без интернета; при наличии сети используется
настоящий спутниковый снимок и настоящие высоты.
"""
from __future__ import annotations

import math
import urllib.request

import numpy as np
from PIL import Image, ImageDraw

from . import map_core

_NETWORK_OK = None


def ensure_mode():
    """True — доступны реальные тайлы, False — включён демо-режим."""
    global _NETWORK_OK
    if _NETWORK_OK is None:
        try:
            url = map_core.TERRAIN_URL.format(z=2, x=2, y=1)
            req = urllib.request.Request(url, headers=map_core.UA)
            with urllib.request.urlopen(req, timeout=3) as resp:
                _NETWORK_OK = len(resp.read(64)) > 0
        except Exception:
            _NETWORK_OK = False
    return _NETWORK_OK


def valley_center(v):
    """Ось долины; при v = 0.5 (центр окна) она проходит ровно через 0.5."""
    return (0.5 + 0.045 * np.sin(2 * math.pi * (v - 0.5))
            + 0.018 * np.sin(4 * math.pi * (v - 0.5)))


def terrain_field(u, v):
    """Высоты синтетической местности в относительных координатах окна.

    u, v — координаты окна (v растёт к югу). Долина с меандрирующим руслом
    проходит через центр; высоты убывают к югу, поэтому направления стока
    сходятся к руслу и текут вниз по течению.
    """
    u = np.asarray(u, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)
    dist = (u - valley_center(v)) / 0.09
    valley = np.exp(-(dist * dist))
    ridges = (0.55 * np.sin(2 * math.pi * (2.3 * u + 1.1 * v) + 0.4)
              + 0.30 * np.sin(2 * math.pi * (4.7 * u - 0.8 * v) + 1.7)
              + 0.15 * np.sin(2 * math.pi * (9.1 * u + 3.3 * v)))
    small = 0.35 * np.sin(2 * math.pi * (17.0 * u + 5.0 * v) + 2.1)
    return (-1200.0 * v + 120.0 * ridges * (1.0 - valley)
            + 25.0 * small * (1.0 - valley) - 400.0 * valley).astype(np.float32)


def _dem_geometry(geo, dem_zoom, margin=1):
    k = 2.0 ** (dem_zoom - geo["z"])
    tx0 = int(math.floor(geo["x0"] * k - margin))
    ty0 = int(math.floor(geo["y0"] * k - margin))
    tx1 = int(math.floor((geo["x0"] + geo["w"] / float(map_core.TILE)) * k + margin))
    ty1 = int(math.floor((geo["y0"] + geo["h"] / float(map_core.TILE)) * k + margin))
    nx, ny = max(1, tx1 - tx0 + 1), max(1, ty1 - ty0 + 1)
    dgeo = {"x0": tx0, "y0": ty0, "z": int(dem_zoom),
            "w": nx * map_core.TILE, "h": ny * map_core.TILE,
            "view_x0": geo["x0"], "view_y0": geo["y0"], "view_z": geo["z"],
            "tiles_ok": 0, "tiles_all": nx * ny, "synthetic": True}
    return dgeo, nx, ny


def synthetic_dem_for_view(geo, dem_zoom, margin=1, progress=None):
    """Тот же интерфейс, что у fetch_dem_for_view, но без сети."""
    if progress:
        progress("Демо-режим: генерация рельефа…")
    dgeo, nx, ny = _dem_geometry(geo, dem_zoom, margin)
    H = ny * map_core.TILE
    W = nx * map_core.TILE
    rows = (np.arange(H, dtype=np.float32) + 0.5)
    cols = (np.arange(W, dtype=np.float32) + 0.5)
    # тайлы рельефа и окно карты могут быть разных зумов: переводим
    # координаты демо-рельефа в системе координат окна карты
    k = 2.0 ** (dem_zoom - geo["z"])
    tx = (dgeo["x0"] + cols / float(map_core.TILE)) / k
    ty = (dgeo["y0"] + rows / float(map_core.TILE)) / k
    u = (tx - geo["x0"]) * map_core.TILE / float(geo["w"])
    v = (ty - geo["y0"]) * map_core.TILE / float(geo["h"])
    dem = terrain_field(u[None, :], v[:, None])
    return dem, dgeo


def synthetic_base_image(geo, source="esri"):
    """Подложка в стиле спутника/топокарты, согласованная с рельефом."""
    W, H = int(geo["w"]), int(geo["h"])
    u = (np.arange(W, dtype=np.float32) + 0.5) / W
    v = (np.arange(H, dtype=np.float32) + 0.5) / H
    z = terrain_field(u[None, :], v[:, None])
    lo, hi = np.percentile(z, [3, 97])
    zn = np.clip((z - lo) / max(hi - lo, 1e-6), 0, 1)

    gy, gx = np.gradient(zn)
    az, alt = math.radians(315), math.radians(45)
    nx, ny, nz = -gx * 8.0, -gy * 8.0, np.ones_like(zn)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    shade = ((nx * math.cos(alt) * math.sin(az)
              + ny * math.cos(alt) * math.cos(az)
              + nz * math.sin(alt)) / norm)
    shade = np.clip(0.72 + 0.45 * shade, 0.35, 1.15)

    if source == "sentinel":
        low = np.array([206, 214, 178], dtype=np.float32)
        mid = np.array([174, 190, 141], dtype=np.float32)
        high = np.array([214, 198, 166], dtype=np.float32)
    else:
        low = np.array([63, 96, 63], dtype=np.float32)
        mid = np.array([104, 123, 70], dtype=np.float32)
        high = np.array([149, 132, 101], dtype=np.float32)
    t = np.clip(zn * 2.0, 0, 1)[..., None]
    rgb = low[None, None, :] * (1 - t) + mid[None, None, :] * t
    t2 = np.clip((zn - 0.5) * 2.0, 0, 1)[..., None]
    rgb = rgb * (1 - t2) + high[None, None, :] * t2
    rgb = np.clip(rgb * shade[..., None], 0, 255).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB")

    # меандрирующая река точно по оси долины
    d = ImageDraw.Draw(img, "RGBA")
    pts = []
    for row in range(H):
        vv = (row + 0.5) / H
        bend = valley_center(vv)
        pts.append((max(0, min(W - 1, bend * W)), row))
    width = max(2, int(round(min(W, H) / 260)))
    d.line(pts, fill=(63, 97, 116, 90), width=width + 5)
    d.line(pts, fill=(58, 116, 152, 220), width=width)

    if source == "sentinel":
        draw = ImageDraw.Draw(img, "RGBA")
        step = max(45, int(np.ptp(z) / 14))
        base = math.ceil(float(z.min()) / step) * step
        for level in range(int(base), int(z.max()) + step, step):
            mask = (np.floor(z / step) != np.floor((z - 6) / step)) & (z > level - step)
            ys, xs = np.nonzero(mask)
            for y, x in zip(ys[::6], xs[::6]):
                draw.point((int(x), int(y)), fill=(116, 92, 60, 90))
    return img
