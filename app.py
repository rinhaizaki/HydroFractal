# -*- coding: utf-8 -*-
"""HydroFractal — версия приложения для браузера.

Сервер отдаёт сайт и считает те же самые алгоритмы, что и оригинальное
приложение river_fractal.py / map_core.py:
  * сегментация воды по RGB/HSV;
  * скелет/контур маски;
  * фрактальная размерность методом Кантора (квадраты);
  * оценка характеристик стока по D;
  * спутниковая карта, тайлы рельефа, D8-гидрология и водосбор.

Запуск:
    python app.py
"""
from __future__ import annotations

import base64
import datetime
import io
import math
import os
from xml.sax.saxutils import escape

import numpy as np
from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageDraw

from core import hydro_core, map_core, offline_map

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TILE_CACHE = os.path.join(BASE_DIR, "tile_cache")
map_core.set_cache_dir(TILE_CACHE)

# В изолированном окружении (без доступа к тайлам) сервер показывает
# детерминированную демо-местность — все алгоритмы при этом работают на
# настоящем массиве высот, просто он сгенерирован локально.
_orig_best_dem_zoom = map_core.best_dem_zoom
_orig_fetch_dem = map_core.fetch_dem_for_view


def _best_dem_zoom(view_zoom, lat):
    zoom = _orig_best_dem_zoom(view_zoom, lat)
    if not offline_map.ensure_mode():
        # меньше тайлов → быстрее используется демо-рельеф
        return min(zoom, 10)
    return zoom


def _fetch_dem_with_fallback(geo, dem_zoom, margin=1, use_cache=True, progress=None):
    dem, dgeo = _orig_fetch_dem(geo, dem_zoom, margin=margin,
                                use_cache=use_cache, progress=progress)
    if dem is None:
        return offline_map.synthetic_dem_for_view(geo, dem_zoom, margin, progress)
    return dem, dgeo


map_core.best_dem_zoom = _best_dem_zoom
map_core.fetch_dem_for_view = _fetch_dem_with_fallback

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

MAX_IMAGE_SIDE = 1600
MAP_MAX_W = 1100
MAP_MAX_H = 760


# ---------------------------------------------------------------------------
# Утилиты изображений
# ---------------------------------------------------------------------------
def _decode_data_url(value: str) -> bytes:
    if not value or not isinstance(value, str):
        raise ValueError("Пустые данные изображения.")
    if "," in value and value.strip().lower().startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def _encode_png(img: Image.Image) -> str:
    bio = io.BytesIO()
    img.save(bio, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode("ascii")


def _encode_jpeg(img: Image.Image, quality: int = 88) -> str:
    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(bio.getvalue()).decode("ascii")


def _rgb_from_bytes(data: bytes, max_side: int = MAX_IMAGE_SIDE):
    """Аккуратная загрузка 8/16-битных снимков + нормализация размера."""
    img = Image.open(io.BytesIO(data))
    arr = np.asarray(img)

    if arr.dtype != np.uint8:
        a = arr.astype(np.float32)
        if a.ndim == 3:
            out = np.empty_like(a)
            for c in range(a.shape[2]):
                lo, hi = np.nanpercentile(a[..., c], [1, 99])
                out[..., c] = np.clip((a[..., c] - lo) / max(hi - lo, 1e-6), 0, 1) * 255
            arr = out
        else:
            lo, hi = np.nanpercentile(a, [1, 99])
            arr = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255
        arr = arr.astype(np.uint8)

    if arr.ndim == 2:
        rgb = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 4:
        rgb = arr[..., :3]
    else:
        rgb = arr[..., :3]

    img = Image.fromarray(np.ascontiguousarray(rgb), "RGB")
    if max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    return np.asarray(img), img


def _bool_mask_from_data_url(value: str) -> np.ndarray:
    img = Image.open(io.BytesIO(_decode_data_url(value))).convert("L")
    return np.asarray(img) > 127


def _overlay_from_mask(rgb: np.ndarray, mask: np.ndarray,
                       seed=None, extras=None) -> Image.Image:
    base = Image.fromarray(np.ascontiguousarray(rgb), "RGB").convert("RGBA")
    tint = Image.new("RGBA", base.size, (40, 220, 80, 0))
    m = Image.fromarray((mask.astype(np.uint8) * 255), "L")
    tint.putalpha(m.point(lambda v: int(v * 0.48)))
    base = Image.alpha_composite(base, tint)

    d = ImageDraw.Draw(base)
    if seed is not None:
        x, y = int(seed["x"]), int(seed["y"])
        d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(255, 60, 60, 255), width=3)
        d.line([x - 15, y, x + 15, y], fill=(255, 60, 60, 255), width=2)
        d.line([x, y - 15, x, y + 15], fill=(255, 60, 60, 255), width=2)
    for i, p in enumerate(extras or [], start=2):
        x, y = int(p["x"]), int(p["y"])
        d.ellipse([x - 8, y - 8, x + 8, y + 8], outline=(245, 205, 70, 255), width=3)
        d.text((x + 10, y - 10), str(i), fill=(245, 205, 70, 255))
    return base.convert("RGB")


