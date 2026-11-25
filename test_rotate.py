# -*- coding: utf-8 -*-
"""test_rotate.py — интеграционная проверка поворотов/отражений снимка."""
import types
import numpy as np
from river_fractal import load_image_as_rgb_array, segment_water, RiverFractalApp

img = load_image_as_rgb_array("demo_synthetic_river.png")
yy = lambda x: int(round(256 + 70 * np.sin(2 * np.pi * x / 170.0)
                         + 25 * np.sin(2 * np.pi * x / 61.0)))
seed = (100, yy(100))
mask = segment_water(img, seed, method="color", tol=70, keep_largest=True)

fake = types.SimpleNamespace()
fake.rgb = img.copy()
fake.mask = mask.copy()
fake.seed_xy = seed
fake.result = None
fake.image_path = "demo_synthetic_river.png"
fake.scale = 1.0
fake._set_status = lambda s: None
fake.refresh_canvas = lambda: None
fake._reset_view_state = types.MethodType(RiverFractalApp._reset_view_state, fake)
fake.rotate_view = types.MethodType(RiverFractalApp.rotate_view, fake)

snap = (fake.rgb.copy(), fake.mask.copy(), fake.seed_xy)

# 4 поворота по 90° против часовой → всё возвращается к исходному
for _ in range(4):
    fake.rotate_view("rot1")
print("после 4× rot1: rgb совпадает:", np.array_equal(fake.rgb, snap[0]),
      "| mask совпадает:", np.array_equal(fake.mask, snap[1]),
      "| seed:", fake.seed_xy)

# 2 отражения слева-направо → исходное состояние
fake.rotate_view("fliph"); fake.rotate_view("fliph")
print("после 2× fliph: rgb совпадает:", np.array_equal(fake.rgb, snap[0]),
      "| mask совпадает:", np.array_equal(fake.mask, snap[1]),
      "| seed:", fake.seed_xy)

# 2 отражения сверху-вниз → исходное состояние
fake.rotate_view("flipv"); fake.rotate_view("flipv")
print("после 2× flipv: rgb совпадает:", np.array_equal(fake.rgb, snap[0]),
      "| mask совпадает:", np.array_equal(fake.mask, snap[1]))

# связность: маркер соответствует пикселю той же реки после rot3
fake.rotate_view("rot3")
x, y = int(fake.seed_xy[0]), int(fake.seed_xy[1])
print("после rot3 маркер на воде (HSV-близкой):", fake.mask[y, x],
      "(ожидается True)")
