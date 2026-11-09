#!/usr/bin/env python3
"""
Rebuild the alpha channel of a lower third that was rendered on solid black,
and write a vMix-ready ProRes 4444 overlay with transparency.

See PROCESSING_BRIEF.md for the reasoning. In short, per frame:

  * solid artwork (alpha 1): the banner's footprint, found from the hold part
    of the clip (per-pixel minimum brightness, so glows and particles drop
    out), with every dark area enclosed by artwork filled in, and shifted
    vertically to follow the slide-in;
  * edges: alpha = brightness / brightness of the nearest solid pixel, colour
    un-premultiplied, so edges are clean with no dark fringe;
  * small particles (confetti, sparkles): alpha relative to the particle's
    own peak, so a blue confetti piece stays solid blue;
  * glows and other soft light: alpha = brightness above the noise floor,
    colour un-premultiplied ("unmultiply from black").

Needs ffmpeg/ffprobe, numpy and scipy.

  python make_alpha_overlay.py IN.mp4 OUT_alpha.mov [--qc QC.mp4]
                               [--hold-from SECONDS] [--max-hole PIXELS]
"""

import argparse
import json
import subprocess
import sys

import numpy as np
from scipy import ndimage as ndi

SOLID_T = 0.10       # brightness that is certainly artwork, not background
NOISE = 0.015        # H.264 noise floor on the black background
PARTICLE_AREA = 400  # blobs smaller than this (pixels) outside the banner are particles
EDGE_BAND = 2        # pixels around the solid area treated as anti-aliased edge


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    st = json.loads(out)["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    has_audio = bool(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip())
    return (int(st["width"]), int(st["height"]), st["r_frame_rate"],
            float(num) / float(den), int(st["nb_read_frames"]), has_audio)


def frames(path, w, h):
    """Yield float32 RGB frames (0..1), decoded as BT.709 limited range."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf",
           "scale=in_color_matrix=bt709:in_range=limited:"
           "flags=accurate_rnd+full_chroma_int+bicubic,format=rgb48le",
           "-f", "rawvideo", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = w * h * 3 * 2
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint16).reshape(h, w, 3).astype(np.float32) / 65535.0
    p.wait()


def fill_holes(mask, max_hole):
    """Fill dark areas fully enclosed by artwork (optionally only small ones)."""
    filled = ndi.binary_fill_holes(mask)
    if max_hole is None:
        return filled
    holes = filled & ~mask
    lab, n = ndi.label(holes)
    if n:
        sizes = ndi.sum(holes, lab, range(1, n + 1))
        big = np.isin(lab, np.nonzero(sizes > max_hole)[0] + 1)
        filled &= ~big
    return filled


def shift_rows(mask, dy):
    """Move a mask down by dy rows (negative = up), filling with False."""
    out = np.zeros_like(mask)
    if dy >= 0:
        out[dy:] = mask[:mask.shape[0] - dy]
    else:
        out[:dy] = mask[-dy:]
    return out


def best_shift(binary, footprint, max_dy):
    """Vertical offset of the banner in this frame (0 once it has landed)."""
    h = binary.shape[0]
    b4, f4 = binary[::4, ::4], footprint[::4, ::4]
    if not b4.any():
        return None
    best, best_dy = -1.0, 0
    for d in range(-4, max_dy // 4 + 1):
        s = shift_rows(f4, d)
        inter = np.count_nonzero(s & b4)
        union = np.count_nonzero(s | b4)
        iou = inter / union if union else 0
        if iou > best:
            best, best_dy = iou, d * 4
    best_full = best_dy
    for d in range(best_dy - 4, best_dy + 5):
        if abs(d) >= h:
            continue
        s = shift_rows(footprint, d)
        union = np.count_nonzero(s | binary)
        iou = np.count_nonzero(s & binary) / union if union else 0
        if iou >= best:
            best, best_full = iou, d
    return best_full


def build_alpha(rgb, solid):
    m = rgb.max(axis=2)
    soft = np.clip((m - NOISE) / (1 - NOISE), 0, 1)
    alpha = soft.copy()

    interior = ndi.binary_erosion(solid, iterations=1)
    near = ndi.binary_dilation(solid, iterations=EDGE_BAND)
    band = near & ~interior
    if interior.any():
        # brightness of the nearest fully solid pixel, for anti-aliased edges
        _, (iy, ix) = ndi.distance_transform_edt(~interior, return_indices=True)
        m_nn = m[iy, ix]
        alpha[band] = np.clip(m[band] / np.maximum(m_nn[band], 0.05), 0, 1)
    alpha[interior] = 1.0

    # particles (confetti, sparkles) away from the banner
    blobs = (m > SOLID_T) & ~near
    lab, n = ndi.label(blobs)
    if n:
        idx = np.arange(1, n + 1)
        area = ndi.sum(blobs, lab, idx)
        peak = ndi.maximum(m, lab, idx)
        small = np.zeros(n + 1, bool)
        small[1:] = area < PARTICLE_AREA
        pk = np.zeros(n + 1, np.float32)
        pk[1:] = peak
        grown = ndi.grey_dilation(lab, size=3) * ~near   # include the blob's soft rim
        sel = small[grown] & (grown > 0)
        alpha[sel] = np.maximum(alpha[sel], np.clip(m[sel] / np.maximum(pk[grown[sel]], 0.05), 0, 1))

    alpha[alpha < 0.02] = 0.0
    color = np.where(alpha[..., None] > 0,
                     np.clip(rgb / np.maximum(alpha[..., None], 1e-4), 0, 1), 0.0)
    color[interior] = rgb[interior]
    return color, alpha


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--qc", help="also write a check video over checkerboard / bright picture")
    ap.add_argument("--hold-from", type=float, default=None,
                    help="seconds from which the banner is still (default: last 40%%)")
    ap.add_argument("--max-hole", type=int, default=None,
                    help="only fill enclosed dark areas up to this many pixels "
                         "(larger ones, e.g. a black panel, become see-through)")
    a = ap.parse_args()

    w, h, rate, fps, n, has_audio = probe(a.src)
    hold = int(a.hold_from * fps) if a.hold_from is not None else int(n * 0.6)
    print("%s: %dx%d %s fps, %d frames, hold from frame %d" % (a.src, w, h, rate, n, hold))

    # pass 1: banner footprint from the hold section, and per-frame position
    min_m, binaries = None, []
    for i, rgb in enumerate(frames(a.src, w, h)):
        m = rgb.max(axis=2)
        binaries.append(np.packbits(m > SOLID_T, axis=1))
        if i >= hold:
            min_m = m if min_m is None else np.minimum(min_m, m)
    footprint = fill_holes(min_m > SOLID_T, a.max_hole)
    footprint = ndi.binary_opening(footprint, iterations=1)
    shifts = []
    for pb in binaries:
        b = np.unpackbits(pb, axis=1)[:, :w].astype(bool)
        shifts.append(best_shift(b, footprint, h))
    print("banner offset per frame (rows):", shifts[:40], "...")

    # pass 2: build RGBA and encode
    enc = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgba64le", "-s", "%dx%d" % (w, h),
           "-r", rate, "-i", "-"]
    if has_audio:
        enc += ["-i", a.src, "-map", "0:v", "-map", "1:a", "-c:a", "pcm_s16le"]
    enc += ["-vf", "scale=out_color_matrix=bt709:out_range=limited:"
            "flags=accurate_rnd+full_chroma_int,format=yuva444p10le",
            "-c:v", "prores_ks", "-profile:v", "4444", "-alpha_bits", "16",
            "-vendor", "apl0", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-colorspace", "bt709", "-color_range", "tv", "-shortest", a.out]
    p = subprocess.Popen(enc, stdin=subprocess.PIPE)
    for i, rgb in enumerate(frames(a.src, w, h)):
        m = rgb.max(axis=2)
        dy = shifts[i]
        if dy is None:
            solid = np.zeros((h, w), bool)
        else:
            here = fill_holes(m > SOLID_T, a.max_hole)
            solid = shift_rows(footprint, dy) & here
        color, alpha = build_alpha(rgb, solid)
        rgba = np.dstack([color, alpha])
        p.stdin.write((np.clip(rgba, 0, 1) * 65535 + 0.5).astype("<u2").tobytes())
        if i % 40 == 0:
            print("  frame %d/%d" % (i, n), flush=True)
    p.stdin.close()
    if p.wait():
        sys.exit("ffmpeg encode failed")
    print("wrote", a.out)

    if a.qc:
        # composite the finished file (decoded like vMix would) over two backgrounds
        flt = ("[0:v]format=yuva444p10le,split=2[a][b];"
               "color=c=0x777777:s=%dx%d:r=%s,format=yuv444p[g];"
               "[g]geq=lum='if(eq(mod(floor(X/32)+floor(Y/32),2),0),80,170)':cb=128:cr=128[cb];"
               "testsrc2=s=%dx%d:r=%s,eq=brightness=0.25:saturation=1.3[tp];"
               "[cb][a]overlay=format=auto:shortest=1[o1];"
               "[tp][b]overlay=format=auto:shortest=1[o2];"
               "[o1][o2]vstack,format=yuv420p" % (w, h, rate, w, h, rate))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.out, "-filter_complex", flt,
                        "-c:v", "libx264", "-crf", "16", "-preset", "medium",
                        "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-colorspace", "bt709", "-an", a.qc], check=True)
        print("wrote", a.qc)


if __name__ == "__main__":
    main()
