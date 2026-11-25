# -*- coding: utf-8 -*-
"""
river_fractal.py — Расчёт фрактальной размерности реки по спутниковому снимку.
============================================================================

Что делает программа
--------------------
1. Загружает спутниковый снимок (JPEG / PNG / TIFF / BMP).
2. Позволяет кликнуть мышью точку НА реке — цвет этой точки
   используется как эталон для выделения водной поверхности
   (пороговая сегментация по цвету в пространстве HSV).
   Эта же точка — ТОЧКА РАСХОДА (створ): относительно неё
   считается фрактальная размерность фракции реки ВЫШЕ створа.
3. Выделенная маска реки отображается поверх снимка зелёным.
   ВАЖНО: оставьте выделенной только ту область реки, которая
   ВЫШЕ створа (точка расхода); всё, что ниже по течению, сотрите
   «🧹 Ластиком» — иначе расчёт D будет неверным.
4. Фрактальная размерность считается КАНТОРОВСКИМ МЕТОДОМ
   (квадраты, покрытие изображения сеткой):

   изображение покрывается квадратной сеткой n×n (n = 2, 3, …, 60;
   число делений растёт на 1 за шаг); ε = side/n — сторона ячейки;
   N(ε) — число клеток, по которым идёт линия реки (хотя бы один
   объектный пиксель); точки (log 1/ε, log N) ложатся на прямую;
   наклон h (размерность блуждания); D = 1 + h/2.

   Нет ветвлений (по идее метода) → N = const → h = 0 → D = 1;
   ветвления заполняют плоскость → N ∝ 1/ε² → h = 2 → D = 2.
   На практике метод откалиброван на разветвлённых сетях:
   для разветвлённых дельт получается D ≈ 1,56–1,63.

   «Клеточный» box-counting сохранён в коде для сравнения
   (boxcount_fractal_dimension).

Запуск
------
    python river_fractal.py

Зависимости
-----------
    pip install numpy pillow opencv-python matplotlib reportlab
    (matplotlib нужен только для графика «log–log»; без него
     программа работает, график просто не рисуется.
     reportlab нужен для сохранения PDF-отчёта; шрифт Tinos —
     метрический аналог Times New Roman — лежит в папке fonts/)

    Tkinter входит в стандартную поставку Python для Windows/macOS.
    В Linux: sudo apt install python3-tk

Как пользоваться
----------------
    1. Нажмите «📂 Загрузить снимок» и выберите файл.
    2. Кликните ЛЕВОЙ кнопкой мыши по руслу реки на снимке —
       это точка расхода (створ). Программа подставит цвет под
       курсором как эталон «воды».
    3. При необходимости подвигайте ползунок «Допуск по цвету»
       и нажмите «🌊 Выделить реку». Зелёным будет показано,
       что посчиталось рекой.
    4. (Необязательно) Переверните снимок нужной ориентации кнопками
       «⟲ 90°» / «⟳ 90°» / «180°» / «⇋» / «⇵».
    5. (ВАЖНО) Сотрите «🧹 Ластиком» ВСЁ, что ниже по течению от
       створа: в выделенной области должна остаться только часть
       реки ВЫШЕ створа.
    6. Нажмите «📐 Рассчитать D» — справа появится фрактальная
       размерность (метод Кантора, квадраты), h, R², таблица,
       график log N от log(1/ε).
    7. «📄 Сохранить отчёт (PDF)» сохраняет отчёт: параметры и
       результаты (таблицы), график log N(ε), таблица измерений,
       снимок со створом, отдельная страница с маской, заготовка
       блока статистических характеристик стока (Q_ср, C_v, C_s)
       и альбомная страница-бланк (клетчатка) под кривую
       обеспеченности. Оформление: A4, Times New Roman, поля
       3/1,5/2/2 см, страницы пронумерованы, таблицы и рисунки
       подписаны.

    Если программа захватила лишнее (тени, дороги, крыши) — выберите
    «🧹 Ластик» и стирайте зелёные области; «🖌 Кисть» дорисовывает маску.
    После любой правки маски D нужно пересчитать.

Подсказки в интерфейсе
----------------------
При наведении курсора на любой параметр (способ выделения, допуск,
галочки, выбор объекта расчёта и т.д.) появляется всплывающая
подсказка: что делает параметр, как его менять и как он влияет
на фрактальную размерность.

Замечание про выбор «Объект расчёта»
------------------------------------
* «Скелет (центр русла)» — осевая линия водной маски (нужна
  scikit-image). Наиболее честная оценка фрактальной размерности хода реки.
* «Граница воды (контур)» — морфологический градиент маски; работает
  без scikit-image.
* «Заполненная маска» — ячейки считаются по всей площади воды.
  Для широкой реки даёт завышение к D → 2 (это размерность области,
  а не линии), поэтому используйте осторожно.
"""

import os
import sys
import math
import threading
import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext

try:
    import numpy as np
    from PIL import Image, ImageTk, ImageDraw
    from PIL.PngImagePlugin import PngInfo
    import cv2
except ImportError as exc:  # понятное сообщение вместо traceback
    sys.exit(
        f"Не хватает библиотеки: {exc.name}\n"
        "Установите зависимости:\n"
        "    pip install numpy pillow opencv-python matplotlib"
    )

# --- картографический режим: необязательный модуль ---
try:
    import map_core
    HAVE_MAP = True
except Exception:
    map_core = None
    HAVE_MAP = False

# matplotlib — необязателен: если его нет, работаем без графика
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False


def _ru_axes(ax):
    """Десятичные числа на осях графика — через запятую (русская традиция)."""
    from matplotlib.ticker import FuncFormatter

    def fmt(x, _pos=None):
        s = f"{x:g}"
        return s.replace(".", ",")

    ax.xaxis.set_major_formatter(FuncFormatter(fmt))
    ax.yaxis.set_major_formatter(FuncFormatter(fmt))


# =====================================================================
# ЦВЕТОВАЯ ГАММА (природная палитра: олива, беж, крем, коричневый, бордо)
# =====================================================================
PALETTE = {
    "olive":    "#9CA75A",   # оливковый — кнопки, акценты
    "beige":    "#DACAB0",   # бежевый — поля ввода, чередование строк
    "cream":    "#F3EBE0",   # кремовый — фон панелей
    "brown":    "#8B6431",   # коричневый — заголовки, рамки
    "burgundy": "#733933",   # бордовый — важные предупреждения
    "canvas":   "#EDE4D6",   # фон холста (светлый беж)
    "text":     "#3B3027",   # основной текст
    "olive_d":  "#7E8948",   # олива тёмная (нажатие)
    "olive_l":  "#AEBA6A",   # олива светлая (наведение)
    "field":    "#FBF6EE",   # поля ввода — почти белый с тёплым оттенком
    "hint":     "#7A6A55",   # подсказки, пояснения
    "row":      "#FFFFFF",   # чётные строки таблиц (на белой бумаге)
}


