"""生成播客封面图（1400×1400 PNG）。

Apple Podcasts / 小宇宙 要求方形封面（建议 ≥1400px）。用 Pillow + 系统 CJK 字体绘制，
无需外部素材。在 publish 阶段自动生成到 site/cover.png。
"""
from __future__ import annotations

from pathlib import Path

from . import config

# 优先使用 CJK 字体（中文需要），按可用性回退。
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def generate(out_path: Path | None = None, size: int = 1400) -> Path:
    from PIL import Image, ImageDraw

    p = config.load_config().get("publish", {})
    title = p.get("title", "每日科技播客")
    subtitle = "每日科技动态 · 双人对话"

    img = Image.new("RGB", (size, size), (15, 17, 21))
    draw = ImageDraw.Draw(img)

    # 垂直渐变背景
    top, bottom = (18, 22, 34), (10, 12, 16)
    for y in range(size):
        draw.line([(0, y), (size, y)], fill=_lerp(top, bottom, y / size))

    # 顶部品牌强调条
    accent = (110, 168, 254)
    draw.rectangle([0, 0, size, 16], fill=accent)

    # 麦克风图标（用基本图形绘制，避免依赖 emoji 字体）
    cx, cy = size // 2, int(size * 0.34)
    r = 92
    draw.rounded_rectangle([cx - 54, cy - 120, cx + 54, cy + 40], radius=54,
                           fill=(230, 230, 230))
    draw.arc([cx - 92, cy - 60, cx + 92, cy + 110], start=20, end=160,
             fill=(230, 230, 230), width=16)
    draw.line([cx, cy + 110, cx, cy + 170], fill=(230, 230, 230), width=16)
    draw.line([cx - 60, cy + 170, cx + 60, cy + 170], fill=(230, 230, 230), width=16)

    # 标题
    tfont = _font(150)
    tw = draw.textbbox((0, 0), title, font=tfont)
    draw.text(((size - (tw[2] - tw[0])) / 2, int(size * 0.56)), title,
              font=tfont, fill=(245, 245, 245))

    # 副标题
    sfont = _font(56)
    sw = draw.textbbox((0, 0), subtitle, font=sfont)
    draw.text(((size - (sw[2] - sw[0])) / 2, int(size * 0.70)), subtitle,
              font=sfont, fill=(150, 160, 175))

    # 合规标识徽章
    badge = "AI 自动生成"
    bfont = _font(40)
    bb = draw.textbbox((0, 0), badge, font=bfont)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    bx, by = (size - bw) / 2, int(size * 0.82)
    draw.rounded_rectangle([bx - 32, by - 18, bx + bw + 32, by + bh + 22],
                           radius=40, outline=accent, width=3)
    draw.text((bx, by), badge, font=bfont, fill=accent)

    out = out_path or (config.ROOT / "site" / "cover.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return out
