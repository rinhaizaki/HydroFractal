# -*- coding: utf-8 -*-
"""Смоук-тесты веб-приложения: страница и основной конвейер расчётов."""
import base64
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw

import app as web


def river_image_data_url():
    rgb = np.full((220, 300, 3), [118, 137, 86], dtype=np.uint8)
    img = Image.fromarray(rgb, "RGB")
    d = ImageDraw.Draw(img)
    main = [(int(150 + 42 * np.sin(y / 28)), y) for y in range(220)]
    d.line(main, fill=(26, 66, 92), width=12)
    for dx, dy in [(-90, -70), (85, -95), (-120, -25), (105, -40)]:
        x, y = main[150]
        d.line([(x, y), (x + dx, y + dy)], fill=(32, 72, 98), width=6)
    bio = io.BytesIO()
    img.save(bio, "PNG")
    return "data:image/png;base64," + base64.b64encode(bio.getvalue()).decode("ascii")


def test_index_and_health():
    client = web.app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json["ok"] is True
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_photo_pipeline():
    client = web.app.test_client()
    image = river_image_data_url()

    uploaded = client.post("/api/upload", json={"image": image})
    assert uploaded.status_code == 200
    assert uploaded.json["width"] == 300

    segmented = client.post("/api/segment", json={
        "image": image, "seed": {"x": 150, "y": 10},
        "tol": 70, "method": "color", "keep_largest": True,
    })
    assert segmented.status_code == 200
    assert segmented.json["water_pixels"] > 100
    mask = segmented.json["mask"]

    analyzed = client.post("/api/analyze", json={"mask": mask, "object": "skeleton"})
    assert analyzed.status_code == 200
    result = analyzed.json["result"]
    assert 1.0 <= result["D"] <= 2.0
    assert result["table"] and result["plot"].startswith("data:image/png")

    mask_png = client.post("/api/mask/png", json={"mask": mask, "source_name": "test.png"})
    assert mask_png.status_code == 200
    assert mask_png.mimetype == "image/png"

    report = client.post("/api/report", json={
        "title": "тест", "result": result, "table": result["table"],
        "stream": result["stream"], "plot": result["plot"],
    })
    assert report.status_code == 200
    assert report.data[:4] == b"%PDF"


def test_tiff_ndwi_upload():
    tifffile = pytest.importorskip("tifffile")
    client = web.app.test_client()
    green = np.full((60, 80), 60, np.uint8)
    nir = np.full((60, 80), 120, np.uint8)
    green[15:45, 20:60] = 180
    nir[15:45, 20:60] = 40
    rgb = np.stack([green // 2, green, nir], axis=2)
    bio = io.BytesIO()
    tifffile.imwrite(bio, rgb)
    data = "data:image/tiff;base64," + base64.b64encode(bio.getvalue()).decode("ascii")

    resp = client.post("/api/tiff/ndwi", json={
        "files": [{"name": "water.tif", "data": data}],
        "green": 2, "nir": 3, "threshold": -0.25, "max": 0.9})
    assert resp.status_code == 200
    assert resp.json["ok"] is True
    assert resp.json["water_pixels"] == 40 * 30
    assert (resp.json["width"], resp.json["height"]) == (80, 60)
    assert resp.json["photo"].startswith("data:image/png")
    assert resp.json["mask"].startswith("data:image/png")
    assert 20 <= resp.json["seed"]["x"] <= 60
    assert resp.json["max"] == 0.9

    # Потоковая загрузка больших файлов: multipart вместо base64.
    streamed = client.post("/api/tiff/ndwi/file", data={
        "files": (io.BytesIO(bio.getvalue()), "water.tif"),
        "green": "2", "nir": "3", "threshold": "-0.25"
    }, content_type="multipart/form-data")
    assert streamed.status_code == 200
    assert streamed.json["water_pixels"] == 40 * 30


def test_map_pipeline():
    client = web.app.test_client()
    view = client.post("/api/map/view", json={
        "lon": 41.7, "lat": 43.5, "zoom": 11, "width": 480, "height": 320,
    })
    assert view.status_code == 200
    assert view.json["image"].startswith("data:image/jpeg")

    analyzed = client.post("/api/map/analyze", json={
        "lon": 41.7, "lat": 43.5, "zoom": 11, "width": 480, "height": 320,
        "outlet_lon": 41.7, "outlet_lat": 43.5,
    })
    assert analyzed.status_code == 200
    assert analyzed.json["map"]["area_km2"] > 0
    assert 1.0 <= analyzed.json["result"]["D"] <= 2.0
    # Водосбор и речная сеть отдаются в размере окна карты — оттуда они
    # превращаются в обрезанный «фотоснимок» на вкладке «Фотоснимок».
    assert analyzed.json["catchment"].startswith("data:image/png")
    assert analyzed.json["network"].startswith("data:image/png")
    catch_img = Image.open(io.BytesIO(base64.b64decode(
        analyzed.json["catchment"].split(",", 1)[1])))
    assert catch_img.size == (480, 320)
    assert catch_img.getbbox()  # водосбор не пустой
    assert 0 <= analyzed.json["outlet_px"]["x"] <= 480
    assert 0 <= analyzed.json["outlet_px"]["y"] <= 320
    assert analyzed.json["geo"]["z"] == 11
