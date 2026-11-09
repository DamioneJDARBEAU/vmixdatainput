# Lower-third overlays with transparency

`make_alpha_overlay.py` turns a lower third rendered on solid black into a vMix
overlay with a real alpha channel (Apple ProRes 4444). The full method is in
[`PROCESSING_BRIEF.md`](PROCESSING_BRIEF.md).

```
python make_alpha_overlay.py "DipWin-Lower_3rd.mp4" "DipWin-Lower_3rd_alpha.mov" --qc "DipWin_QC.mp4"
python make_alpha_overlay.py "10X_Lower_3rd.mp4"    "10X_Lower_3rd_alpha.mov"    --qc "10X_QC.mp4"
# black panel inside the 10X gold frame see-through instead of solid:
python make_alpha_overlay.py "10X_Lower_3rd.mp4" "10X_panel-see-through_alpha.mov" --max-hole 3000
```

Needs `ffmpeg`, `numpy` and `scipy` (`pip install numpy scipy`). Options:

* `--hold-from SECONDS`: where the banner has stopped moving (the default is the
  last 40% of the clip).
* `--max-hole PIXELS`: only fill dark areas inside the artwork up to this size.
  Larger dark areas become transparent.
* `--qc FILE.mp4`: also write a check video. The top half shows the overlay over a
  checkerboard, the bottom half over a bright test picture.

## New dates on the 10X lower third

`retext_10x_dates.py` replaces the yellow date on the 10X banner ("LIMITED PERIOD:
9th - 14th NOVEMBER 2026"). It paints the old date out with the panel's navy and
draws the new one in the same place, size, colour and shadow, with small raised
"st/nd/rd/th". The change follows the banner's slide-in. Then run the alpha step
as usual:

```
python retext_10x_dates.py 10X_Lower_3rd.mp4 10X_23-28_Nov.mkv \
       --font roboto-condensed-latin-800-normal.woff --dates "23rd" "28th" "NOVEMBER 2026"
python make_alpha_overlay.py 10X_23-28_Nov.mkv 10X_23-28_Nov_alpha.mov --qc 10X_23-28_Nov_QC.mp4
```

The font is Roboto Condensed ExtraBold, the closest free match to the original
lettering (`npm pack @fontsource/roboto-condensed`, or Google Fonts). If the text
would run past the panel's rounded end, it's narrowed slightly to fit.

## Using the files in vMix

1. **Add Input → Video** and pick the `_alpha.mov` file. vMix reads the transparency
   from the file, so there's nothing to key.
2. Put it on an **Overlay** channel (1–4). Turn **Loop** off, so it holds the
   finished banner on its last frame until you take the overlay off.
3. The files are 1280×720, like the originals. vMix scales them to a 1080p output
   automatically and keeps the position at the bottom.
4. The original audio is kept. If you don't want it, mute the input in the
   Audio Mixer.

Check: in the vMix preview, put the overlay over a bright camera or a colour input.
You should see no black box, no grey haze and no dark edge around the banner.

## If the designer can re-export

The cleanest result is always a re-render from the original project with
**RGB + Alpha** (ProRes 4444 or QuickTime Animation, "Straight" alpha). Ask the
designer for that next time, and this step isn't needed.
