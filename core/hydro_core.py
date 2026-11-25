# -*- coding: utf-8 -*-
"""Вычислительное ядро веб-версии HydroFractal (без Tkinter).

Функции перенесены из river_fractal.py без изменений алгоритмов:
сегментация воды, скелет/контур, канторовский метод и оценка стока.
"""
from __future__ import annotations

import datetime
import math
import os

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Нужна библиотека opencv-python-headless") from exc


def _hsv_distance(hsv, seed_hsv):
    """
    Цветовое расстояние в HSV между каждым пикселем и эталоном seed_hsv.

    Канал H (тон) циклический: разница 179 и 1 — это 2, а не 178.
    H приводим к шкале 0–255 (×255/180), чтобы все три канала
    были сопоставимы и один ползунок «допуск» имел смысл.
    """
    h = hsv[..., 0].astype(np.float32)
    s = hsv[..., 1].astype(np.float32)
    v = hsv[..., 2].astype(np.float32)

    hs, ss, vs = (float(seed_hsv[0]), float(seed_hsv[1]), float(seed_hsv[2]))

    dh = np.abs(h - hs)
    dh = np.minimum(dh, 180.0 - dh)          # циклическая разность тонов
    dh *= (255.0 / 180.0)                    # приводим H к шкале 0–255

    ds = s - ss
    dv = v - vs
    return np.sqrt(dh * dh + ds * ds + dv * dv)


