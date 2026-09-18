"""生成 README 首屏用的交互示意长图（示意图，非真实截图）。

用法：python tools/make_demo_image.py docs/demo.png
依赖：Pillow（pip install Pillow）；仅在维护文档时使用，运行程序本身不需要。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W = 860
PAD = 26
HEADER_H = 76
FOOTER_H = 28
BG = (244, 245, 247)
HEADER_BG = (255, 255, 255)
BOT_BUBBLE = (255, 255, 255)
USER_BUBBLE = (0, 122, 255)
TEXT = (28, 32, 38)
TEXT_DIM = (138, 145, 156)
BORDER = (226, 229, 234)

REG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(BOLD if bold else REG, size)


F_NAME = font(15, bold=True)
F_BODY = font(17)
F_SMALL = font(13)
F_TIME = font(12)
F_TITLE = font(18, bold=True)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        cur = ""
        for ch in raw:
            if fnt.getlength(cur + ch) <= max_w:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines
def draw_photo_card(d: ImageDraw.ImageDraw, box):
    """画一张示意照片：窗户 + 两只橘猫。"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    d.rounded_rectangle(box, radius=12, fill=(214, 232, 248))
    # 窗户
    wx0, wy0 = x0 + w * 0.18, y0 + h * 0.12
    wx1, wy1 = x0 + w * 0.92, y0 + h * 0.74
    d.rectangle((wx0, wy0, wx1, wy1), fill=(236, 246, 255), outline=(255, 255, 255), width=6)
    d.line((wx0 + (wx1 - wx0) / 2, wy0, wx0 + (wx1 - wx0) / 2, wy1), fill=(255, 255, 255), width=6)
    d.line((wx0, wy0 + (wy1 - wy0) / 2, wx1, wy0 + (wy1 - wy0) / 2), fill=(255, 255, 255), width=6)
    # 窗台
    d.rectangle((wx0 - 6, wy1 - 4, wx1 + 6, wy1 + 10), fill=(226, 214, 198))
    # 两只橘猫
    for cx, scale in ((wx0 + (wx1 - wx0) * 0.36, 1.0), (wx0 + (wx1 - wx0) * 0.66, 0.86)):
        body_w, body_h = 62 * scale, 26 * scale
        by = wy1 - body_h - 4
        d.ellipse((cx - body_w / 2, by, cx + body_w / 2, by + body_h), fill=(240, 160, 78))
        head_r = 15 * scale
        hx, hy = cx + body_w * 0.32, by - head_r * 0.5
        d.ellipse((hx - head_r, hy - head_r, hx + head_r, hy + head_r), fill=(246, 174, 94))
        d.polygon([(hx - head_r, hy - head_r * 0.6), (hx - head_r * 0.4, hy - head_r * 1.5),
                   (hx - head_r * 0.1, hy - head_r * 0.7)], fill=(246, 174, 94))
        d.polygon([(hx + head_r, hy - head_r * 0.6), (hx + head_r * 0.4, hy - head_r * 1.5),
                   (hx + head_r * 0.1, hy - head_r * 0.7)], fill=(246, 174, 94))


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_avatar(draw, x, y, size, color, label):
    draw.ellipse((x, y, x + size, y + size), fill=color)
    f = font(15, bold=True)
    w = f.getlength(label)
    draw.text((x + size / 2 - w / 2, y + size / 2 - 9), label, font=f, fill=(255, 255, 255))


