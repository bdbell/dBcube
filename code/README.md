# Pico Desktop Sound Level Meter (LAS / LAF, dBA)

A USB‑powered desktop decibel meter for sound operators. A Raspberry Pi Pico 2
reads an INMP441 I2S MEMS microphone, applies A‑weighting in software,
applies standard Slow (1 s) or Fast (125 ms) time weighting, and shows a large, colour‑coded reading on a
Waveshare 1.5" 128×128 RGB OLED (SSD1351).

---

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi Pico 2 (RP2350) | Recommended: 150 MHz Cortex‑M33 gives headroom for the A‑weighting filter. MicroPython 1.24 or newer, **ARM** build (`RPI_PICO2`). An original Pico (RP2040, MicroPython 1.20+) also works, with less headroom |
| INMP441 I2S microphone breakout | 24‑bit, 3.3 V only |
| Waveshare 1.5" RGB OLED module, SSD1351, 128×128, SPI | 7‑pin SPI module (VCC GND DIN CLK CS DC RST). A 1.27" 128×96 SSD1351 also works: set `OLED_HEIGHT = 96` |
| USB cable | Powers everything |

## Pin connections

All GPIO numbers can be changed in `config.py`. Power both modules from the
Pico's **3V3(OUT)** pin (physical pin 36), **not** VBUS (5 V).

### INMP441 microphone → Pico

| INMP441 pin | Pico GPIO | Pico physical pin | Notes |
|---|---|---|---|
| VDD | 3V3(OUT) | 36 | 3.3 V only |
| GND | GND | 38 (any GND) | |
| L/R | GND | any GND | Selects the **left** channel; the code reads left |
| SCK | GP10 | 14 | I2S bit clock |
| WS | GP11 | 15 | Word select — **must be SCK GPIO + 1** |
| SD | GP12 | 16 | Serial data out |

### SSD1351 OLED → Pico (SPI0)

| OLED pin (common labels) | Pico GPIO | Pico physical pin | Notes |
|---|---|---|---|
| VCC / VIN | 3V3(OUT) | 36 | |
| GND | GND | 23 (any GND) | |
| DIN / MOSI / SDA | GP19 | 25 | SPI0 TX |
| CLK / SCK / SCL | GP18 | 24 | SPI0 SCK |
| CS | GP17 | 22 | Chip select |
| DC / RS | GP16 | 21 | Data/command |
| RST / RES | GP20 | 26 | Reset |

> **Pin rules:** WS must be the GPIO directly after SCK (a Pico I2S
> requirement). If you move the OLED, keep SCK/MOSI on a valid SPI0 or SPI1
> pin pair and set `SPI_ID` to match.

**Mounting tip:** keep the microphone port (the small hole on the board) clear
and away from the Pico/OLED, and avoid putting it inside a closed box — an
enclosure changes the frequency response. Point it at the stage/PA.

---

## Installing

1. Flash MicroPython onto the Pico 2 (hold BOOTSEL, plug in, drop the `.uf2` on).
   Use the **RPI_PICO2** (ARM) firmware from micropython.org, not the RISC‑V
   build: the fast `@micropython.viper` filter code is tested on ARM.
2. Using Thonny or `mpremote`, copy these files to the Pico's root:
   `main.py`, `config.py`, `aweight.py`, `ssd1351.py`, `bigfont.bin`
3. Unplug and replug. `main.py` runs automatically on power‑up.

```
mpremote cp main.py config.py aweight.py ssd1351.py bigfont.bin :
mpremote reset
```

---

## Files and what they do

### `main.py` — the application
- Sets the CPU clock, starts I2S (32‑bit mono, 48 kHz) and SPI.
- **Warm‑up:** discards ~0.5 s of audio while the mic powers up and the
  filters settle.