def _clean_number(v, digits=4):
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return v


def _result_payload(result: dict) -> dict:
    """Сериализуем результат алгоритма Кантора для браузера."""
    table = [[int(n), round(float(eps), 3), int(cnt)] for n, eps, cnt in result["table"]]
    fit_rows = [[int(n), float(eps), int(cnt)] for n, eps, cnt in result["fit_rows"]]
    return {
        "D": _clean_number(result["D"], 6),
        "h": _clean_number(result["h"], 6),
        "dh": _clean_number(result["dh"], 6),
        "dD": _clean_number(result["dD"], 6),
        "r2": _clean_number(result["r2"], 8),
        "intercept": _clean_number(result["intercept"], 6),
        "water_pixels": int(result.get("water_pixels", 0)),
        "object": result.get("object", "skeleton"),
        "table": table,
        "fit_rows": fit_rows,
        "n_divs_used": int(result.get("n_divs_used", 0)),
        "method": "Кантор (квадраты), D = 1 + h/2",
    }


def _stream_payload(D: float, dD: float = 0.0) -> dict:
    s = hydro_core.stream_stats_from_D(D, dD)
    keep = ["Q_mean", "Cv", "Cs", "rel_err_Q", "rel_err_Cv", "rel_err_Cs"]
    out = {k: _clean_number(s[k], 5) for k in keep}
    out["qp"] = [{"p": p, "k": _clean_number(s["kp_by_p"][p], 4),
                  "q": _clean_number(s["qp_by_p"][p], 2)} for p in hydro_core.MAJOR_P]
    out["sp33"] = [[_clean_number(v, 5) for v in row]
                   for row in hydro_core.sp33_kp_table(s["Cv"])]
    return out