def install_theme(root):
    """Единая природная тема для ttk-виджетов и классических tk."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")          # лучше всего перекрашивается
    except tk.TclError:
        pass
    C = PALETTE
    root.configure(bg=C["cream"])
    style.configure(".", background=C["cream"], foreground=C["text"],
                    fieldbackground=C["field"], bordercolor=C["brown"],
                    lightcolor=C["beige"], darkcolor=C["brown"],
                    troughcolor=C["beige"], selectbackground=C["olive"],
                    selectforeground="#FFFFFF", font=("Segoe UI", 9))
    style.configure("TFrame", background=C["cream"])
    style.configure("TLabel", background=C["cream"], foreground=C["text"])
    style.configure("TLabelFrame", background=C["cream"],
                    bordercolor=C["brown"])
    style.configure("TLabelFrame.Label", background=C["cream"],
                    foreground=C["brown"], font=("Segoe UI", 10, "bold"))
    style.configure("TButton", background=C["olive"], foreground="#FFFFFF",
                    bordercolor=C["olive_d"], padding=(8, 4),
                    font=("Segoe UI", 9, "bold"))
    style.map("TButton",
              background=[("pressed", C["olive_d"]),
                          ("active", "#AEBA6A"),
                          ("disabled", C["beige"])],
              foreground=[("disabled", "#8A8177")])
    style.configure("TCombobox", fieldbackground=C["field"],
                    background=C["beige"], arrowcolor=C["brown"],
                    bordercolor=C["brown"], lightcolor=C["beige"],
                    darkcolor=C["brown"], foreground=C["text"])
    style.map("TCombobox",
              fieldbackground=[("readonly", C["field"]),
                               ("!disabled", C["field"])],
              background=[("active", C["beige"]), ("readonly", C["beige"]),
                          ("!disabled", C["beige"])],
              foreground=[("readonly", C["text"]), ("!disabled", C["text"])],
              arrowcolor=[("!disabled", C["brown"])])
    root.option_add("*TCombobox*Listbox.background", C["field"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["olive"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    style.configure("TCheckbutton", background=C["cream"],
                    foreground=C["text"], indicatorcolor=C["olive"],
                    indicatorbackground=C["field"],
                    upperbordercolor=C["brown"], lowerbordercolor=C["brown"])
    style.map("TCheckbutton",
              background=[("active", C["cream"])],
              indicatorcolor=[("selected", C["olive"]),
                              ("!selected", C["olive"]),
                              ("active", C["olive"])],
              indicatorbackground=[("selected", C["olive"]),
                                   ("!selected", C["field"])])
    style.configure("TRadiobutton", background=C["cream"],
                    foreground=C["text"])
    # спинбокс: и поле, и стрелки — из палитры (по умолчанию они серые)
    style.configure("TSpinbox", fieldbackground=C["field"],
                    background=C["beige"], arrowcolor=C["brown"],
                    bordercolor=C["brown"], lightcolor=C["field"],
                    darkcolor=C["brown"], foreground=C["text"],
                    arrowsize=14, relief="solid", borderwidth=1)
    style.map("TSpinbox",
              fieldbackground=[("!disabled", C["field"]),
                               ("readonly", C["field"]),
                               ("focus", C["field"])],
              lightcolor=[("!disabled", C["field"]), ("focus", C["field"]),
                          ("readonly", C["field"])],
              background=[("active", C["beige"]), ("!disabled", C["beige"]),
                          ("readonly", C["field"]),
                          ("pressed", C["olive_l"])],
              bordercolor=[("focus", C["olive"]), ("!disabled", C["brown"])],
              foreground=[("!disabled", C["text"])],
              arrowcolor=[("active", C["brown"]), ("pressed", C["text"]),
                          ("!disabled", C["brown"])])
    # Entry/Spinbox в «clam» рисуют поле цветом lightcolor — перекрашиваем
    # и его, иначе поле остаётся белым независимо от fieldbackground
    style.configure("TEntry", fieldbackground=C["field"], foreground=C["text"],
                    bordercolor=C["brown"], lightcolor=C["field"],
                    darkcolor=C["brown"], insertcolor=C["brown"],
                    insertwidth=1, relief="solid", borderwidth=1)
    style.map("TEntry",
              fieldbackground=[("!disabled", C["field"]),
                               ("readonly", C["field"])],
              lightcolor=[("!disabled", C["field"]), ("focus", C["field"]),
                          ("readonly", C["field"])],
              background=[("readonly", C["field"])],
              bordercolor=[("focus", C["olive"]), ("!disabled", C["brown"])],
              foreground=[("!disabled", C["text"])])
    style.configure("TNotebook", background=C["cream"],
                    bordercolor=C["brown"])
    style.configure("TNotebook.Tab", background=C["beige"],
                    foreground=C["text"], padding=(10, 4))
    style.map("TNotebook.Tab",
              background=[("selected", C["olive"])],
              foreground=[("selected", "#FFFFFF")])
    for _orient in ("Vertical", "Horizontal"):
        style.configure(_orient + ".TScrollbar",
                        background=C["beige"], troughcolor=C["cream"],
                        arrowcolor=C["brown"], bordercolor=C["brown"],
                        lightcolor=C["beige"], darkcolor=C["brown"])
        style.map(_orient + ".TScrollbar",
                  background=[("active", C["olive_l"]),
                              ("pressed", C["olive_d"]),
                              ("!disabled", C["beige"])])
    style.configure("TScrollbar", background=C["beige"],
                    troughcolor=C["cream"], arrowcolor=C["brown"])
    # ползунки «Допуск по цвету» и «Максимальное число делений сетки» —
    # классический tk.Scale не перекрашивается, поэтому только ttk
    # в clam ползунок рисуется цветом lightcolor, а жёлоб — darkcolor;
    # если оставить их по умолчанию, ползунок становится серым
    style.configure("TScale", background=C["olive"],
                    troughcolor=C["beige"], bordercolor=C["brown"],
                    lightcolor=C["olive"], darkcolor=C["cream"],
                    sliderlength=18, sliderthickness=14, gripcount=0)
    style.map("TScale",
              background=[("active", C["olive_l"]), ("!disabled", C["olive"])],
              lightcolor=[("active", C["olive_l"]), ("!disabled", C["olive"])],
              darkcolor=[("active", C["olive_d"]), ("!disabled", C["cream"])])


# =====================================================================
# ВСПЛЫВАЮЩИЕ ПОДСКАЗКИ (tooltip)
# =====================================================================

class ToolTip:
    """
    Подсказка, появляющаяся при наведении курсора на виджет,
    и исчезающая при уходе курсора или нажатии кнопки.
    Текст подсказки объясняет параметр и его влияние на расчёт.
    """

    def __init__(self, widget, text, delay=450, wraplength=460):
        self.widget = widget
        self.text = text
        self.delay = delay            # мс до появления подсказки
        self.wraplength = wraplength  # перенос строк, px
        self._after_id = None
        self._tip = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        # прокрутка колесом и нажатие Esc закрывают подсказку,
        # чтобы она не висела поверх интерфейса
        widget.bind("<MouseWheel>", self._hide, add="+")
        widget.bind("<Button-4>", self._hide, add="+")
        widget.bind("<Button-5>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip is not None:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)          # без рамки окна
        self._tip.wm_attributes("-topmost", True)
        # по ширине: justify=LEFT + anchor="nw" + wraplength даёт ровный
        # левый край и аккуратный перенос. Ширину метки в СИМВОЛАХ
        # (configure(width=...)) задавать нельзя: она считается в знаках
        # моноширинного шрифта и обрезает текст — отсюда «не видно полностью».
        label = tk.Label(self._tip, text=self.text, justify=tk.LEFT,
                         anchor="nw",
                         wraplength=self.wraplength,
                         background=PALETTE["cream"], foreground=PALETTE["text"],
                         relief=tk.SOLID, borderwidth=1,
                         font=("Segoe UI", 10), padx=12, pady=9)
        label.pack()

        # --- позиционирование с учётом краёв экрана ---
        self._tip.update_idletasks()
        tw = self._tip.winfo_reqwidth()
        th = self._tip.winfo_reqheight()
        sw = self._tip.winfo_screenwidth()
        sh = self._tip.winfo_screenheight()

        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        if x + tw > sw - 8:                  # не влезает справа
            x = max(8, sw - tw - 8)
        if y + th > sh - 8:                  # не влезает снизу — над виджетом
            y = max(8, self.widget.winfo_rooty() - th - 8)
        self._tip.wm_geometry(f"+{int(x)}+{int(y)}")

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def add_tooltip(widget, text):
    """Короткая обёртка: add_tooltip(кнопка, 'Текст подсказки…')."""
    ToolTip(widget, text)


# =====================================================================
# ЯДРО (чистые функции, без GUI) — их можно импортировать и тестировать
# =====================================================================

def load_image_as_rgb_array(path):
    """
    Читает изображение и возвращает массив RGB uint8 (H, W, 3).

    Спутниковые снимки часто бывают 16-битными TIFF (mode 'I;16', 'F').
    Их нельзя просто конвертнуть в RGB — значения «обрежутся» и всё
    станет чёрным. Поэтому не-uint8 данные нормализуем по 1–99 перцентилю
    в диапазон 0–255.
    """
    img = Image.open(path)
    arr = np.asarray(img)

    if arr.dtype != np.uint8:
        a = arr.astype(np.float32)
        if a.ndim == 3:  # мультиканальный 16-битный снимок — нормализуем поканально
            out = np.empty_like(a)
            for c in range(a.shape[2]):
                lo, hi = np.nanpercentile(a[..., c], [1, 99])
                out[..., c] = np.clip((a[..., c] - lo) / max(hi - lo, 1e-6), 0, 1) * 255
            arr = out
        else:
            lo, hi = np.nanpercentile(a, [1, 99])
            arr = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255
        arr = arr.astype(np.uint8)

    if arr.ndim == 2:                      # градации серого → 3 канала
        rgb = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 4:                # RGBA → отбрасываем альфу
        rgb = arr[..., :3]
    elif arr.shape[2] >= 3:                # берём первые 3 канала (RGB)
        rgb = arr[..., :3]
    else:
        rgb = np.stack([arr[..., 0]] * 3, axis=-1)
    return rgb


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


# =====================================================================
# ГРАФИЧЕСКИЙ ИНТЕРФЕЙС (tkinter)
# =====================================================================

_INITIAL_REPORT_TEXT = (
    "Здесь появятся результаты расчёта.\n\n"
    "Порядок действий:\n"
    "  1) Загрузите спутниковый снимок реки\n"
    "  2) Отметьте ЛКМ точкой на реке створ, данные по которому\n"
    "     Вы хотите получить\n"
    "  3) Нажмите «🌊 Выделить реку» и при необходимости, используя\n"
    "     инструменты, внесите правки по выделенной области\n"
    "  4) ВАЖНО: сотрите «🧹 Ластиком» ВСЁ, что ниже по течению\n"
    "     от створа. В выделенной области должна остаться\n"
    "     только часть реки ВЫШЕ створа\n"
    "  5) Нажмите «📐 Рассчитать D» и подождите расчётов\n"
    "  6) Нажмите «📄 Сохранить отчёт (PDF)»\n"
)

CANVAS_W, CANVAS_H = 860, 620      # размер области просмотра, пикселей
OVERLAY_COLOR = (40, 220, 80)      # зелёный цвет маски поверх снимка
OVERLAY_ALPHA = 0.45               # прозрачность наложения маски


class RiverFractalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Фрактальная размерность реки по спутниковому снимку")
        self.geometry("1420x760")
        self.minsize(1180, 640)
        install_theme(self)             # природная цветовая гамма

        # --- состояние ---
        self.image_path = None          # путь к загруженному файлу
        self.rgb = None                 # исходный снимок, np.uint8 RGB
        self.scale = 1.0                # масштаб отображения canvas↔оригинал
        self.seed_xy = None             # ТОЧКА РАСХОДА (створ), координаты ОРИГИНАЛА
        self.mask = None                # выделенная маска реки (bool)
        self.mask_touched = False       # True, если маску правили вручную (ластик/кисть)
        self.result = None              # результат расчёта (dict)
        self.photo = None               # текущий PhotoImage для canvas
        self._last_paint = None         # предыдущая позиция штриха (для интерполяции)
        self.zoom = 1.0                 # 1.0 = «вся картинка»; до 12×
        self.view_cx = None             # центр видимой области, px снимка (None = центр)
        self.view_cy = None
        self._view_cache = None         # геометрия вида для перевода координат мыши
        self._pan_state = None          # состояние панорамирования перетаскиванием
        self.minimap = None             # Toplevel «🗺 Карта просмотра» или None
        self._minimap_canvas = None     # холст мини-карты
        self._minimap_photo = None      # миниатюра (защитить от сборки мусора)
        self._minimap_geo = None        # геометрия миниатюры для кликов
        self._undo_stack = []           # снимки маски «до» каждого штриха/точек
        self._redo_stack = []           # отменённые состояния (для «вперёд»)
        self._stroke_snapshot = None    # состояние маски на начало штриха
        self.color_pts = []             # доп. точки-эталоны цвета [(x, y), …]


        # --- состояние карты (вкладка «Карта») ---
        self.map_lon = 41.70
        self.map_lat = 43.50
        self.map_zoom = 11
        self.map_source = "esri"
        self.map_geo = None
        self.map_base_img = None
        self.map_photo = None
        self.map_res = None
        self.map_dim = None
        self.map_outlet = None          # (lat, lon)
        self._map_pan = None
        self._map_loading = False
        self._map_started = False

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._install_tooltips()        # всплывающие подсказки к параметрам
        # отмена/повтор — привычные сочетания клавиш
        self.bind_all("<Control-z>", lambda e: self.undo())
        self.bind_all("<Control-Z>", lambda e: self.undo())
        self.bind_all("<Control-y>", lambda e: self.redo())
        self.bind_all("<Control-Y>", lambda e: self.redo())

    # ------------------------------------------------------------------
    # Построение интерфейса
    # ------------------------------------------------------------------
    def _build_toolbar(self):
        # ---------- строка 1: файл и параметры выделения ----------
        bar = ttk.Frame(self, padding=(6, 6, 6, 0))
        bar.pack(side=tk.TOP, fill=tk.X)

        self.btn_load = ttk.Button(bar, text="📂 Загрузить снимок",
                                   command=self.load_image)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_close = ttk.Button(bar, text="🗑 Закрыть снимок",
                                    command=self.close_image)
        self.btn_close.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar, text="Способ выделения:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value="color")
        self.method_box = ttk.Combobox(
            bar, textvariable=self.method_var, state="readonly", width=26,
            values=["По цвету точки (HSV)",
                    "Тёмная вода (яркость)",
                    "Комбинация признаков"])
        self.method_box.current(0)
        self.method_box.pack(side=tk.LEFT, padx=(4, 12))
        self._method_values = ["color", "dark", "hybrid"]
        self.method_box.bind("<<ComboboxSelected>>",
                             lambda e: setattr(self, "_method_index",
                                               self.method_box.current()))
        self._method_index = 0

        ttk.Label(bar, text="Допуск по цвету:").pack(side=tk.LEFT)
        self.tol_var = tk.IntVar(value=60)
        self.tol_scale = ttk.Scale(bar, from_=10, to=160, orient=tk.HORIZONTAL,
                                   variable=self.tol_var, length=170,
                                   command=lambda v: self._set_status(
                                       f"Допуск = {int(float(v))}. Нажмите «🌊 Выделить реку»."))
        self.tol_scale.pack(side=tk.LEFT, padx=(4, 2))
        # ttk.Scale не рисует число — показываем его в отдельном поле
        self.tol_entry = ttk.Entry(bar, textvariable=self.tol_var, width=4,
                                   justify="center")
        self.tol_entry.pack(side=tk.LEFT, padx=(0, 12))

        self.largest_var = tk.BooleanVar(value=True)
        self.largest_chk = ttk.Checkbutton(bar, text="Только крупнейшая область воды",
                                           variable=self.largest_var)
        self.largest_chk.pack(side=tk.LEFT)

        # ---------- строка 2: инструменты мыши и объект расчёта ----------
        bar2 = ttk.Frame(self, padding=(6, 2, 6, 6))
        bar2.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(bar2, text="Инструмент:").pack(side=tk.LEFT)
        self.tool_var = tk.StringVar(value="point")
        self.tool_box = ttk.Combobox(
            bar2, textvariable=self.tool_var, state="readonly", width=42,
            values=["🖱 Точка расхода (створ) — выбрать реку",
                    "➕ Доп. точка цвета — добавить оттенок воды",
                    "✋ Двигать — панорамирование снимка",
                    "🧹 Ластик — стереть лишнее из выделения",
                    "🖌 Кисть — дорисовать выделение вручную"])
        self.tool_box.current(0)
        self.tool_box.pack(side=tk.LEFT, padx=(4, 12))
        self._tool_values = ["point", "colorpoint", "pan", "eraser", "brush"]
        self._tool_index = 0

        def _on_tool_change(_event=None):
            self._tool_index = self.tool_box.current()
            self._last_paint = None
            self._update_cursor()
            hints = {
                "point": "Кликните по руслу реки — это точка расхода (створ): относительно неё считается D.",
                "colorpoint": "Кликните по участку воды ДРУГОГО оттенка — его цвет станет дополнительным эталоном для выделения.",
                "pan": "Зажмите левую кнопку и ведите мышью, чтобы передвинуть снимок (или вращайте колесо мыши для масштаба).",
                "eraser": "Ведите мышью с зажатой левой кнопкой по зелёным областям. Сотрите ВСЁ ниже по течению от створа — в расчёте должна остаться только область ВЫШЕ створа.",
                "brush": "Ведите мышью с зажатой левой кнопкой, дорисовывая воду в маску.",
            }
            self._set_status(hints[self._tool_values[self._tool_index]])

        self.tool_box.bind("<<ComboboxSelected>>", _on_tool_change)

        ttk.Label(bar2, text="Размер ластика/кисти:").pack(side=tk.LEFT)
        self.brush_var = tk.IntVar(value=18)
        self.brush_scale = ttk.Scale(bar2, from_=2, to=80, orient=tk.HORIZONTAL,
                                     variable=self.brush_var, length=150)
        self.brush_scale.pack(side=tk.LEFT, padx=(4, 2))
        self.brush_entry = ttk.Entry(bar2, textvariable=self.brush_var,
                                     width=4, justify="center")
        self.brush_entry.pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(bar2, text="Правка:").pack(side=tk.LEFT)
        self.btn_undo = ttk.Button(bar2, text="↶ Назад", width=9,
                                   command=self.undo)
        self.btn_undo.pack(side=tk.LEFT, padx=(4, 2))
        self.btn_redo = ttk.Button(bar2, text="↷ Вперёд", width=9,
                                   command=self.redo)
        self.btn_redo.pack(side=tk.LEFT, padx=(0, 12))
        self.btn_undo.state(["disabled"])
        self.btn_redo.state(["disabled"])

        ttk.Label(bar2, text="Объект расчёта:").pack(side=tk.LEFT)
        self.object_var = tk.StringVar(value=("Скелет (центр русла)" if HAVE_SKIMAGE
                                              else "Граница воды (контур)"))
        self.object_box = ttk.Combobox(bar2, textvariable=self.object_var,
                                       state="readonly", width=26,
                                       values=["Скелет (центр русла)",
                                               "Граница воды (контур)",
                                               "Заполненная маска"])
        self.object_box.current(0 if HAVE_SKIMAGE else 1)
        self.object_box.pack(side=tk.LEFT, padx=(4, 0))
        self.object_box.bind("<<ComboboxSelected>>",
                             lambda e: setattr(self, "_object_index",
                                               self.object_box.current()))
        self._object_values = ["skeleton", "boundary", "mask"]
        self._object_index = 0 if HAVE_SKIMAGE else 1

        # ---------- строка 3: ориентация снимка и обрезка по течению ----------
        bar3 = ttk.Frame(self, padding=(6, 0, 6, 6))
        bar3.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(bar3, text="Ориентация:").pack(side=tk.LEFT)
        self.btn_rot_ccw = ttk.Button(bar3, text="⟲ 90°", width=7,
                                      command=lambda: self.rotate_view("rot1"))
        self.btn_rot_ccw.pack(side=tk.LEFT, padx=(6, 2))
        self.btn_rot_cw = ttk.Button(bar3, text="⟳ 90°", width=7,
                                     command=lambda: self.rotate_view("rot3"))
        self.btn_rot_cw.pack(side=tk.LEFT, padx=2)
        self.btn_rot_180 = ttk.Button(bar3, text="180°", width=6,
                                      command=lambda: self.rotate_view("rot2"))
        self.btn_rot_180.pack(side=tk.LEFT, padx=2)
        self.btn_flip_h = ttk.Button(bar3, text="⇋ отразить", width=12,
                                     command=lambda: self.rotate_view("fliph"))
        self.btn_flip_h.pack(side=tk.LEFT, padx=(10, 2))
        self.btn_flip_v = ttk.Button(bar3, text="⇵ отразить", width=12,
                                     command=lambda: self.rotate_view("flipv"))
        self.btn_flip_v.pack(side=tk.LEFT, padx=2)

        ttk.Separator(bar3, orient=tk.VERTICAL).pack(side=tk.LEFT,
                                                     fill=tk.Y, padx=12)
        ttk.Label(bar3, text="Максимальное число делений сетки:").pack(side=tk.LEFT)
        self.cantor_cells_var = tk.IntVar(value=60)
        self.cantor_scale = ttk.Scale(bar3, from_=10, to=120, orient=tk.HORIZONTAL,
                                      variable=self.cantor_cells_var, length=110)
        self.cantor_scale.pack(side=tk.LEFT, padx=(4, 2))
        self.cantor_entry = ttk.Entry(bar3, textvariable=self.cantor_cells_var,
                                      width=4, justify="center")
        self.cantor_entry.pack(side=tk.LEFT, padx=(0, 0))

        ttk.Separator(bar3, orient=tk.VERTICAL).pack(side=tk.LEFT,
                                                     fill=tk.Y, padx=12)
        self.btn_zoom_out = ttk.Button(bar3, text="🔍−", width=4,
                                       command=lambda: self._zoom_at(1 / 1.25))
        self.btn_zoom_out.pack(side=tk.LEFT)
        self.btn_zoom_in = ttk.Button(bar3, text="🔍+", width=4,
                                      command=lambda: self._zoom_at(1.25))
        self.btn_zoom_in.pack(side=tk.LEFT, padx=(2, 6))
        self.btn_zoom_fit = ttk.Button(bar3, text="⛶ Всё", width=7,
                                       command=self.reset_zoom)
        self.btn_zoom_fit.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_minimap = ttk.Button(bar3, text="🗺 Карта", width=9,
                                      command=self.toggle_minimap)
        self.btn_minimap.pack(side=tk.LEFT)

    def _build_body(self):
        # Верхний уровень — вкладки: «Фотоснимок» и «Карта»
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True,
                           padx=4, pady=(2, 4))

        self.tab_photo = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_photo, text="  📷 Фотоснимок  ")

        self.tab_map = ttk.Frame(self.notebook)
        if HAVE_MAP:
            self.notebook.add(self.tab_map, text="  🗺 Карта и водосбор  ")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._build_photo_tab(self.tab_photo)
        if HAVE_MAP:
            self._build_map_tab(self.tab_map)

    # ------------------------------------------------------------------
    # Вкладка 1 — фотоснимок (прежняя работа)
    # ------------------------------------------------------------------
    def _build_photo_tab(self, parent):
        body = ttk.Frame(parent, padding=(6, 6, 6, 6))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Левая часть — снимок на холсте
        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(left, width=CANVAS_W, height=CANVAS_H,
                                bg=PALETTE["canvas"], highlightthickness=2,
                                highlightbackground=PALETTE["brown"],
                                cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-2>", self._pan_middle_press)
        self.canvas.bind("<B2-Motion>", self._pan_middle_drag)
        self.canvas.bind("<ButtonRelease-2>", self.on_canvas_release)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)   # Windows / macOS
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)     # Linux (колесо вверх)
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)     # Linux (колесо вниз)
        self._draw_placeholder("Загрузите спутниковый снимок\n«📂 Загрузить снимок»,\nкликните по руслу реки (створ),\n«🌊 Выделить реку»,\nсотрите «🧹 Ластиком» всё ниже створа")

        btns = ttk.Frame(left, padding=(0, 6, 0, 0))
        btns.pack(side=tk.TOP, fill=tk.X)
        self.btn_segment = ttk.Button(btns, text="🌊 Выделить реку",
                                      command=self.run_segmentation)
        self.btn_segment.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_calc = ttk.Button(btns, text="📐 Рассчитать D",
                                   command=self.run_calculation)
        self.btn_calc.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(btns, text="Вид:").pack(side=tk.LEFT)
        self.view_var = tk.StringVar(value="Снимок + маска")
        self.view_box = ttk.Combobox(btns, textvariable=self.view_var,
                                     state="readonly", width=16,
                                     values=["Снимок + маска", "Только снимок",
                                             "Только маска"])
        self.view_box.current(0)
        self.view_box.pack(side=tk.LEFT, padx=(4, 8))
        self.view_box.bind("<<ComboboxSelected>>",
                           lambda e: self.refresh_canvas())
        self.btn_save_mask = ttk.Button(btns, text="💾 Сохранить маску (PNG)",
                                        command=self.save_mask)
        self.btn_save_mask.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_save_report = ttk.Button(btns, text="📄 Сохранить отчёт (PDF)",
                                          command=self.save_report)
        self.btn_save_report.pack(side=tk.LEFT)

        ttk.Label(left,
                  text="Важно: оставьте выделенной только ту часть реки, "
                       "которая ВЫШЕ створа (точка 1).\nВсё ниже по течению "
                       "от створа сотрите «🧹 Ластиком» — иначе расчёт D "
                       "будет неверным.",
                  foreground=PALETTE["burgundy"], justify=tk.LEFT).pack(anchor="w",
                                                             pady=(2, 0))

        # Правая часть — результаты
        right = ttk.Frame(body, width=470)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=(10, 0))
        right.pack_propagate(False)

        ttk.Label(right, text="Результаты",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")

        # Характеристики стока пользователь не вводит: Qср, C_v и C_s
        # оцениваются по фрактальной размерности D (калибровочная связь),
        # поэтому полей ввода в интерфейсе нет.

        scale_row = ttk.Frame(right)
        scale_row.pack(fill=tk.X, pady=(2, 2))
        ttk.Label(scale_row, text="Масштаб, м/пиксель:").pack(side=tk.LEFT)
        self.scale_var = tk.StringVar(value="")
        self.scale_entry = ttk.Entry(scale_row, textvariable=self.scale_var,
                                     width=10)
        self.scale_entry.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Label(scale_row, text="(попадёт в метаданные PNG маски)",
                  foreground=PALETTE["hint"]).pack(side=tk.LEFT)

        self.report = scrolledtext.ScrolledText(
            right, height=16, wrap=tk.WORD, font=("Consolas", 10),
            bg=PALETTE["field"], fg=PALETTE["text"], relief=tk.SOLID, bd=1,
            insertbackground=PALETTE["brown"],
            selectbackground=PALETTE["olive"], selectforeground="#FFFFFF")
        self.report.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.report.insert("1.0", _INITIAL_REPORT_TEXT)
        self.report.configure(state=tk.DISABLED)

        # Область графика log–log (если есть matplotlib)
        self.plot_frame = ttk.LabelFrame(right, text=" График log N(ε) — метод Кантора (квадраты) ")
        self.plot_frame.pack(fill=tk.BOTH, expand=True)
        if HAVE_MPL:
            self.figure = Figure(figsize=(4.6, 3.4), dpi=100,
                                 facecolor=PALETTE["cream"])
            self.ax = self.figure.add_subplot(111)
            self.ax.set_xlabel("log₁₀ (1/ε), ε — пиксели")
            self.ax.set_ylabel("log₁₀ N(ε)")
            self.ax.grid(True, ls=":", alpha=0.6)
            _ru_axes(self.ax)
            self.mpl_canvas = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
            self.mpl_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        else:
            ttk.Label(self.plot_frame,
                      text="matplotlib не установлен —\nграфик недоступен, всё остальное работает.\n"
                           "pip install matplotlib",
                      justify=tk.CENTER).pack(expand=True)

    # ------------------------------------------------------------------
    # Вкладка 2 — КАРТА И ВОДОСБОР (встроена в основное окно)
    # ------------------------------------------------------------------
    def _build_map_tab(self, parent):
        # ---- верхняя строка карты ----
        top = ttk.Frame(parent, padding=(6, 6, 6, 2))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Слой:").pack(side=tk.LEFT)
        self.map_src_var = tk.StringVar(value="Esri (спутник)")
        self.map_src_box = ttk.Combobox(
            top, textvariable=self.map_src_var, state="readonly", width=20,
            values=[v["name"] for v in map_core.SOURCES.values()])
        self.map_src_box.current(0)
        self.map_src_box.pack(side=tk.LEFT, padx=(4, 10))
        self.map_src_box.bind("<<ComboboxSelected>>", self._on_map_source)

        self.map_relief_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Рельеф", variable=self.map_relief_var,
                        command=self.map_reload).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(top, text="⌂", width=3,
                   command=self.map_reset).pack(side=tk.LEFT, padx=(0, 8))
        self.btn_map_catch = ttk.Button(top, text="🌊 Построить водосбор",
                                        command=self.map_build_catchment)
        self.btn_map_catch.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_map_dim = ttk.Button(top, text="📐 Рассчитать D",
                                      command=self.map_calc_dimension)
        self.btn_map_dim.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_map_pdf = ttk.Button(top, text="💾 Отчёт PDF",
                                      command=self.map_save_pdf)
        self.btn_map_pdf.pack(side=tk.LEFT)

        self.map_zoom_lbl = tk.Label(top, text="", bg=PALETTE["cream"],
                                     fg=PALETTE["hint"], font=("Segoe UI", 9))
        self.map_zoom_lbl.pack(side=tk.RIGHT)

        # ---- тело вкладки: карта + результаты ----
        body = ttk.Frame(parent, padding=(6, 0, 6, 6))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.map_canvas = tk.Canvas(left, bg=PALETTE["canvas"],
                                    highlightthickness=2,
                                    highlightbackground=PALETTE["brown"],
                                    cursor="crosshair")
        self.map_canvas.pack(fill=tk.BOTH, expand=True)
        self.map_canvas.bind("<Button-1>", self._map_on_press)
        self.map_canvas.bind("<B1-Motion>", self._map_on_drag)
        self.map_canvas.bind("<ButtonRelease-1>", self._map_on_release)
        self.map_canvas.bind("<Button-2>", self._map_on_mb)
        self.map_canvas.bind("<B2-Motion>", self._map_on_drag)
        self.map_canvas.bind("<ButtonRelease-2>", self._map_on_release)
        self.map_canvas.bind("<MouseWheel>", self._map_on_wheel)
        self.map_canvas.bind("<Button-4>", self._map_on_wheel)
        self.map_canvas.bind("<Button-5>", self._map_on_wheel)

        self.map_credit = tk.Label(left, text="", bg=PALETTE["cream"],
                                   fg=PALETTE["hint"], font=("Segoe UI", 8),
                                   anchor="w")
        self.map_credit.pack(fill=tk.X, pady=(2, 0))

        # ---- правая панель с результатами карты ----
        right = ttk.Frame(body, width=440)
        right.pack(side=tk.LEFT, fill=tk.BOTH, padx=(10, 0))
        right.pack_propagate(False)

        ttk.Label(right, text="Результаты по карте",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")

        self.map_report = scrolledtext.ScrolledText(
            right, height=24, wrap=tk.WORD, font=("Consolas", 10),
            bg=PALETTE["field"], fg=PALETTE["text"], relief=tk.SOLID, bd=1,
            insertbackground=PALETTE["brown"],
            selectbackground=PALETTE["olive"], selectforeground="#FFFFFF")
        self.map_report.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.map_report.insert("1.0", self._MAP_INITIAL_TEXT)
        self.map_report.configure(state=tk.DISABLED)

    # ---------- переключение вкладок ----------
    def _on_tab_change(self, _e=None):
        try:
            idx = self.notebook.index(self.notebook.select())
        except Exception:
            return
        if idx == 1 and HAVE_MAP and not self._map_started:
            self._map_started = True
            map_core.set_cache_dir(
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "tile_cache"))
            self.after(200, self.map_reload)

    # ---------- загрузка и отрисовка карты ----------
    def map_reload(self):
        if not HAVE_MAP or self._map_loading:
            return
        self._map_loading = True
        w = max(300, self.map_canvas.winfo_width())
        h = max(240, self.map_canvas.winfo_height())
        if w < 310:
            w, h = 860, 560

        def work():
            try:
                img, geo = map_core.render_view(
                    self.map_lon, self.map_lat, self.map_zoom, w, h,
                    source=self.map_source)
                if self.map_relief_var.get():
                    dz = map_core.best_dem_zoom(self.map_zoom, self.map_lat)
                    dem, dgeo = map_core.fetch_dem_for_view(geo, dz, margin=0)
                    if dem is not None:
                        img = map_core._blend_relief(img, dem, dgeo,
                                                     alpha=0.55, view_geo=geo)
                self.after(0, lambda: self._map_show(img, geo))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self._map_fail(m))

        threading.Thread(target=work, daemon=True).start()

    def _map_show(self, img, geo):
        from PIL import ImageTk
        self.map_base_img = img
        self.map_geo = geo
        self.map_photo = ImageTk.PhotoImage(img)
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.map_photo, anchor="nw")

        if self.map_outlet is not None:
            lat, lon = self.map_outlet
            tx, ty = map_core.lonlat_to_tile(lon, lat, geo["z"])
            px = (tx - geo["x0"]) * map_core.TILE
            py = (ty - geo["y0"]) * map_core.TILE
            self._map_draw_outlet(px, py)

        if self.map_res is not None:
            self._map_draw_layers()

        cell = map_core.resolution_m(self.map_lat, self.map_zoom)
        self.map_zoom_lbl.config(
            text=f"z{self.map_zoom} · {cell:.0f} м/пиксель · "
                 f"{self.map_lat:.4f}°, {self.map_lon:.4f}°")
        src = map_core.SOURCES[self.map_source]
        self.map_credit.config(
            text=f"Карта: {src['credit']} · {map_core.TERRAIN_CREDIT}")
        self._map_loading = False
        self._set_status("Карта загружена. Кликните по реке — это створ.")

    def _map_fail(self, msg):
        self._map_loading = False
        self._set_status(f"Карта не загрузилась: {msg}")

    def _map_draw_outlet(self, px, py):
        r = 9
        c = self.map_canvas
        c.create_oval(px-r, py-r, px+r, py+r, outline="#FF3C3C", width=3)
        c.create_line(px-r-6, py, px+r+6, py, fill="#FF3C3C", width=2)
        c.create_line(px, py-r-6, px, py+r+6, fill="#FF3C3C", width=2)
        c.create_text(px+r+8, py-r, text="1", fill="#FF3C3C",
                      font=("Segoe UI", 10, "bold"), anchor="w")

    def _map_draw_layers(self):
        """Водосбор и русло поверх карты на холсте."""
        res, geo = self.map_res, self.map_geo
        if not res or not geo:
            return
        dgeo = res["dgeo"]
        catch, line = res["catchment"], res["main_line"]

        def to_screen(row, col):
            tx = dgeo["x0"] + (col + 0.5) / map_core.TILE
            ty = dgeo["y0"] + (row + 0.5) / map_core.TILE
            lon, lat = map_core.tile_to_lonlat(tx, ty, dgeo["z"])
            vx, vy = map_core.lonlat_to_tile(lon, lat, geo["z"])
            return ((vx - geo["x0"]) * map_core.TILE,
                    (vy - geo["y0"]) * map_core.TILE)

        ys, xs = np.nonzero(catch)
        if ys.size == 0:
            return
        r0, r1, c0, c1 = ys.min(), ys.max(), xs.min(), xs.max()

        px0, py0 = to_screen(r0, c0)
        px1, py1 = to_screen(r0 + 1, c0 + 1)
        cell_px = max(1.0, abs(px1 - px0), abs(py1 - py0))
        step = max(1, int(round(cell_px)))
        for row in range(r0, r1 + 1, step):
            for col in range(c0, c1 + 1, step):
                if not catch[row, col]:
                    continue
                px, py = to_screen(row, col)
                self.map_canvas.create_rectangle(
                    px, py, px + cell_px + 0.6, py + cell_px + 0.6,
                    fill=PALETTE["olive"], outline="", stipple="gray50")

        from scipy.ndimage import binary_erosion
        try:
            edge = catch & ~binary_erosion(catch, iterations=1)
        except Exception:
            edge = catch
        pts = []
        for row, col in zip(*np.nonzero(edge)):
            px, py = to_screen(row, col)
            pts.extend([px, py])
        if len(pts) >= 4:
            self.map_canvas.create_line(*pts, fill=PALETTE["burgundy"], width=2)

        pts = []
        for row, col in zip(*np.nonzero(line)):
            px, py = to_screen(row, col)
            pts.extend([px, py])
        if len(pts) >= 4:
            self.map_canvas.create_line(*pts, fill=PALETTE["burgundy"], width=3)

        if self.map_outlet is not None:
            lat, lon = self.map_outlet
            tx, ty = map_core.lonlat_to_tile(lon, lat, geo["z"])
            self._map_draw_outlet((tx-geo["x0"])*map_core.TILE,
                                  (ty-geo["y0"])*map_core.TILE)

    # ---------- мышь на карте ----------
    def _on_map_source(self, _e=None):
        self.map_source = list(map_core.SOURCES.keys())[self.map_src_box.current()]
        self.map_reload()

    def map_reset(self):
        """Сброс вида карты и всех результатов."""
        self.map_lon, self.map_lat, self.map_zoom = 41.70, 43.50, 11
        self.map_outlet = None
        self.map_res = None
        self.map_dim = None
        self.map_reload()

    def _map_on_wheel(self, event):
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        elif getattr(event, "delta", 0):
            delta = 1 if event.delta > 0 else -1
        if delta == 0 or not self.map_geo:
            return
        old = self.map_geo
        lat, lon = map_core.pixel_to_lonlat(old, event.x, event.y)
        newz = max(3, min(16, self.map_zoom + delta))
        if newz == self.map_zoom:
            return
        self.map_zoom = newz
        tx, ty = map_core.lonlat_to_tile(lon, lat, newz)
        nx = tx - (event.x - old["w"] / 2.0) / map_core.TILE
        ny = ty - (event.y - old["h"] / 2.0) / map_core.TILE
        lon_c, lat_c = map_core.tile_to_lonlat(nx, ny, newz)
        self.map_lon, self.map_lat = lon_c, lat_c
        self.map_reload()

    def _map_on_press(self, event):
        self._map_pan = ("maybe", event.x, event.y, event.x, event.y)

    def _map_on_mb(self, event):
        self._map_pan = ("drag", event.x, event.y, event.x, event.y)

    def _map_on_drag(self, event):
        if self._map_pan is None or not self.map_geo:
            return
        kind, sx, sy, ox, oy = self._map_pan
        if kind == "maybe" and (abs(event.x - sx) > 4 or abs(event.y - sy) > 4):
            kind = "drag"
        self._map_pan = (kind, sx, sy, event.x, event.y)
        if kind != "drag":
            return
        dx, dy = event.x - ox, event.y - oy
        f = 1.0 / map_core.TILE
        g = self.map_geo
        lon, lat = map_core.tile_to_lonlat(
            g["x0"] - dx * f + g["w"] / (2 * map_core.TILE),
            g["y0"] - dy * f + g["h"] / (2 * map_core.TILE),
            self.map_zoom)
        self.map_lon, self.map_lat = lon, lat
        self.map_reload()

    def _map_on_release(self, event):
        state = self._map_pan
        self._map_pan = None
        if not state or state[0] != "maybe" or not self.map_geo:
            return
        lat, lon = map_core.pixel_to_lonlat(self.map_geo, event.x, event.y)
        self.map_outlet = (lat, lon)
        self.map_res = None
        self.map_dim = None
        from PIL import ImageTk
        self.map_photo = ImageTk.PhotoImage(self.map_base_img)
        self.map_canvas.delete("all")
        self.map_canvas.create_image(0, 0, image=self.map_photo, anchor="nw")
        self._map_draw_outlet(event.x, event.y)
        self._set_status(f"Створ: {lat:.5f}°, {lon:.5f}°. "
                         f"Нажмите «🌊 Построить водосбор».")

    # ---------- расчёт по карте ----------
    def map_build_catchment(self):
        if not HAVE_MAP:
            return
        if self.map_outlet is None:
            messagebox.showinfo("Нет створа", "Кликните по реке на карте.")
            return
        if self.map_geo is None:
            messagebox.showinfo("Карта не загружена", "Дождитесь загрузки карты.")
            return
        lat, lon = self.map_outlet
        view_geo = dict(self.map_geo)
        self._set_status("Расчёт водосбора…")

        def work():
            try:
                res = map_core.analyse_map(
                    view_geo, lon, lat,
                    progress=lambda m: self.after(0, lambda m=m: self._set_status(m)))
                self.after(0, lambda: self._map_on_result(res))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: messagebox.showerror("Ошибка", m))

        threading.Thread(target=work, daemon=True).start()

    def _map_on_result(self, res):
        self.map_res = res
        st = res["stats"]
        self.map_reload()
        lines = [
            "ВОДОСБОР ПОСТРОЕН (по ЦМР с карты)",
            "=" * 46,
            f"Створ: {res['outlet_lat']:.5f}°, {res['outlet_lon']:.5f}°",
            f"Клетка рельефа: {st['cell_m']:.1f} м",
            "",
            "МОРФОМЕТРИЯ",
            "-" * 46,
            f"Площадь водосбора:    {st['area_km2']:.2f} км²",
            f"Длина главного русла: {st['channel_km']:.2f} км",
            f"Клеток водосбора:     {st['cells']}",
            f"Клеток сети:          {st['network_cells']}",
            f"Порядок Стралера:     {st['strahler']}",
            "",
            "Дальше: «📐 Рассчитать D».",
        ]
        self.map_report.configure(state=tk.NORMAL)
        self.map_report.delete("1.0", tk.END)
        self.map_report.insert("1.0", "\n".join(lines))
        self.map_report.configure(state=tk.DISABLED)
        self._set_status(f"Водосбор: {st['area_km2']:.2f} км², "
                         f"русло {st['channel_km']:.2f} км.")

    def map_calc_dimension(self):
        if not self.map_res:
            messagebox.showinfo("Нет водосбора",
                                "Сначала нажмите «🌊 Построить водосбор».")
            return
        line = self.map_res["main_line"]
        if int(line.sum()) < 10:
            messagebox.showerror("Русло короткое",
                                 f"В линии {int(line.sum())} клеток — мало для D.")
            return
        try:
            r = cantor_squares_dimension(line, max_divs=60)
        except Exception as exc:
            messagebox.showerror("Ошибка расчёта", str(exc))
            return

        self.map_dim = r
        st = self.map_res["stats"]
        rr = lambda v, n=4: f"{v:.{n}f}".replace(".", ",")
        lines = [
            "ФРАКТАЛЬНАЯ РАЗМЕРНОСТЬ (карта)",
            "=" * 46,
            f"Объект: главное русло, {st['line_cells']} клеток",
            "Метод: Кантор (квадраты)",
            "",
            f"Размерность блуждания h = {rr(r['h'])} ± {rr(r['dh'])}",
            f"Фрактальная размерность D = 1 + h/2 = {rr(r['D'])} ± {rr(r['dD'])}",
            f"R² = {rr(r['r2'], 6)}",
            "",
            "ХАРАКТЕРИСТИКИ СТОКА (по D)",
            "-" * 46,
        ]
        try:
            s = stream_stats_from_D(r["D"], r["dD"])
            lines += [
                f"Cv = 2(D−1) = {rr(s['Cv'], 3)}",
                f"Cs = 2Cv    = {rr(s['Cs'], 3)}",
                f"Q(0,1%)  = {rr(s['qp_by_p'][0.1], 1)} м³/с",
                f"Q(50%)   = {rr(s['qp_by_p'][50], 1)} м³/с",
                f"Q(99,9%) = {rr(s['qp_by_p'][99.9], 1)} м³/с",
            ]
        except Exception:
            pass
        self.map_report.configure(state=tk.NORMAL)
        self.map_report.delete("1.0", tk.END)
        self.map_report.insert("1.0", "\n".join(lines))
        self.map_report.configure(state=tk.DISABLED)
        self._set_status(f"D = {rr(r['D'])} ± {rr(r['dD'])} "
                         f"(R² = {rr(r['r2'], 4)})")

    def map_save_pdf(self):
        if not self.map_dim:
            messagebox.showinfo("Нет расчёта", "Сначала посчитайте D.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт по карте", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            self._map_write_pdf(path)
            self._set_status(f"Отчёт сохранён: {os.path.basename(path)}")
            messagebox.showinfo("Готово", f"Отчёт сохранён:\n{path}")
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{exc}")

    def _map_write_pdf(self, path):
        """PDF-отчёт по расчёту на карте."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.platypus import (SimpleDocTemplate, Paragraph,
                                        Table, TableStyle, Image as RLImage,
                                        Spacer)
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        here = os.path.dirname(os.path.abspath(__file__))
        fdir = os.path.join(here, "fonts")
        for fs in [("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
                   ("Tinos-Regular.ttf", "Tinos-Bold.ttf",
                    "Tinos-Italic.ttf", "Tinos-BoldItalic.ttf")]:
            if all(os.path.exists(os.path.join(fdir, f)) for f in fs):
                try:
                    pdfmetrics.getFont("Times New Roman")
                except Exception:
                    pdfmetrics.registerFont(TTFont("Times New Roman",
                                                   os.path.join(fdir, fs[0])))
                    pdfmetrics.registerFont(TTFont("Times New Roman Bold",
                                                   os.path.join(fdir, fs[1])))
                break

        r = self.map_dim
        st = self.map_res["stats"]
        rr = lambda v, n=4: f"{v:.{n}f}".replace(".", ",")

        title = ParagraphStyle("t", fontName="Times New Roman Bold", fontSize=16,
                               leading=22, alignment=TA_CENTER, spaceAfter=10)
        cap = ParagraphStyle("c", fontName="Times New Roman", fontSize=12,
                             leading=16, alignment=TA_CENTER, spaceAfter=10)
        h2 = ParagraphStyle("h2", fontName="Times New Roman Bold", fontSize=14,
                            leading=20, spaceBefore=10, spaceAfter=8)

        doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=3*cm,
                                rightMargin=1.5*cm, topMargin=2*cm,
                                bottomMargin=2*cm,
                                title="Гидрофрактал — отчёт по карте")
        story = [Paragraph("ОТЧЁТ О ФРАКТАЛЬНОЙ РАЗМЕРНОСТИ РЕКИ<br/>"
                           "ПО ДАННЫМ КАРТЫ И ЦИФРОВОЙ МОДЕЛИ РЕЛЬЕФА", title)]
        story.append(Paragraph(
            f"Створ: {self.map_res['outlet_lat']:.5f}° с. ш., "
            f"{self.map_res['outlet_lon']:.5f}° в. д.", cap))

        def _tbl(rows, widths=(7*cm, 8*cm)):
            t = Table(rows, colWidths=list(widths))
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.94, 0.94, 0.90)),
            ]))
            return t

        story.append(Paragraph("I. Исходные данные", h2))
        story.append(_tbl([
            ["Параметр", "Значение"],
            ["Слой карты", map_core.SOURCES[self.map_source]["name"]],
            ["Источник рельефа", map_core.TERRAIN_CREDIT],
            ["Клетка рельефа", f"{st['cell_m']:.1f} м"],
            ["Координаты створа",
             f"{self.map_res['outlet_lat']:.5f}°, {self.map_res['outlet_lon']:.5f}°"],
        ]))

        story.append(Paragraph("II. Морфометрия водосбора", h2))
        story.append(_tbl([
            ["Характеристика", "Значение"],
            ["Площадь водосбора", f"{rr(st['area_km2'], 2)} км²"],
            ["Длина главного русла", f"{rr(st['channel_km'], 2)} км"],
            ["Клеток водосбора", str(st["cells"])],
            ["Порядок Стралера", str(st["strahler"])],
        ]))

        story.append(Paragraph("III. Фрактальная размерность", h2))
        story.append(_tbl([
            ["Показатель", "Значение"],
            ["Размерность блуждания h", f"{rr(r['h'])} ± {rr(r['dh'])}"],
            ["Фрактальная размерность D", f"{rr(r['D'])} ± {rr(r['dD'])}"],
            ["Коэффициент детерминации R²", rr(r["r2"], 6)],
        ]))

        if self.map_base_img is not None:
            tmp = os.path.join(os.path.dirname(path), "_map_shot.png")
            shot = self.map_base_img.copy()
            shot.thumbnail((1300, 1300), Image.LANCZOS)
            shot.save(tmp)
            wpx = 15 * cm
            story.append(Spacer(1, 10))
            story.append(RLImage(tmp, width=wpx,
                                 height=wpx * shot.height / shot.width))
            story.append(Paragraph(
                "Рисунок 1 — Спутниковый снимок участка", cap))
        doc.build(story)

    _MAP_INITIAL_TEXT = """КАРТА И ВОДОСБОР

1. Перетаскивайте карту мышью,
   колесо — масштаб.
2. Кликните по реке — створ.
3. «🌊 Построить водосбор».

Программа скачает рельеф участка
и сама определит, откуда течёт
вода к створу."""

    def _build_statusbar(self):
        self.status = tk.StringVar(value="Готов. Загрузите снимок.")
        bar = tk.Label(self, textvariable=self.status, relief=tk.SUNKEN,
                       anchor="w", padx=8, pady=3,
                       bg=PALETTE["beige"], fg=PALETTE["text"],
                       bd=1, highlightthickness=0)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _set_status(self, text):
        self.status.set(text)

    # ------------------------------------------------------------------
    # Всплывающие подсказки к параметрам
    # ------------------------------------------------------------------
    def _install_tooltips(self):
        add_tooltip(self.btn_load,
                    "Загружает снимок (JPG, PNG, TIFF…).\n"
                    "16-битные TIFF нормализуются автоматически.\n"
                    "После загрузки кликните по руслу реки инструментом «Точка».")

        add_tooltip(self.btn_close,
                    "Прекращает работу с текущим снимком: снимок, маска,\n"
                    "точки и результаты удаляются с экрана.\n"
                    "Сначала показывается предупреждение — подтверждайте,\n"
                    "только если точно хотите закрыть снимок\n"
                    "(несохранённые результаты будут утеряны).")

        add_tooltip(self.method_box,
                    "Как программа отличает воду от берега.\n"
                    "\n"
                    "• «По цвету точки (HSV)» — пиксель считается водой, если\n"
                    "  его цвет ближе, чем «допуск», к цвету кликнутой точки\n"
                    "  (с учётом тона, насыщенности и яркости).\n"
                    "\n"
                    "• «Тёмная вода (яркость)» — водой считается всё, что\n"
                    "  ТЕМНЕЕ точки клика (канал V) + допуск. Удобно для\n"
                    "  почти серых снимков.\n"
                    "\n"
                    "• «Комбинация признаков» — объединение правил (ИЛИ):\n"
                    "  выделяется больше воды, но выше риск захватить тени.\n"
                    "\n"
                    "Влияние на расчёт: более широкое правило даёт более\n"
                    "широкую реку в маске и мельче детали русла на мелкой ε-сетке.")

        add_tooltip(self.tol_scale,
                    "Порог «похожести на воду» (HSV-расстояние, 10…160).\n"
                    "\n"
                    "• Меньше (20–40) — выделяются только пиксели почти цвета\n"
                    "  точки: маска узкая и чистая, но русло может разорваться.\n"
                    "• Больше (90–130) — русло сплошное и широкое, но\n"
                    "  захватываются тени, тёмные крыши и дороги.\n"
                    "\n"
                    "Для D это важно так: разрывы маски порождают много мелких\n"
                    "компонентов, из-за чего N(ε) на малых ε завышается и\n"
                    "наклон прямой в log–log «плывёт».\n"
                    "\n"
                    "Ориентир: двигать допуск, пока зелёная подсветка не\n"
                    "покроет русло без разрывов и без луж за его пределами;\n"
                    "обычно это 50–80.")

        add_tooltip(self.largest_chk,
                    "Оставляет в маске только самую БОЛЬШУЮ связную область\n"
                    "воды, всё остальное удаляется.\n"
                    "\n"
                    "Зачем: отсекает случайные тёмные пятна (тени леса, крыши),\n"
                    "которые иначе попадут в подсчёт ячеек.\n"
                    "\n"
                    "Влияние на расчёт: без галочки посторонние «островки»\n"
                    "раздувают N(ε) на малых размерах ячеек и завышают D.\n"
                    "Снимите галочку, если нужно считать и основное русло,\n"
                    "и протоки/старицы как единое целое.")

        add_tooltip(self.tool_box,
                    "Что делает левая кнопка мыши на снимке.\n"
                    "\n"
                    "• «Точка расхода (створ)» — отмечает створ (красный\n"
                    "  маркер «1»): цвет под курсором становится эталоном\n"
                    "  воды, а сама точка — опорой для расчёта D.\n"
                    "\n"
                    "• «Доп. точка цвета» — НЕ точка створа! Задаёт\n"
                    "  дополнительный оттенок воды: кликните по участку реки\n"
                    "  другого цвета (мутный приток, тень на воде) — при\n"
                    "  выделении этот цвет тоже будет считаться водой.\n"
                    "  Такие точки помечаются жёлтыми кружками «2», «3», …\n"
                    "  Повторный клик по точке убирает её.\n"
                    "\n"
                    "• «Ластик» — удаляет ошибочно выделенные области (вести\n"
                    "  с зажатой ЛКМ по зелёному; снимок не меняется).\n"
                    "  ИМ ЖЕ убирают всё ниже по течению: в расчёте должна\n"
                    "  остаться только часть реки ВЫШЕ створа.\n"
                    "\n"
                    "• «Кисть» — дорисовывает пропущенные участки воды.\n"
                    "\n"
                    "Любую правку можно отменить кнопкой «↶ Назад» (Ctrl+Z).\n"
                    "После правки нажмите «📐 Рассчитать D» заново.")

        add_tooltip(self.brush_scale,
                    "Радиус ластика/кисти в пикселях ИСХОДНОГО снимка\n"
                    "(не экрана).\n"
                    "\n"
                    "10–20 — для тонкой работы вдоль береговой линии и проток.\n"
                    "40–80 — чтобы быстро счистить большие тёмные пятна.\n"
                    "\n"
                    "На значение D влияет косвенно: радиус определяет,\n"
                    "насколько точно вы повторите береговую линию вручную.")

        add_tooltip(self.object_box,
                    "По какому объекту строится зависимость N(ε).\n"
                    "\n"
                    "• «Скелет (центр русла)» — осевая однопиксельная линия\n"
                    "  реки; самая честная оценка D хода реки (нужна\n"
                    "  библиотека scikit-image).\n"
                    "• «Граница воды (контур)» — тонкий контур маски;\n"
                    "  результат близок к скелету, но D чуть выше из-за двух\n"
                    "  берегов сразу.\n"
                    "• «Заполненная маска» — вся площадь воды; N(ε) ≈ A/ε²,\n"
                    "  поэтому D завышается к 2 и описывает «заполнение\n"
                    "  области», а не извилистость реки.\n"
                    "\n"
                    "Ожидаемое D для рек: скелет ≈ 1,05–1,35.")

        add_tooltip(self.view_box,
                    "Что показывать на холсте.\n"
                    "\n"
                    "• «Снимок + маска» — снимок с полупрозрачной зелёной\n"
                    "  подсветкой выделенной воды;\n"
                    "• «Только снимок» — сам снимок без подсветки;\n"
                    "• «Только маска» — белая река на чёрном фоне (удобно\n"
                    "  проверить, что выделилось ровно русло).\n"
                    "\n"
                    "На маску и на расчёт D выбор вида не влияет.")

        add_tooltip(self.btn_zoom_in,
                    "Увеличить масштаб (×1,25) с привязкой к центру.\n"
                    "Точная привязка — колесом мыши над холстом: точка\n"
                    "под курсором остаётся на месте.\n"
                    "Максимум — 12×.")
        add_tooltip(self.btn_zoom_out,
                    "Уменьшить масштаб (÷1,25).\n"
                    "При 100 % видна вся картинка.")
        add_tooltip(self.btn_zoom_fit,
                    "Вернуться к масштабу «вся картинка» и центру.")
        add_tooltip(self.btn_minimap,
                    "Открыть/закрыть мини-окно «🗺 Карта просмотра»:\n"
                    "вся картинка целиком с красной рамкой текущего вида.\n"
                    "\n"
                    "Клик или перетаскивание по мини-карте — перейти к этому\n"
                    "месту на основном холсте.\n"
                    "Передвигать вид также можно средней кнопкой мыши или\n"
                    "инструментом «✋ Двигать».")
        add_tooltip(self.scale_entry,
                    "Реальный масштаб снимка, м/пиксель (необязательно),\n"
                    "например 0,5. Подставляется в метаданные PNG маски\n"
                    "(поле Scale), куда также записываются размер,\n"
                    "разрешение 300 dpi, источник и дата.\n"
                    "Если оставить пустым — будет «not set».")

        add_tooltip(self.btn_undo,
                    "Отменить последнее действие (Ctrl+Z).\n"
                    "\n"
                    "Отменяется целый штрих ластика или кисти, а также\n"
                    "добавление или удаление дополнительной точки цвета —\n"
                    "не отдельный пиксель, а всё движение мыши целиком.\n"
                    "\n"
                    "Можно отменить до 50 последних действий.")

        add_tooltip(self.btn_redo,
                    "Вернуть отменённое действие (Ctrl+Y).\n"
                    "\n"
                    "Работает, пока вы не начали новое действие: после\n"
                    "нового штриха история «вперёд» очищается.")

        add_tooltip(self.btn_segment,
                    "Пересоздаёт маску воды от точки-эталона с текущими\n"
                    "«Способом выделения», «Допуском» и флажком «Только\n"
                    "крупнейшая область».\n"
                    "Учитываются и дополнительные точки цвета, если они есть.\n"
                    "\n"
                    "Внимание: ручные правки ластиком/кистью при этом теряются.")

        add_tooltip(self.btn_calc,
                    "Метод Кантора (квадраты).\n"
                    "\n"
                    "Изображение покрывается сеткой n×n, n увеличивается на 1\n"
                    "за шаг; ε = side/n. N(ε) — число клеток, по которым идёт\n"
                    "линия реки. Прямая по точкам (log 1/ε, log N), её наклон —\n"
                    "размерность блуждания h. Итог: D = 1 + h/2.\n"
                    "\n"
                    "Считается по «Объект расчёта» (по умолчанию — скелет).\n"
                    "Ориентир для разветвлённых дельт: D ≈ 1,56–1,63.\n"
                    "\n"
                    "Для одиночного неразветвлённого русла метод завышает D\n"
                    "(любое мелкоячеистое покрытие даёт наклон ≈ 1) — там\n"
                    "правильнее клеточный box-counting (в коде сохранён).")

        add_tooltip(self.cantor_scale,
                    "Максимальное число делений сетки n×n по стороне\n"
                    "(по умолчанию 60).\n"
                    "\n"
                    "Точки (log 1/ε, log N(ε)) берутся по всем n от 1 до этого\n"
                    "значения. Больше — длиннее ряд и стабильнее наклон, но\n"
                    "N упирается в число пикселей реки (насыщение), и наклон\n"
                    "слегка занижается на мелких ε.\n"
                    "\n"
                    "40–80 — разумный диапазон.")

        add_tooltip(self.btn_save_mask,
                    "Сохраняет маску отдельным PNG: чёрная река на белом\n"
                    "фоне, разрешение 300 dpi.\n"
                    "\n"
                    "В метаданные PNG записываются размер снимка, масштаб\n"
                    "(если указан), источник и дата — такой файл удобно\n"
                    "открыть в ГИС или приложить к отчёту.")

        add_tooltip(self.btn_save_report,
                    "Сохраняет отчёт в PDF (A4, Times New Roman 14/12/10):\n"
                    "исходные данные, результаты измерения D, полная таблица\n"
                    "измерений, снимок с маской, статистические характеристики\n"
                    "стока, теоретическая кривая обеспеченности и формулы.\n"
                    "\n"
                    "Перед сохранением нужен выполненный расчёт D.")

        add_tooltip(self.btn_rot_ccw,
                    "Повернуть снимок против часовой стрелки на 90°.\n"
                    "Поворот влияет только на отображение и сохранение;\n"
                    "маска и точки поворачиваются вместе со снимком.")

        add_tooltip(self.btn_rot_cw,
                    "Повернуть снимок по часовой стрелке на 90°.")
        add_tooltip(self.btn_rot_180,
                    "Повернуть снимок на 180°.")
        add_tooltip(self.btn_flip_h,
                    "Отразить снимок по горизонтали (зеркально).")
        add_tooltip(self.btn_flip_v,
                    "Отразить снимок по вертикали (зеркально).")

    def _draw_placeholder(self, text):
        self.canvas.delete("all")
        self.canvas.create_text(CANVAS_W // 2, CANVAS_H // 2, text=text,
                                fill=PALETTE["brown"], font=("Segoe UI", 14),
                                justify=tk.CENTER)

    def load_image(self):
        path = filedialog.askopenfilename(
            title="Выберите спутниковый снимок",
            filetypes=[("Изображения", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"),
                       ("Все файлы", "*.*")])
        if not path:
            return
        try:
            self.rgb = load_image_as_rgb_array(path)
        except Exception as exc:
            messagebox.showerror("Ошибка чтения файла", str(exc))
            return

        self.image_path = path
        self.seed_xy = None
        self.mask = None
        self.mask_touched = False
        self.result = None
        self._last_paint = None
        self._reset_view_state()

        h, w = self.rgb.shape[:2]
        self.scale = min(CANVAS_W / w, CANVAS_H / h, 1.0)
        self._set_status(f"Загружено: {os.path.basename(path)}  ({w}×{h} px). "
                         f"Кликните по руслу реки.")
        self.refresh_canvas()

    def close_image(self):
        """Закрывает снимок и сбрасывает всю работу (с подтверждением)."""
        if self.rgb is None:
            self._set_status("Снимок не загружен — закрывать нечего.")
            return
        ok = messagebox.askyesno(
            "Закрыть снимок",
            "Вы уверены, что хотите прекратить работу\n"
            "с данным спутниковым снимком?\n\n"
            "Несохранённые результаты (маска, расчёт D, отчёт)\n"
            "будут удалены.",
            icon=messagebox.WARNING)
        if not ok:
            return
        # мини-карта — закрыть
        if self.minimap is not None:
            try:
                self.minimap.destroy()
            except Exception:
                pass
            self.minimap = None
            self._minimap_photo = None
            self._minimap_geo = None
        if hasattr(self, "view_var"):
            self.view_var.set("Снимок + маска")
        self._reset_view_state()
        # полный сброс состояния
        self.image_path = None
        self.rgb = None
        self.mask = None
        self.seed_xy = None
        self.result = None
        self.photo = None
        self.mask_touched = False
        # холст: приглашение к загрузке нового снимка
        self.canvas.delete("all")
        self._draw_placeholder("Снимок закрыт.\n«📂 Загрузить снимок» — работа с новым снимком")
        # панель результатов — исходная инструкция
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", _INITIAL_REPORT_TEXT)
        self.report.configure(state=tk.DISABLED)
        # график — пустые оси
        if HAVE_MPL:
            self.ax.clear()
            self.ax.set_xlabel(r"$\log_{10}(1/\varepsilon)$")
            self.ax.set_ylabel(r"$\log_{10}N(\varepsilon)$")
            self.ax.grid(True, ls=":", alpha=0.6)
            self.mpl_canvas.draw()
        self._set_status("Работа с снимком прекращена.")

    def _render_scene_image(self, max_side=None, force_overlay=False, view=None):
        """
        Снимок + (необязательно) зелёное наложение маски + маркеры точек.

        view=None          — рендер всего кадра (для PDF / мини-карты);
        view=dict          — только видимая область (зум/панорама), см. _current_view().
        """
        h, w = self.rgb.shape[:2]
        if view is None:
            if max_side is not None:
                sc = min(max_side / w, max_side / h, 1.0)
            else:
                sc = 1.0
            rgb_c, mask_c, origin = self.rgb, self.mask, (0, 0)
        else:
            x0i, y0i, x1i, y1i = view["x0i"], view["y0i"], view["x1i"], view["y1i"]
            rgb_c = self.rgb[y0i:y1i, x0i:x1i]
            mask_c = (self.mask[y0i:y1i, x0i:x1i]
                      if self.mask is not None else None)
            sc = view["sc"]
            origin = (x0i, y0i)

        disp_w = max(1, int(round(rgb_c.shape[1] * sc)))
        disp_h = max(1, int(round(rgb_c.shape[0] * sc)))
        disp = Image.fromarray(rgb_c).resize((disp_w, disp_h), Image.LANCZOS)

        view_mode = (getattr(self, "view_var", None).get()
                     if hasattr(self, "view_var") else "Снимок + маска")
        if force_overlay:
            view_mode = "Снимок + маска"

        if view_mode == "Только маска":
            # маска без снимка: белая река на чёрном фоне
            only = np.zeros_like(rgb_c)
            if mask_c is not None:
                only[mask_c] = (255, 255, 255)
            disp = Image.fromarray(only).resize((disp_w, disp_h), Image.NEAREST)
        elif mask_c is not None and view_mode == "Снимок + маска":
            base = np.asarray(disp).astype(np.float32)
            m = np.asarray(Image.fromarray(mask_c.astype(np.uint8) * 255)
                           .resize((disp_w, disp_h), Image.NEAREST)) > 0
            overlay = np.zeros_like(base)
            overlay[..., 0], overlay[..., 1], overlay[..., 2] = OVERLAY_COLOR
            base[m] = base[m] * (1 - OVERLAY_ALPHA) + overlay[m] * OVERLAY_ALPHA
            disp = Image.fromarray(base.astype(np.uint8))
        # режим «Только снимок» — обычный кадр без наложения

        ox, oy = origin
        draw = ImageDraw.Draw(disp)
        if self.seed_xy is not None:                      # ① створ — красная «1»
            cx, cy = int((self.seed_xy[0] - ox) * sc), int((self.seed_xy[1] - oy) * sc)
            r = 10
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 60, 60), width=3)
            draw.line([cx - r - 7, cy, cx + r + 7, cy], fill=(255, 60, 60), width=2)
            draw.line([cx, cy - r - 7, cx, cy + r + 7], fill=(255, 60, 60), width=2)
            draw.text((cx + r + 2, cy - r), "1", fill=(255, 60, 60))
        # дополнительные точки цвета: жёлтые кружки с номерами 2, 3, …
        for i, (px, py) in enumerate(getattr(self, "color_pts", []), start=2):
            cx = int((px - ox) * sc)
            cy = int((py - oy) * sc)
            r = 8
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         outline=(255, 210, 0), width=3)
            draw.text((cx + r + 2, cy - r), str(i), fill=(255, 210, 0))
        return disp

    # ------------------------------------------------------------------
    # Зум и панорама (колесо мыши, «✋ Двигать», средняя кнопка, мини-карта)
    # ------------------------------------------------------------------
    def _canvas_size(self):
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1:                     # холст ещё не разметился — берём проектный
            cw = CANVAS_W
        if ch <= 1:
            ch = CANVAS_H
        return cw, ch

    def _base_fit(self):
        h, w = self.rgb.shape[:2]
        return min(CANVAS_W / w, CANVAS_H / h, 1.0)

    def _current_view(self):
        """Какой кусок снимка виден сейчас (с учётом зума и панорамы)."""
        h, w = self.rgb.shape[:2]
        cw, ch = self._canvas_size()
        s = self._base_fit() * self.zoom
        vw, vh = cw / s, ch / s
        if vw >= w:
            vw = float(w)
        if vh >= h:
            vh = float(h)
        # центр видимой области, зажатый в границы снимка
        cx = ((w / 2.0) if vw >= w else
              min(max(self.view_cx if self.view_cx is not None else w / 2.0,
                      vw / 2.0), w - vw / 2.0))
        cy = ((h / 2.0) if vh >= h else
              min(max(self.view_cy if self.view_cy is not None else h / 2.0,
                      vh / 2.0), h - vh / 2.0))
        x0, y0 = cx - vw / 2.0, cy - vh / 2.0
        x0i, y0i = max(0, int(round(x0))), max(0, int(round(y0)))
        x1i, y1i = min(w, int(round(x0 + vw))), min(h, int(round(y0 + vh)))
        x1i, y1i = max(x0i + 1, x1i), max(y0i + 1, y1i)
        # не растягиваем сверх масштаба zoom×fit (никакого апскейла), но при
        # обрезанной по краям рамке немного уменьшаем, чтобы влезло в холст
        sc = min(s, cw / (x1i - x0i), ch / (y1i - y0i))
        disp_w, disp_h = max(1, int(round((x1i - x0i) * sc))), max(1, int(round((y1i - y0i) * sc)))
        return {
            "x0i": x0i, "y0i": y0i, "x1i": x1i, "y1i": y1i,
            "sc": sc, "disp_w": disp_w, "disp_h": disp_h,
            "off_x": (cw - disp_w) // 2, "off_y": (ch - disp_h) // 2,
            "cw": cw, "ch": ch,
        }

    def _reset_view_state(self):
        self.zoom = 1.0
        self.view_cx = None
        self.view_cy = None
        self._view_cache = None

    def _zoom_at(self, factor, anchor=None):
        """Увеличить/уменьшить с привязкой к точке anchor=(x, y) на холсте."""
        if self.rgb is None:
            self._set_status("Сначала загрузите снимок.")
            return
        old = self.zoom
        new = min(max(old * factor, 1.0), 12.0)
        if new == old:
            return
        h, w = self.rgb.shape[:2]
        fit = self._base_fit()
        s0, s1 = fit * old, fit * new
        cw, ch = self._canvas_size()
        px, py = anchor if anchor is not None else (cw / 2.0, ch / 2.0)
        cx0 = self.view_cx if self.view_cx is not None else w / 2.0
        cy0 = self.view_cy if self.view_cy is not None else h / 2.0
        # точка снимка под курсором ДО зума → после зума она же под курсором
        img_x = cx0 + (px - cw / 2.0) / s0
        img_y = cy0 + (py - ch / 2.0) / s0
        self.view_cx = img_x - (px - cw / 2.0) / s1
        self.view_cy = img_y - (py - ch / 2.0) / s1
        self.zoom = new
        self.refresh_canvas()
        self._set_status(f"Масштаб: {int(round(self.zoom * 100))}% "
                         f"(колесо мыши; «✋ Двигать» или средняя кнопка — сдвинуть вид).")

    def reset_zoom(self):
        if self.rgb is None:
            return
        self._reset_view_state()
        self.refresh_canvas()
        self._set_status("Масштаб: вся картинка (100%).")

    def _on_mouse_wheel(self, event):
        """Колесо мыши над холстом — зум к курсору."""
        if self.rgb is None:
            return "break"
        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", 0)
        if delta > 0 or num == 4:
            factor = 1.15
        else:
            factor = 1 / 1.15
        self._zoom_at(factor, anchor=(event.x, event.y))
        return "break"

    def _pan_start(self, event):
        h, w = self.rgb.shape[:2]
        cx0 = self.view_cx if self.view_cx is not None else w / 2.0
        cy0 = self.view_cy if self.view_cy is not None else h / 2.0
        self._pan_state = (event.x, event.y, cx0, cy0)

    def _pan_middle_press(self, event):
        if self.rgb is None:
            return
        self._pan_start(event)

    def _pan_middle_drag(self, event):
        if self._pan_state is None:
            return
        self._pan_move(event)

    def _pan_move(self, event):
        x0e, y0e, cx0, cy0 = self._pan_state
        s = self._base_fit() * self.zoom
        self.view_cx = cx0 - (event.x - x0e) / s
        self.view_cy = cy0 - (event.y - y0e) / s
        self.refresh_canvas()

    def toggle_minimap(self):
        """Мини-окно «🗺 Карта просмотра»: вся картинка + красная рамка вида."""
        if self.minimap is not None:
            self.minimap.destroy()
            self.minimap = None
            self._minimap_photo = None
            self._minimap_geo = None
            return
        if self.rgb is None:
            self._set_status("Сначала загрузите снимок.")
            return
        self.minimap = tk.Toplevel(self)
        self.minimap.title("🗺 Карта просмотра")
        self.minimap.resizable(False, False)
        self.minimap.transient(self)
        self.minimap.protocol("WM_DELETE_WINDOW", self.toggle_minimap)
        self._minimap_canvas = tk.Canvas(self.minimap, width=240, height=170,
                                         bg=PALETTE["canvas"],
                                         highlightthickness=2,
                                         highlightbackground=PALETTE["brown"],
                                         cursor="hand2")
        self._minimap_canvas.pack(padx=8, pady=(8, 4))
        self._minimap_canvas.bind("<Button-1>", self._minimap_jump)
        self._minimap_canvas.bind("<B1-Motion>", self._minimap_jump)
        ttk.Label(self.minimap,
                  text="Клик или перетаскивание — перейти к месту.\n"
                       "Красная рамка — видимая область.",
                  justify=tk.CENTER).pack(padx=8, pady=(0, 8))
        self._update_minimap()

    def _update_minimap(self):
        """Перерисовать миниатюру и рамку видимой области."""
        if self.minimap is None or self.rgb is None:
            return
        thumb = self._render_scene_image(max_side=220, force_overlay=True)
        tw, th = thumb.size
        ox, oy = (240 - tw) // 2, (170 - th) // 2
        self._minimap_photo = ImageTk.PhotoImage(thumb)
        cv = self._minimap_canvas
        cv.delete("all")
        cv.create_image(ox, oy, image=self._minimap_photo, anchor="nw")
        h, w = self.rgb.shape[:2]
        sx, sy = tw / w, th / h
        view = self._view_cache if self._view_cache is not None else self._current_view()
        rx0, ry0 = ox + view["x0i"] * sx, oy + view["y0i"] * sy
        rx1, ry1 = ox + view["x1i"] * sx, oy + view["y1i"] * sy
        cv.create_rectangle(rx0, ry0, rx1, ry1, outline="#ff4040", width=2)
        self._minimap_geo = (ox, oy, sx, sy, w, h)

    def _minimap_jump(self, event):
        """Клик/перетаскивание по мини-карте — центр вида в этот пиксель."""
        if self.rgb is None or self._minimap_geo is None:
            return
        ox, oy, sx, sy, w, h = self._minimap_geo
        ix = (event.x - ox) / sx
        iy = (event.y - oy) / sy
        self.view_cx = min(max(ix, 0), w)
        self.view_cy = min(max(iy, 0), h)
        self.refresh_canvas()

    def refresh_canvas(self):
        """Перерисовывает снимок на холсте (с учётом зума): маска + створ."""
        if self.rgb is None:
            return
        view = self._current_view()
        self._view_cache = view
        disp = self._render_scene_image(view=view)
        self.photo = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(view["off_x"], view["off_y"],
                                 image=self.photo, anchor="nw")
        self._update_minimap()

    # ------------------------------------------------------------------
    # Ориентация снимка
    # ------------------------------------------------------------------
    def rotate_view(self, op):
        """Поворачивает/отражает снимок вместе с маской и точками."""
        if self.rgb is None:
            self._set_status("Сначала загрузите снимок.")
            return
        H, W = self.rgb.shape[:2]
        if op in ("rot1", "rot2", "rot3"):
            k = {"rot1": 1, "rot2": 2, "rot3": 3}[op]
            self.rgb = np.ascontiguousarray(np.rot90(self.rgb, k))
            if self.mask is not None:
                self.mask = np.ascontiguousarray(np.rot90(self.mask, k))
        elif op == "fliph":
            self.rgb = np.ascontiguousarray(np.fliplr(self.rgb))
            if self.mask is not None:
                self.mask = np.ascontiguousarray(np.fliplr(self.mask))
        elif op == "flipv":
            self.rgb = np.ascontiguousarray(np.flipud(self.rgb))
            if self.mask is not None:
                self.mask = np.ascontiguousarray(np.flipud(self.mask))

        if self.seed_xy is not None:
            self.seed_xy = transform_point(self.seed_xy, op, (H, W))

        self.result = None
        h, w = self.rgb.shape[:2]
        self.scale = min(CANVAS_W / w, CANVAS_H / h, 1.0)
        self._reset_view_state()
        self._set_status(f"Снимок преобразован. Новый размер: {w}×{h}. "
                         f"Нажмите «📐 Рассчитать D» для пересчёта.")
        self.refresh_canvas()

    def _current_tool(self):
        return self._tool_values[self._tool_index]

    def _update_cursor(self):
        """Курсор холста зависит от активного инструмента."""
        cursor = {"point": "crosshair", "colorpoint": "plus",
                  "pan": "fleur", "eraser": "circle", "brush": "circle"}
        self.canvas.configure(cursor=cursor[self._current_tool()])

    def _event_to_image_xy(self, event):
        """Координаты события мыши → пиксели исходного снимка (или None)."""
        h, w = self.rgb.shape[:2]
        view = self._view_cache if self._view_cache is not None else self._current_view()
        x = view["x0i"] + (event.x - view["off_x"]) / view["sc"]
        y = view["y0i"] + (event.y - view["off_y"]) / view["sc"]
        if not (0 <= x < w and 0 <= y < h):
            return None                      # клик мимо изображения
        return x, y

    def on_canvas_press(self, event):
        """ЛКМ: выбрать точку-эталон или начать штрих ластиком/кистью."""
        if self.rgb is None:
            self._set_status("Сначала загрузите снимок.")
            return
        tool = self._current_tool()
        if tool == "point":
            self._set_seed_from_event(event)
            return
        if tool == "colorpoint":
            self._add_color_point(event)
            return
        if tool == "pan":
            self._pan_start(event)
            return
        self._last_paint = None              # начинаем новый штрих
        # запоминаем маску на начало штриха: одна отмена = весь штрих
        self._stroke_snapshot = self._snapshot_state()
        self._apply_brush(event)

    def on_canvas_drag(self, event):
        """Движение мыши с зажатой ЛКМ — непрерывный штрих ластика/кисти."""
        if self._pan_state is not None:          # панорамирование
            self._pan_move(event)
            return
        if self.rgb is None or self._current_tool() not in ("eraser", "brush"):
            return
        self._apply_brush(event)

    def on_canvas_release(self, _event):
        self._last_paint = None              # конец штриха
        self._pan_state = None               # конец панорамирования

    def _set_seed_from_event(self, event):
        """Клик по холсту → ТОЧКА РАСХОДА в системе оригинала снимка."""
        pos = self._event_to_image_xy(event)
        if pos is None:
            return
        x, y = pos
        self.seed_xy = (x, y)

        r = self.rgb[int(y), int(x)]
        self._set_status(f"Точка расхода (створ): x={int(x)}, y={int(y)}, "
                         f"RGB=({r[0]}, {r[1]}, {r[2]}). Нажмите «🌊 Выделить реку».")
        self.refresh_canvas()

    # ------------------------------------------------------------------
    # Отмена и повтор действий (ластик, кисть, цветовые точки)
    # ------------------------------------------------------------------
    def _snapshot_state(self):
        """Снимок текущего состояния маски и точек — для отмены."""
        return {
            "mask": None if self.mask is None else self.mask.copy(),
            "color_pts": list(getattr(self, "color_pts", [])),
            "mask_touched": self.mask_touched,
        }

    def _push_undo(self, snapshot=None):
        """Кладём состояние в стек отмены и чистим «вперёд»."""
        snap = snapshot if snapshot is not None else self._snapshot_state()
        self._undo_stack.append(snap)
        if len(self._undo_stack) > 50:       # ограничение памяти
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _restore_state(self, snap):
        """Восстанавливает маску и точки из снимка."""
        self.mask = None if snap["mask"] is None else snap["mask"].copy()
        self.color_pts = list(snap["color_pts"])
        self.mask_touched = snap["mask_touched"]
        self.result = None                   # результат стал неактуален
        self.refresh_canvas()

    def undo(self):
        """«Назад»: отменяет последний штрих/точку."""
        if not self._undo_stack:
            self._set_status("Отменять нечего.")
            return
        self._redo_stack.append(self._snapshot_state())
        snap = self._undo_stack.pop()
        self._restore_state(snap)
        self._update_undo_buttons()
        self._set_status(f"Действие отменено. Осталось к отмене: "
                         f"{len(self._undo_stack)}, к повтору: "
                         f"{len(self._redo_stack)}.")

    def redo(self):
        """«Вперёд»: возвращает отменённое действие."""
        if not self._redo_stack:
            self._set_status("Повторять нечего.")
            return
        self._undo_stack.append(self._snapshot_state())
        snap = self._redo_stack.pop()
        self._restore_state(snap)
        self._update_undo_buttons()
        self._set_status(f"Действие повторено. К отмене: "
                         f"{len(self._undo_stack)}, к повтору: "
                         f"{len(self._redo_stack)}.")

    def _update_undo_buttons(self):
        """Кнопки «назад/вперёд» активны, только если есть что отменять."""
        if hasattr(self, "btn_undo"):
            self.btn_undo.state(["!disabled"] if self._undo_stack
                                else ["disabled"])
        if hasattr(self, "btn_redo"):
            self.btn_redo.state(["!disabled"] if self._redo_stack
                                else ["disabled"])

    def _add_color_point(self, event):
        """Клик «Доп. точкой цвета»: добавляет участок-эталон оттенка воды.

        В отличие от точки расхода (створ, маркер «1») эти точки НЕ влияют
        на положение створа — они расширяют набор цветов, которые
        считаются водой (мутный приток, тень на воде и т. п.).

        Берётся НЕ один пиксель, а кружок вокруг клика (радиус = размер
        кисти): на шумном спутниковом снимке отдельный пиксель слишком
        случаен, и эталон получался «не тем». Дополнительно цвет
        усредняется по кружку.

        Повторный клик рядом с существующей точкой — удалить её.
        """
        pos = self._event_to_image_xy(event)
        if pos is None:
            self._set_status("Клик мимо снимка — точку не поставил.")
            return
        if self.rgb is None:
            return
        x, y = int(round(pos[0])), int(round(pos[1]))

        # повторный клик рядом с существующей точкой — удалить её
        for i, (cx, cy) in enumerate(self.color_pts):
            if abs(cx - x) <= 10 and abs(cy - y) <= 10:
                self._push_undo()
                self.color_pts.pop(i)
                self.result = None
                self.refresh_canvas()
                self._set_status(
                    f"Доп. точка цвета удалена. Осталось точек: "
                    f"{len(self.color_pts)}. Нажмите «🌊 Выделить реку».")
                return

        # средний цвет по кружку радиуса «кисти» — устойчивее одиночного пикселя
        radius = max(2, int(self.brush_var.get()))
        h, w = self.rgb.shape[:2]
        y0, y1 = max(0, y - radius), min(h, y + radius + 1)
        x0, x1 = max(0, x - radius), min(w, x + radius + 1)
        patch = self.rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
        mean_rgb = patch.mean(axis=0)

        self._push_undo()
        self.color_pts.append((x, y))
        self.result = None
        self.refresh_canvas()

        # --- сразу пересобираем маску, чтобы точка не была «мёртвой» ---
        if self.seed_xy is None:
            self._set_status(
                f"Доп. точка цвета №{len(self.color_pts)}: x={x}, y={y}, "
                f"средний RGB=({int(mean_rgb[0])}, {int(mean_rgb[1])}, "
                f"{int(mean_rgb[2])}).\n"
                f"Сначала отметьте точку расхода (створ) — без неё маску "
                f"не построить.")
            return

        method = self._method_values[self._method_index]
        self.mask = segment_water(self.rgb, self.seed_xy,
                                  method=method,
                                  tol=self.tol_var.get(),
                                  keep_largest=self.largest_var.get(),
                                  extra_points=self.color_pts)
        self.mask_touched = False
        n_px = int(self.mask.sum())
        frac = 100.0 * n_px / self.mask.size
        self._set_status(
            f"Доп. точка цвета №{len(self.color_pts)}: x={x}, y={y}, "
            f"средний RGB=({int(mean_rgb[0])}, {int(mean_rgb[1])}, "
            f"{int(mean_rgb[2])}). Маска пересобрана: {n_px} px "
            f"({frac:.2f}% кадра).")
        self.refresh_canvas()

    def _apply_brush(self, event):
        """
        Ластик (вычитает из маски) или кисть (добавляет в маску).

        Штрих — это толстая линия от прошлой позиции до текущей плюс
        круг на текущей позиции: так даже быстрый взмах мыши
        оставляет непрерывный след без «дырок» между событиями.
        """
        pos = self._event_to_image_xy(event)
        if pos is None:
            return
        tool = self._current_tool()
        if tool not in ("eraser", "brush"):
            return

        if self.mask is None:
            if tool == "eraser":
                self._set_status("Ластику нечего стирать — сначала «🌊 Выделить реку».")
                return
            # кистью можно рисовать маску с чистого листа
            self.mask = np.zeros(self.rgb.shape[:2], dtype=bool)

        radius = max(1, int(self.brush_var.get()))
        px, py = int(round(pos[0])), int(round(pos[1]))
        prev = self._last_paint if self._last_paint is not None else pos
        qx, qy = int(round(prev[0])), int(round(prev[1]))

        m = self.mask.astype(np.uint8) * 255
        color = 0 if tool == "eraser" else 255
        cv2.line(m, (qx, qy), (px, py), color, thickness=2 * radius)
        cv2.circle(m, (px, py), radius, color, thickness=-1)
        self.mask = m > 0
        if self._stroke_snapshot is not None:
            self._push_undo(self._stroke_snapshot)
            self._stroke_snapshot = None
        self._last_paint = pos
        self.mask_touched = True

        # правка маски делает готовый результат неактуальным
        if self.result is not None:
            self.result = None
        n_px = int(self.mask.sum())
        self._set_status(("Ластик" if tool == "eraser" else "Кисть") +
                         f": в маске {n_px} px. Нажмите «📐 Рассчитать D» для пересчёта.")
        self.refresh_canvas()

    # ------------------------------------------------------------------
    # Обработка и расчёт
    # ------------------------------------------------------------------
    def run_segmentation(self):
        if self.rgb is None:
            messagebox.showinfo("Нет снимка", "Сначала загрузите изображение.")
            return
        if self.seed_xy is None:
            messagebox.showinfo("Нет точки", "Кликните точку на русле реки.")
            return

        method = self._method_values[self._method_index]
        self.mask = segment_water(self.rgb, self.seed_xy,
                                  method=method,
                                  tol=self.tol_var.get(),
                                  keep_largest=self.largest_var.get(),
                                  extra_points=self.color_pts)
        self.mask_touched = False
        self.result = None
        n_px = int(self.mask.sum())
        frac = 100.0 * n_px / self.mask.size
        if n_px == 0:
            self._set_status("Ничего не выделилось — увеличьте допуск "
                             "или смените способ выделения.")
        else:
            extra = (f" Учтено доп. точек цвета: {len(self.color_pts)}."
                     if self.color_pts else "")
            self._set_status(f"Выделено {n_px} px ({frac:.2f}% кадра).{extra} "
                             f"Лишнее можно стереть ластиком (вторая панель).")
        self.refresh_canvas()

    def run_calculation(self):
        """Расчёт по текущему объекту методом Кантора (квадраты)."""
        if self.mask is None:
            # если маску ещё не строили — попробуем построить сейчас
            self.run_segmentation()
            if self.mask is None:
                return

        # --- подтверждение: пользователь проверяет выделение перед расчётом ---
        n_px = int(self.mask.sum())
        share = 100.0 * n_px / self.mask.size
        seed_txt = ("точка расхода (створ) отмечена" if self.seed_xy is not None
                    else "точка расхода (створ) НЕ отмечена")
        if not messagebox.askyesno(
                "Проверка перед расчётом D",
                "Вы уверены, что выделили необходимую область реки?\n\n"
                f"• {seed_txt};\n"
                f"• пикселей воды в маске: {n_px} ({share:.2f} % кадра);\n"
                f"• маска: {'правилась вручную (ластик/кисть)' if self.mask_touched else 'получена автоматически'};\n"
                f"• объект расчёта: {self.object_var.get()};\n"
                f"• максимальное число делений сетки: {self.cantor_cells_var.get()}.\n\n"
                "Проверьте, что в маске ТОЛЬКО река ВЫШЕ створа (точки 1),\n"
                "а всё ниже по течению стёрто «🧹 Ластиком».\n\n"
                "Продолжить расчёт?"):
            self._set_status("Расчёт отменён пользователем.")
            return

        mode = self._object_values[self._object_index]
        try:
            if mode == "skeleton":
                src = skeleton_mask(self.mask)
            elif mode == "boundary":
                src = boundary_mask(self.mask)
            else:
                src = self.mask
        except RuntimeError as exc:
            messagebox.showerror("Нет scikit-image", str(exc))
            return
        try:
            self.result = cantor_squares_dimension(
                src, max_divs=self.cantor_cells_var.get())
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Ошибка расчёта", str(exc))
            return

        self.refresh_canvas()
        self._render_report()
        self._render_plot()
        r = self.result
        _f = lambda v: f"{v:.4f}".replace(".", ",")
        self._set_status(
            "Готово (метод Кантора, квадраты): "
            f"D = {_f(r['D'])} ± {_f(r['dD'])}  "
            f"(h = {_f(r['h'])} ± {_f(r['dh'])}, R² = {_f(r['r2'])}).")

    # ------------------------------------------------------------------
    # Вывод результатов
    # ------------------------------------------------------------------
    def _report_text_lines(self):
        """Единый текст отчёта — используется и панели, и PDF."""
        def _ru(v, nd=4):
            return f"{v:.{nd}f}".replace(".", ",")

        r = self.result
        mode = ["скелет (центр русла)", "граница воды (контур)",
                "заполненная маска"][self._object_index]
        seed_rgb = (self.rgb[int(self.seed_xy[1]), int(self.seed_xy[0])]
                    if self.seed_xy is not None else (0, 0, 0))
        touch_txt = ("отредактирована вручную (ластик/кисть)" if self.mask_touched
                     else "автоматическая сегментация")
        frac = 100.0 * self.mask.sum() / self.mask.size
        return [
            "ОТЧЁТ О ЗНАЧЕНИЯХ ФРАКТАЛЬНОЙ РАЗМЕРНОСТИ, СРЕДНЕГО",
            "МНОГОЛЕТНЕГО РАСХОДА ВОДЫ, КОЭФФИЦИЕНТА ВАРИАЦИИ,",
            "КОЭФФИЦИЕНТА АСИММЕТРИИ И КРИВОЙ ОБЕСПЕЧЕННОСТИ",
            "ДЛЯ ВЫБРАННОГО СТВОРА РЕКИ",
            "Метод Кантора (квадраты)",
            "N ~ (1/ε)^h,  h = 2(D − 1),  D = 1 + h/2",
            "=" * 52,
            f"Файл:            {os.path.basename(self.image_path or '—')}",
            f"Размер (тек.):   {self.rgb.shape[1]}×{self.rgb.shape[0]} px",
            (f"Доп. точки цвета: {len(self.color_pts)} шт."
             if getattr(self, "color_pts", None) else "Доп. точки цвета: нет"),
            f"Точка расхода (створ, 1): x={int(self.seed_xy[0])}, y={int(self.seed_xy[1])}"
            f"   RGB=({seed_rgb[0]}, {seed_rgb[1]}, {seed_rgb[2]})",
            f"Способ выделения: {['по цвету точки (HSV)', 'тёмная вода', 'комбинация'][self._method_index]}, "
            f"допуск = {self.tol_var.get()}",
            f"Объект расчёта:  {mode}",
            f"Максимальное число делений сетки: {r.get('n_divs_used', '—')}  "
            f"(шаг n += 1)",
            f"Пикселей воды:   {int(self.mask.sum())} ({frac:.2f}% кадра)",
            f"Маска:           {touch_txt}",
            "-" * 52,
            f"Размерность блуждания  h = {_ru(r['h'])} ± {_ru(r['dh'])}",
            f"Фрактальная размерность D = 1 + h/2 = {_ru(r['D'])} ± {_ru(r['dD'])}",
            f"R² = {_ru(r['r2'], 10)}  (1,0 — идеальная прямая в log–log)",
            f"r  = {_ru(math.sqrt(r['r2']), 10)}  (r = √R², коэффициент корреляции)",
            "",
            "СТАТИСТИЧЕСКИЕ ХАРАКТЕРИСТИКИ СТОКА",
            "────────────────────────────────────────────────────",
            "Средний многолетний расход воды  Qср, м³/с = — (или по D)",
            "Коэффициент вариации             Cv = — (или по D)",
            "Коэффициент асимметрии           Cs = — (или по D)",
            "Примечание: характеристики стока оценены по фрактальной",
            "размерности D (калибровочная связь).",
            "",
            "КРИВАЯ ОБЕСПЕЧЕННОСТИ",
            "────────────────────────────────────────────────────",
            "Бланк-клетчатка (P, % — Q, м³/с) печатается на альбомной",
            "странице A4 вместе с таблицей P–Q — см. последнюю страницу",
        ]

    def _render_report(self):
        lines = list(self._report_text_lines())
        lines += [
            "",
            f"{'n':>5} | {'ε, px':>7} | {'N(ε)':>6} | "
            f"{'log1/ε':>7} | {'logN':>7}",
            "-" * 44,
        ]
        def _ru2(v, nd):
            return f"{v:.{nd}f}".replace(".", ",")

        for n_div, eps, cnt in self.result["table"]:
            lines.append(f"{n_div:>5} | {_ru2(eps, 1):>7} | {cnt:>6} | "
                         f"{_ru2(math.log10(1 / eps), 3):>7} | "
                         f"{_ru2(math.log10(cnt), 3):>7}")
        text = "\n".join(lines)

        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", text)
        self.report.configure(state=tk.DISABLED)

    def _render_plot(self):
        if not HAVE_MPL:
            return
        r = self.result
        self.ax.clear()
        self.ax.set_facecolor(PALETTE["field"])     # фон области графика
        self.ax.scatter(r["x"], r["y"], s=26, color=PALETTE["olive"], zorder=3,
                        edgecolors=PALETTE["brown"], linewidths=0.4,
                        label="данные (n)")
        xs = np.linspace(r["x"].min(), r["x"].max(), 50)
        self.ax.plot(xs, r["h"] * xs + r["intercept"], color=PALETTE["burgundy"],
                     lw=1.6, label=(f"h = {r['h']:.3f}  →  D = {r['D']:.4f}"
                                    .replace(".", ",")))
        self.ax.set_xlabel("log₁₀ (1/ε), ε — пиксели")
        self.ax.set_ylabel("log₁₀ N(ε)")
        self.ax.grid(True, ls=":", alpha=0.6)
        _ru_axes(self.ax)
        _leg = self.ax.legend(loc="upper left", fontsize=9, frameon=True)
        _leg.get_frame().set_facecolor(PALETTE["cream"])
        _leg.get_frame().set_edgecolor(PALETTE["brown"])
        self.figure.tight_layout()
        self.mpl_canvas.draw()

    # ------------------------------------------------------------------
    # Сохранение результатов
    # ------------------------------------------------------------------
    def save_mask(self):
        if self.mask is None:
            messagebox.showinfo("Нет маски", "Сначала выделите реку.")
            return
        default = "mask.png"
        if self.image_path:
            base = os.path.splitext(os.path.basename(self.image_path))[0]
            default = f"{base}_mask.png"
        path = filedialog.asksaveasfilename(
            title="Сохранить маску реки", defaultextension=".png",
            initialfile=default, filetypes=[("PNG", "*.png")])
        if not path:
            return
        scale_txt = self.scale_var.get().strip() if hasattr(self, "scale_var") else ""
        write_mask_png(path, self.mask, scale_txt=scale_txt,
                       image_path=self.image_path, seed_xy=self.seed_xy)
        self._set_status(f"Маска сохранена: {path} (чёрная река на белом фоне; "
                         f"размер, разрешение 300 dpi и масштаб — в метаданных PNG).")

    def _write_pdf_report(self, path):
        """
        PDF-отчёт (A4, односторонняя печать):
          стр. 1 — параметры расчёта и результаты (+ график log–log);
          далее  — полная таблица измерений (n, ε, N);
          далее  — снимок со створом; отдельная страница — маска реки.

        Оформление: Times New Roman (в комплекте — Tinos, метрический
        аналог; при наличии в папке fonts/ настоящего Times New Roman
        используется он). Поля: левое 3 см, правое 1,5 см, верхнее и
        нижнее по 2 см. Основной текст 14 pt, таблицы 12 pt,
        примечания 10 pt; межстрочный интервал 1,5; абзацный отступ
        1,25 см; выравнивание основного текста по ширине; страницы
        пронумерованы; рисунки и таблицы подписаны.
        """
        try:
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.lib.enums import (TA_JUSTIFY, TA_CENTER, TA_LEFT,
                                 TA_RIGHT)
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.platypus import (BaseDocTemplate, PageTemplate,
                                             Frame, Paragraph, Spacer,
                                             Table, TableStyle, Flowable,
                                             NextPageTemplate, PageBreak,
                                             Image as RLImage, KeepTogether)
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
        except ImportError as exc:
            raise RuntimeError(
                "Для отчёта PDF нужен reportlab:\n"
                "    pip install reportlab") from exc

        import io as _io
        from xml.sax.saxutils import escape

        # ---------- шрифт Times New Roman (или метрический аналог) ----------
        here = os.path.dirname(os.path.abspath(__file__))
        font_sets = [
            # 1) настоящий Times New Roman, если пользователь положил его в fonts/
            (os.path.join(here, "fonts"),
             ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf")),
            (os.path.join(here, "fonts"),
             ("Times New Roman.ttf", "Times New Roman Bold.ttf",
              "Times New Roman Italic.ttf", "Times New Roman Bold Italic.ttf")),
            # 2) Tinos — метрический аналог (идёт в комплекте)
            (os.path.join(here, "fonts"),
             ("Tinos-Regular.ttf", "Tinos-Bold.ttf",
              "Tinos-Italic.ttf", "Tinos-BoldItalic.ttf")),
        ]
        if HAVE_MPL:                     # запасной вариант: STIX из matplotlib
            try:
                import matplotlib
                stix_dir = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
                font_sets.append((stix_dir, ("STIXGeneral.ttf", "STIXGeneralBol.ttf",
                                             "STIXGeneralItalic.ttf",
                                             "STIXGeneralBolIta.ttf")))
            except Exception:
                pass
        registered = False
        for d, fs in font_sets:
            if all(os.path.exists(os.path.join(d, f)) for f in fs):
                pdfmetrics.registerFont(TTFont("Times New Roman", os.path.join(d, fs[0])))
                pdfmetrics.registerFont(TTFont("Times New Roman Bold", os.path.join(d, fs[1])))
                pdfmetrics.registerFont(TTFont("Times New Roman Italic", os.path.join(d, fs[2])))
                pdfmetrics.registerFont(TTFont("Times New Roman Bold Italic", os.path.join(d, fs[3])))
                pdfmetrics.registerFontFamily(
                    "Times New Roman", normal="Times New Roman",
                    bold="Times New Roman Bold",
                    italic="Times New Roman Italic",
                    boldItalic="Times New Roman Bold Italic")
                registered = True
                break
        if not registered:
            raise RuntimeError(
                "Не найден шрифт Times New Roman. Положите файлы\n"
                "Tinos-Regular/Bold/Italic/BoldItalic.ttf в папку fonts/ рядом\n"
                "с программой (или установите matplotlib — тогда подойдёт STIX).")

        def ru(v, nd=4):
            """Число с запятой в качестве десятичного разделителя."""
            return f"{v:.{nd}f}".replace(".", ",")

        def ru_s(v, nd=4):
            """Как ru(), но со знаком: «± 0,0084»."""
            return (";" if v < 0 else "") + ru(abs(v), nd)

        r = self.result
        stamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        h_px, w_px = self.rgb.shape[:2]
        mode_txt = ["скелет (центр русла)", "граница воды (контур)",
                    "заполненная маска"][self._object_index]
        method_txt = ["по цвету точки (HSV)", "тёмная вода (яркость)",
                      "комбинация признаков"][self._method_index]
        seed_rgb = (self.rgb[int(self.seed_xy[1]), int(self.seed_xy[0])]
                    if self.seed_xy is not None else (0, 0, 0))
        seed_txt = (f"x = {int(self.seed_xy[0])}, y = {int(self.seed_xy[1])} "
                    f"(RGB = {seed_rgb[0]}, {seed_rgb[1]}, {seed_rgb[2]})"
                    if self.seed_xy is not None else "не отмечена")
        touch_txt = ("отредактирована вручную (ластик/кисть)" if self.mask_touched
                     else "автоматическая сегментация")
        frac = 100.0 * self.mask.sum() / self.mask.size
        r2 = float(r["r2"])
        corr = math.sqrt(r2)

        # ---------- стили ----------
        body = ParagraphStyle("body", fontName="Times New Roman", fontSize=14,
                              leading=21,                     # 1,5 интервала
                              alignment=TA_JUSTIFY, firstLineIndent=1.25 * cm,
                              spaceAfter=8)
        body_noind = ParagraphStyle("body_noind", parent=body,
                                    firstLineIndent=0)
        formula = ParagraphStyle("formula", parent=body,
                                 alignment=TA_CENTER, firstLineIndent=0,
                                 spaceAfter=2, leading=26)
        title = ParagraphStyle("title", fontName="Times New Roman Bold",
                               fontSize=16, leading=22, alignment=TA_CENTER,
                               spaceAfter=2)
        subtitle = ParagraphStyle("subtitle", fontName="Times New Roman",
                                  fontSize=10, leading=13, alignment=TA_CENTER,
                                  textColor=colors.Color(0.35, 0.35, 0.35),
                                  spaceAfter=12)
        caption_fig = ParagraphStyle("caption_fig", fontName="Times New Roman",
                                     fontSize=14, leading=18, alignment=TA_CENTER,
                                     spaceBefore=4, spaceAfter=10)
        caption_tbl = ParagraphStyle("caption_tbl", fontName="Times New Roman",
                                     fontSize=14, leading=18, alignment=TA_RIGHT,
                                     spaceBefore=4, spaceAfter=4)
        formula_num = ParagraphStyle("formula_num", fontName="Times New Roman",
                                     fontSize=14, leading=21, alignment=TA_RIGHT)
        heading = ParagraphStyle("heading", fontName="Times New Roman Bold",
                                 fontSize=14, leading=21, alignment=TA_LEFT,
                                 spaceBefore=10, spaceAfter=8)
        heading2 = ParagraphStyle("heading2", fontName="Times New Roman Bold",
                                  fontSize=14, leading=21, alignment=TA_LEFT,
                                  spaceBefore=8, spaceAfter=6)
        # примечания — по ширине (п.1)
        note = ParagraphStyle("note", fontName="Times New Roman", fontSize=10,
                              leading=13, firstLineIndent=0,
                              alignment=TA_JUSTIFY,
                              textColor=colors.Color(0.35, 0.35, 0.35),
                              spaceAfter=6)
        cell = ParagraphStyle("cell", fontName="Times New Roman", fontSize=12,
                              leading=15)
        cell_bold = ParagraphStyle("cell_bold", parent=cell,
                                   fontName="Times New Roman Bold")
        cell_center = ParagraphStyle("cell_center", parent=cell,
                                     alignment=TA_CENTER)
        cell_bold_center = ParagraphStyle("cell_bold_center", parent=cell,
                                          fontName="Times New Roman Bold",
                                          alignment=TA_CENTER)

        def tbl_caption(text, markup=False):
            return Paragraph(text if markup else escape(text), caption_tbl)

        def fig_caption(text, markup=False):
            return Paragraph(text if markup else escape(text), caption_fig)

        def table(data, widths, header=True, center=False, keep_whole=False,
                  markup=False, font_size=12, bold_first_col=False):
            """center=True — все ячейки по центру;
            keep_whole=True — таблица не разрывается между страницами;
            markup=True — в ячейках разрешена разметка (<sub>, <super>)."""
            cell_plain = ParagraphStyle("cell_plain", parent=cell,
                                        fontSize=font_size,
                                        leading=font_size * 1.25,
                                        splitLongWords=0)
            cell_plain_c = ParagraphStyle("cell_plain_c", parent=cell_plain,
                                          alignment=TA_CENTER)
            cell_bold_c = ParagraphStyle("cell_bold_c", parent=cell_plain_c,
                                         fontName="Times New Roman Bold",
                                         fontSize=max(8.0, font_size - 2),
                                         leading=max(10.0, font_size * 1.15))
            rows = []
            for i, row in enumerate(data):
                if header and i == 0:
                    style = cell_bold_c
                elif center:
                    style = cell_plain_c
                else:
                    style = cell_plain
                style_first = cell_bold_c if bold_first_col else style
                cells = []
                for j, v in enumerate(row):
                    st = style_first if j == 0 else style
                    if isinstance(v, Flowable):
                        cells.append(v)
                    else:
                        cells.append(Paragraph(
                            str(v) if markup else escape(str(v)), st))
                rows.append(cells)
            sc = cell_center
            t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
            style = [
                # шрифт ячеек (страховка от Helvetica по умолчанию)
                ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("LEADING", (0, 0), (-1, -1), font_size * 1.25),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
            if header:
                style.append(("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)))
            t.setStyle(TableStyle(style))
            t.hAlign = ("CENTER" if center else "LEFT")
            if keep_whole:
                t.splitByRow = 0
                t.splitInRow = 0
            return t

        # ---------- бланк-клетчатка для кривой обеспеченности ----------
        from statistics import NormalDist
        _nd = NormalDist()

        class ProbGrid(Flowable):
            """Клетчатка вероятностей для теоретической кривой обеспеченности:
            по горизонтали — обеспеченность P, % (вероятностная, нормальная
            шкала 0,1…99,9 %), по вертикали — модульный коэффициент K_P
            (правая ось расходов не выводится)."""

            # основные значения P (подписываются на оси)
            major_p = MAJOR_P
            # промежуточные значения P (тонкие линии без подписей)
            minor_p = [0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9, 1.5,
                       3, 4, 6, 7, 8, 9, 15, 25, 35, 45, 55, 65, 75, 85,
                       92, 93, 94, 96, 97, 98.5, 99.2, 99.3, 99.4, 99.6,
                       99.7, 99.8]

            def __init__(self, width, height, kp_func=None, major_labels=True):
                Flowable.__init__(self)
                self.width = width
                self.height = height
                self.kp_func = kp_func
                self.major_labels = major_labels

            def wrap(self, aw, ah):
                return self.width, self.height

            @staticmethod
            def _z(p):
                return _nd.inv_cdf(p / 100.0)

            # ---------- шкала K_P: границы по краям бланка ----------
            def _kp_range(self):
                if not hasattr(self, "_kp_lo"):
                    ks = [self.kp_func(p) for p in (0.1, 99.9)]
                    lo, hi = min(ks), max(ks)
                    pad = 0.06 * (hi - lo) if hi > lo else 0.1
                    self._kp_lo, self._kp_hi = lo - pad, hi + pad
                return self._kp_lo, self._kp_hi

            def _kp_to_y(self, kp, y0, y1):
                lo, hi = self._kp_range()
                if hi <= lo:
                    return None
                return y0 + (kp - lo) / (hi - lo) * (y1 - y0)

            def draw(self):
                c = self.canv
                # слева оставляем место для шкалы K_P
                x0, y0 = 64.0, 40.0
                x1, y1 = self.width - 10.0, self.height - 10.0
                zmin, zmax = self._z(0.1), self._z(99.9)

                def xp(p):
                    return x0 + (self._z(p) - zmin) / (zmax - zmin) * (x1 - x0)

                # ---------- горизонтальная сетка по K_P ----------
                if self.kp_func is not None:
                    lo, hi = self._kp_range()
                    # шаг 0.2 — промежуточные линии, 1.0 — основные
                    k = math.ceil(round(lo / 0.2, 9)) * 0.2
                    while k <= hi + 1e-9:
                        y = self._kp_to_y(k, y0, y1)
                        if y0 - 0.5 <= y <= y1 + 0.5:
                            is_major = abs(k - round(k)) < 1e-6
                            c.setLineWidth(0.55 if is_major else 0.22)
                            c.setStrokeColor(colors.black if is_major
                                             else colors.Color(0.72, 0.72, 0.72))
                            c.line(x0, y, x1, y)
                        k += 0.2
                else:
                    n_h = 30
                    c.setLineWidth(0.22)
                    c.setStrokeColor(colors.Color(0.72, 0.72, 0.72))
                    for i in range(1, n_h):
                        y = y0 + (y1 - y0) * i / n_h
                        c.line(x0, y, x1, y)

                # ---------- вертикальная сетка по P ----------
                c.setLineWidth(0.22)          # промежуточные
                c.setStrokeColor(colors.Color(0.72, 0.72, 0.72))
                for p in self.minor_p:
                    c.line(xp(p), y0, xp(p), y1)
                c.setLineWidth(0.55)          # основные
                c.setStrokeColor(colors.black)
                for p in self.major_p:
                    c.line(xp(p), y0, xp(p), y1)

                # рамка
                c.setLineWidth(0.9)
                c.setStrokeColor(colors.black)
                c.rect(x0, y0, x1 - x0, y1 - y0)

                # ---------- подписи P (снизу) ----------
                c.setFillColor(colors.black)
                c.setFont("Times New Roman", 8)
                for p in self.major_p:
                    x = xp(p)
                    lab = ("%g" % p).replace(".", ",")
                    tw = c.stringWidth(lab, "Times New Roman", 8)
                    xl = min(max(x - tw / 2.0, x0 + 1), x1 - tw - 1)
                    c.drawString(xl, y0 - 12, lab)
                c.setFont("Times New Roman", 9.5)
                c.drawRightString(x1, y0 - 28, "Обеспеченность P, %")

                # ---------- слева: шкала модульных коэффициентов K_P ----------
                if self.kp_func is not None:
                    lo, hi = self._kp_range()
                    c.setFont("Times New Roman", 8.5)
                    k = math.ceil(round(lo / 0.2, 9)) * 0.2
                    placed = []
                    while k <= hi + 1e-9:
                        y = self._kp_to_y(k, y0, y1)
                        if y0 - 0.5 <= y <= y1 + 0.5:
                            c.setLineWidth(0.5)
                            c.line(x0 - 6, y, x0, y)      # засечка
                            if abs(k - round(k)) < 1e-6:
                                # подписи только у целых значений
                                lab = ("%g" % k).replace(".", ",")
                                c.drawRightString(x0 - 8, y - 3, lab)
                                placed.append(y)
                        k += 0.2
                    c.saveState()
                    c.translate(13, (y0 + y1) / 2.0)
                    c.rotate(90)
                    c.setFont("Times New Roman", 9.5)
                    c.drawCentredString(0, 0, "Модульный коэффициент K_P")
                    c.restoreState()

        def buf_image(pil_image, width_cm, fmt="PNG"):
            buf = _io.BytesIO()
            pil_image.save(buf, format=fmt)
            buf.seek(0)
            iw, ih = pil_image.size
            return RLImage(buf, width=width_cm * cm,
                           height=width_cm * cm * ih / iw)

        # ---------- Q с чертой сверху (среднее многолетнее значение) ----------
        class QBar(Flowable):
            """Символ Q с горизонтальной чертой над ним (норма стока)."""

            def __init__(self, size=12):
                Flowable.__init__(self)
                self.size = size

            def wrap(self, aw, ah):
                from reportlab.pdfbase.pdfmetrics import stringWidth
                self.w = stringWidth("Q", "Times New Roman", self.size) + 2
                self.h = self.size * 1.35
                return self.w, self.h

            def draw(self):
                c = self.canv
                c.setFont("Times New Roman", self.size)
                c.setFillColor(colors.black)
                base = self.size * 0.28
                c.drawString(1, base, "Q")   # левый край — в начале ячейки
                c.setLineWidth(0.55)
                c.setStrokeColor(colors.black)
                c.line(1.2, base + self.size * 0.82,
                       self.w - 0.2, base + self.size * 0.82)

        # ---------- настоящие дроби (числитель над знаменателем) ----------
        def sq_frac(num, den, size=13):
            """Дробь столбиком: числитель над чертой, знаменатель под ней.

            Ведущая увеличена, чтобы <sub>/<super> внутри числителя и
            знаменателя не наезжали друг на друга, а черта не срезала
            верх и низ строки."""
            from reportlab.pdfbase.pdfmetrics import stringWidth as _sw
            st = ParagraphStyle("frac_part", fontName="Times New Roman",
                                fontSize=size, leading=size * 1.55,
                                alignment=TA_CENTER)
            w_max = max(_sw(num, "Times New Roman", size),
                        _sw(den, "Times New Roman", size), size * 0.9)
            t = Table([[Paragraph(num, st)], [Paragraph(den, st)]],
                      colWidths=[w_max + 8])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), size),
                ("LINEBELOW", (0, 0), (0, 0), 0.7, colors.black),
                # отступы дают воздух вокруг черты: она не срезает
                # верхушки цифр числителя и не липнет к знаменателю
                ("TOPPADDING", (0, 0), (0, 0), 2),
                ("BOTTOMPADDING", (0, 0), (0, 0), 3),
                ("TOPPADDING", (0, 1), (0, 1), 3),
                ("BOTTOMPADDING", (0, 1), (0, 1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            t.hAlign = "CENTER"
            return t

        # <sub>/<super> по умолчанию мелкие и жмутся к базовой строке —
        # поднимаем их размер и сдвиги один раз для всего документа
        def _tune_scripts():
            from reportlab.platypus.paraparser import ParaParser
            return True          # настройка сделана через стили формулы

        def bigparen(ch, size=13):
            """Крупная скобка вровень с дробью: символ набирается кеглем
            выше строки и центрируется по вертикали."""
            return Paragraph(
                ch, ParagraphStyle("bigparen", fontName="Times New Roman",
                                   fontSize=size * 1.70, leading=size * 1.70,
                                   alignment=TA_CENTER))

        def root(inner, size=13):
            """Корень «в скобках со степенью 1/2» с крупными скобками."""
            return [bigparen("(", size), inner,
                    bigparen(")", size), "<super>1/2</super>"]

        def mix(parts, style):
            """Строка из текста и дробей: строки → абзацы, Flowable — как есть.
            Ширины колонок измеряются по фактическому содержимому, чтобы
            дроби оставались компактными и не растягивались на всю строку."""
            from reportlab.pdfbase.pdfmetrics import stringWidth as _sw
            import re as _re
            cells, widths = [], []
            for p in parts:
                if isinstance(p, Flowable):
                    cells.append(p)
                    # ширину берём у самого объекта, НЕ вызывая wrap():
                    # wrap() с большой шириной заставляет абзац/таблицу
                    # «запомнить» её и растянуться на всю страницу
                    if getattr(p, "_colWidths", None):       # таблица-дробь
                        w = float(sum(p._colWidths))
                    elif hasattr(p, "_width") and p._width:  # готовый размер
                        w = float(p._width)
                    else:                                    # абзац-скобка
                        w = p.minWidth() + 2
                    widths.append(w + 2)
                else:
                    par = Paragraph(p, style)
                    # фактическая ширина строки без тегов разметки:
                    # minWidth() режет по словам и даёт слишком узко
                    plain = _re.sub(r"<[^>]+>", "", p).replace("&nbsp;", " ")
                    w = _sw(plain, style.fontName, style.fontSize)
                    cells.append(par)
                    widths.append(w + 3)
            t = Table([cells], colWidths=widths)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            t.hAlign = "CENTER"
            return t

        class ReportDoc(BaseDocTemplate):
            """Doc, который передаёт заголовки в оглавление."""

            def afterFlowable(self, flowable):
                memo = getattr(flowable, "_memo", None)
                if memo is not None:
                    level, text = memo
                    self.notify("TOCEntry", (level, text, self.page))

        # ---------- нумерация страниц ----------
        def on_page(canv, doc):
            canv.saveState()
            canv.setFont("Times New Roman", 12)
            page_w = canv._pagesize[0]      # ширина текущей страницы (A4 или A4 альбом)
            canv.drawCentredString(page_w / 2.0, 1.2 * cm, str(doc.page))
            canv.restoreState()

        # определяем ReportDoc ДО создания doc, чтобы оглавление работало
        doc = ReportDoc(path, pagesize=A4,
                              leftMargin=3 * cm, rightMargin=1.5 * cm,
                              topMargin=2 * cm, bottomMargin=2 * cm,
                              # чтобы даже «служебный» шрифт документа был Times:
                              initialFontName="Times New Roman",
                              initialFontSize=12, initialLeading=21,
                              title=("Отчёт о значениях фрактальной размерности, "
                                     "среднего многолетнего расхода воды, "
                                     "коэффициента вариации, коэффициента "
                                     "асимметрии и кривой обеспеченности"),
                              author="river_fractal.py")
        # Frame. 6 pt отступов по умолчанию «съедали» поля — обнуляем их,
        # чтобы текст начинался ровно с 3 см, а таблицы влезали в полосу
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id="main")
        # альбомный лист A4 (297 x 210 мм), те же поля
        LW, LH = landscape(A4)
        frame_land = Frame(3 * cm, 2 * cm,
                           LW - 3 * cm - 1.5 * cm, LH - 2 * cm - 2 * cm,
                           leftPadding=0, rightPadding=0,
                           topPadding=0, bottomPadding=0, id="land")
        doc.addPageTemplates([
            PageTemplate(id="portrait", frames=[frame], onPage=on_page),
            PageTemplate(id="landscape", frames=[frame_land],
                         onPage=on_page, pagesize=landscape(A4)),
        ])

        # ================= структура отчёта =====================
        # Разделы нумеруются римскими цифрами, формулы — арабскими в
        # круглых скобках, пояснения к таблицам — «Пояснение».
        memo = []                     # (уровень, метка, текст) для оглавления
        p_no = [0]                    # счётчик формул

        def formula_no(parts, style=None):
            """Формула по центру полосы, номер (1), (2), … — справа от неё
            на той же строке (как в методичках).

            Раскладка: три колонки — левая «распорка» той же ширины, что
            и номер, сама формула (центр), номер (справа). Так формула
            остаётся ровно по центру полосы, а номер прижат к правому
            краю, независимо от длины формулы."""
            from reportlab.pdfbase.pdfmetrics import stringWidth as _sw
            p_no[0] += 1
            num = f"({p_no[0]})"
            num_w = _sw(num, "Times New Roman", 14) + 8
            fw = mix(parts, style or formula)
            avail = A4[0] - 3 * cm - 1.5 * cm          # ширина полосы набора
            fw_w = fw.wrap(avail, 20 * cm)[0]
            # формула центрируется внутри средней колонки; ширина по факту
            mid_w = max(fw_w, avail - 2 * num_w)
            if fw_w > mid_w:                            # очень длинная формула
                mid_w = fw_w
            spacer = Spacer(1, 1)
            t = Table([[spacer, fw, Paragraph(num, formula_num)]],
                      colWidths=[num_w, mid_w, num_w])
            t.setStyle(TableStyle([
                # шрифт обязателен и для пустой ячейки-распорки:
                # иначе ReportLab подставляет Helvetica внутрь PDF
                ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
                ("FONTSIZE", (0, 0), (-1, -1), 14),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            t.hAlign = "CENTER"
            return t

        def sect(text, level=1):
            """Заголовок раздела: попадает и в текст, и в оглавление."""
            par = Paragraph(text, heading if level == 1 else heading2)
            par._memo = (level, text)
            return par

        # ---------- оглавление (заполняется автоматически при сборке) ----------
        from reportlab.platypus.tableofcontents import TableOfContents
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle("toc1", fontName="Times New Roman", fontSize=14,
                           leading=21, leftIndent=0, firstLineIndent=0,
                           spaceBefore=0),
            ParagraphStyle("toc2", fontName="Times New Roman", fontSize=12,
                           leading=18, leftIndent=18, firstLineIndent=0),
        ]
        toc.dotsMinLevel = 1        # точки у всех уровней, начиная с I
        # шрифт самой таблицы оглавления — Times (иначе в PDF попадает Helvetica)
        from reportlab.platypus.tableofcontents import defaultTableStyle
        toc.tableStyle = TableStyle(list(defaultTableStyle.getCommands()) + [
            ("FONTNAME", (0, 0), (-1, -1), "Times New Roman"),
            ("FONTSIZE", (0, 0), (-1, -1), 14),
        ])

        story = []
        # ---------------- титульный лист (без номера) ----------------
        story.append(Paragraph(
            "Отчёт о значениях фрактальной размерности, среднего многолетнего "
            "расхода воды, коэффициента вариации, коэффициента асимметрии "
            "и кривой обеспеченности для выбранного створа реки", title))
        story.append(Paragraph(f"Метод Кантора (квадраты) &nbsp;·&nbsp; "
                               f"создан {stamp}", subtitle))
        story.append(Paragraph(
            f"В отчёте приведены результаты измерения фрактальной размерности "
            f"реки по спутниковому снимку «{escape(os.path.basename(self.image_path or '—'))}». "
            f"Измерение выполнено методом Кантора (квадраты); связь размерности "
            f"блуждания h с фрактальной размерностью D задаётся формулой:",
            body))
        story.append(formula_no([
            "N ~ (", sq_frac("1", "ε", 13), ")<super>h</super>"
        ]))
        story.append(Paragraph(
            "где ε — сторона ячейки сетки, N(ε) — число ячеек, по которым "
            "проходит линия реки.", body))
        story.append(formula_no([
            "h = 2(D − 1),&nbsp;&nbsp;&nbsp; D = 1 + ",
            sq_frac("h", "2", 13),
        ]))
        story.append(Paragraph(
            "Наклон прямой в координатах «log<sub>10</sub> N(ε) — "
            "log<sub>10</sub> (1/ε)» оценивается методом наименьших "
            "квадратов по всем делениям сетки от 1 до максимального.", body))

        # ---------------- I. параметры расчёта ----------------
        story.append(sect("I. Исходные данные и параметры расчёта"))
        story.append(tbl_caption("Таблица 1 — Параметры расчёта"))
        t1 = table([
            ["Параметр", "Значение"],
            ["Файл", os.path.basename(self.image_path or "—")],
            ["Размер снимка", f"{w_px}×{h_px} px"],
            ["Точка расхода (створ)", seed_txt],
            ["Доп. точки цвета",
             (f"{len(self.color_pts)} шт.: " +
              ", ".join(f"x={x}, y={y}" for x, y in self.color_pts)
              if getattr(self, "color_pts", None) else "нет")],
            ["Способ выделения", f"{method_txt}; допуск = {self.tol_var.get()}"],
            ["Объект расчёта", mode_txt],
            ["Максимальное число делений сетки",
             f"{r.get('n_divs_used', '—')} (шаг n += 1)"],
            ["Пикселей воды",
             f"{int(self.mask.sum())} ({ru(frac, 2)} % кадра)"],
            ["Маска", touch_txt],
        ], [7.2 * cm, 9.1 * cm])
        story.append(t1)

        # ---------------- II. результаты измерения D ----------------
        story.append(PageBreak())       # глава 2 — с новой страницы
        story.append(sect("II. Результаты измерения фрактальной размерности"))
        story.append(tbl_caption("Таблица 2 — Результаты измерения"))
        story.append(table([
            ["Показатель", "Значение"],
            ["Размерность блуждания",
             f"h = {ru(r['h'])} ± {ru(r['dh'])}"],
            ["Фрактальная размерность",
             f"D = 1 + h/2 = {ru(r['D'])} ± {ru(r['dD'])}"],
            ["R² (коэффициент детерминации)", f"R² = {ru(r2, 10)}"],
            ["Коэффициент корреляции (r = √R²)", f"r = {ru(corr, 10)}"],
        ], [7.6 * cm, 8.7 * cm]))
        story.append(Paragraph(
            "R² = 1,0 соответствует идеальной прямой в логарифмических "
            "координатах; погрешность D получена из ошибки наклона h "
            "(метод наименьших квадратов).", note))

        if HAVE_MPL:
            # рисунок 1 в отчёте — на БЕЛОМ фоне (для печати)
            fig1 = Figure(figsize=(6.42, 4.2), dpi=170, facecolor="white")
            ax = fig1.add_subplot(111)
            ax.set_facecolor("white")
            ax.scatter(r["x"], r["y"], s=22, color=PALETTE["olive"], zorder=3,
                       edgecolors=PALETTE["brown"], linewidths=0.4,
                       label="данные")
            xs = np.linspace(r["x"].min(), r["x"].max(), 50)
            ax.plot(xs, r["h"] * xs + r["intercept"],
                    color=PALETTE["burgundy"], lw=1.6,
                    label=(f"h = {r['h']:.3f},  D = {r['D']:.4f}"
                           .replace(".", ",")))
            ax.set_xlabel(r"$\log_{10}(1/\varepsilon)$")
            ax.set_ylabel(r"$\log_{10}N(\varepsilon)$")
            ax.grid(True, ls=":", alpha=0.6)
            _ru_axes(ax)
            _leg1 = ax.legend(loc="upper left", fontsize=9, frameon=True)
            _leg1.get_frame().set_facecolor("white")
            _leg1.get_frame().set_edgecolor(PALETTE["brown"])
            fig1.tight_layout()
            buf1 = _io.BytesIO()
            fig1.savefig(buf1, format="png")
            buf1.seek(0)
            story.append(Spacer(1, 6))
            # рисунок 1 — на всю ширину полосы набора
            story.append(RLImage(buf1, width=16.3 * cm,
                                 height=16.3 * cm * 4.2 / 6.42))
            story.append(fig_caption(
                "Рисунок 1 — Зависимость log<sub>10</sub> N(ε) от "
                "log<sub>10</sub> (1/ε)", markup=True))
            story.append(Paragraph(
                f"h = {ru(r['h'])},&nbsp; D = {ru(r['D'])},"
                f"&nbsp; R² = {ru(r2, 10)}", caption_fig))
        else:
            story.append(Paragraph("График недоступен: matplotlib не установлен.",
                                   note))

        # ---------------- III. полная таблица измерений ----------------
        story.append(PageBreak())       # глава 3 — с новой страницы
        story.append(sect("III. Полная таблица измерений"))
        story.append(Paragraph(
            "Ниже представлены результаты обмера маски реки сеткой: для "
            "каждого деления сетки указаны сторона ячейки ε в пикселях, "
            "число ячеек N(ε), через которые проходит линия реки, и их "
            "десятичные логарифмы, по которым строится прямая рисунка 1.",
            body))
        story.append(tbl_caption("Таблица 3 — Полная таблица измерений"))
        data = [["n", "ε, px", "N(ε)", "log<sub>10</sub> (1/ε)",
                 "log<sub>10</sub> N(ε)"]]
        for n_div, eps, cnt in r["table"]:
            data.append([str(n_div), ru(eps, 1), str(cnt),
                         ru(math.log10(1 / eps), 3),
                         ru(math.log10(cnt), 3)])
        story.append(table(data, [1.9 * cm, 3.1 * cm, 2.4 * cm,
                                  4.45 * cm, 4.45 * cm],
                           center=True, markup=True))
        story.append(Paragraph(
            "Пояснение: n — номер деления сетки (число ячеек по стороне "
            "снимка); ε — сторона ячейки сетки, px; N(ε) — число ячеек "
            "сетки, через которые проходит линия реки; "
            "log<sub>10</sub>(1/ε) — десятичный логарифм обратной стороны "
            "ячейки; log<sub>10</sub> N(ε) — десятичный логарифм числа "
            "ячеек.", note))

        # ---------------- IV. снимок и маска ----------------
        story.append(PageBreak())       # глава 4 — с новой страницы
        story.append(sect("IV. Снимок с выделенной маской и маска реки"))
        scene = self._render_scene_image(max_side=1400, force_overlay=True)
        story.append(KeepTogether([
            buf_image(scene, 15.0),
            fig_caption("Рисунок 2 — Снимок с выделенной маской воды "
                        "(зелёный) и точкой расхода (створ, маркер «1»)"),
        ]))
        inv = np.where(self.mask, 0, 255).astype(np.uint8)
        mask_img = Image.fromarray(inv, mode="L").convert("RGB")
        story.append(PageBreak())
        story.append(KeepTogether([
            buf_image(mask_img, 15.0),
            fig_caption("Рисунок 3 — Маска реки (чёрный — вода, белый — фон)"),
        ]))

        # ---------------- V. статистические характеристики стока ----------------
        def fmt(v, nd=3):
            if v is None:
                return "—"
            return ru(v, nd)

        # Характеристики стока не вводятся пользователем — оцениваются
        # по фрактальной размерности D в ядре (stream_stats_from_D).
        stats = stream_stats_from_D(r["D"], r["dD"])
        d_val = r["D"]
        q_mean = stats["Q_mean"]
        cv = stats["Cv"]
        cs = stats["Cs"]
        rel_err_q = stats["rel_err_Q"]
        rel_err_cv = stats["rel_err_Cv"]
        rel_err_cs = stats["rel_err_Cs"]
        abs_err = lambda val, rel_pct: val * rel_pct / 100.0

        story.append(PageBreak())
        story.append(sect("V. Статистические характеристики стока"))
        story.append(Paragraph(
            "В таблице ниже представлены статистические характеристики стока "
            "для данного створа, определённые по фрактальной размерности.",
            body))
        story.append(tbl_caption("Таблица 4 — Статистические характеристики стока"))
        t4 = table([
            ["&nbsp;Характеристика&nbsp;", "&nbsp;Обозначение&nbsp;",
             "&nbsp;&nbsp;Значение&nbsp;&nbsp;",
             "Относительная<br/>погрешность",
             "Абсолютная<br/>погрешность"],
            ["Средний многолетний расход воды, м³/с",
             "Q<sub>ср</sub>", fmt(q_mean, 2), fmt(rel_err_q, 1),
             "± " + fmt(abs_err(q_mean, rel_err_q), 2)],
            ["Коэффициент вариации",
             "C<sub>v</sub>", fmt(cv, 3), fmt(rel_err_cv, 1),
             "± " + fmt(abs_err(cv, rel_err_cv), 3)],
            ["Коэффициент асимметрии",
             "C<sub>s</sub>", fmt(cs, 3), fmt(rel_err_cs, 1),
             "± " + fmt(abs_err(cs, rel_err_cs), 3)],
        ], [4.5 * cm, 2.7 * cm, 2.6 * cm, 3.25 * cm, 3.25 * cm],
           center=True, keep_whole=True, markup=True)
        story.append(t4)
        story.append(Paragraph(
            "Пояснение: Q<sub>ср</sub> — средний многолетний расход воды "
            "(норма стока), м³/с; C<sub>v</sub> — коэффициент вариации; "
            "C<sub>s</sub> — коэффициент асимметрии. Характеристики "
            "определены по фрактальной размерности D (калибровочная связь); "
            "относительная погрешность указана в долях процента, абсолютная "
            "— в единицах измерения характеристики.", note))

        # ---------- погрешности: формулы (п.5) ----------
        # Абсолютные и относительные погрешности характеристик стока
        # вычисляются по формулам теории вероятностей и математической
        # статистики (СП 33-101-2003, прил. Ж).
        story.append(Paragraph("Погрешности характеристик стока вычисляются "
                               "по формулам математической статистики.", body))

        sub10 = lambda t: f"<sub>{t}</sub>"      # короткая запись индекса

        # Каждая пара «формула + пояснение к ней» — неразрывный блок:
        # иначе пояснение уезжает на следующую страницу без своей формулы.
        # Подпункты начинаются с точки-маркера (•), как в перечне.
        # Корень записывается скобками со степенью 1/2: (…)^1/2 —
        # скобки крупные, по высоте дроби, поэтому читается однозначно.
        def err_item(header, formula_parts, expl):
            return KeepTogether([Paragraph(header, body_noind),
                                 formula_no(formula_parts),
                                 Paragraph(expl, body)])

        story.append(Paragraph("а) абсолютные погрешности", body_noind))
        story.append(err_item(
            "• для среднего значения",
            ["ε<sub>Q</sub> = ",
             sq_frac("σ<sub>Q</sub>", "n<super>1/2</super>", 13)],
            "где σ<sub>Q</sub> — среднеквадратическое отклонение расхода "
            "воды, м³/с; n — число членов ряда наблюдений."))

        story.append(err_item(
            "• для коэффициента вариации",
            ["ε<sub>Cv</sub> = ",
             sq_frac("C<sub>v</sub>", "n + 4C<sub>v</sub>²", 13),
             "&nbsp;",
             *root(sq_frac("n(1 + C<sub>v</sub>²)", "2", 13))],
            "где C<sub>v</sub> — коэффициент вариации; n — число членов "
            "ряда наблюдений."))

        story.append(err_item(
            "• для коэффициента асимметрии",
            ["ε<sub>Cs</sub> = ",
             *root(sq_frac("6", "n", 13)),
             "(1 + 6C<sub>v</sub>² + 5C<sub>v</sub><super>4</super>)"
             "<super>1/2</super>"],
            "где C<sub>v</sub> — коэффициент вариации; n — число членов "
            "ряда наблюдений."))

        story.append(Paragraph("б) относительные погрешности", body_noind))
        story.append(err_item(
            "• для среднего значения",
            ["ε<sub>Q, %</sub> = ",
             sq_frac("C<sub>v</sub>", "n<super>1/2</super>", 13),
             "·100 %"],
            "где C<sub>v</sub> — коэффициент вариации; n — число членов "
            "ряда наблюдений."))

        story.append(err_item(
            "• для коэффициента вариации",
            ["ε<sub>Cv, %</sub> = ",
             sq_frac("1", "n + 4C<sub>v</sub>²", 13),
             "&nbsp;",
             *root(sq_frac("n(1 + C<sub>v</sub>²)", "2", 13)),
             "·100 %"],
            "где C<sub>v</sub> — коэффициент вариации; n — число членов "
            "ряда наблюдений."))

        story.append(err_item(
            "• для коэффициента асимметрии",
            ["ε<sub>Cs, %</sub> = ",
             sq_frac("1", "C<sub>s</sub>", 13),
             *root(sq_frac("6", "n", 13)),
             "(1 + 6C<sub>v</sub>² + 5C<sub>v</sub><super>4</super>)"
             "<super>1/2</super>·100 %"],
            "где C<sub>v</sub> и C<sub>s</sub> — коэффициенты вариации и "
            "асимметрии; n — число членов ряда наблюдений."))

        # ---------------- VI. теоретическая кривая обеспеченности ----------------
        kp_by_p = stats["kp_by_p"]

        story.append(NextPageTemplate("landscape"))
        story.append(PageBreak())
        story.append(sect(
            "VI. Теоретическая кривая обеспеченности (Пирсона III типа)"))
        grid_w = landscape(A4)[0] - 3 * cm - 1.5 * cm
        # почти вся страница: остаётся только заголовок и подпись рисунка
        grid_h = landscape(A4)[1] - 2 * cm - 2 * cm - 3.2 * cm
        story.append(ProbGrid(grid_w, grid_h, kp_func=lambda p: kp_by_p[p],
                              major_labels=False))
        story.append(fig_caption(
            "Рисунок 4 — Теоретическая кривая обеспеченности "
            "(Пирсона III типа): P, % — модульный коэффициент "
            "K<sub>P</sub>", markup=True))

        # ---------------- VII. таблица P, K_P, Q_P + пояснения ----------------
        story.append(NextPageTemplate("portrait"))
        story.append(PageBreak())
        story.append(sect(
            "VII. Расчёт ординат теоретической кривой обеспеченности"))
        story.append(Paragraph(
            "В таблице 5 приведены ординаты теоретической кривой: "
            "обеспеченность P, модульные коэффициенты K<sub>P</sub> и "
            "соответствующие расходы воды Q<sub>P</sub>.", body))
        # вводный текст до таблицы
        story.append(tbl_caption(
            "Таблица 5 — Ординаты теоретической кривой", markup=True))
        p_majors = ProbGrid.major_p
        # вертикальная таблица: строка = значение обеспеченности
        t5_rows = [["Обеспеченность<br/>P, %", "Модульный коэффициент<br/>K<sub>P</sub>",
                    "Расход воды<br/>Q<sub>P</sub>, м³/с"]]
        for p in p_majors:
            t5_rows.append([("%g" % p).replace(".", ","),
                            fmt(kp_by_p[p], 2),
                            fmt(kp_by_p[p] * q_mean, 1)])
        story.append(table(t5_rows, [5.4 * cm, 5.4 * cm, 5.4 * cm],
                           header=True, center=True, keep_whole=True,
                           markup=True))

        story.append(PageBreak())      # пояснения — на отдельной странице
        story.append(sect("Порядок вычисления", level=2))
        story.append(Paragraph(
            "Теоретическая кривая строится по трём характеристикам стока — "
            "Q<sub>ср</sub>, C<sub>v</sub> и C<sub>s</sub>. Расход воды "
            "обеспеченности P вычисляется по формуле", body))
        story.append(formula_no([
            "Q<sub>P</sub> = (Φ<sub>P</sub>·C<sub>v</sub> + 1)·"
            "Q<sub>ср</sub> = K<sub>P</sub>·Q<sub>ср</sub>",
        ]))
        story.append(Paragraph(
            "где Φ<sub>P</sub> — коэффициент Фостера–Рыбкина, зависящий от "
            "обеспеченности P и коэффициента асимметрии C<sub>s</sub>",
            body))
        story.append(formula_no([
            "Φ<sub>P</sub> = z<sub>P</sub> + (C<sub>s</sub>/6)·"
            "(z<sub>P</sub>² − 1)",
        ]))
        story.append(Paragraph(
            "а K<sub>P</sub> — модульный коэффициент, показывающий, во "
            "сколько раз расход обеспеченности P отличается от Q<sub>ср</sub>",
            body))
        story.append(formula_no([
            "K<sub>P</sub> = Φ<sub>P</sub>·C<sub>v</sub> + 1",
        ]))
        story.append(Paragraph(
            f"В формулах ({p_no[0] - 1}) и ({p_no[0]}) z<sub>P</sub> — квантиль "
            "стандартного нормального распределения для обеспеченности P; "
            "значения Φ<sub>P</sub> определяются по стандартным таблицам "
            "(например, СП 33-101-2003). Модульные коэффициенты "
            "K<sub>P</sub> образуют вспомогательную шкалу перехода от "
            "обеспеченности к расходу.", body))

        # ---------- сборка ----------
        # Оглавление по требованию убрано: разделы нумеруются римскими
        # цифрами прямо в заголовках, их же можно печатать в колонтитуле.
        doc.build(story)

    def save_report(self):
        if self.result is None:
            messagebox.showinfo("Нет результатов", "Сначала выполните расчёт D.")
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить отчёт", defaultextension=".pdf",
            initialfile="river_fractal_report.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return

        try:
            self._write_pdf_report(path)
        except Exception as exc:
            # запасной вариант: текстовый отчёт с теми же данными
            txt_path = path[:-4] + ".txt" if path.lower().endswith(".pdf") else path + ".txt"
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            body = "\n".join(self._report_text_lines())
            with open(txt_path, "w", encoding="utf-8") as fh:
                fh.write(f"Отчёт сформирован: {stamp}\n\n{body}\n\n"
                         f"PDF-отчёт не создан: {exc}\n")
            messagebox.showwarning(
                "PDF не создан",
                f"Не удалось сформировать PDF:\n{exc}\n\n"
                f"Сохранён текстовый отчёт:\n{txt_path}")
            self._set_status(f"Отчёт сохранён (TXT): {txt_path}")
            return
        self._set_status(f"PDF-отчёт сохранён: {path}")


def main():
    app = RiverFractalApp()
    app.mainloop()


if __name__ == "__main__":
    main()
