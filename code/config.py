# config.py - everything you are likely to want to change lives here.

# ---------------- Pins (GPIO numbers) ----------------
# INMP441: VDD -> 3V3, GND -> GND, L/R -> GND (left channel)
I2S_ID  = 0
I2S_SCK = 10        # INMP441 SCK
I2S_WS  = 11        # INMP441 WS  -- MUST be I2S_SCK + 1 on the Pico
I2S_SD  = 12        # INMP441 SD

# SSD1351 RGB OLED on SPI0: Waveshare 1.5" 128x128 (a 1.27" 128x96 also works)
OLED_WIDTH  = 128
OLED_HEIGHT = 128        # 96 for the 1.27" module
SPI_ID    = 0
OLED_SCK  = 18
OLED_MOSI = 19
OLED_CS   = 17
OLED_DC   = 16
OLED_RST  = 20
SPI_BAUD  = 20_000_000
OLED_START_LINE = None   # None = auto (0 for 128 rows, 96 for 96). If the picture is shifted, try 0, 32 or 96.
OLED_BRIGHTNESS = 12     # 0..15 (master current)

# ---------------- Audio ----------------
SAMPLE_RATE = 48000      # must be >= 32000 for the A-weighting filter
BLOCK       = 512        # samples per processing block (keep <= 1024)
CPU_FREQ    = None       # None = board default (Pico 2: 150 MHz, Pico: 125 MHz);
                         # set e.g. 200_000_000 if DEBUG shows load > ~60 %

# ---------------- Measurement ----------------
TIME_WEIGHTING = "S"     # "S" = Slow (1 s, steady, shows "LASlow"), "F" = Fast (125 ms, shows "LAFast")
UPDATE_MS     = 250      # display refresh interval
MAX_HOLD_S    = 10       # how long the "MAX" reading is held
MIC_SENS_DBFS = -26.0    # INMP441 datasheet: -26 dBFS @ 94 dB SPL, 1 kHz
CAL_OFFSET_DB = 0.0      # trim after comparing with a reference meter/calibrator
FLOOR_DB      = 40.0     # readings below this show as "LO" (mic self-noise ~33 dBA)

# ---------------- Display ----------------
FONT_FILE    = "bigfont.bin"  # smooth digits from tools/make_font.py; None = blocky built-in font
SHOW_DECIMAL = True     # True = "87.4" below 100 dBA, whole numbers above; False = always "87" (wider digits)
BAR_MIN_DB   = 50
BAR_MAX_DB   = 110

# Colour zones: (upper limit in dBA, (R, G, B)). Checked in order; the first
# zone whose limit is above the reading wins. Add or remove rows freely.
ZONES = [
    (77,  (0,   110, 255)),   # below 77 dBA  -> blue   (too quiet)
    (88,  (0,   220,  40)),   # 77 - 87.9     -> green  (normal)
    (95,  (255, 220,   0)),   # 88 - 94.9     -> yellow (getting loud)
    (999, (255,  30,  30)),   # 95 dBA and up -> red    (too loud)
]
BG_COLOR    = (0, 0, 0)
LABEL_COLOR = (150, 150, 150)

# ---------------- Misc ----------------
DEBUG        = False     # print level + CPU load to the USB serial console
PRINT_SERIAL = False     # print each reading over USB (for logging on a PC)
