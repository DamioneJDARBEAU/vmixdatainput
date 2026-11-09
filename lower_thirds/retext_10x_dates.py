#!/usr/bin/env python3
"""
Replace the date line on the 10X Play Way lower third
("LIMITED PERIOD: 9th - 14th NOVEMBER 2026") and write a lossless
intermediate video, ready for make_alpha_overlay.py.

  python retext_10x_dates.py SRC.mp4 OUT.mkv --font ROBOTO_CONDENSED_BOLD \\
         --dates "23rd" "28th" "NOVEMBER 2026"

Only the yellow date part is replaced; "LIMITED PERIOD:" is untouched. The old
date is painted out with the panel's navy (interpolated per column from just
above and below the text), the new date is drawn in the same place, size,
colour and drop shadow, and the change follows the banner's slide-in.
"""

import argparse
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_alpha_overlay as mao  # noqa: E402

# Measured on the original 1280x720 frame (banner at rest)
ERASE = (274, 605, 497, 631)        # x0, y0, x1, y1 of the old date + shadow
NAVY_ABOVE, NAVY_BELOW = 604, 632   # clean panel rows above / below the text
TEXT_X = 278                        # left edge of the first digit
CAP_TOP, BASELINE = 611, 626        # cap height 15 px
MAX_RIGHT = 494                     # keep clear of the panel's rounded end
YELLOW_TOP = (238, 236, 190)
YELLOW_BOTTOM = (242, 238, 166)
SHADOW = (14, 16, 36)
SS = 8                              # supersampling


