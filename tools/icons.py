"""Gera o ícone do app (mesmo desenho no Android e no Windows).

    python tools/icons.py

Saídas: android/app/src/main/res/drawable/ic_launcher_*.xml e pc/icon.ico.
"""
import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAD = ("#4338CA", "#7C3AED")  # fundo: índigo -> violeta (diagonal)

# Formas na grade 108x108 do ícone adaptativo: (x0, y0, x1, y1, raio, cor)
SHAPES = [
    (24, 30, 70, 61, 4, "#F1F5F9"),    # monitor
    (27, 33, 67, 58, 2, "#312E81"),    # tela do monitor
    (44, 61, 50, 66, 0, "#F1F5F9"),    # pescoço
    (37, 66, 57, 69, 1.5, "#F1F5F9"),  # base
    (55, 41, 87, 83, 6, "#1E1B4B"),    # contorno do tablet
    (58, 44, 84, 80, 4, "#22D3EE"),    # tablet
    (60.5, 47, 81.5, 76, 2, "#312E81"),  # tela do tablet (mesma do monitor = espelho)
    (68, 78, 72, 79, 0.5, "#0E7490"),      # botão
]


def rounded_path(x0, y0, x1, y1, r):
    if not r:
        return f"M{x0},{y0} H{x1} V{y1} H{x0} Z"
    a = f"A{r},{r} 0 0 1"
    return (f"M{x0 + r},{y0} H{x1 - r} {a} {x1},{y0 + r} V{y1 - r} {a} {x1 - r},{y1} "
            f"H{x0 + r} {a} {x0},{y1 - r} V{y0 + r} {a} {x0 + r},{y0} Z")


def android():
    res = os.path.join(ROOT, "android", "app", "src", "main", "res", "drawable")
    os.makedirs(res, exist_ok=True)
    paths = "\n".join(f'    <path android:fillColor="{c}" android:pathData="{rounded_path(*s)}" />'
                      for *s, c in SHAPES)
    with open(os.path.join(res, "ic_launcher_foreground.xml"), "w", encoding="utf-8") as f:
        f.write('<vector xmlns:android="http://schemas.android.com/apk/res/android"\n'
                '    android:width="108dp" android:height="108dp"\n'
                '    android:viewportWidth="108" android:viewportHeight="108">\n'
                f"{paths}\n</vector>\n")
    with open(os.path.join(res, "ic_launcher_background.xml"), "w", encoding="utf-8") as f:
        f.write('<shape xmlns:android="http://schemas.android.com/apk/res/android">\n'
                f'    <gradient android:angle="315" android:startColor="{GRAD[0]}" android:endColor="{GRAD[1]}" />\n'
                "</shape>\n")


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def render(size=1024, lo=14, hi=94):
    """Desenha a área [lo, hi] da grade 108 num quadrado arredondado."""
    a, b = hex_rgb(GRAD[0]), hex_rgb(GRAD[1])
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
    mask = Image.new("L", (size, size))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 0.22, fill=255)
    img = Image.new("RGBA", (size, size))
    img.paste(grad, mask=mask)
    d = ImageDraw.Draw(img)
    k = size / (hi - lo)
    for x0, y0, x1, y1, r, c in SHAPES:
        d.rounded_rectangle(((x0 - lo) * k, (y0 - lo) * k, (x1 - lo) * k, (y1 - lo) * k), radius=r * k, fill=c)
    return img.resize((256, 256), Image.LANCZOS)


if __name__ == "__main__":
    android()
    img = render()
    img.save(os.path.join(ROOT, "pc", "icon.ico"), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    img.save(os.path.join(ROOT, "pc", "icon.png"))
    print("ícones gerados")
