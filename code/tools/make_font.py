# make_font.py - build bigfont.bin, the anti-aliased digits for the big reading.
#
# Runs on a desktop PC (not the Pico):
#     pip install pillow
#     python3 tools/make_font.py                      # Oswald Bold (default)
#     python3 tools/make_font.py --font X.ttf --weight 600
# then copy bigfont.bin to the Pico with the other files.
#
# Each glyph is rendered 8x oversized, cropped to a box shared by all digits
# (so they line up and are all the same width) and box-filtered down to the
# exact cell main.py lays out, giving 4-bit (16 level) coverage. The cells
# match the blocky fallback font: 7*sx wide (6*sx ink + sx gap), '.' 4*sx,
# all HEIGHT tall. main.py picks sx = 4 ("87.4"), 5 ("104") or 8 ("87", "LO").
#
# bigfont.bin layout (all u8 unless noted):
#   b"BF1", nsizes, height
#   per size: sx, nglyphs; per glyph: char, width, stride, then
#             stride * height / 2 bytes of GS4_HMSB data (stride is even)

import argparse
import os
import struct
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
HEIGHT = 70                    # 7 * NUM_SY in main.py
SIZES = (4, 5, 8)              # sx values main.py can choose on a 128 px wide screen
CHARS = "0123456789.LO"
SS = 8                         # oversampling factor


def ink_box(font, ch):
    img = Image.new("L", (4 * font.size, 2 * font.size), 0)
    ImageDraw.Draw(img).text((font.size, 0), ch, font=font, fill=255)
    return img, img.getbbox()


def render(font, ch, src_box, out_w):
    img, _ = ink_box(font, ch)
    return img.crop(src_box).resize((out_w, HEIGHT), Image.BOX)


def pack_gs4(img, stride):
    out = bytearray(stride * HEIGHT // 2)
    px = img.load()
    for y in range(HEIGHT):
        for x in range(img.width):
            v = (px[x, y] * 15 + 127) // 255
            i = (y * stride + x) >> 1
            out[i] |= v << 4 if x % 2 == 0 else v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=os.path.join(HERE, "fonts", "Oswald[wght].ttf"))
    ap.add_argument("--weight", type=int, default=700, help="for variable fonts")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "bigfont.bin"))
    ap.add_argument("--preview", help="also save a PNG of every glyph")
    args = ap.parse_args()

    # size the font so the digits' ink is HEIGHT * SS tall
    font = ImageFont.truetype(args.font, 1000)
    try:
        font.set_variation_by_axes([args.weight])
    except OSError:
        pass                                   # not a variable font
    h = ink_box(font, "8")[1]
    font = font.font_variant(size=round(1000 * HEIGHT * SS / (h[3] - h[1])))
    try:
        font.set_variation_by_axes([args.weight])
    except OSError:
        pass

    boxes = [ink_box(font, d)[1] for d in "0123456789"]
    x0 = min(b[0] for b in boxes); x1 = max(b[2] for b in boxes)
    y0 = min(b[1] for b in boxes); y1 = max(b[3] for b in boxes)
    dw = x1 - x0

    data = bytearray(b"BF1") + bytes((len(SIZES), HEIGHT))
    previews = []
    for sx in SIZES:
        data += bytes((sx, len(CHARS)))
        for ch in CHARS:
            if ch in "0123456789":
                ink_w, cell_w, box = 6 * sx, 7 * sx, (x0, y0, x1, y1)
            else:
                # same horizontal scale as the digits, centred on the glyph
                b = ink_box(font, ch)[1]
                ink_w = 6 * sx if ch != "." else 4 * sx
                cell_w = 7 * sx if ch != "." else 4 * sx
                half = dw * ink_w / (6 * sx) / 2
                c = (b[0] + b[2]) / 2
                if ch == ".":
                    c += dw / 12           # half a column left, towards the digit before
                box = (round(c - half), y0, round(c + half), y1)
            glyph = Image.new("L", (cell_w, HEIGHT), 0)
            glyph.paste(render(font, ch, box, ink_w), (0, 0))
            stride = (cell_w + 1) & ~1
            data += bytes((ord(ch), cell_w, stride)) + pack_gs4(glyph, stride)
            previews.append(glyph)

    with open(args.out, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes)" % (os.path.normpath(args.out), len(data)))

    if args.preview:
        w = sum(g.width for g in previews[-len(CHARS):]) + 4
        sheet = Image.new("L", (w, (HEIGHT + 4) * len(SIZES)), 40)
        for row in range(len(SIZES)):
            x = 2
            for g in previews[row * len(CHARS):(row + 1) * len(CHARS)]:
                sheet.paste(g, (x, 2 + row * (HEIGHT + 4)))
                x += g.width
        sheet.save(args.preview)
        print("preview", args.preview)


if __name__ == "__main__":
    main()
