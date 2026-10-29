# main.py - desktop A-weighted sound level meter (LAS / LAF) for Raspberry Pi Pico 2
import gc
import math
import time
import machine
from machine import Pin, I2S, SPI

import config as C
from aweight import AWeighting, FULL_SCALE
from ssd1351 import SSD1351, rgb, big_cols, load_font, palette

if C.CPU_FREQ:
    machine.freq(C.CPU_FREQ)

# ---------- hardware ----------
mic = I2S(C.I2S_ID, sck=Pin(C.I2S_SCK), ws=Pin(C.I2S_WS), sd=Pin(C.I2S_SD),
          mode=I2S.RX, bits=32, format=I2S.MONO, rate=C.SAMPLE_RATE,
          ibuf=C.BLOCK * 4 * 16)            # ~170 ms of DMA buffering

spi = SPI(C.SPI_ID, baudrate=C.SPI_BAUD, polarity=0, phase=0,
          sck=Pin(C.OLED_SCK), mosi=Pin(C.OLED_MOSI))
oled = SSD1351(spi, Pin(C.OLED_CS), Pin(C.OLED_DC), Pin(C.OLED_RST),
               width=C.OLED_WIDTH, height=C.OLED_HEIGHT,
               start_line=C.OLED_START_LINE, brightness=C.OLED_BRIGHTNESS)

# ---------- colours ----------
BG = rgb(*C.BG_COLOR)
LABEL = rgb(*C.LABEL_COLOR)
WHITE = rgb(255, 255, 255)
RED = rgb(255, 0, 0)
# (limit, RGB565 colour, anti-aliasing palette for the smooth font)
ZONES = [(lim, rgb(*col), palette(col, C.BG_COLOR)) for lim, col in C.ZONES]


def zone(db):
    for z in ZONES:
        if db < z[0]:
            return z
    return ZONES[-1]


# smooth digits for the big reading; fall back to the blocky built-in font
FONT = {}
if C.FONT_FILE:
    try:
        FONT = load_font(C.FONT_FILE)
    except (OSError, ValueError) as e:
        print("font %s not loaded (%s), using built-in font" % (C.FONT_FILE, e))


# ---------- level maths ----------
# A full-scale sine is 0 dBFS and has RMS = FS/sqrt(2), hence the +3.01 dB.
DB_OFFSET = 94.0 - C.MIC_SENS_DBFS + 3.01 + C.CAL_OFFSET_DB

aw = AWeighting(C.SAMPLE_RATE)
buf = bytearray(C.BLOCK * 4)

# Exponential time weighting (IEC 61672 Slow = 1 s, Fast = 125 ms), applied
# once per block to the block's mean square: ms += (block - ms) * K.
# A 10.7 ms block is short next to either time constant.
TW = C.TIME_WEIGHTING.upper()[:1]
if TW not in ("S", "F"):
    raise ValueError("TIME_WEIGHTING must be 'S' or 'F'")
TAU = 1.0 if TW == "S" else 0.125
K = 1 - math.exp(-C.BLOCK / C.SAMPLE_RATE / TAU)


def to_db(ms):
    return 10 * math.log10(ms) + DB_OFFSET if ms > 0 else 0.0


