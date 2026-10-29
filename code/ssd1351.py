# ssd1351.py - minimal driver for SSD1351 RGB OLEDs (1.27" 128x96, 1.5" 128x128)
import time
import framebuf
from machine import Pin


def rgb(r, g, b):
    """RGB888 -> RGB565, byte-swapped because framebuf is little-endian
    and the SSD1351 wants big-endian pixels."""
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8)


_glyph = bytearray(8)
_gfb = framebuf.FrameBuffer(_glyph, 8, 8, framebuf.MONO_HLSB)

# Columns of the built-in 8x8 font that big_text() draws: (first, count).
# Digits and letters use columns 1-7 (column 0 is always blank, '4' reaches
# column 7); '.' only needs 2-5. All of them sit in rows 0-6.
_SPAN = (1, 7)
_NARROW = {'.': (2, 4)}

# 3x5 font for the "dBA" unit label; bit 2 is the left column.
_TINY = {
    'd': (0b001, 0b001, 0b111, 0b101, 0b111),
    'B': (0b110, 0b101, 0b110, 0b101, 0b110),
    'A': (0b010, 0b101, 0b111, 0b101, 0b101),
}


def big_cols(s):
    """Width of s in font columns as drawn by big_text (multiply by sx)."""
    return sum(_NARROW.get(ch, _SPAN)[1] for ch in s)


def load_font(path):
    """Read an anti-aliased font made by tools/make_font.py.
    Returns {sx: {char: (FrameBuffer, width)}}, all glyphs the same height."""
    with open(path, "rb") as f:
        d = bytearray(f.read())
    mv = memoryview(d)                          # glyphs share d, no copies
    if d[:3] != b"BF1":
        raise ValueError("not a bigfont file")
    nsizes, h = d[3], d[4]
    i = 5
    sizes = {}
    for _ in range(nsizes):
        sx, n = d[i], d[i + 1]
        i += 2
        glyphs = {}
        for _ in range(n):
            ch, w, stride = chr(d[i]), d[i + 1], d[i + 2]
            i += 3
            size = stride * h // 2
            fb = framebuf.FrameBuffer(mv[i:i + size], w, h,
                                      framebuf.GS4_HMSB, stride)
            glyphs[ch] = (fb, w)
            i += size
        sizes[sx] = glyphs
    return sizes


def palette(fg, bg):
    """16-entry RGB565 palette fading from bg (RGB888) to fg, for font_text."""
    p = framebuf.FrameBuffer(bytearray(32), 16, 1, framebuf.RGB565)
    for i in range(16):
        p.pixel(i, 0, rgb(*[(b * (15 - i) + f * i + 7) // 15 for f, b in zip(fg, bg)]))
    return p


class SSD1351(framebuf.FrameBuffer):
    def __init__(self, spi, cs, dc, rst, width=128, height=128,
                 start_line=None, brightness=15):
        self.spi, self.cs, self.dc, self.rst = spi, cs, dc, rst
        self.width, self.height = width, height
        self.buffer = bytearray(width * height * 2)
        super().__init__(self.buffer, width, height, framebuf.RGB565)
        cs.init(Pin.OUT, value=1)
        dc.init(Pin.OUT, value=0)
        rst.init(Pin.OUT, value=1)
        if start_line is None:
            start_line = height % 128
        self._init(start_line, brightness)

    def cmd(self, c, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((c,)))
        if data:
            self.dc(1)
            self.spi.write(bytes(data))
        self.cs(1)

    def _init(self, start_line, brightness):
        self.rst(0); time.sleep_ms(20)
        self.rst(1); time.sleep_ms(120)
        for c, d in (
            (0xFD, (0x12,)), (0xFD, (0xB1,)),   # unlock
            (0xAE, None),                       # display off
            (0xB3, (0xF1,)),                    # clock divider
            (0xCA, (0x7F,)),                    # mux ratio
            (0xA2, (0x00,)),                    # display offset
            (0xA1, (start_line,)),              # start line
            (0xA0, (0x74,)),                    # remap, 65k colour (0x70 if R/B swapped)
            (0xB5, (0x00,)), (0xAB, (0x01,)),
            (0xB1, (0x32,)), (0xBE, (0x05,)),
            (0xA6, None),                       # normal display
            (0xC1, (0xC8, 0x80, 0xC8)),         # contrast A/B/C
            (0xC7, (brightness & 0x0F,)),       # master current
            (0xB4, (0xA0, 0xB5, 0x55)),
            (0xB6, (0x01,)),
            (0xAF, None),                       # display on
        ):
            self.cmd(c, d)

    def show(self):
        self.cmd(0x15, (0, self.width - 1))
        self.cmd(0x75, (0, self.height - 1))
        self.cs(0)
        self.dc(0)
        self.spi.write(b'\x5c')                 # write RAM
        self.dc(1)
        self.spi.write(self.buffer)
        self.cs(1)

    def big_text(self, s, x, y, sx, sy, color):
        """Built-in 8x8 font scaled by integer factors sx (width) and sy (height),
        tightly spaced. Drawn size is big_cols(s) * sx by 7 * sy."""
        for ch in s:
            lo, w = _NARROW.get(ch, _SPAN)
            _gfb.fill(0)
            _gfb.text(ch, 0, 0, 1)
            for row in range(7):
                bits = _glyph[row]
                if bits:
                    for col in range(lo, lo + w):
                        if bits & (0x80 >> col):
                            self.fill_rect(x + (col - lo) * sx, y + row * sy,
                                           sx, sy, color)
            x += w * sx

    def font_text(self, glyphs, s, x, y, pal):
        """Draw s with one size of a load_font() font, coloured by palette()."""
        for ch in s:
            fb, w = glyphs[ch]
            self.blit(fb, x, y, -1, pal)
            x += w

    def tiny_text(self, s, x, y, color):
        """3x5 text (only the characters in _TINY); 4 px per character."""
        for ch in s:
            for row, bits in enumerate(_TINY.get(ch, ())):
                for col in range(3):
                    if bits & (4 >> col):
                        self.pixel(x + col, y + row, color)
            x += 4