- **Main loop:** reads 512‑sample blocks, passes each to the A‑weighting
  filter, and feeds each block's mean‑square energy into an exponential average
  (IEC 61672 time weighting: Slow τ = 1 s or Fast τ = 125 ms, `TIME_WEIGHTING`).
  A loud sound raises the reading at once and it then decays smoothly
  (4.3 dB/s Slow, 34.7 dB/s Fast), like a conventional sound level meter.
- Every `UPDATE_MS` it converts to dBA, updates the MAX hold and overload flag, and redraws.
- Key functions:
  - `zone(db)` — returns the zone a reading falls in (limit, colour, font palette).
  - `to_db(ms)` — mean square → dB SPL using mic sensitivity + calibration.
  - `bar_x(db)` — maps a level onto the bar graph.
  - `draw(db, max_db, clipped)` — renders the screen.
  - `run()` — warm‑up then the measurement loop.

### `aweight.py` — A‑weighting signal processing
- Implements the IEC 61672 A‑weighting curve as six first‑order filter sections
  (poles at 20.6, 20.6, 107.7, 737.9 Hz high‑pass and 12194 Hz ×2 low‑pass),
  converted to digital with a pre‑warped bilinear transform.
- `_filter_block()` is a `@micropython.viper` function using 32‑bit integer
  maths — MicroPython floats are too slow for 48 000 samples/s. It also
  computes an exact sum of squares and tracks the peak sample.
- `AWeighting(fs)` — designs and quantises the coefficients for the sample
  rate and normalises the gain to 0 dB at 1 kHz.
  - `process(buf, n)` — filters one block, returns A‑weighted mean square
    relative to full scale.
  - `take_peak()` — returns and resets the largest raw sample (clip check).
  - `gain(f, fs)` — response of the filter at any frequency (handy for testing).
- Simulated accuracy vs. the IEC curve: ±0.1 dB from 31 Hz–2 kHz, within
  0.7 dB to 8 kHz.

### `ssd1351.py` — OLED driver
- `SSD1351` subclasses `framebuf.FrameBuffer`, so all the usual drawing calls
  (`fill`, `text`, `rect`, `fill_rect`, `vline` …) work on an off‑screen buffer.
- `show()` sends the whole frame over SPI (~13 ms for 128×128 at 20 MHz).
- `load_font(path)` / `font_text(glyphs, s, x, y, pal)` — the smooth,
  anti‑aliased digits from `bigfont.bin`, drawn with `blit` through a
  16‑colour `palette(fg, bg)` that fades the zone colour into the background.
- `big_text(s, x, y, sx, sy, color)` — fallback: the built‑in 8×8 font scaled
  up, used if `bigfont.bin` is missing. `tiny_text()` draws the 3×5 "dBA".
- `rgb(r, g, b)` — converts 0–255 colour values to the panel's byte order.

### `config.py` — all settings
| Setting | Default | Purpose |
|---|---|---|
| `TIME_WEIGHTING` | "S" | `"S"` Slow (1 s, steady, label LASlow) or `"F"` Fast (125 ms, responsive, label LAFast) |
| `UPDATE_MS` | 250 | Screen refresh interval |
| `ZONES` | blue <77, green 77–87.9, yellow 88–94.9, red ≥95 | Colour thresholds — add or remove rows for more or fewer zones |
| `CAL_OFFSET_DB` | 0.0 | Calibration trim |
| `MIC_SENS_DBFS` | −26 | INMP441 datasheet sensitivity |
| `FONT_FILE` | "bigfont.bin" | Smooth digits; `None` = blocky built‑in font |
| `SHOW_DECIMAL` | True | "87.4" below 100 dBA and "104" above, vs always "87" (wider digits) |
| `BAR_MIN_DB` / `BAR_MAX_DB` | 40 / 110 | Bar graph range |
| `MAX_HOLD_S` | 10 | How long MAX is held |
| `FLOOR_DB` | 30 | Below this shows "LO" |
| `OLED_BRIGHTNESS` | 12 | 0–15 |
| `CPU_FREQ` | None (board default: 150 MHz on Pico 2) | Set e.g. 200 MHz if load is high |
| `DEBUG` / `PRINT_SERIAL` | False | Diagnostics / logging over USB |