def segment_water(rgb, seed_xy, method="color", tol=60,
                  keep_largest=True, morph_close=2, morph_open=1,
                  extra_points=None):
    """
    Пороговая сегментация воды по эталону из точки seed_xy.

    Параметры
    ---------
    rgb          : массив (H, W, 3) uint8 — снимок.
    seed_xy      : (x, y) — координаты кликнутой точки в пикселях снимка
                   (точка расхода/створ; её цвет — основной эталон).
    extra_points : список (x, y) — дополнительные точки-эталоны цвета.
                   Вода выделяется, если пиксель похож на ЛЮБОЙ из
                   эталонов (основной или дополнительный). Так можно
                   добавить в маску участок реки другого оттенка
                   (мутная/чистая вода, тени на воде).
    method       : "color" — по цвету точки (HSV-дистанция ≤ tol);
                   "dark"  — тёмная вода (V-канал не выше, чем у точки + tol);
                   "hybrid"— объединение обоих признаков (ИЛИ).
    tol          : допуск (чем больше, тем «шире» выделение).
    keep_largest : оставить только самую крупную связную область
                   (отсекает тени, крыши, дороги и прочий тёмный мусор).
    morph_close  : число итераций морфологического закрытия
                   (склеивает разрывы внутри русла).
    morph_open   : число итераций открытия (смоет мелкий шум).
                   Ядро открытия — 3×3: река на снимке может быть
                   всего в несколько пикселей шириной, и крупное
                   ядро (5×5+) «съест» её на крутых изгибах.

    Возвращает
    ----------
    mask : bool-массив (H, W) — True для «водных» пикселей.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    x, y = int(seed_xy[0]), int(seed_xy[1])
    x = min(max(x, 0), rgb.shape[1] - 1)
    y = min(max(y, 0), rgb.shape[0] - 1)
    def _ref_hsv(cx, cy, rad=4):
        """Эталонный цвет точки как МЕДИАНА по кружку вокруг неё.

        Одиночный пиксель на спутниковом снимке шумный: его цвет может
        случайно оказаться темнее или светлее настоящего. Медиана по
        окрестности даёт устойчивый оттенок воды."""
        cx = min(max(int(cx), 0), rgb.shape[1] - 1)
        cy = min(max(int(cy), 0), rgb.shape[0] - 1)
        hh, ww = hsv.shape[:2]
        y0, y1 = max(0, cy - rad), min(hh, cy + rad + 1)
        x0, x1 = max(0, cx - rad), min(ww, cx + rad + 1)
        patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
        return np.median(patch, axis=0)

    seed_hsv = _ref_hsv(x, y)
    # все эталоны цвета: основной створ + дополнительные точки
    seeds_hsv = [seed_hsv]
    for (ex, ey) in (extra_points or []):
        seeds_hsv.append(_ref_hsv(ex, ey))

    tol = float(tol)
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)

    if method in ("color", "hybrid"):
        # пиксель — вода, если он близок к ЛЮБОМУ эталону цвета
        for ref in seeds_hsv:
            dist = _hsv_distance(hsv, ref)
            mask |= (dist <= tol).astype(np.uint8)

    if method in ("dark", "hybrid"):
        # «тёмная вода»: всё, что не светлее самого ТЁМНОГО эталона + допуск
        v_seed = max(float(r[2]) for r in seeds_hsv)
        mask |= (hsv[..., 2].astype(np.float32) <= v_seed + tol).astype(np.uint8)

    # --- морфологическая чистка (ядра 3×3, чтобы не «съесть» тонкую реку) ---
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    if morph_open > 0:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=morph_open)
    if morph_close > 0:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=morph_close)

    # --- оставляем самую большую связную область (опционально) ---
    if keep_largest:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n > 1:
            biggest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
            mask = (labels == biggest).astype(np.uint8)

    return mask.astype(bool)


def boundary_mask(mask):
    """Тонкий контур маски (морфологический градиент): граница − эрозия."""
    m = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grad = cv2.morphologyEx(m, cv2.MORPH_GRADIENT, kernel)
    return grad > 0


try:
    from skimage.morphology import skeletonize
    HAVE_SKIMAGE = True
except Exception:                    # scikit-image не обязателен
    HAVE_SKIMAGE = False


def skeleton_mask(mask):
    """
    Скелет (осевой линии) водной маски — однопиксельно тонкая «линия реки».

    Именно скелет русла даёт наиболее осмысленную фрактальную размерность
    хода реки. Требует scikit-image (pip install scikit-image).
    На больших снимках (несколько Мп) может занимать несколько секунд.
    """
    if not HAVE_SKIMAGE:
        raise RuntimeError("Для режима «Скелет» нужен scikit-image:\n"
                           "    pip install scikit-image")
    return skeletonize(mask)


def boxcount_fractal_dimension(mask, drop_last=True):
    """
    Фрактальная размерность методом подсчёта ячеек (box-counting).

    Алгоритм
    --------
    1. Для размеров ячейки ε = 2^k (от 1 до min(H,W)//2) изображение
       дополняется нулями до кратности ε и разбивается на непересекающиеся
       ячейки ε×ε.
    2. N(ε) = число ячеек, содержащих хотя бы один «объектный» пиксель.
    3. По точкам (log(1/ε), log N(ε)) строится линейная регрессия;
       наклон прямой k = D — искомая фрактальная размерность.

    drop_last : исключить ячейку 1×1 из регрессии — на очень мелком
                масштабе сказывается дискретность пикселей и оценка шумит.

    Возвращает словарь:
        D        — фрактальная размерность (наклон прямой),
        dD       — стандартная ошибка наклона,
        r2       — коэффициент детерминации R² (качество прямолинейности),
        table    — список (ε, N),
        x, y     — точки для графика (log10(1/ε), log10 N).
    """
    m = mask.astype(np.uint8)
    H, W = m.shape
    if m.sum() == 0:
        raise ValueError("Маска пуста — нечего считать. Кликните точку на реке "
                         "и/или увеличьте допуск.")

    max_pow = int(math.floor(math.log2(min(H, W) // 2)))
    sizes = [2 ** k for k in range(0, max_pow + 1)]

    table = []
    for eps in sizes:
        pad_h = (-H) % eps
        pad_w = (-W) % eps
        mp = np.pad(m, ((0, pad_h), (0, pad_w)), mode="constant")
        blocks = mp.reshape(mp.shape[0] // eps, eps, mp.shape[1] // eps, eps)
        occupied = blocks.any(axis=(1, 3))
        n = int(occupied.sum())
        if n > 0:
            table.append((eps, n))

    fit_rows = [(e, n) for e, n in table if n >= 2]
    if drop_last:
        fit_rows = [(e, n) for e, n in fit_rows if e > 1]
    if len(fit_rows) < 3:
        fit_rows = [(e, n) for e, n in table if n >= 2]  # откат: чего есть
    if len(fit_rows) < 2:
        raise ValueError("Слишком мало точек для регрессии — объект слишком мал.")

    x = np.array([math.log10(1.0 / e) for e, _ in fit_rows])
    y = np.array([math.log10(n) for _, n in fit_rows])

    # Линейная регрессия y = D·x + b и её статистика
    x_mean, y_mean = x.mean(), y.mean()
    sxx = float(((x - x_mean) ** 2).sum())
    sxy = float(((x - x_mean) * (y - y_mean)).sum())
    slope = sxy / sxx                       # это и есть D
    intercept = y_mean - slope * x_mean

    resid = y - (slope * x + intercept)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    dof = max(len(x) - 2, 1)
    slope_std = math.sqrt((ss_res / dof) / sxx) if sxx > 0 else 0.0

    return {
        "D": float(slope),
        "dD": float(slope_std),
        "r2": float(r2),
        "intercept": float(intercept),
        "table": table,
        "fit_rows": fit_rows,
        "x": x,
        "y": y,
    }


# =====================================================================
# КАНТОРОВСКИЙ МЕТОД ИЗМЕРЕНИЯ ФРАКТАЛЬНОЙ РАЗМЕРНОСТИ (основной метод)
# =====================================================================

def cantor_squares_dimension(mask, max_divs=60):
    """
    Фрактальная размерность методом Кантора (квадраты).

    Изображение покрывается сеткой из квадратов, считается число
    пересечений линии реки с клетками сетки:

      «Изображение покрывается сеткой, состоящей из квадратов,
       с площадью ε² каждый. Подсчитывается число пересечений N(ε)
       линии на изображении с клетками сетки. Шаги повторяются,
       увеличивая число делений сетки на одну. Строится график
       зависимости N(ε) в билогарифмических координатах. Методом
       наименьших квадратов оценивается наклон h; связь
       размерности блуждания с фрактальной размерностью:
       h = 2(D − 1)».

    Алгоритм
    --------
    1. Квадратная сетка n×n, n = 2, 3, 4, … (число делений увеличивается
       на 1 за шаг, а не умножается на 2, как в box-counting).
       Сторона ячейки ε = side / n, side = max(H, W), сетка от левого
       верхнего угла.
    2. N(ε) — число клеток сетки, по которым проходит линия реки
       (хотя бы один объектный пиксель).
    3. По точкам (log10(1/ε), log10 N(ε)) строится прямая (МНК),
       её наклон h. Фрактальная размерность:  D = 1 + h/2.

    Контрольный пример: для дельты Волги в указанной статье
    получено h ≈ 1.26 и D ≈ 1.63 (клеточный метод дал 1.61) —
    та же схема измерения воспроизводится этой функцией.

    ВАЖНО (честно о границах применимости): метод откалиброван
    на РАЗВЕТВЛЁННЫХ структурах (дельты, пойменные сети). Для
    неразветвлённого одиночного русла (гладкая кривая, кривая Коха)
    наклон любого мелкоячеистого покрытия → 1, поэтому D ≈ 1.5
    вместо ожидаемого ≈ 1. Для одиночных русел используйте
    клеточный метод (boxcount_fractal_dimension) — он сохранён в коде.

    Возвращает словарь: D, h, dh, dD, r2, table [(n, ε_px, N)],
    x, y, intercept, fit_rows, n_divs_used.
    """
    m = mask.astype(np.uint8)
    H, W = m.shape
    if m.sum() == 0:
        raise ValueError("Маска пуста — нечего считать. Кликните точку на реке "
                         "и/или увеличьте допуск.")

    side = max(H, W)
    max_divs = int(min(max_divs, max(2, side // 2)))

    ys, xs = np.nonzero(m)
    table = []
    for n in range(1, max_divs + 1):
        ci = (ys.astype(np.int64) * n) // side
        cj = (xs.astype(np.int64) * n) // side
        occupied = int(np.unique(ci * n + cj).size)
        table.append((n, side / n, occupied))

    fit_rows = [(n, eps, cnt) for n, eps, cnt in table if cnt >= 2]
    if len(fit_rows) < 3:
        raise ValueError("Слишком мало точек для регрессии — объект слишком мал "
                         "или плохо выделен.")

    x = np.array([math.log10(1.0 / eps) for _n, eps, _c in fit_rows])
    y = np.array([math.log10(cnt) for _n, _eps, cnt in fit_rows])

    x_mean, y_mean = x.mean(), y.mean()
    sxx = float(((x - x_mean) ** 2).sum())
    sxy = float(((x - x_mean) * (y - y_mean)).sum())
    h = sxy / sxx                                     # наклон = размерность блуждания
    intercept = y_mean - h * x_mean

    D = 1.0 + h / 2.0                                 # D = 1 + h/2  ⇔  h = 2(D − 1)

    resid = y - (h * x + intercept)
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    dof = max(len(x) - 2, 1)
    dh = math.sqrt((ss_res / dof) / sxx) if sxx > 0 else 0.0
    dD = dh / 2.0

    return {
        "D": float(D),
        "h": float(h),
        "dh": float(dh),
        "dD": float(dD),
        "r2": float(r2),
        "intercept": float(intercept),
        "table": table,
        "fit_rows": fit_rows,
        "x": x,
        "y": y,
        "method": "cantor_squares",
        "n_divs_used": max_divs,
    }


# =====================================================================
# СТАТИСТИЧЕСКИЕ ХАРАКТЕРИСТИКИ СТОКА ПО ФРАКТАЛЬНОЙ РАЗМЕРНОСТИ
# =====================================================================

#: основные обеспеченности P, % — для кривой и таблицы ординат
MAJOR_P = [0.1, 0.5, 1, 2, 5, 10, 20, 30, 40, 50,
           60, 70, 80, 90, 95, 98, 99, 99.5, 99.9]


def foster_rybkin(p_pct, c_s):
    """Коэффициент Фостера–Рыбкина Φ_P для обеспеченности P, %.

    Приближение через квантиль нормального распределения:
        Φ_P = z_P + (C_s / 6)·(z_P² − 1)
    """
    from statistics import NormalDist
    z = NormalDist().inv_cdf(1.0 - p_pct / 100.0)
    return z + (c_s / 6.0) * (z * z - 1.0)


def stream_stats_from_D(D, dD=0.0):
    """Статистические характеристики стока по фрактальной размерности.

    Для малоизученных и неизученных рек ряд наблюдений отсутствует,
    поэтому Q_ср, C_v и C_s не измеряются, а ОЦЕНИВАЮТСЯ по
    фрактальной размерности D (калибровочная связь):

        C_v  = 2·(D − 1),  ограничено 0,10…0,80
        C_s  = 2·C_v
        Q_ср = 100 м³/с — условная норма (масштабируется при расчёте
               расходов обеспеченности)

    Погрешности переносятся с D линейно: относительная погрешность
    характеристики = dD/(D−1)·100 %, абсолютная = значение·погрешность/100.

    Возвращает dict с характеристиками, погрешностями и коэффициентами
    K_P/Q_P по всем основным обеспеченностям MAJOR_P.
    """
    d_val = float(D)
    q_mean = 100.0
    cv = max(0.10, min(0.80, 2.0 * (d_val - 1.0)))
    cs = 2.0 * cv

    rel = 100.0 * (float(dD) / max(d_val - 1.0, 1e-9))
    rel_cv = rel
    rel_cs = rel * 1.5
    rel_q = rel

    kp_by_p = {p: 1.0 + foster_rybkin(p, cs) * cv for p in MAJOR_P}

    return {
        "Q_mean": q_mean,
        "Cv": cv,
        "Cs": cs,
        "rel_err_Q": rel_q,
        "rel_err_Cv": rel_cv,
        "rel_err_Cs": rel_cs,
        "abs_err_Q": q_mean * rel_q / 100.0,
        "abs_err_Cv": cv * rel_cv / 100.0,
        "abs_err_Cs": cs * rel_cs / 100.0,
        "kp_by_p": kp_by_p,
        "qp_by_p": {p: kp_by_p[p] * q_mean for p in MAJOR_P},
    }


# =====================================================================
# ОБРЕЗКА МАСКИ ПО ТЕЧЕНИЮ (точка расхода = опорная точка)
# =====================================================================

def transform_point(pt, op, shape):
    """
    Пересчёт координат точки при повороте/отражении изображения.

    pt    — (x, y) в пикселях исходного изображения;
    op    — 'rot1' (90° против часовой), 'rot2' (180°), 'rot3' (90° по часовой),
            'fliph' (отразить слева↔направо), 'flipv' (сверху↔снизу);
    shape — (H, W) ИСХОДНОГО (до преобразования) изображения.
    """
    x, y = float(pt[0]), float(pt[1])
    H, W = shape
    if op == "rot1":
        return (y, W - 1 - x)
    if op == "rot2":
        return (W - 1 - x, H - 1 - y)
    if op == "rot3":
        return (H - 1 - y, x)
    if op == "fliph":
        return (W - 1 - x, y)
    if op == "flipv":
        return (x, H - 1 - y)
    raise ValueError(f"Неизвестное преобразование: {op}")


def write_mask_png(path, mask, scale_text="", image_path=None, seed_xy=None):
    """
    Сохраняет маску как PNG: РЕКА — ЧЁРНАЯ, фон — БЕЛЫЙ (маска-подложка).

    В метаданные файла записываются: размер, разрешение (300 dpi),
    масштаб (если пользователь указал, м/пиксель), источник, число
    пикселей воды, точка расхода, дата и программа.
    """
    inv = np.where(mask, 0, 255).astype(np.uint8)          # река → 0 (чёрная)
    h, w = inv.shape
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scale_text = (scale_text or "").strip()
    seed_txt = (f"x={int(seed_xy[0])}, y={int(seed_xy[1])}"
                if seed_xy is not None else "not set")
    water_px = int(mask.sum())
    meta = PngInfo()
    meta.add_text("Title", "River mask")
    meta.add_text("Dimensions", f"{w} x {h} px")
    meta.add_text("Resolution", "300 dpi")
    meta.add_text("Scale", f"{scale_text} m/px" if scale_text else "not set")
    meta.add_text("Source", os.path.basename(image_path) if image_path else "unknown")
    meta.add_text("Water pixels", str(water_px))
    meta.add_text("Water share, pct", f"{100.0 * water_px / mask.size:.2f}")
    meta.add_text("Seed point", seed_txt)
    meta.add_text("Created", stamp)
    meta.add_text("Software", "river_fractal.py - fractal dimension of rivers")
    meta.add_text("Description", "Black = water, white = background")
    Image.fromarray(inv, mode="L").save(path, pnginfo=meta, dpi=(300, 300))
    return water_px