def render_date(font_path, parts, width, height):
    """RGBA layer (float 0..1) with the date drawn at its place in the frame."""
    big = ImageFont.truetype(font_path, 100)
    cap = big.getbbox("H")
    cap_h = cap[3] - cap[1]
    size = (BASELINE - CAP_TOP) * SS / cap_h * 100
    f = ImageFont.truetype(font_path, round(size))
    fs = ImageFont.truetype(font_path, round(size * 0.64))
    f_cap = f.getbbox("H")
    fs_cap = fs.getbbox("H")
    space = f.getlength(" ")

    first, second, rest = parts            # e.g. "23rd", "28th", "NOVEMBER 2026"
    def split(day):
        digits = "".join(c for c in day if c.isdigit())
        return digits, day[len(digits):]
    pieces = []                            # (text, font, is_superscript)
    for i, day in enumerate((first, second)):
        d, suf = split(day)
        pieces += [(d, f, False), (suf, fs, True)]
        if i == 0:
            pieces.append((" - ", f, False))
    pieces.append((" " + rest, f, False))

    # natural width, then squeeze horizontally if it would not fit the panel
    widths = [fnt.getlength(t) + (space * 0.08 if sup else 0) for t, fnt, sup in pieces]
    total = sum(widths) / SS
    xscale = min(0.96, (MAX_RIGHT - TEXT_X) / total)

    W = int((MAX_RIGHT - TEXT_X + 8) * SS / xscale)
    H = (ERASE[3] - ERASE[1] + 8) * SS
    top = (CAP_TOP - ERASE[1] + 2) * SS     # cap top inside this canvas
    mask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(mask)
    x = -float(f.getbbox(pieces[0][0])[0])   # first digit starts exactly at TEXT_X
    for (t, fnt, sup), w in zip(pieces, widths):
        if sup:
            d.text((x + space * 0.04, top - fs_cap[1]), t, font=fnt, fill=255)
        else:
            d.text((x, top - f_cap[1]), t, font=fnt, fill=255)
        x += w
    mask = mask.resize((int(W * xscale), H), Image.LANCZOS)
    mask = mask.resize((mask.width // SS, H // SS), Image.LANCZOS)
    m = np.asarray(mask, np.float32) / 255.0

    shadow = np.asarray(Image.fromarray((m * 255).astype(np.uint8))
                        .filter(ImageFilter.GaussianBlur(0.6)), np.float32) / 255.0
    sh = np.zeros_like(shadow)
    sh[2:, 1:] = shadow[:-2, :-1]          # 2 px down, 1 px right
    rows = np.linspace(0, 1, m.shape[0])[:, None, None]
    fill = (np.array(YELLOW_TOP) * (1 - rows) + np.array(YELLOW_BOTTOM) * rows) / 255.0
    sa = np.clip(sh * 0.85, 0, 1)                      # shadow coverage
    a = m + sa * (1 - m)                                # text over its shadow
    premult = fill * m[..., None] + (np.array(SHADOW) / 255.0) * (sa * (1 - m))[..., None]
    rgb = premult / np.maximum(a, 1e-4)[..., None]
    layer = np.zeros((height, width, 4), np.float32)
    y0, x0 = ERASE[1] - 2, TEXT_X
    hh = min(m.shape[0], height - y0)
    ww = min(m.shape[1], width - x0)
    layer[y0:y0 + hh, x0:x0 + ww, :3] = rgb[:hh, :ww]
    layer[y0:y0 + hh, x0:x0 + ww, 3] = a[:hh, :ww]
    right = TEXT_X + total * xscale
    return layer, right, xscale


def patch(rest_frame, layer):
    """Return the banner-at-rest frame with the old date replaced."""
    out = rest_frame.copy()
    x0, y0, x1, y1 = ERASE
    above = rest_frame[NAVY_ABOVE, x0:x1]
    below = rest_frame[NAVY_BELOW, x0:x1]
    t = ((np.arange(y0, y1) - NAVY_ABOVE) / (NAVY_BELOW - NAVY_ABOVE))[:, None, None]
    out[y0:y1, x0:x1] = above * (1 - t) + below * t
    a = layer[..., 3:4]
    return out * (1 - a) + layer[..., :3] * a


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--font", required=True)
    ap.add_argument("--dates", nargs=3, required=True,
                    metavar=("FROM", "TO", "MONTH_YEAR"))
    ap.add_argument("--still", help="also save the patched banner-at-rest frame as PNG")
    a = ap.parse_args()

    w, h, rate, fps, n, has_audio = mao.probe(a.src)
    hold = int(n * 0.6)
    layer, right, xscale = render_date(a.font, a.dates, w, h)
    print("new date ends at x=%.0f (original 489, panel limit %d), x-scale %.3f"
          % (right, MAX_RIGHT, xscale))

    # banner position per frame, as in make_alpha_overlay.py
    min_m, binaries, rest = None, [], None
    for i, rgb in enumerate(mao.frames(a.src, w, h)):
        m = rgb.max(axis=2)
        binaries.append(np.packbits(m > mao.SOLID_T, axis=1))
        if i >= hold:
            min_m = m if min_m is None else np.minimum(min_m, m)
        if i == n - 1:
            rest = rgb
    footprint = mao.fill_holes(min_m > mao.SOLID_T, None)
    shifts = [mao.best_shift(np.unpackbits(pb, axis=1)[:, :w].astype(bool), footprint, h)
              for pb in binaries]

    delta = patch(rest, layer) - rest
    x0, y0, x1, y1 = ERASE[0], ERASE[1] - 2, MAX_RIGHT + 8, ERASE[3] + 6
    d = delta[y0:y1, x0:x1]
    if a.still:
        Image.fromarray((np.clip(rest + delta, 0, 1) * 255 + 0.5).astype(np.uint8)).save(a.still)

    enc = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le",
           "-s", "%dx%d" % (w, h), "-r", rate, "-i", "-"]
    if has_audio:
        enc += ["-i", a.src, "-map", "0:v", "-map", "1:a", "-c:a", "copy"]
    enc += ["-vf", "scale=out_color_matrix=bt709:out_range=limited:"
            "flags=accurate_rnd+full_chroma_int,format=yuv444p10le",
            "-c:v", "ffv1", "-level", "3", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
            "-shortest", a.out]
    p = subprocess.Popen(enc, stdin=subprocess.PIPE)
    for i, rgb in enumerate(mao.frames(a.src, w, h)):
        dy = shifts[i]
        if dy is not None:
            ya, yb = y0 + dy, y1 + dy
            ca, cb = max(0, ya), min(h, yb)
            if cb > ca:
                rgb[ca:cb, x0:x1] = np.clip(rgb[ca:cb, x0:x1] + d[ca - ya:cb - ya], 0, 1)
        p.stdin.write((rgb * 65535 + 0.5).astype("<u2").tobytes())
    p.stdin.close()
    if p.wait():
        sys.exit("ffmpeg failed")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