**Changing colours:** edit `ZONES`. Each row is `(upper limit, (R, G, B))`;
the first row whose limit is above the reading wins, and the last row catches
everything louder. Example with an amber warning band:

```python
ZONES = [
    (70,  (0, 110, 255)),    # blue  - too quiet
    (95,  (0, 220, 40)),     # green - normal
    (100, (255, 170, 0)),    # amber - getting loud
    (999, (255, 30, 30)),    # red   - too loud
]
```

---

## The display

```
LASlow           MAX 98      <- time weighting ("OVL" in red if the mic clipped), 10 s max hold
   ██ ██
   87.4  dBA                 <- tall reading, coloured by zone, small "dBA" on the same row
   ██ ██
[██████████|░░░░░░|░░░░]     <- bar on the bottom edge (BAR_MIN_DB..BAR_MAX_DB), ticks at zone limits
```

The reading is stretched to fill the space: every reading is 70 px tall, with
smooth anti‑aliased digits (Oswald Bold), a narrow decimal point and a 3x5 "dBA". With `SHOW_DECIMAL`
(the default) "87.4" has 24 px wide digits and "104" 30 px; with it off "87"
gets 48 px wide digits.

### Changing the digit font

The smooth digits live in `bigfont.bin`, made on a PC by `tools/make_font.py`
from a TrueType font (default: Oswald Bold, `tools/fonts/`, SIL Open Font
License). To try another font or weight:

```
pip install pillow
python3 tools/make_font.py --font MyFont.ttf --weight 700 --preview sheet.png
mpremote cp bigfont.bin :
```

Glyphs are generated at the exact sizes the layout uses (70 px tall; 24, 30
and 48 px wide), so the digit size does not change. Condensed fonts look best.
If `bigfont.bin` is missing, the meter falls back to the blocky built‑in font.

---

## Calibration

The datasheet sensitivity gets you within roughly ±2–3 dB. For better accuracy:

1. Place the meter next to a trusted sound level meter (A‑weighted, Slow) or
   use a 94 dB / 1 kHz acoustic calibrator over the mic port.
2. Play steady pink noise or the calibrator tone.
3. Set `CAL_OFFSET_DB` to (reference reading − this meter's reading).
4. Check at a second level (e.g. 75 and 95 dBA) to confirm.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Reads "LO" or never changes | Check SD/SCK/WS wiring; WS must be SCK+1; L/R tied to GND |
| Reads "LO" but wiring looks right | L/R is floating or tied high, so the mic talks on the right channel; tie L/R to GND |
| Picture shifted up/down | Set `OLED_START_LINE = 0` (or 32 / 96) |
| Blank screen on the Waveshare module | Check the BS1/BS2 interface-select resistors on the back are set for 4‑wire SPI (the factory default) |
| Red and blue swapped | In `ssd1351.py` change remap `0x74` to `0x70` |
| Blank screen | Check CS/DC/RST and 3V3; try `SPI_BAUD = 10_000_000` |
| Reading jumpy | Use `TIME_WEIGHTING = "S"` (Slow) |
| Hum or bad readings | Set `DEBUG = True`; if load >60 %, raise `CPU_FREQ` |
| Quiet room reads mid‑30s | Normal — that's the INMP441's self‑noise floor (~33 dBA) |

**Measurement range:** about 35–118 dBA. Below that the mic's own noise
dominates; above ~120 dB SPL the INMP441 clips and "OVL" appears.

---

## Limitations

This is a practical reference meter, not a certified instrument. It uses
uncalibrated MEMS microphone hardware, has no traceable calibration, and its
high‑frequency response above ~10 kHz deviates from the standard. Use it as a
consistent guide for mix levels, and a certified meter for compliance
measurements.
