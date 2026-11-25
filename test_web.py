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


def test_local_dem_geotiff():
    tifffile = pytest.importorskip("tifffile")
    client = web.app.test_client()
    dem = (np.arange(16 * 16, dtype=np.int16).reshape(16, 16) + 100)
    dem[0, 0] = -32768
    bio = io.BytesIO()
    tifffile.imwrite(bio, dem, extratags=[
        (33550, "d", 3, (0.01, 0.01, 0.0)),
        (33922, "d", 6, (0.0, 0.0, 0.0, 30.0, 60.0, 0.0)),
        (34735, "H", 8, (1, 1, 0, 1, 2048, 0, 1, 4326)),
        (42113, "s", 6, "-32768"),
    ])
    data = "data:image/tiff;base64," + base64.b64encode(bio.getvalue()).decode("ascii")
    try:
        uploaded = client.post("/api/dem/upload", json={
            "files": [{"name": "dem.tif", "data": data}]})
        assert uploaded.status_code == 200
        tile = uploaded.json["tiles"][0]
        assert tile["name"] == "dem.tif"
        assert (tile["west"], tile["north"]) == (30.0, 60.0)
        assert round(tile["east"] - tile["west"], 5) == 0.16

        view = client.post("/api/map/view", json={
            "lon": 30.08, "lat": 59.92, "zoom": 12, "width": 240,
            "height": 180, "relief": True})
        assert view.status_code == 200
        assert "локальный DEM GeoTIFF" in view.json["credit"]

        far = client.post("/api/map/view", json={
            "lon": 41.7, "lat": 43.5, "zoom": 11, "width": 240,
            "height": 180, "relief": True})
        assert far.status_code == 200
        assert "локальный DEM GeoTIFF" not in far.json["credit"]

        lon, lat, zoom = 30.08, 59.92, 12
        cx, cy = web.map_core.lonlat_to_tile(lon, lat, zoom)
        geo = {"x0": cx - 240 / 512.0, "y0": cy - 180 / 512.0, "z": zoom,
               "w": 240, "h": 180, "center_lon": lon, "center_lat": lat}
        dz = web.map_core.best_dem_zoom(zoom, lat)
        heights, dgeo = web.map_core.fetch_dem_for_view(geo, dz, margin=0)
        assert dgeo["view_z"] == zoom
        assert np.nanmin(heights) < np.nanmax(heights)
        assert np.nanmin(heights) > 0  # GDAL_NODATA не попал в высоты
    finally:
        client.post("/api/dem/clear", json={})
    assert not web.LOCAL_DEMS


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
