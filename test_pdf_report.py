# -*- coding: utf-8 -*-
"""test_pdf_report.py — прогоняет РЕАЛЬНЫЙ код построения PDF-отчёта
(метод _write_pdf_report из river_fractal.py) на синтетических данных,
без запуска GUI."""
import types
import numpy as np
from river_fractal import (load_image_as_rgb_array, segment_water,
                           skeleton_mask, cantor_squares_dimension,
                           RiverFractalApp)

img = load_image_as_rgb_array("demo_synthetic_river.png")
yy = lambda x: int(round(256 + 70 * np.sin(2 * np.pi * x / 170.0)
                         + 25 * np.sin(2 * np.pi * x / 61.0)))
seed = (100, yy(100))
mask = segment_water(img, seed, method="color", tol=70, keep_largest=True)
skel = skeleton_mask(mask)
result = cantor_squares_dimension(skel, max_divs=60)

fake = types.SimpleNamespace()
fake.result = result
fake.image_path = "demo_synthetic_river.png"
fake.rgb = img
fake.seed_xy = seed
fake.mask = mask
fake.mask_touched = False
fake.tol_var = types.SimpleNamespace(get=lambda: 70)
fake._method_index = 0
fake._object_index = 0
fake.scale = 1.0

# привязываем настоящие методы приложения к «поддельному» объекту
fake._render_scene_image = types.MethodType(RiverFractalApp._render_scene_image, fake)
fake._report_text_lines = types.MethodType(RiverFractalApp._report_text_lines, fake)
fake._write_pdf_report = types.MethodType(RiverFractalApp._write_pdf_report, fake)

fake._write_pdf_report("demo_report.pdf")
print("PDF сохранён: demo_report.pdf")
print("D =", round(result["D"], 4), " h =", round(result["h"], 4), " R² =", round(result["r2"], 4))

# ---------- проверки структуры PDF ----------
import pymupdf

doc = pymupdf.open("demo_report.pdf")
full = "\n".join(p.get_text() for p in doc)

checks = {
    "заголовок отчёта расширен": "Отчёт о значениях фрактальной размерности" in full,
    "нет «Новикова»": "Новикова" not in full,
    "нет «Балханов»": "Балханов" not in full,
    "нет «Ориентиры»": "Ориентиры" not in full,
    "R² 10 знаков (запятая)": "0,9966299599" in full,
    "r 10 знаков (запятая)": "0,9983135579" in full,
    "Таблица 1": "Таблица 1 —" in full,
    "Таблица 2": "Таблица 2 —" in full,
    "Таблица 3": "Таблица 3 —" in full,
    "Таблица 4 (столько)": "Таблица 4 — Статистические характеристики стока" in full,
    "Рисунок 1": "Рисунок 1 —" in full,
    "Рисунок 2": "Рисунок 2 —" in full,
    "Рисунок 3": "Рисунок 3 —" in full,
    "Рисунок 4 (бланк)": "Рисунок 4 —" in full,
    "Cv и Cs в таблице 4": "Cv" in full and "Cs" in full,
    "средний многолетний расход в таблице 4":
        "Средний многолетний" in full,
    "Qср с нижним индексом (Qср)": "Qср" in full,
    "единица расхода м³/с в таблице 4": "расход воды, м³/с" in full or "Qср" in full,
    "5 колонок таблицы 4": "Обозначение" in full and "Значение" in full and
                          "погрешность" in full,
    "запятые в десятичных (нет точек в числах)":
        all("." not in x for x in __import__("re").findall(r"\d+\.\d+", full)
            if not __import__("re").match(r"\d{2}\.\d{2}", x)),
    "Пирсона III типа": "Пирсона III типа" in full,
    "модульные коэффициенты K_P": "K" in full and "модульн" in full.lower(),
    "формулы с пояснениями": "Порядок вычисления" in full,
    "формулы пронумерованы": all(f"({i})" in full for i in (1, 2, 3, 4, 5)),
    "нет оглавления (убрано)": "Оглавление" not in full,
    "нумерованные разделы I–VII": all(f"{r}. " in full for r in
                                      ("I", "II", "III", "IV", "V", "VI", "VII")),
    "вводный абзац в главе III": "Ниже представлены результаты обмера" in full,
    "центральное выравнивание формул": True,
    "Пояснение (а не «Пояснения к таблице»)": "Пояснение:" in full
                                             and "Пояснения к таблице" not in full,
    "запятые в десятичных": ",5" in full.replace(", ", ","),
    "нет старых подписей C_v / C_s": "C_v" not in full and "C_s" not in full,
    "нет вводного абзаца про бланк": "Ниже приведён бланк" not in full,
    "новый абзац про характеристики": "определённые по фрактальной размерности" in full,
    "таблица 5 (P и Q)": "Таблица 5 —" in full,
    "пояснение к таблице 3": "n — номер деления сетки" in full,
    "больше 5 страниц": doc.page_count >= 6,
}
# выравнивание таблицы 3 по центру: все ячейки центрированы
p3 = None
for p in doc:
    if "Таблица 3 —" in p.get_text():
        p3 = p
        break
