# -*- coding: utf-8 -*-
"""HydroFractal Web — веб-версия десктопного приложения.

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
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    font_dir = "/usr/share/fonts/truetype/dejavu"
    pdfmetrics.registerFont(TTFont("HF", os.path.join(font_dir, "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("HF-Bold", os.path.join(font_dir, "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("HF", normal="HF", bold="HF-Bold")

    olive = colors.HexColor("#9CA75A")
    burgundy = colors.HexColor("#733933")
    brown = colors.HexColor("#8B6431")
    cream = colors.HexColor("#F3EBE0")
    beige = colors.HexColor("#DACAB0")

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName="HF-Bold",
                        fontSize=20, leading=25, textColor=burgundy, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName="HF-Bold",
                        fontSize=13, leading=17, textColor=brown, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="HF",
                          fontSize=9.5, leading=14, alignment=TA_JUSTIFY,
                          textColor=colors.HexColor("#3d2f22"))
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=11,
                           textColor=colors.HexColor("#6b5238"))
    cell = ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11, alignment=0)
    center = ParagraphStyle("center", parent=body, alignment=TA_CENTER, fontSize=9)

    def P(text, style=body):
        return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)

    def tbl(data, widths, header=True):
        rows = []
        for i, row in enumerate(data):
            rows.append([P(c, cell) if not hasattr(c, "wrap") else c for c in row])
        t = Table(rows, colWidths=widths, hAlign="CENTER", repeatRows=1 if header else 0)
        cmds = [
            ("GRID", (0, 0), (-1, -1), 0.5, beige),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, cream]),
        ]
        if header:
            cmds += [("BACKGROUND", (0, 0), (-1, 0), olive),
                     ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(cmds))
        return t

    def _img_from_data_url(value, max_w, max_h):
        if not value or not isinstance(value, str):
            return None
        raw = _decode_data_url(value)
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        bio = io.BytesIO()
        im.save(bio, format="PNG")
        bio.seek(0)
        ratio = min(max_w / im.width, max_h / im.height, 1.0)
        return RLImage(bio, width=im.width * ratio, height=im.height * ratio)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("HF", 8)
        canvas.setFillColor(brown)
        canvas.drawString(2 * cm, 1.1 * cm, "Гидрофрактал — веб-версия")
        canvas.drawRightString(A4[0] - 1.5 * cm, 1.1 * cm, f"Страница {doc.page}")
        canvas.setStrokeColor(beige)
        canvas.line(2 * cm, 1.5 * cm, A4[0] - 1.5 * cm, 1.5 * cm)
        canvas.restoreState()

    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, leftMargin=2 * cm, rightMargin=1.5 * cm,
                            topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                            title="Отчёт «Гидрофрактал»")
    story = []

    story.append(P("ОТЧЁТ О ФРАКТАЛЬНОЙ РАЗМЕРНОСТИ РЕКИ", h1))
    story.append(P(payload.get("title", "Гидрофрактал — веб-версия"), center))
    story.append(P("Дата: " + datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), small))
    story.append(Spacer(1, 10))

    story.append(P("I. Исходные данные и параметры", h2))
    params = payload.get("params", [])
    story.append(tbl([["Параметр", "Значение"]] +
                     [[str(a), str(b)] for a, b in params], [7.2 * cm, 9.4 * cm]))
    story.append(Spacer(1, 6))

    story.append(P("II. Результаты расчёта", h2))
    result = payload.get("result", {})
    metrics = payload.get("metrics", [])
    if not metrics:
        metrics = [["Фрактальная размерность D", result.get("D", "—")],
                   ["Размерность блуждания h", result.get("h", "—")],
                   ["Стандартная ошибка dD", result.get("dD", "—")],
                   ["Коэффициент детерминации R²", result.get("r2", "—")]]
    story.append(tbl([["Показатель", "Значение"]] +
                     [[str(a), str(b)] for a, b in metrics], [7.2 * cm, 9.4 * cm]))

    plot = _img_from_data_url(payload.get("plot"), 16.4 * cm, 8 * cm)
    if plot is not None:
        story.append(Spacer(1, 8))
        story.append(plot)
        story.append(P("Рисунок 1 — Зависимость log N(ε) от log(1/ε).", small))

    table = payload.get("table", [])
    if table:
        story.append(PageBreak())
        story.append(P("III. Полная таблица измерений", h2))
        head = [["n", "ε, px", "N(ε)"]]
        chunk = head + [[str(r[0]), str(r[1]), str(r[2])] for r in table]
        story.append(tbl(chunk, [3.2 * cm, 4.2 * cm, 4.2 * cm]))

    stream = payload.get("stream", {})
    if stream:
        story.append(Spacer(1, 10))
        story.append(P("IV. Характеристики стока (ориентировочная оценка по D)", h2))
        srows = [["Характеристика", "Обозначение", "Значение"],
                 ["Средний многолетний расход", "Qср, м³/с", stream.get("Q_mean", "—")],
                 ["Коэффициент вариации", "Cv", stream.get("Cv", "—")],
                 ["Коэффициент асимметрии", "Cs", stream.get("Cs", "—")]]
        story.append(tbl(srows, [8.2 * cm, 4 * cm, 4.4 * cm]))
        story.append(Spacer(1, 6))
        story.append(P("Использованы калибровочные связи Cv = 2(D − 1), Cs = 2Cv и "
                       "распределение Пирсона III типа (коэффициенты Фостера–Рыбкина). "
                       "Оценка предназначена для малоизученных рек и не заменяет "
                       "наблюдённые гидрологические ряды.", small))

    image = _img_from_data_url(payload.get("image"), 16.4 * cm, 9.5 * cm)
    if image is not None:
        story.append(PageBreak())
        story.append(P("V. Снимок / карта и выделенная область", h2))
        story.append(image)
        story.append(P("Рисунок 2 — Исходные данные с наложенными результатами анализа.", small))

    story.append(Spacer(1, 12))
    story.append(P("Метод: покрытие изображения квадратной сеткой n×n, подсчёт числа "
                   "клеток N(ε), пересекаемых линией реки, аппроксимация зависимости "
                   "log N(ε) от log(1/ε) методом наименьших квадратов; "
                   "D = 1 + h/2.", small))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
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
            main_line=res["main_line"], network=res["network"])
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
