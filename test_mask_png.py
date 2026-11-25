# -*- coding: utf-8 -*-
"""test_mask_png.py — проверка сохранения маски: цвета + метаданные PNG."""
import numpy as np
from PIL import Image
from river_fractal import write_mask_png, load_image_as_rgb_array, segment_water

img = load_image_as_rgb_array("demo_synthetic_river.png")
yy = lambda x: int(round(256 + 70 * np.sin(2 * np.pi * x / 170.0)
                         + 25 * np.sin(2 * np.pi * x / 61.0)))
seed = (100, yy(100))
mask = segment_water(img, seed, method="color", tol=70, keep_largest=True)

# с масштабом
write_mask_png("demo_mask_out.png", mask, scale_text="0.5",
               image_path="demo_synthetic_river.png", seed_xy=seed)
im = Image.open("demo_mask_out.png")
arr = np.asarray(im)
print("режим:", im.mode, "| размер:", arr.shape, "(ожидалось (512, 512))")
print("река чёрная (0):", arr[mask].mean() == 0.0, "| фон белый (255):", arr[~mask].mean() == 255.0)
print("dpi:", im.info.get("dpi"))
for key in ("Dimensions", "Resolution", "Scale", "Source", "Water pixels",
            "Seed point", "Created", "Software", "Description"):
    print(f"  {key}: {im.info.get(key)}")
assert im.info.get("Scale") == "0.5 m/px"
assert str(im.info.get("Dimensions")).startswith("512 x 512")
assert im.info.get("Resolution") == "300 dpi"
assert arr[mask].mean() == 0.0 and arr[~mask].mean() == 255.0

# без масштаба → Scale: not set
write_mask_png("demo_mask_out2.png", mask, scale_text="",
               image_path="demo_synthetic_river.png", seed_xy=seed)
im2 = Image.open("demo_mask_out2.png")
print("Scale без ввода:", im2.info.get("Scale"))
assert im2.info.get("Scale") == "not set"
print("Все проверки маски пройдены.")