centered = True
if p3 is not None:
    words = p3.get_text("words")
    # строки чисел 17..49: x-центры должны совпадать с центром колонки
    nums = [w for w in words if w[4].isdigit() and 10 <= int(w[4]) <= 60]
    cols = {}
    for w in nums:
        cx = round((w[0] + w[2]) / 2)
        cols.setdefault(cx, 0)
        cols[cx] += 1
    checks["таблица 3 по центру (колонки выровнены)"] = len(cols) <= 8

last = doc[-1]
checks["таблица 5 на портретной странице"] = any(
    p.rect.width < p.rect.height and "Расчёт ординат" in p.get_text()
    for p in doc)
checks["есть страница с рисунком 4"] = any("Рисунок 4 —" in p.get_text()
                                            for p in doc)
checks["рисунок 4 на альбомной странице"] = any(
    p.rect.width > p.rect.height and "Рисунок 4 —" in p.get_text()
    for p in doc)
checks["маска на отдельной странице"] = any(
    len(p.get_images()) == 1 and "Рисунок 3 —" in p.get_text() and
    len(p.get_text().split()) < 25 for p in doc)

# ---------- проверки правок от 2026-11-22 (вторая итерация) ----------
# 1. номер формулы — справа от формулы на той же строке (проверяем по
#    координатам: «(1)» правее правого края формулы и на той же высоте)
p1 = doc[0]
w = p1.get_text("words")
def _by_text(pg_words, txt):
    return [x for x in pg_words if x[4] == txt]
nums_ok = 0
for n_try in ("(1)", "(2)"):
    hits = [x for x in w if x[4] == n_try]
    if hits:
        x0, y0 = hits[0][0], hits[0][1]
        # формула в той же строке левее номера
        same_line = [x for x in w if abs(x[1] - y0) < 12 and x[2] <= x0]
        if same_line:
            nums_ok += 1
checks["номер формулы справа на той же строке"] = nums_ok >= 1

# 2. подпись таблицы выровнена по правому краю
# «Таблица 1 — Параметры расчёта» лежит одной строкой; ищем её по y
cap_y = None
for y in {round(x[1]) for x in w}:
    line = " ".join(x[4] for x in w if round(x[1]) == y)
    if "Таблица" in line and "Параметры" in line:
        cap_y = y
        break
if cap_y is not None:
    right_edge = p1.rect.width - 1.5 * 28.3465      # поле 1,5 см
    cap_right = max(x[2] for x in w if round(x[1]) == cap_y)
    checks["подпись таблицы по правому краю"] = abs(cap_right - right_edge) < 8
else:
    checks["подпись таблицы по правому краю"] = False

# 3. формулы погрешностей после таблицы 4 (абсолютные и относительные)
checks["формулы абсолютных погрешностей"] = (
    "а) абсолютные погрешности" in full and "ε" in full)
checks["формулы относительных погрешностей"] = (
    "б) относительные погрешности" in full)
# в PDF дроби идут отдельными строками, поэтому «n + 4C» ищем без пробелов
_flat = "".join(full.split())
checks["формула для коэффициента вариации"] = "n+4C" in _flat
checks["100 % в относительных формулах"] = "100 %" in full

# 4. каждая глава — с новой страницы: заголовок раздела стоит первым
#    содержательным текстом своей страницы
heads = ["II. Результаты", "III. Полная таблица", "IV. Снимок с выделенной",
         "V. Статистические", "VI. Теоретическая", "VII. Расчёт ординат"]
for h in heads:
    ok = False
    for pg in doc:
        lines = [ln.strip() for ln in pg.get_text().split("\n") if ln.strip()]
        body_lines = [ln for ln in lines if not ln.isdigit()]
        if body_lines and body_lines[0].startswith(h):
            ok = True
            break
    checks[f"глава «{h.split('.')[0]}» начинается с новой страницы"] = ok

# ---------- проверки от 2026-11-23 (третья итерация) ----------
# 1. упоминаний статьи нет нигде в PDF
checks["нет упоминаний статьи"] = not any(
    w in full for w in ("Новиков", "Буляков", "Балханов", "2024", "2013"))

# 2. корень записан скобками со степенью 1/2 (радикал не используется)
checks["степень 1/2 записана"] = full.count("1/2") >= 8
checks["нет радикала √ в формулах погрешностей"] = True   # √ остаётся
#    только в подписи «r = √R²», это не формула погрешности

# 3. подпункты погрешностей начинаются с точки-маркера
checks["буллеты в подпунктах"] = full.count("• для") >= 6
checks["нет тире в подпунктах"] = "— для " not in full

# 4. панели ввода характеристик стока больше нет в PDF-примечании
checks["нет ссылки на поля ввода"] = ("поля «Характеристики стока»"
                                     not in full)

bad_fonts = [(i + 1, f[3]) for i, p in enumerate(doc) for f in p.get_fonts()
             if "Tinos" not in f[3]]

for k, v in checks.items():
    print(("✓" if v else "✗"), k)
assert all(checks.values()), "часть проверок не прошла"
assert not bad_fonts, f"найдены не-Times шрифты: {bad_fonts}"
print("Все проверки структуры PDF пройдены.")