# ---------- drawing ----------
W, H = oled.width, oled.height
BAR_X, BAR_W, BAR_H = 4, W - 8, 10
BAR_Y = H - 1 - BAR_H                     # bar sits on the bottom edge
NUM_SY = 10                               # vertical scale: glyphs are 7 rows -> 70 px
# centre the reading between the top labels (end at y=10) and the bar ticks
NUM_Y = 11 + max(0, (BAR_Y - 4 - 11 - 7 * NUM_SY) // 2)
UNIT_W = 2 + 11                           # gap + "dBA" in the 3x5 font
win_label = "LASlow" if TW == "S" else "LAFast"


def bar_x(db):
    f = (db - C.BAR_MIN_DB) / (C.BAR_MAX_DB - C.BAR_MIN_DB)
    return BAR_X + int(max(0.0, min(1.0, f)) * BAR_W)


def draw(db, max_db, clipped):
    oled.fill(BG)
    _, col, pal = zone(db)
    if clipped:
        oled.text("OVL", 2, 2, RED)
    else:
        oled.text(win_label, 2, 2, LABEL)
    m = "MAX %d" % round(max_db)
    oled.text(m, W - 2 - 8 * len(m), 2, LABEL)

    if db < C.FLOOR_DB:
        s = "LO"
    elif C.SHOW_DECIMAL and db < 99.95:           # 99.95+ would print as "100.0"
        s = "%.1f" % db
    else:
        s = "%d" % round(db)
    # widest scale that fits the reading plus "dBA" on one row
    cols = big_cols(s)
    sx = min(NUM_SY, (W - 2 - UNIT_W) // cols)
    x = (W - sx * cols - UNIT_W) // 2
    if sx in FONT:
        oled.font_text(FONT[sx], s, x, NUM_Y, pal)
    else:
        oled.big_text(s, x, NUM_Y, sx, NUM_SY, col)
    oled.tiny_text("dBA", x + sx * cols + 2, NUM_Y + 7 * NUM_SY - 5, LABEL)

    oled.rect(BAR_X - 1, BAR_Y - 1, BAR_W + 2, BAR_H + 2, LABEL)
    oled.fill_rect(BAR_X, BAR_Y, bar_x(db) - BAR_X, BAR_H, col)
    for z in ZONES[:-1]:                          # tick at each zone boundary
        x = bar_x(z[0])
        oled.vline(x, BAR_Y - 3, BAR_H + 6, WHITE)
    mx = round(max_db)                            # same value as the "MAX" text
    oled.fill_rect(min(bar_x(mx), BAR_X + BAR_W - 2), BAR_Y, 2, BAR_H, zone(mx)[1])
    oled.show()


# ---------- main loop ----------
def run():
    # let the mic power up and the high-pass filters settle (~0.5 s)
    for _ in range(C.SAMPLE_RATE // C.BLOCK // 2):
        n = mic.readinto(buf) // 4
        ms = aw.process(buf, n)                   # start the weighting at the current level
    aw.take_peak()

    max_db, max_t = 0.0, time.ticks_ms()
    last = time.ticks_ms()
    busy_us, t_start = 0, time.ticks_us()
    clip_level = FULL_SCALE - 2

    while True:
        n = mic.readinto(buf) // 4                # blocks until a block is ready
        t0 = time.ticks_us()
        ms += (aw.process(buf, n) - ms) * K
        busy_us += time.ticks_diff(time.ticks_us(), t0)

        now = time.ticks_ms()
        gap = time.ticks_diff(now, last)
        if gap < C.UPDATE_MS:
            continue
        last = now

        db = to_db(ms)
        old_max = round(max_db)
        if db >= max_db or time.ticks_diff(now, max_t) > C.MAX_HOLD_S * 1000:
            max_db, max_t = db, now
        clipped = aw.take_peak() >= clip_level

        t0 = time.ticks_us()
        draw(db, max_db, clipped)
        draw_us = time.ticks_diff(time.ticks_us(), t0)
        busy_us += draw_us

        if C.PRINT_SERIAL:
            print("%.1f" % db)
        if C.DEBUG:
            el = time.ticks_diff(time.ticks_us(), t_start)
            # gap: time since the previous refresh (should be ~UPDATE_MS);
            # free: heap left (a jump up means a garbage collection ran)
            print("%s %.1f dBA  max %.1f%s  load %d%%  draw %d ms  gap %d ms  free %dk%s" % (
                win_label, db, max_db, " *" if round(max_db) != old_max else "  ",
                100 * busy_us // el, draw_us // 1000, gap, gc.mem_free() // 1024,
                "  <-- SLOW" if gap > C.UPDATE_MS + 100 else ""))
            busy_us, t_start = 0, time.ticks_us()


run()