# ---------------------------------------------------------------------------
# График log N — log(1/ε)
# ---------------------------------------------------------------------------
def make_plot_png(result: dict) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    rows = result["fit_rows"]
    x = [math.log10(1.0 / float(eps)) for _n, eps, _c in rows]
    y = [math.log10(int(c)) for _n, _eps, c in rows]

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=150)
    fig.patch.set_facecolor("#F3EBE0")
    ax.set_facecolor("#FBF7F0")
    ax.scatter(x, y, s=34, color="#9CA75A", edgecolors="#8B6431",
               linewidths=0.8, zorder=3, label="Измерения")
    if x:
        xs = np.linspace(min(x), max(x), 60)
        ax.plot(xs, result["h"] * xs + result["intercept"],
                color="#733933", lw=2.0, zorder=2, label="Аппроксимация")
    ax.set_xlabel("log₁₀(1/ε)", fontsize=10, color="#4d3524")
    ax.set_ylabel("log₁₀ N(ε)", fontsize=10, color="#4d3524")
    ax.set_title("Канторовский метод: log N(ε) от log(1/ε)",
                 fontsize=11, color="#733933")
    ax.grid(True, color="#DACAB0", linewidth=0.8, alpha=0.9)
    ax.tick_params(colors="#6b5238", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#8B6431")
        spine.set_linewidth(0.9)
    fmt = FuncFormatter(lambda v, _p: f"{v:,.1f}".replace(",", " ").replace(".", ","))
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.tight_layout()
    bio = io.BytesIO()
    fig.savefig(bio, format="PNG", bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# PDF-отчёт
# ---------------------------------------------------------------------------
def make_report_pdf(payload: dict) -> bytes:
    """Канонический отчёт HydroFractal: разделы I–VII, таблицы и рисунки."""
    import report_reference
    from types import SimpleNamespace

    result = dict(payload.get("result") or {})
    fit_rows = result.get("fit_rows") or []
    if fit_rows and "x" not in result:
        result["x"] = np.array([math.log10(1.0 / float(row[1])) for row in fit_rows])
        result["y"] = np.array([math.log10(float(row[2])) for row in fit_rows])

    # Изображение и маска нужны ядру отчёта для рисунков 2 и 3.
    try:
        _rgb, scene = _rgb_from_bytes(_decode_data_url(payload.get("image", "")))
    except Exception:
        scene = Image.new("RGB", (800, 500), "white")
        _rgb = np.asarray(scene)
    try:
        mask = _bool_mask_from_data_url(payload.get("mask", ""))
    except Exception:
        mask = np.zeros(_rgb.shape[:2], dtype=bool)

    seed = payload.get("seed") or {}
    try:
        seed_xy = (float(seed["x"]), float(seed["y"])) if seed else None
    except (KeyError, TypeError, ValueError):
        seed_xy = None
    seed_rgb = payload.get("seed_rgb")
    if seed_rgb and seed_xy:
        try:
            sx = int(max(0, min(_rgb.shape[1] - 1, seed_xy[0])))
            sy = int(max(0, min(_rgb.shape[0] - 1, seed_xy[1])))
            _rgb = _rgb.copy()
            _rgb[sy, sx] = [int(v) for v in seed_rgb[:3]]
        except Exception:
            pass

    method = str(payload.get("method", "color"))
    obj = str(result.get("object") or payload.get("object") or "skeleton")
    tol_value = payload.get("tol", 60)

    class _Tol:
        def get(self):
            return tol_value

    def _render_scene_image(max_side=1400, force_overlay=False):
        img = scene.convert("RGB")
        if max(img.size) > max_side:
            k = max_side / max(img.size)
            img = img.resize((max(1, round(img.width * k)),
                              max(1, round(img.height * k))), Image.LANCZOS)
        return img

    ctx = SimpleNamespace(
        image_path=payload.get("source_name") or "—",
        rgb=_rgb,
        seed_xy=seed_xy,
        color_pts=payload.get("color_pts") or [],
        mask=mask,
        mask_touched=bool(payload.get("mask_touched", False)),
        tol_var=_Tol(),
        result=result,
        _method_index={"color": 0, "dark": 1, "hybrid": 2}.get(method, 0),
        _object_index={"skeleton": 0, "boundary": 1, "mask": 2}.get(obj, 0),
        _render_scene_image=_render_scene_image,
        notify=lambda *args, **kwargs: None,
    )
    bio = io.BytesIO()
    report_reference.write_report(ctx, bio)
    return bio.getvalue()


# ---------------------------------------------------------------------------
# Страница
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


# Относительные пути в разметке одинаково работают и на Flask, и на GitHub Pages
# (где каталог static/ становится корнем сайта).
@app.route("/styles.css")
def styles_alias():
    return app.send_static_file("styles.css")


@app.route("/app.js")
def app_js_alias():
    return app.send_static_file("app.js")


@app.route("/client-core.js")
def client_core_alias():
    return app.send_static_file("client-core.js")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "HydroFractal Web"})


