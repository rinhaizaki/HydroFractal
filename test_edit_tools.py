# -*- coding: utf-8 -*-
"""test_edit_tools.py — проверки новых возможностей:
   1) отмена/повтор правок маски (вперёд-назад);
   2) дополнительные точки-эталоны цвета для сегментации.
Работает на настоящих функциях из river_fractal.py без запуска GUI.
"""
import numpy as np

from river_fractal import segment_water, load_image_as_rgb_array

img = load_image_as_rgb_array("demo_synthetic_river.png")
yy = lambda x: int(round(256 + 70 * np.sin(2 * np.pi * x / 170.0)
                         + 25 * np.sin(2 * np.pi * x / 61.0)))
seed = (100, yy(100))

# --- 1) базовая сегментация по одной точке ---
m1 = segment_water(img, seed, method="color", tol=70, keep_largest=True)
print("маска по основной точке:", m1.sum(), "px")

# --- 2) дополнительная точка НЕ уменьшает маску (правило «ИЛИ») ---
extra = [(300, yy(300))]
m2 = segment_water(img, seed, method="color", tol=70, keep_largest=True,
                   extra_points=extra)
print("маска с доп. точкой:    ", m2.sum(), "px")
assert m2.sum() >= m1.sum(), "доп. точка не должна сужать выделение"
assert np.all(m2 >= m1), "всё, что было водой, должно остаться водой"

# --- 3) доп. точка другого цвета РАСШИРЯЕТ маску ---
# берём точку на зелёном фоне (не вода) — её цвет добавит фон в маску
bg_point = (20, 20)
m3 = segment_water(img, seed, method="color", tol=70, keep_largest=False,
                   extra_points=[bg_point])
print("маска с точкой фона:    ", m3.sum(), "px")
assert m3.sum() > m1.sum(), "эталон другого цвета должен добавлять пиксели"

# --- 4) пустой список доп. точек работает как раньше ---
m4 = segment_water(img, seed, method="color", tol=70, keep_largest=True,
                   extra_points=[])
assert np.array_equal(m4, m1), "пустой список не должен менять результат"
print("пустой список доп. точек: результат идентичен — ок")


# --- 5) логика отмены/повтора (на массивах, без GUI) ---
class MiniHistory:
    """Повторяет логику _push_undo / undo / redo из приложения."""

    def __init__(self, mask):
        self.mask = mask.copy()
        self._undo, self._redo = [], []

    def snap(self):
        return self.mask.copy()

    def push(self, snapshot=None):
        self._undo.append(snapshot if snapshot is not None else self.snap())
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(self.snap())
        self.mask = self._undo.pop()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(self.snap())
        self.mask = self._redo.pop()
        return True


h = MiniHistory(m1)
state0 = h.mask.sum()

# штрих 1 — стёрли прямоугольник
h.push()
h.mask[100:200, 100:200] = False
s1 = h.mask.sum()
assert s1 < state0

# штрих 2 — дорисовали ещё
h.push()
h.mask[300:340, 200:260] = True
s2 = h.mask.sum()

# назад → вернулись к состоянию после штриха 1
assert h.undo() and h.mask.sum() == s1, "отмена вернула не то состояние"
# назад → вернулись к исходному
assert h.undo() and h.mask.sum() == state0, "вторая отмена вернула не то"
# отменять больше нечего
assert not h.undo(), "отмена должна сообщать, что история пуста"
# вперёд → состояние после штриха 1
assert h.redo() and h.mask.sum() == s1, "повтор вернул не то состояние"
# вперёд → после штриха 2
assert h.redo() and h.mask.sum() == s2, "второй повтор вернул не то"
assert not h.redo(), "повтор должен сообщать, что история пуста"
print("отмена/повтор: все состояния совпали — ок")

# новое действие очищает историю «вперёд»
h.undo()
h.push()
assert not h.redo(), "новое действие должно очищать историю повтора"
print("новое действие очищает «вперёд» — ок")

# --- 6) реалистичный сценарий: мутный приток другого оттенка ---
img2 = img.copy()
h2, w2 = img2.shape[:2]
yy2 = lambda x: int(round(256 + 70 * np.sin(2 * np.pi * x / 170.0)
                          + 25 * np.sin(2 * np.pi * x / 61.0)))
mx, my = 300, yy2(300)
Y, X = np.ogrid[:h2, :w2]
circle = (X - mx) ** 2 + (Y - my) ** 2 <= 30 ** 2
img2[circle] = (150, 120, 80)                # мутная вода

m_plain = segment_water(img2, seed, method="color", tol=60,
                        keep_largest=False)
m_with = segment_water(img2, seed, method="color", tol=60,
                       keep_largest=False, extra_points=[(mx, my)])
cov_plain = (m_plain & circle).sum() / circle.sum()
cov_with = (m_with & circle).sum() / circle.sum()
print(f"мутный участок: без точки {cov_plain*100:.0f}%, "
      f"с точкой {cov_with*100:.0f}%")
assert cov_with > cov_plain + 0.3, "доп. точка должна добавлять участок"

# --- 7) эталон берётся по медиане кружка, а не по одному пикселю ---
# ставим точку на шумном участке и проверяем устойчивость результата
m_a = segment_water(img, (101, yy2(101)), method="color", tol=60,
                    keep_largest=False)
m_b = segment_water(img, (100, yy2(100)), method="color", tol=60,
                    keep_largest=False)
diff = abs(int(m_a.sum()) - int(m_b.sum())) / max(int(m_a.sum()), 1)
print(f"соседние точки дают маски, различающиеся на {diff*100:.1f}%")
assert diff < 0.25, "результат не должен сильно зависеть от пикселя клика"

print("\nВсе проверки правок (отмена/повтор, доп. точки цвета) пройдены.")
