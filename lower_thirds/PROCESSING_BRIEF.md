# Brief: convert two lower thirds into transparent vMix overlays

## Source material

| File | Content | Format |
|---|---|---|
| `DipWin-Lower_3rd_OOTH_NA.mp4` | Dip & Win "Home Edition" banner: logo, Santa, appliances, "Over $60,000 in guaranteed prizes", red gift box, social bar. Builds on with a glow, confetti burst, then a pulsing gold glow on the box. | 1280×720, 24 fps, 10.04 s (241 frames), H.264 4:2:0, no colour tags, AAC audio |
| `10X_Lower_3rd_Video_NA.mp4` | NLA "It's Back! 10X Play Way" banner: NLA ball, 10X logo, multiplied-winnings panel, QR panel, draw info, 10X/7X/5X/3X/FP badges, 18+, navy social bar. Builds on, then gold sparkle drift and badge pops. | same |

Both clips were rendered on **solid black instead of with an alpha channel**. Every pixel
that should be transparent is black. Glows and sparkles were added *on top of* that black.

## Goal

Two overlay files that vMix plays with real transparency:

* no black box or black haze anywhere the background should show through;
* the banners stay **100% solid**, including their dark parts (navy bar, black text,
  dark shading in the logos, Santa's face);
* glows, light bursts and sparkles stay **soft and see-through**, with their full
  colour (they must not turn grey or dark at the edges);
* colours match the original: same hue and brightness, no colour shift from a wrong
  YUV/RGB conversion;
* the same timing, frame count and audio as the original.

## Why a simple key will not work

* **Luma or chroma key on black:** the navy bar, black text, dark logo shading and the
  black inside the 10X panel would also go transparent and show the programme through
  the graphic.
* **Lighten / screen / add blend in vMix:** the banner would become semi-transparent
  over bright pictures, and dark parts would disappear.

## Method (per frame)

1. **Decode with the correct colour maths.** Untagged 720p H.264 is treated as
   **BT.709, limited (TV) range**. Convert to 16-bit RGB so the next steps don't
   create banding.
2. **Find the solid artwork.** Pixels clearly brighter than the background (max of
   R,G,B above a threshold just over the compression noise) make a mask. Any dark
   area **completely enclosed** by artwork is filled into the mask: black lettering,
   outlines inside the banner, the 10X panel's black inside its gold frame. The
   background touches the frame edge and is never enclosed, so it stays out. The
   mask is shrunk 1 px so the anti-aliased edge goes through step 3.
3. **Recover soft light (glows, sparkles, confetti edges, banner edges).** Outside
   the solid mask, a black-background render is "colour × coverage". So coverage
   (alpha) = the brightest channel above the noise floor, and the true colour =
   pixel ÷ alpha (un-premultiply). This keeps glows bright and coloured instead of
   grey, and gives clean, fringe-free edges.
4. **Clean up.** Coverage below the H.264 noise floor (dark blocky macroblock noise)
   is set to 0 so the empty area is truly clear. Isolated specks of a few pixels are
   removed.
5. **Combine:** inside the solid mask, alpha = 1 with the original colour; outside it,
   the soft alpha and un-premultiplied colour.

## Deliverables

For each clip:

* **`<name>_alpha.mov`**: Apple **ProRes 4444** with alpha (10-bit 4:4:4 + 16-bit
  alpha), BT.709 tagged, 24 fps, original audio as PCM. This is the file to load in vMix.
* **`<name>_QC.mp4`**: a check copy showing the overlay over a checkerboard and over
  a bright test picture, to confirm there is no black left and no dark fringe.

For the 10X clip, also **`10X_..._panel-see-through_alpha.mov`**: the same, but with
the black inside the gold frame transparent, in case that panel was meant to show
the picture behind it.

## vMix setup

1. Add Input → Video → choose `<name>_alpha.mov`. Leave "Loop" off; at the end the
   last frame (the finished banner) stays on screen.
2. Use it as an **Overlay** (1–4). The transparency comes from the file, so no key,
   blend or colour settings are needed (the file uses straight, not premultiplied, alpha).
3. The file is 1280×720, like the original. vMix scales it to fill a 1080p output
   automatically, so the banner stays in the same place. No zoom is needed.
4. If the clip has music, set the input's audio as you need (Audio Mixer: on/off).

## Limits (honest)

* This rebuilds an alpha channel that was thrown away. The best possible result
  still comes from **re-exporting from the original After Effects/Premiere project
  with "RGB + Alpha"** (ProRes 4444 or QuickTime Animation). If the designer can
  supply that, use it instead.
* A dark element that sits on the outside edge of the artwork, touching the black
  background (a black drop shadow, for example), cannot be told apart from the
  background, and becomes transparent. The banners checked here have light outer
  outlines, so this does not affect them.
* Colour detail is limited by the 4:2:0 H.264 source; nothing is invented.