# ---------------------------------------------------------------------------
# Режим «Снимок»
# ---------------------------------------------------------------------------
@app.post("/api/upload")
def api_upload():
    """Нормализует загруженный снимок и возвращает его для холста."""
    try:
        data = request.get_json(force=True) or {}
        _rgb, img = _rgb_from_bytes(_decode_data_url(data.get("image", "")))
        return jsonify({"ok": True, "image": _encode_jpeg(img),
                        "width": int(img.width), "height": int(img.height)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


@app.post("/api/segment")
def api_segment():
    try:
        data = request.get_json(force=True) or {}
        rgb, img = _rgb_from_bytes(_decode_data_url(data.get("image", "")))
        seed = data.get("seed") or {}
        if "x" not in seed or "y" not in seed:
            raise ValueError("Сначала отметьте точку на реке.")
        seed = {"x": float(seed["x"]), "y": float(seed["y"])}
        extras = [{"x": float(p["x"]), "y": float(p["y"])} for p in data.get("extras", [])]
        tol = max(1.0, min(180.0, float(data.get("tol", 70))))
        method = data.get("method", "color")
        if method not in ("color", "dark", "hybrid"):
            method = "color"

        mask = hydro_core.segment_water(
            rgb, (seed["x"], seed["y"]), method=method, tol=tol,
            keep_largest=bool(data.get("keep_largest", True)),
            morph_close=2, morph_open=1,
            extra_points=[(p["x"], p["y"]) for p in extras])
        water = int(mask.sum())
        overlay = _overlay_from_mask(rgb, mask, seed, extras)
        mask_img = Image.fromarray((mask.astype(np.uint8) * 255), "L")
        return jsonify({
            "ok": True,
            "image": _encode_jpeg(img),
            "overlay": _encode_jpeg(overlay),
            "mask": _encode_png(mask_img),
            "width": int(img.width), "height": int(img.height),
            "water_pixels": water,
            "water_share": round(100.0 * water / mask.size, 3),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


@app.post("/api/analyze")
def api_analyze():
    try:
        data = request.get_json(force=True) or {}
        mask = _bool_mask_from_data_url(data.get("mask", ""))
        obj = data.get("object", "skeleton")
        if obj == "skeleton":
            if not hydro_core.HAVE_SKIMAGE:
                obj = "boundary"
            else:
                working = hydro_core.skeleton_mask(mask)
        elif obj == "boundary":
            working = hydro_core.boundary_mask(mask)
        else:
            working = mask
        try:
            max_divs = int(data.get("max_divs", 60))
        except (TypeError, ValueError):
            max_divs = 60
        result = hydro_core.cantor_squares_dimension(working, max_divs=max_divs)
        result["water_pixels"] = int(mask.sum())
        result["object"] = obj
        payload = _result_payload(result)
        payload["plot"] = make_plot_png(result)
        payload["stream"] = _stream_payload(result["D"], result["dD"])
        return jsonify({"ok": True, "result": payload})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


@app.post("/api/mask/png")
def api_mask_png():
    """Маска-подложка: чёрная река на белом фоне + метаданные PNG."""
    try:
        data = request.get_json(force=True) or {}
        mask = _bool_mask_from_data_url(data.get("mask", ""))
        seed = data.get("seed")
        seed_xy = (float(seed["x"]), float(seed["y"])) if seed else None
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            hydro_core.write_mask_png(
                tmp_path, mask,
                scale_text=str(data.get("scale_text", "") or ""),
                image_path=str(data.get("source_name", "") or "unknown"),
                seed_xy=seed_xy)
            with open(tmp_path, "rb") as f:
                png_bytes = f.read()
        finally:
            try: os.remove(tmp_path)
            except OSError: pass
        return send_file(io.BytesIO(png_bytes), mimetype="image/png",
                         as_attachment=True, download_name="river_mask.png")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


# ---------------------------------------------------------------------------
# Режим «Карта»
# ---------------------------------------------------------------------------
def _map_params(data):
    try:
        lon = float(data.get("lon", 41.70))
        lat = float(data.get("lat", 43.50))
        zoom = int(max(3, min(16, int(data.get("zoom", 11)))))
        width = int(max(240, min(MAP_MAX_W, int(data.get("width", 900)))))
        height = int(max(180, min(MAP_MAX_H, int(data.get("height", 580)))))
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректные параметры карты.") from exc
    source = data.get("source", "esri")
    if source not in map_core.SOURCES:
        source = "esri"
    return lon, lat, zoom, width, height, source


def _render_map(lon, lat, zoom, width, height, source, relief=False):
    if offline_map.ensure_mode():
        img, geo = map_core.render_view(lon, lat, zoom, width, height, source=source)
    else:
        # Без сети сразу строим согласованную с рельефом подложку.
        img = offline_map.synthetic_base_image(
            {"w": width, "h": height}, source=source)
        cx, cy = map_core.lonlat_to_tile(lon, lat, zoom)
        geo = {"x0": cx - width / (2.0 * map_core.TILE),
               "y0": cy - height / (2.0 * map_core.TILE),
               "z": zoom, "w": width, "h": height,
               "center_lon": lon, "center_lat": lat}
    if relief:
        try:
            dz = map_core.best_dem_zoom(zoom, lat)
            dem, dgeo = map_core.fetch_dem_for_view(geo, dz, margin=0)
            if dem is not None:
                img = map_core._blend_relief(img, dem, dgeo, alpha=0.55, view_geo=geo)
        except Exception:
            pass
    return img, geo


@app.post("/api/map/view")
def api_map_view():
    try:
        data = request.get_json(force=True) or {}
        lon, lat, zoom, w, h, source = _map_params(data)
        img, geo = _render_map(lon, lat, zoom, w, h, source,
                               bool(data.get("relief", False)))
        return jsonify({
            "ok": True,
            "image": _encode_jpeg(img),
            "credit": f"{map_core.SOURCES[source]['credit']} · {map_core.TERRAIN_CREDIT}",
            "demo": not offline_map.ensure_mode(),
            "cell_m": round(map_core.resolution_m(lat, zoom), 2),
            "geo": {"x0": geo["x0"], "y0": geo["y0"], "z": geo["z"],
                    "w": geo["w"], "h": geo["h"]},
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


@app.post("/api/map/analyze")
def api_map_analyze():
    try:
        data = request.get_json(force=True) or {}
        lon, lat, zoom, w, h, source = _map_params(data)
        outlet_lon = float(data.get("outlet_lon", lon))
        outlet_lat = float(data.get("outlet_lat", lat))

        img, geo = _render_map(lon, lat, zoom, w, h, source,
                               bool(data.get("relief", False)))
        res = map_core.analyse_map(geo, outlet_lon, outlet_lat)
        line = res["main_line"]
        if int(line.sum()) < 10:
            raise ValueError("Главное русло слишком короткое для расчёта D. "
                             "Попробуйте кликнуть ниже по течению.")

        dim = hydro_core.cantor_squares_dimension(line, max_divs=60)
        dim["water_pixels"] = int(line.sum())
        dim["object"] = "skeleton"

        overlay = map_core.overlay_on_image(
            img, geo, res["dgeo"], catchment=res["catchment"],
            main_line=res["main_line"], network=res["network"],
            preview=res.get("preview"))
        tx, ty = map_core.lonlat_to_tile(outlet_lon, outlet_lat, zoom)
        overlay = map_core.draw_outlet(
            overlay, (tx - geo["x0"]) * map_core.TILE,
            (ty - geo["y0"]) * map_core.TILE)

        st = res["stats"]
        payload = _result_payload(dim)
        payload["plot"] = make_plot_png(dim)
        payload["stream"] = _stream_payload(dim["D"], dim["dD"])
        return jsonify({
            "ok": True,
            "image": _encode_png(overlay.convert("RGB")),
            "credit": (f"{map_core.SOURCES[source]['credit']} · "
                       f"{map_core.TERRAIN_CREDIT}"),
            "demo": not offline_map.ensure_mode(),
            "map": {
                "area_km2": round(st["area_km2"], 3),
                "channel_km": round(st["channel_km"], 3),
                "cells": st["cells"],
                "preview_cells": st.get("preview_cells", st["cells"]),
                "line_cells": st["line_cells"],
                "network_cells": st["network_cells"],
                "threshold": round(st["threshold"], 2),
                "strahler": st["strahler"],
                "cell_m": round(st["cell_m"], 2),
                "dem_zoom": st["dem_zoom"],
                "outlet_lat": round(outlet_lat, 5),
                "outlet_lon": round(outlet_lon, 5),
            },
            "result": payload,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
@app.post("/api/report")
def api_report():
    try:
        payload = request.get_json(force=True) or {}
        pdf = make_report_pdf(payload)
        return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                         as_attachment=True, download_name="gidrofraktal-report.pdf")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc) or exc.__class__.__name__}), 400


if __name__ == "__main__":
    print("HydroFractal Web: http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
