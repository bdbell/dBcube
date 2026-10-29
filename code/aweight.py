# aweight.py - fixed-point A-weighting filter for the RP2040 / RP2350.
#
# The IEC 61672 A-weighting curve is
#     H(s) = k * s^4 / ((s+w1)^2 (s+w2) (s+w3) (s+w4)^2)
# with poles at 20.6, 107.7, 737.9 and 12194 Hz. That factors exactly into
# four first-order high-pass sections and two first-order low-pass sections,
# each converted to digital form with a pre-warped bilinear transform.
#
# MicroPython floats are heap objects and far too slow for 48 000 samples/s,
# so the per-sample work runs in @micropython.viper using 32-bit integers.
# Coefficients are kept to 9 bits so no product can overflow 32 bits, and
# the high-pass sections are written in "leaky" form (multiply by the small
# number 1-a instead of a = 0.997...) so 9 bits is still accurate.

import math
import micropython
from array import array

IN_SHIFT = 13                 # 32-bit I2S word >> 13  ->  +/- 2^18
FULL_SCALE = 1 << 18
_HP_POLES = (20.598997, 20.598997, 107.65265, 737.86223)
_LP_POLE = 12194.217


def _quant(c, maxv=511):
    """Return (k, s) so that k / 2**s ~= c with |k| <= maxv."""
    s = 0
    while s < 30 and round(abs(c) * (1 << (s + 1))) <= maxv:
        s += 1
    return round(c * (1 << s)), s


# st (state) layout: [x1,y1] * 6 sections, then hi, mid, lo, peak
# co (coeffs) layout: 4 HP x [ka, sa, kb, sb], then LP [kc, sc, ka, sa]
@micropython.viper
def _filter_block(buf: ptr32, n: int, st: ptr32, co: ptr32):
    lc = co[16]; ls = co[17]; la = co[18]; lsa = co[19]
    lcr = (1 << ls) >> 1
    lar = (1 << lsa) >> 1
    hi = 0
    mid = 0
    lo = 0
    pk = st[15]
    for i in range(n):
        x = buf[i] >> 13                      # 24-bit mic sample -> +/- 2^18
        if x > pk:
            pk = x
        elif 0 - x > pk:
            pk = 0 - x
        # four high-pass sections: y = y1 + d - (1-a)*y1 - (1-b)*d
        for k in range(4):
            j = k << 2
            ka = co[j]; sa = co[j + 1]; kb = co[j + 2]; sb = co[j + 3]
            p = k << 1
            y1 = st[p + 1]
            d = x - st[p]
            y = y1 + d - ((y1 * ka + ((1 << sa) >> 1)) >> sa) \
                       - ((d * kb + ((1 << sb) >> 1)) >> sb)
            st[p] = x
            st[p + 1] = y
            x = y
        # two identical low-pass sections: y = c*(x + x1) + a*y1
        for k in range(4, 6):
            p = k << 1
            y = (((x + st[p]) * lc + lcr) >> ls) + ((st[p + 1] * la + lar) >> lsa)
            st[p] = x
            st[p + 1] = y
            x = y
        # exact 40-bit sum of squares, split into 10-bit halves
        if x < 0:
            x = 0 - x
        a = x >> 10
        b = x & 1023
        hi += a * a
        mid += a * b
        lo += b * b
    st[12] = hi
    st[13] = mid
    st[14] = lo
    st[15] = pk


class AWeighting:
    def __init__(self, fs):
        if fs < 32000:
            raise ValueError("SAMPLE_RATE must be >= 32000")
        co = []
        self._sec = []                         # float (b0, b1, a1) per section
        for f in _HP_POLES:
            K = math.tan(math.pi * f / fs)
            ka, sa = _quant(2 * K / (1 + K))   # 1 - a
            kb, sb = _quant(K / (1 + K))       # 1 - b
            co += [ka, sa, kb, sb]
            a = 1 - ka / (1 << sa)
            b = 1 - kb / (1 << sb)
            self._sec.append((b, -b, -a))
        K = math.tan(math.pi * _LP_POLE / fs)
        kc, sc = _quant(K / (1 + K))
        ka, sa = _quant((1 - K) / (1 + K))
        co += [kc, sc, ka, sa]
        c = kc / (1 << sc)
        a = ka / (1 << sa)
        self._sec += [(c, c, -a)] * 2
        self.co = array('i', co)
        self.st = array('i', [0] * 16)
        g = self.gain(1000, fs)                # A-weighting is 0 dB at 1 kHz
        self._norm = 1.0 / (g * g * FULL_SCALE * FULL_SCALE)

    def gain(self, f, fs):
        """Linear magnitude of the digital cascade at frequency f."""
        cw = math.cos(2 * math.pi * f / fs)
        g = 1.0
        for b0, b1, a1 in self._sec:
            num = b0 * b0 + b1 * b1 + 2 * b0 * b1 * cw
            den = 1 + a1 * a1 + 2 * a1 * cw
            g *= math.sqrt(num / den)
        return g

    def process(self, buf, n):
        """Filter n samples; return A-weighted mean square relative to full scale."""
        st = self.st
        _filter_block(buf, n, st, self.co)
        energy = (st[12] << 20) + (st[13] << 11) + st[14]
        return energy * self._norm / n

    def take_peak(self):
        """Largest raw sample magnitude since the last call (for clip warning)."""
        p = self.st[15]
        self.st[15] = 0
        return p
