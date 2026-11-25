# -*- coding: utf-8 -*-
"""Канонический формат PDF-отчёта HydroFractal (перенесён из river_fractal.py).

Структура: титул, разделы I–VII, формулы (1)–(11), таблицы 1–5,
рисунки 1–4, альбомная страница кривой обеспеченности, нумерация страниц.
"""
from __future__ import annotations

import datetime
import math
import os

import numpy as np
from PIL import Image

from matplotlib.figure import Figure

from core.hydro_core import MAJOR_P, stream_stats_from_D

HAVE_MPL = True
PALETTE = {
    "olive": "#9CA75A", "beige": "#DACAB0", "cream": "#F3EBE0",
    "brown": "#8B6431", "burgundy": "#733933",
}


def _ru_axes(ax):
    from matplotlib.ticker import FuncFormatter
    fmt = FuncFormatter(lambda v, _p: f"{v:,.2f}".replace(",", " ").replace(".", ","))
    ax.xaxis.set_major_formatter(fmt)
    ax.yaxis.set_major_formatter(fmt)


def write_report(self, path):
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
              markup=False, font_size=12, bold_first_col=False, pad=3):
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
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
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
        шкала 0,1…99,9 %), по вертикали — модульный коэффициент k_p
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

        # ---------- шкала k_p: границы по краям бланка ----------
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
            # слева оставляем место для шкалы k_p
            x0, y0 = 64.0, 40.0
            x1, y1 = self.width - 10.0, self.height - 10.0
            zmin, zmax = self._z(0.1), self._z(99.9)

            def xp(p):
                return x0 + (self._z(p) - zmin) / (zmax - zmin) * (x1 - x0)

            # ---------- горизонтальная сетка по k_p ----------
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

            # ---------- слева: шкала модульных коэффициентов k_p ----------
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
                label = "Модульный коэффициент k"
                lw = c.stringWidth(label, "Times New Roman", 9.5)
                c.setFont("Times New Roman", 7)
                pw = c.stringWidth("P", "Times New Roman", 7)
                c.setFont("Times New Roman", 9.5)
                c.drawString(-(lw + pw) / 2, 0, label)
                c.setFont("Times New Roman", 7)
                c.drawString(-(lw + pw) / 2 + lw, -2.5, "p")
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
        "где ε — сторона ячейки сетки (в пикселях); N(ε) — число ячеек, "
        "через которые проходит линия реки; h — показатель степени "
        "(размерность блуждания), равный наклону прямой в логарифмических "
        "координатах.", note))
    story.append(formula_no([
        "h = 2(D − 1),&nbsp;&nbsp;&nbsp; D = 1 + ",
        sq_frac("h", "2", 13),
    ]))
    story.append(Paragraph(
        "где h — размерность блуждания (наклон аппроксимирующей прямой); "
        "D — фрактальная размерность линии реки; 1 — размерность точки.", note))
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
    ], [7.2 * cm, 9.1 * cm], pad=1.5)
    story.append(t1)
    story.append(Paragraph(
        "Пояснение: файл — имя снимка; створ — точка, выше которой "
        "измеряется русло; допуск — порог HSV-расстояния; объект — что "
        "обмеряется сеткой; пиксели воды — площадь маски.", note))

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
        "Пояснение: R² = 1,0 соответствует идеальной прямой в логарифмических "
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
        fig1.savefig(buf1, format="png", facecolor="white")
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
                             Paragraph(expl, note)])

    story.append(Paragraph("а) абсолютные погрешности", body_noind))
    story.append(err_item(
        "• для среднего значения",
        ["ε<sub>Q</sub> = ",
         sq_frac("σ<sub>Q</sub>", "n<super>1/2</super>", 13)],
        "где ε<sub>Q</sub> — абсолютная погрешность среднего расхода; "
        "σ<sub>Q</sub> — среднеквадратическое отклонение расхода воды, м³/с; "
        "n — число членов ряда наблюдений."))

    story.append(err_item(
        "• для коэффициента вариации",
        ["ε<sub>Cv</sub> = ",
         sq_frac("C<sub>v</sub>", "n + 4C<sub>v</sub>²", 13),
         "&nbsp;",
         *root(sq_frac("n(1 + C<sub>v</sub>²)", "2", 13))],
        "где ε<sub>Cv</sub> — абсолютная погрешность коэффициента вариации; "
        "C<sub>v</sub> — коэффициент вариации; n — число членов ряда "
        "наблюдений."))

    story.append(err_item(
        "• для коэффициента асимметрии",
        ["ε<sub>Cs</sub> = ",
         *root(sq_frac("6", "n", 13)),
         "(1 + 6C<sub>v</sub>² + 5C<sub>v</sub><super>4</super>)"
         "<super>1/2</super>"],
        "где ε<sub>Cs</sub> — абсолютная погрешность коэффициента асимметрии; "
        "C<sub>v</sub> — коэффициент вариации; n — число членов ряда "
        "наблюдений."))

    story.append(Paragraph("б) относительные погрешности", body_noind))
    story.append(err_item(
        "• для среднего значения",
        ["ε<sub>Q, %</sub> = ",
         sq_frac("C<sub>v</sub>", "n<super>1/2</super>", 13),
         "·100 %"],
        "где ε<sub>Q, %</sub> — относительная погрешность среднего расхода, %; "
        "C<sub>v</sub> — коэффициент вариации; n — число членов ряда "
        "наблюдений."))

    story.append(err_item(
        "• для коэффициента вариации",
        ["ε<sub>Cv, %</sub> = ",
         sq_frac("1", "n + 4C<sub>v</sub>²", 13),
         "&nbsp;",
         *root(sq_frac("n(1 + C<sub>v</sub>²)", "2", 13)),
         "·100 %"],
        "где ε<sub>Cv, %</sub> — относительная погрешность коэффициента "
        "вариации, %; C<sub>v</sub> — коэффициент вариации; n — число "
        "членов ряда наблюдений."))

    story.append(err_item(
        "• для коэффициента асимметрии",
        ["ε<sub>Cs, %</sub> = ",
         sq_frac("1", "C<sub>s</sub>", 13),
         *root(sq_frac("6", "n", 13)),
         "(1 + 6C<sub>v</sub>² + 5C<sub>v</sub><super>4</super>)"
         "<super>1/2</super>·100 %"],
        "где ε<sub>Cs, %</sub> — относительная погрешность коэффициента "
        "асимметрии, %; C<sub>s</sub> — коэффициент асимметрии; C<sub>v</sub> "
        "— коэффициент вариации; n — число членов ряда наблюдений."))

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
        "k<sub>p</sub>", markup=True))

    # ---------------- VII. таблица P, k_p, Q_P + пояснения ----------------
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.append(sect(
        "VII. Расчёт ординат теоретической кривой обеспеченности"))
    story.append(Paragraph(
        "В таблице 5 приведены ординаты теоретической кривой: "
        "обеспеченность P, модульные коэффициенты k<sub>p</sub> и "
        "соответствующие расходы воды Q<sub>P</sub>.", body))
    # вводный текст до таблицы
    story.append(tbl_caption(
        "Таблица 5 — Ординаты теоретической кривой", markup=True))
    p_majors = ProbGrid.major_p
    # вертикальная таблица: строка = значение обеспеченности
    t5_rows = [["Обеспеченность<br/>P, %", "Модульный коэффициент<br/>k<sub>p</sub>",
                "Расход воды<br/>Q<sub>P</sub>, м³/с"]]
    for p in p_majors:
        t5_rows.append([("%g" % p).replace(".", ","),
                        fmt(kp_by_p[p], 2),
                        fmt(kp_by_p[p] * q_mean, 1)])
    story.append(table(t5_rows, [5.4 * cm, 5.4 * cm, 5.4 * cm],
                       header=True, center=True, keep_whole=True,
                       markup=True))
    story.append(Paragraph(
        "Пояснение: P — обеспеченность (вероятность превышения), %; "
        "k<sub>p</sub> — модульный коэффициент; Q<sub>P</sub> = "
        "k<sub>p</sub>·Q<sub>ср</sub> — расход воды заданной обеспеченности, "
        "м³/с. Строки соответствуют основным значениям P рисунка 4.", note))

    story.append(PageBreak())      # пояснения — на отдельной странице
    story.append(sect("Порядок вычисления", level=2))
    story.append(Paragraph(
        "Теоретическая кривая строится по трём характеристикам стока — "
        "Q<sub>ср</sub>, C<sub>v</sub> и C<sub>s</sub>. Расход воды "
        "обеспеченности P вычисляется по формуле", body))
    story.append(formula_no([
        "Q<sub>P</sub> = (Φ<sub>P</sub>·C<sub>v</sub> + 1)·"
        "Q<sub>ср</sub> = k<sub>p</sub>·Q<sub>ср</sub>",
    ]))
    story.append(Paragraph(
        "где Q<sub>P</sub> — расход воды обеспеченности P, м³/с; Φ<sub>P</sub> "
        "— коэффициент Фостера–Рыбкина; C<sub>v</sub> — коэффициент вариации; "
        "Q<sub>ср</sub> — средний многолетний расход; k<sub>p</sub> — модульный "
        "коэффициент.", note))
    story.append(formula_no([
        "Φ<sub>P</sub> = z<sub>P</sub> + (C<sub>s</sub>/6)·"
        "(z<sub>P</sub>² − 1)",
    ]))
    story.append(Paragraph(
        "где Φ<sub>P</sub> — коэффициент Фостера–Рыбкина; z<sub>P</sub> — "
        "квантиль стандартного нормального распределения для обеспеченности "
        "P; C<sub>s</sub> — коэффициент асимметрии.", note))
    story.append(formula_no([
        "k<sub>p</sub> = Φ<sub>P</sub>·C<sub>v</sub> + 1",
    ]))
    story.append(Paragraph(
        "где k<sub>p</sub> — модульный коэффициент, показывающий, во сколько "
        "раз расход обеспеченности P отличается от Q<sub>ср</sub>; Φ<sub>P</sub> "
        "— коэффициент Фостера–Рыбкина; C<sub>v</sub> — коэффициент вариации.", note))
    story.append(Paragraph(
        f"В формулах ({p_no[0] - 1}) и ({p_no[0]}) z<sub>P</sub> — квантиль "
        "стандартного нормального распределения для обеспеченности P; "
        "значения Φ<sub>P</sub> определяются по стандартным таблицам "
        "(например, СП 33-101-2003). Модульные коэффициенты "
        "k<sub>p</sub> образуют вспомогательную шкалу перехода от "
        "обеспеченности к расходу.", body))

    # ---------- сборка ----------
    # Оглавление по требованию убрано: разделы нумеруются римскими
    # цифрами прямо в заголовках, их же можно печатать в колонтитуле.
    doc.build(story)
