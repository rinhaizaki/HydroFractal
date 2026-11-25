# -*- coding: utf-8 -*-
"""test_geometry.py — клик по холсту попадает ровно в точку снимка
(при всяком масштабе), и зум/панорама работают согласованно."""
import types
import numpy as np
from river_fractal import RiverFractalApp, CANVAS_W, CANVAS_H

def make_fake(zoom=1.0, view_cx=None, view_cy=None, cw=CANVAS_W, ch=CANVAS_H):
    fake = types.SimpleNamespace()
    fake.rgb = np.zeros((512, 512, 3), dtype=np.uint8)
    fake.scale = 1.0
    fake.zoom = zoom
    fake.view_cx = view_cx
    fake.view_cy = view_cy
    fake._view_cache = None
    fake.canvas = types.SimpleNamespace(winfo_width=lambda: cw,
                                        winfo_height=lambda: ch)
    fake._canvas_size = types.MethodType(RiverFractalApp._canvas_size, fake)
    fake._base_fit = types.MethodType(RiverFractalApp._base_fit, fake)
    fake._current_view = types.MethodType(RiverFractalApp._current_view, fake)
    fake._event_to_image_xy = types.MethodType(RiverFractalApp._event_to_image_xy, fake)
    fake._view_cache = fake._current_view()
    return fake

print("== зум 100%: изображение отцентровано, клик попадает точно ==")
fake = make_fake()
off_x, off_y = (CANVAS_W - 512) // 2, (CANVAS_H - 512) // 2
for img_x, img_y in [(0, 0), (100, 100), (511, 511), (256, 200)]:
    ev = types.SimpleNamespace(x=off_x + img_x, y=off_y + img_y)
    got = fake._event_to_image_xy(ev)
    ok = got is not None and abs(got[0] - img_x) < 1e-9 and abs(got[1] - img_y) < 1e-9
    print(f"клик({ev.x},{ev.y}) → ({got[0]:.1f},{got[1]:.1f})  ожидалось ({img_x},{img_y})  {'OK' if ok else 'FAIL'}")

print("== клики мимо снимка отбрасываются ==")
for ev in [types.SimpleNamespace(x=0, y=0), types.SimpleNamespace(x=CANVAS_W - 1, y=CANVAS_H - 1)]:
    print(f"клик мимо({ev.x},{ev.y}) → {fake._event_to_image_xy(ev)}  (ожидается None)")

print("== зум 200%, вид по центру: центр холста = центр снимка ==")
fake = make_fake(zoom=2.0)
view = fake._current_view()
print(f"вид: x0={view['x0i']}, y0={view['y0i']}, sc={view['sc']:.2f}, off=({view['off_x']},{view['off_y']})")
ev = types.SimpleNamespace(x=view["off_x"] + view["disp_w"] / 2,
                           y=view["off_y"] + view["disp_h"] / 2)
got = fake._event_to_image_xy(ev)
print(f"центр холста → ({got[0]:.1f},{got[1]:.1f})  (ожидается ~256, ~256)")

print("== зум 400%, вид, центрированный на (300, 200) ==")
fake = make_fake(zoom=4.0, view_cx=300, view_cy=200)
view = fake._current_view()
ev = types.SimpleNamespace(x=view["off_x"] + view["disp_w"] / 2,
                           y=view["off_y"] + view["disp_h"] / 2)
got = fake._event_to_image_xy(ev)
ok = got is not None and abs(got[0] - 300) < 1.0 and abs(got[1] - 200) < 1.0
print(f"центр холста → ({got[0]:.1f},{got[1]:.1f})  (ожидается ~300, ~200)  {'OK' if ok else 'FAIL'}")

print("== вид за пределами снимка зажимается ==")
fake = make_fake(zoom=4.0, view_cx=-500, view_cy=9999)
view = fake._current_view()
print(f"вид: x0={view['x0i']}, y0={view['y0i']}  (ожидается x0>=0, y0+vh<=512)")

print("== растянутое окно: геометрия согласована ==")
fake = make_fake(cw=1200, ch=900)
view = fake._current_view()
ev = types.SimpleNamespace(x=view["off_x"] + view["disp_w"] / 2,
                           y=view["off_y"] + view["disp_h"] / 2)
got = fake._event_to_image_xy(ev)
print(f"центр холста → ({got[0]:.1f},{got[1]:.1f})  (ожидается ~256, ~256)")
