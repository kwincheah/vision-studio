"""Labelled pass/fail images for the tasks whose request fully decides the verdict (800x600, like the app's samples).

color_check: mostly green (pass) vs grey with a 1% green patch (fail)
blob_count: 5 dark parts on a bright backlit tray (pass) vs 7 parts (fail)
defect_check: clean brushed metal (pass) vs the same with dark scratches and dirt across it (fail)
read_label: label reading SN-48213 (pass) vs XN-48213 (fail)
"""
import os

import cv2
import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labelled")
W, H = 800, 600
rng = np.random.default_rng(7)


def save(name, img):
    cv2.imwrite(os.path.join(OUT, name), img)


# colour
g = np.zeros((H, W, 3), np.uint8); g[:] = (60, 170, 60); save("color_check_pass.png", g)
f = np.full((H, W, 3), 128, np.uint8); f[280:320, 380:500] = (60, 170, 60); save("color_check_fail.png", f)  # 4800 px = 1%

# blobs: dark discs on bright background
def tray(n):
    img = np.full((H, W, 3), 235, np.uint8)
    xs = np.linspace(110, 690, n).astype(int)
    for i, x in enumerate(xs):
        cv2.circle(img, (int(x), 300 + (60 if i % 2 else -60)), 34, (30, 30, 30), -1)
    return img
save("blob_count_pass.png", tray(5)); save("blob_count_fail.png", tray(7))

# metal surface
base = np.full((H, W), 150, np.float32) + rng.normal(0, 4, (H, W)).astype(np.float32)
base = cv2.blur(base, (25, 1))
metal = cv2.cvtColor(np.clip(base, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
save("defect_check_pass.png", metal)
bad = metal.copy()
for y in range(60, H, 90):
    cv2.line(bad, (20, y), (W - 20, y + 40), (40, 40, 40), 4)
for x in range(80, W, 140):
    cv2.circle(bad, (x, 300), 14, (35, 35, 35), -1)
save("defect_check_fail.png", bad)

# label text
def label(text):
    img = np.full((H, W, 3), 245, np.uint8)
    cv2.putText(img, text, (150, 330), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (20, 20, 20), 8, cv2.LINE_AA)
    return img
save("read_label_pass.png", label("SN-48213")); save("read_label_fail.png", label("XN-48213"))
print(sorted(os.listdir(OUT)))