def build(messages, out_path: Path) -> None:
    # 先量出总高度
    max_body = W - 2 * PAD - 52 - 2 * 16 - 18  # 头像 + 气泡内边距
    height = HEADER_H + 18
    layout = []
    for msg in messages:
        if msg.get("kind") == "time":
            layout.append((msg, F_TIME.getlength(msg["text"]), 22))
            height += 22 + 16
            continue
        if msg.get("kind") == "file":
            bw, bh = 340, 74
            layout.append((msg, bw, bh))
            height += bh + 16
            continue
        if msg.get("kind") == "photo":
            bw, bh = 330, 200
            layout.append((msg, bw, bh))
            height += bh + 16
            continue
        lines = wrap(msg["text"], F_BODY, max_body)
        bw = max(F_BODY.getlength(line) for line in lines) + 2 * 16
        bw = min(bw, max_body + 2 * 16)
        bh = len(lines) * 26 + 2 * 13
        layout.append((msg, bw, bh))
        height += bh + 16
    height += FOOTER_H

    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img)

    # 顶栏
    d.rectangle((0, 0, W, HEADER_H), fill=HEADER_BG)
    d.line((0, HEADER_H, W, HEADER_H), fill=BORDER)
    d.text((PAD, 26), "QQ AI 助手", font=F_TITLE, fill=TEXT)
    d.ellipse((PAD + 108, 33, PAD + 118, 43), fill=(52, 199, 89))
    d.text((PAD + 126, 31), "在线", font=F_SMALL, fill=TEXT_DIM)
    qq = "NapCat / OneBot v11"
    d.text((W - PAD - F_SMALL.getlength(qq), 32), qq, font=F_SMALL, fill=TEXT_DIM)

    y = HEADER_H + 18
    for msg, bw, bh in layout:
        if msg.get("kind") == "time":
            tw = F_TIME.getlength(msg["text"])
            d.text(((W - tw) / 2, y + 3), msg["text"], font=F_TIME, fill=TEXT_DIM)
            y += 22 + 16
            continue
        if msg.get("kind") == "file":
            x = PAD + 52
            rounded(d, (x, y, x + bw, y + bh), 14, BOT_BUBBLE, BORDER, 1)
            d.rounded_rectangle((x + 14, y + 14, x + 58, y + 58), radius=8, fill=(255, 235, 235))
            d.rectangle((x + 27, y + 24, x + 45, y + 48), fill=(230, 90, 90))
            d.text((x + 72, y + 16), msg["title"], font=F_NAME, fill=TEXT)
            d.text((x + 72, y + 42), msg["meta"], font=F_SMALL, fill=TEXT_DIM)
            y += bh + 16
            continue

        if msg.get("kind") == "photo":
            x0 = W - PAD - 52 - bw
            draw_photo_card(d, (x0, y, x0 + bw, y + bh))
            draw_avatar(d, W - PAD - 44, y + bh - 44, 44, (0, 122, 255), "我")
            y += bh + 16
            continue

        mine = msg["role"] == "user"
        if mine:  # 右侧，绿色头像在右
            x0 = W - PAD - 52 - bw
            rounded(d, (x0, y, x0 + bw, y + bh), 14, USER_BUBBLE)
            tc = (255, 255, 255)
        else:
            x0 = PAD + 52
            rounded(d, (x0, y, x0 + bw, y + bh), 14, BOT_BUBBLE, BORDER, 1)
            tc = TEXT
        for i, line in enumerate(msg["lines"]):
            d.text((x0 + 16, y + 13 + i * 26), line, font=F_BODY, fill=tc)
        ax = W - PAD - 44 if mine else PAD
        draw_avatar(
            d, ax, y + bh - 44, 44, (0, 122, 255) if mine else (120, 130, 145), msg["avatar"]
        )
        y += bh + 16

    img.save(out_path, "PNG", optimize=True)
    print(f"{out_path}  {img.width}x{img.height}")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/demo.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    max_body = W - 2 * PAD - 52 - 2 * 16 - 18
    raw = [
        {"kind": "time", "text": "下午 3:24"},
        {"kind": "photo", "role": "user", "avatar": "我"},
        {"role": "user", "avatar": "我", "text": "帮我看看这张图里有什么"},
        {
            "role": "bot",
            "avatar": "AI",
            "text": "两只橘猫趴在窗台上晒太阳。旁边那个蓝色物件先用联网搜索确认了一下，"
            "是猫抓板，置信度中等。",
        },
        {"role": "user", "avatar": "我", "text": "把结论整理成一页 PDF 发我"},
        {"role": "bot", "avatar": "AI", "text": "收到，我看下。"},
        {"role": "bot", "avatar": "AI", "text": "整理好了，见附件。"},
        {
            "kind": "file",
            "title": "猫咪观察笔记.pdf",
            "meta": "PDF · 已发送 · 128 KB",
        },
    ]
    messages = []
    for item in raw:
        item = dict(item)
        if item.get("kind") is None:
            item["lines"] = wrap(item["text"], F_BODY, max_body)
        messages.append(item)
    build(messages, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
