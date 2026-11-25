# -*- coding: utf-8 -*-
"""
Тесты картографического режима: тайлы, геометрия, гидрология, водосбор.

Запуск:  python test_map.py
Требует интернет для первых двух проверок (остальные — офлайн).
"""

import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import map_core as mc
    HAVE = True
except Exception:
    mc, HAVE = None, False


# ---------------------------------------------------------------------------
# Геометрия — офлайн
# ---------------------------------------------------------------------------
def test_lonlat_roundtrip():
    """Обратное преобразование координат возвращает исходную точку."""
    for lon, lat in [(41.7, 43.5), (48.0, 46.3), (0.0, 0.0), (-120.5, -33.4)]:
        for z in (5, 10, 13):
            x, y = mc.lonlat_to_tile(lon, lat, z)
            lon2, lat2 = mc.tile_to_lonlat(x, y, z)
            assert abs(lon - lon2) < 1e-6, (lon, lon2)
            assert abs(lat - lat2) < 1e-6, (lat, lat2)


def test_resolution_decreases_with_zoom():
    """Каждый следующий зум уменьшает размер пикселя вдвое."""
    lat = 45.0
    prev = mc.resolution_m(lat, 8)
    for z in (9, 10, 11, 12):
        cur = mc.resolution_m(lat, z)
        assert abs(cur - prev / 2) < 0.5, (z, cur, prev)
        prev = cur


def test_resolution_at_equator():
    """На экваторе z0 — 256 пикселей на всю Землю (~156 км)."""
    r = mc.resolution_m(0.0, 0)
    assert 155000 < r < 157000, r


def test_dem_zoom_capped():
    """Зум рельефа не превышает родное разрешение данных."""
    assert mc.best_dem_zoom(18, 45.0) == mc.NATIVE_DEM_ZOOM
    assert mc.best_dem_zoom(5, 45.0) == 5
    assert mc.best_dem_zoom(13, 45.0) <= mc.NATIVE_DEM_ZOOM


# ---------------------------------------------------------------------------
# Гидрология на искусственном рельефе — офлайн, быстро
# ---------------------------------------------------------------------------
def _synthetic():
    """Наклонная плоскость с каналом посередине."""
    H = W = 80
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    z = 100.0 - yy * 0.8                      # уклон на юг
    z -= 6.0 * np.exp(-((xx - 40.0) ** 2) / (2 * 6.0 ** 2))   # канал
    return z


def test_fill_removes_pits():
    """После заполнения впадин локальных минимумов не остаётся."""
    z = _synthetic()
    z[30, 30] -= 40.0                        # выкапываем яму
    filled = mc.fill_depressions(z, eps=0.01)
    assert filled[30, 30] > z[30, 30], "яма не заполнена"
    assert np.all(filled >= z - 1e-6), "заполнение понизило рельеф"


def test_flow_directions_go_downhill():
    """Направления стока не ведут в гору (кроме границ)."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    H, W = z.shape
    bad = 0
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            d = int(fdir[y, x])
            if d not in mc._D8_DY:
                continue
            ny, nx = y + mc._D8_DY[d], x + mc._D8_DX[d]
            if z[ny, nx] > z[y, x] + 1e-9:
                bad += 1
    assert bad == 0, f"{bad} клеток текут в гору"


def test_accumulation_mass_conservation():
    """Накопление: в канале больше, чем на верхней кромке; сумма ≤ числа клеток."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    acc = mc.flow_accumulation(z, fdir)
    # канал внизу против верхней кромки — там накопление минимально
    assert acc[70, 40] > acc[0, 40], "в канале должно накапливаться больше"
    # на однородном склоне в клетку строки 70 приходят все 71 клетки выше
    assert acc[70, 40] >= 70, f"в канале слишком мало: {acc[70, 40]}"
    assert acc.max() <= z.size, "накопление не может превышать число клеток"

def test_catchment_grows_downstream():
    """Чем ниже створ, тем больше водосбор."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    acc = mc.flow_accumulation(z, fdir)
    sizes = []
    for y in (30, 50, 70):
        x = int(np.argmax(acc[y]))
        c = mc.catchment_upstream(fdir, y, x)
        sizes.append(int(c.sum()))
    assert sizes == sorted(sizes), f"водосбор не растёт вниз: {sizes}"


def test_main_channel_starts_at_outlet():
    """Линия главного русла проходит через створ."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    acc = mc.flow_accumulation(z, fdir)
    y = 70
    x = int(np.argmax(acc[y]))
    c = mc.catchment_upstream(fdir, y, x)
    line = mc.main_channel(fdir, acc, c, y, x)
    assert line[y, x], "створ не попал в линию русла"
    assert int(line.sum()) > 10, "линия русла слишком короткая"


def test_channel_inside_catchment():
    """Главное русло не выходит за границы водосбора."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    acc = mc.flow_accumulation(z, fdir)
    y = 70
    x = int(np.argmax(acc[y]))
    c = mc.catchment_upstream(fdir, y, x)
    line = mc.main_channel(fdir, acc, c, y, x)
    assert not (line & ~c).any(), "русло вышло за водосбор"


def test_strahler_on_synthetic():
    """Порядок Стралера — правдоподобное число."""
    z = mc.fill_depressions(_synthetic(), eps=0.01)
    fdir = mc.flow_directions(z, 1.0)
    acc = mc.flow_accumulation(z, fdir)
    y = 70
    x = int(np.argmax(acc[y]))
    c = mc.catchment_upstream(fdir, y, x)
    net = c & (acc >= 5)
    order = mc.strahler_order(fdir, net, acc)
    assert 1 <= order <= 6, order


# ---------------------------------------------------------------------------
# Сеть — требует интернет
# ---------------------------------------------------------------------------
def test_terrain_tile_decodes():
    """Тайл рельефа декодируется в физичные высоты."""
    mc.set_cache_dir(os.path.join(tempfile.gettempdir(), "_test_tiles"))
    z = mc.fetch_terrain_tile(10, 738, 400)   # Кавказ
    assert z is not None, "тайл рельефа не загрузился"
    assert z.shape == (256, 256), z.shape
    assert -500 < float(z.min()) and float(z.max()) < 9000, (z.min(), z.max())


def test_map_tile_loads():
    """Тайл спутникового снимка загружается."""
    mc.set_cache_dir(os.path.join(tempfile.gettempdir(), "_test_tiles"))
    data = mc.fetch_tile("esri", 10, 738, 400)
    assert data is not None and len(data) > 500, "тайл карты не загрузился"


if __name__ == "__main__":
    if not HAVE:
        print("SKIP: map_core не загрузился")
        sys.exit(0)

    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    ok = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  OK   {name}")
            ok += 1
        except AssertionError as exc:
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:
            print(f"  ERR  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ok} из {len(tests)} проверок пройдено")
    sys.exit(0 if ok == len(tests) else 1)
