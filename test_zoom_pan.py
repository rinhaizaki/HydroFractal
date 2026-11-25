# -*- coding: utf-8 -*-
"""test_zoom_pan.py — логика зума и панорамирования без GUI."""
import types
import numpy as np
from river_fractal import RiverFractalApp, CANVAS_W, CANVAS_H

def make_fake():
    fake = types.SimpleNamespace()
    fake.rgb = np.zeros((512, 512, 3), dtype=np.uint8)
    fake.scale = 1.0
    fake.zoom = 1.0
    fake.view_cx = None
    fake.view_cy = None
    fake._view_cache = None
    fake._pan_state = None
    fake.canvas = types.SimpleNamespace(winfo_width=lambda: CANVAS_W,
                                        winfo_height=lambda: CANVAS_H)
    fake._canvas_size = types.MethodType(RiverFractalApp._canvas_size, fake)
    fake._base_fit = types.MethodType(RiverFractalApp._base_fit, fake)
    fake._current_view = types.MethodType(RiverFractalApp._current_view, fake)
    fake._reset_view_state = types.MethodType(RiverFractalApp._reset_view_state, fake)
    fake._zoom_at = types.MethodType(RiverFractalApp._zoom_at, fake)
    fake.reset_zoom = types.MethodType(RiverFractalApp.reset_zoom, fake)
    fake._pan_start = types.MethodType(RiverFractalApp._pan_start, fake)
    fake._pan_move = types.MethodType(RiverFractalApp._pan_move, fake)
    fake.refresh_canvas = lambda: setattr(fake, "_view_cache", fake._current_view())
    fake._set_status = lambda s: setattr(fake, "status", s)
    fake.refresh_canvas()
    return fake

fake = make_fake()
print("старт: zoom =", fake.zoom, "(ожидается 1.0)")

# колесо мыши вверх: зум к курсору (в центре холста)
fake._zoom_at(1.15 ** 5)          # ≈ ×2
print("после 5 шагов зума: zoom =", round(fake.zoom, 3))
v = fake._view_cache
print(f"вид: x0={v['x0i']}..{v['x1i']}, sc={v['sc']:.2f} (ожидается sc≈2)")
assert abs(v["sc"] - fake.zoom * fake._base_fit()) < 0.05

# якорный зум к левому краю: точка под курсором не должна уехать
fake = make_fake()
fake._zoom_at(2.0, anchor=(0, 0))
v1 = fake._current_view()
print("якорь (0,0), zoom 2×: x0 =", v1["x0i"], "(ожидается 0 — левый верх в углу)")

# панорама вправо на 100 px холста: вид сдвигается на 100/s px
fake = make_fake()
fake._zoom_at(2.0)                       # вид по центру
cx0 = fake.view_cx
fake._pan_start(types.SimpleNamespace(x=430, y=310))
fake._pan_move(types.SimpleNamespace(x=330, y=310))   # тянем влево → вид вправо
shift = fake.view_cx - cx0
print(f"панорама: центр видa сдвинулся на {shift:.1f} px снимка (ожидается +50 при sc=2)")
assert shift > 0

# зажатие у края: вид не может выйти за снимок
fake = make_fake()
fake._zoom_at(4.0)
fake.view_cx = -10000.0
v = fake._current_view()
print(f"зажатие слева: x0 = {v['x0i']} (ожидается 0)")
assert v["x0i"] == 0
fake.view_cx = 10000.0
v = fake._current_view()
print(f"зажатие справа: x1 = {v['x1i']} (ожидается 512)")
assert v["x1i"] == 512

# сброс зума
fake.reset_zoom()
print("после reset_zoom: zoom =", fake.zoom)
assert fake.zoom == 1.0
print("Все проверки зума и панорамы пройдены.")
