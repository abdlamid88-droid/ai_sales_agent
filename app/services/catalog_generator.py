"""
catalog_generator.py
====================
Generates 800×800 dual-view catalog cards (ALWAYS 50/50 split):

  ┌─────────────────────────────────────────┐
  │   PART TITLE ASSY      (bold, centred)  │
  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │  blue accent
  │       OEM_NUMBER       (72 pt bold)     │
  ├──────────────────────┬──────────────────┤
  │  EXPLODED VIEW       │  PRODUCT PHOTO   │  ← ALWAYS 50/50
  │  (real diagram OR    │  (real photo OR  │
  │   vector placeholder)│   grey stub)     │
  ├──────────────────────┴──────────────────┤
  │ 100% GENUINE …      *ONLY HIGHLIGHTED  │
  └─────────────────────────────────────────┘

Rules enforced here:
  • diagram_image_path == photo_image_path  → left gets placeholder, right gets photo
  • diagram_image_path is None              → left gets placeholder, right gets photo/stub
  • photo_image_path is None               → right gets grey stub, left gets diagram/placeholder
  • Both None                              → both panels get placeholders
  • Pass-through ONLY for files whose basename contains '_card' AND no photo arg given
"""

import os
import re
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def get_system_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"             if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Card-detection helper
# ---------------------------------------------------------------------------

def _is_already_catalog_card(img: Image.Image, filepath: str = "") -> bool:
    """
    True only if the image is a FINISHED dual-view catalog card we can serve as-is.
    Criteria (ALL must pass for heuristic; criteria 1 alone is sufficient):
      1. Filename contains '_card'   [most reliable]
      2. (Heuristic) 800×800 with white central body + coloured top/bottom bands
    Note: 500×500 raw OEM images are NOT cards – they go through dual-view generation.
    """
    basename = os.path.basename(filepath).lower()
    if "_card" in basename:
        logger.debug("Card via filename: %s", filepath)
        return True

    # Heuristic: only 800×800 images that have header/footer bands + white body
    if img.size == (800, 800):
        try:
            rgb   = img.convert("RGB")
            w, h  = rgb.size
            bh    = max(1, int(h * 0.12))

            def _ratio(y0, y1):
                strip  = rgb.crop((0, y0, w, y1))
                pixels = list(strip.getdata())
                dark   = sum(1 for r, g, b in pixels if r < 240 or g < 240 or b < 240)
                return dark / max(1, len(pixels))

            top_r = _ratio(0, bh)
            bot_r = _ratio(h - bh, h)
            mid_r = _ratio(int(h * 0.25), int(h * 0.75))

            if top_r > 0.55 and bot_r > 0.55 and mid_r < 0.45:
                logger.debug("Card via band-heuristic: %s", filepath)
                return True
        except Exception as exc:
            logger.warning("Card heuristic failed for %s: %s", filepath, exc)

    return False


# ---------------------------------------------------------------------------
# Schematic crop helper
# ---------------------------------------------------------------------------

def crop_to_schematic(img: Image.Image) -> Image.Image:
    """Remove outer 15 % bands (banners / watermarks) from a raw OEM image."""
    w, h = img.size
    mx, my = int(w * 0.15), int(h * 0.15)
    l, t, r, b = mx, my, w - mx, h - my
    if r - l < 50 or b - t < 50:
        return img
    return img.crop((l, t, r, b))


# ---------------------------------------------------------------------------
# Compositing helpers
# ---------------------------------------------------------------------------

def _fit_into_box(img: Image.Image, bw: int, bh: int, pad: int = 12) -> Image.Image:
    img.thumbnail((bw - 2 * pad, bh - 2 * pad), Image.Resampling.LANCZOS)
    return img


def _paste_centred(canvas: Image.Image, src: Image.Image,
                   bx: int, by: int, bw: int, bh: int) -> None:
    sw, sh = src.size
    canvas.paste(src, (bx + (bw - sw) // 2, by + (bh - sh) // 2), src)


# ---------------------------------------------------------------------------
# Vector placeholder schematic
# ---------------------------------------------------------------------------

def _draw_placeholder_schematic(
    draw: ImageDraw.ImageDraw,
    bx: int, by: int, bw: int, bh: int,
    oem_text: str = "",
) -> None:
    """
    Render a clean grid + exploded-view outline in the left (diagram) panel
    when no actual schematic is available.
    """
    GRID     = (232, 238, 248)
    LINE     = (175, 192, 215)
    TEXT_COL = (155, 175, 210)
    PAD      = 16

    # Grid lines
    step = 22
    for gx in range(bx + PAD, bx + bw - PAD, step):
        draw.line([(gx, by + PAD), (gx, by + bh - PAD)], fill=GRID, width=1)
    for gy in range(by + PAD, by + bh - PAD, step):
        draw.line([(bx + PAD, gy), (bx + bw - PAD, gy)], fill=GRID, width=1)

    # Outer border
    draw.rectangle([(bx + PAD, by + PAD), (bx + bw - PAD, by + bh - PAD)],
                   outline=LINE, width=1)

    # Central "part" box
    cx, cy = bx + bw // 2, by + bh // 2
    hw, hh = int(bw * 0.19), int(bh * 0.17)
    draw.rectangle([(cx - hw, cy - hh), (cx + hw, cy + hh)], outline=LINE, width=2)

    # Exploded leader lines + small callout boxes
    sm = 7
    for ox, oy in [(-hw - 24, -hh - 20), (hw + 24, -hh - 20),
                   (-hw - 24,  hh + 20), (hw + 24,  hh + 20)]:
        lx, ly = cx + ox, cy + oy
        anchor_x = cx + (hw if ox > 0 else -hw)
        anchor_y = cy + (hh if oy > 0 else -hh)
        draw.line([(anchor_x, anchor_y), (lx, ly)], fill=LINE, width=1)
        draw.rectangle([(lx - sm, ly - sm), (lx + sm, ly + sm)], outline=LINE, width=1)

    # Label
    fnt = get_system_font(14, bold=False)
    lbl = "DIAGRAM N/A"
    lw  = draw.textbbox((0, 0), lbl, font=fnt)[2]
    draw.text((bx + (bw - lw) // 2, by + bh - 32), lbl, fill=TEXT_COL, font=fnt)


# ---------------------------------------------------------------------------
# Main entry point  —  ALWAYS renders 50/50 dual-view
# ---------------------------------------------------------------------------

def generate_part_catalog_card(
    oem_number: str,
    part_title: str = "AUTO PART ASSY",
    diagram_image_path: str = None,
    photo_image_path: str = None,
    output_path: str = None,
    brand_text: str = "100% GENUINE HYUNDAI / KIA",
    canvas_size: tuple = (800, 800),
) -> str:
    """
    Compose and save an 800×800 dual-view catalog card.

    GUARANTEE: The output ALWAYS has a left (EXPLODED VIEW) panel and a right
    (PRODUCT PHOTO) panel, each exactly 400 px wide.  If either source image
    is missing, the panel receives a clean placeholder instead of scaling the
    other image to full width.

    diagram_image_path == photo_image_path  →  left = placeholder, right = photo
    diagram_image_path is None              →  left = placeholder, right = photo/stub
    photo_image_path is None               →  left = diagram/placeholder, right = grey stub
    Both None                              →  both panels = placeholders

    Pass-through: a file is served as-is ONLY if its basename contains '_card'
    AND no separate photo_image_path is given.
    """
    width, height = canvas_size
    clean_oem = re.sub(r"[^A-Z0-9]", "", str(oem_number).upper())

    # ------------------------------------------------------------------
    # Pass-through: only genuine _card files bypass re-composition
    # ------------------------------------------------------------------
    if (diagram_image_path and os.path.exists(diagram_image_path)
            and not photo_image_path
            and "_card" in os.path.basename(diagram_image_path).lower()):
        try:
            with Image.open(diagram_image_path) as probe:
                probe.load()
                if not output_path:
                    output_path = os.path.join("media", "catalogs", f"{clean_oem}.jpg")
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                probe.convert("RGB").save(output_path, "JPEG", quality=98)
                logger.info("Pass-through _card file → '%s'", output_path)
                return output_path
        except Exception as exc:
            logger.warning("Pass-through failed for '%s': %s", diagram_image_path, exc)

    # ------------------------------------------------------------------
    # Normalise inputs:
    #   • Treat diagram == photo as "no diagram" (use placeholder on left)
    #   • Treat non-existent paths as None
    # ------------------------------------------------------------------
    diag_path  = diagram_image_path  if diagram_image_path  and os.path.exists(diagram_image_path)  else None
    photo_path = photo_image_path    if photo_image_path    and os.path.exists(photo_image_path)    else None

    if diag_path and photo_path and os.path.abspath(diag_path) == os.path.abspath(photo_path):
        print(f"[DUALVIEW] diagram == photo path – forcing placeholder on left: {diag_path}")
        logger.warning("diagram_image_path == photo_image_path; left panel → placeholder")
        diag_path = None   # left panel will render placeholder

    print(f"[DUALVIEW] Generator Mode Used: Dual-View Forced")
    print(f"[DUALVIEW] Diagram Path Resolved: {diag_path}")
    print(f"[DUALVIEW] Photo Path Resolved:   {photo_path}")

    # ------------------------------------------------------------------
    # Build white canvas
    # ------------------------------------------------------------------
    canvas = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw   = ImageDraw.Draw(canvas)

    # ------------------------------------------------------------------
    # Header: title → blue line → OEM number
    # ------------------------------------------------------------------
    TITLE_MAP = {
        "ALTERNATEUR": "ALTERNATOR ASSY",
        "AMORTISSEUR": "SHOCK ABSORBER ASSY",
        "FILTRE AIR":  "AIR FILTER ASSY",
        "FILTRE HUILE": "OIL FILTER ASSY",
        "ARBRACAME":   "CAMSHAFT ASSY",
        "AIL":    "FRONT FENDER ASSY",
        "AILE":   "FRONT FENDER ASSY",
        "ANTIVOL": "STEERING LOCK ASSY",
        "DURITE":  "AIR INTAKE HOSE ASSY",
    }
    raw_title   = str(part_title).upper().split("/")[0].split("-")[0].strip()
    clean_title = next((v for k, v in TITLE_MAP.items() if k in raw_title), None)
    if not clean_title:
        clean_title = raw_title
        if "ASSY" not in clean_title and "ASSEMBLY" not in clean_title:
            clean_title += " ASSY"

    max_w     = width - 60
    tfs       = 46
    tfnt      = get_system_font(tfs, bold=True)
    while tfs > 18:
        if draw.textbbox((0, 0), clean_title, font=tfnt)[2] <= max_w:
            break
        tfs -= 2
        tfnt = get_system_font(tfs, bold=True)
    tw = draw.textbbox((0, 0), clean_title, font=tfnt)[2]
    draw.text(((width - tw) // 2, 28), clean_title, fill=(0, 0, 0), font=tfnt)

    draw.line([(30, 90), (width - 30, 90)], fill=(49, 130, 206), width=4)

    oem_text = clean_oem or str(oem_number).upper()
    ofs = 72
    ofnt = get_system_font(ofs, bold=True)
    while ofs > 24:
        if draw.textbbox((0, 0), oem_text, font=ofnt)[2] <= max_w:
            break
        ofs -= 4
        ofnt = get_system_font(ofs, bold=True)

    spc = 4
    cw  = [draw.textbbox((0, 0), c, font=ofnt)[2] for c in oem_text]
    tot = sum(cw) + (len(oem_text) - 1) * spc
    cx  = (width - tot) // 2
    for i, ch in enumerate(oem_text):
        draw.text((cx, 105), ch, fill=(0, 0, 0), font=ofnt)
        cx += cw[i] + spc

    # ------------------------------------------------------------------
    # Central dual-view zone  (ALWAYS 50/50)
    # ------------------------------------------------------------------
    ZT   = int(height * 0.225)   # zone top    ≈ 180
    ZB   = int(height * 0.825)   # zone bottom ≈ 660
    ZH   = ZB - ZT               # ≈ 480 px
    PW   = width // 2            # 400 px each panel
    LBH  = 22                    # label height reserved at bottom
    MG   = 6                     # panel margin
    IAH  = ZH - LBH - MG * 2    # image area height inside panel

    DIV_COL    = (210, 220, 235)
    LABEL_COL  = (95, 118, 148)
    BORDER_COL = (218, 228, 242)
    LBL_FNT    = get_system_font(14, bold=False)

    # Vertical divider (must ALWAYS be present)
    draw.line([(PW, ZT), (PW, ZB)], fill=DIV_COL, width=2)

    def _draw_panel(px: int, img_path, label: str, is_diag: bool) -> None:
        """Draw one 400-px panel with image or placeholder."""
        # Panel border
        draw.rectangle(
            [(px + MG, ZT + MG), (px + PW - MG, ZB - MG)],
            outline=BORDER_COL, width=1,
        )

        if img_path and os.path.exists(img_path):
            try:
                raw = Image.open(img_path).convert("RGBA")
                if is_diag:
                    raw = crop_to_schematic(raw)
                raw = _fit_into_box(raw, PW, IAH, pad=14)
                _paste_centred(canvas, raw, px, ZT, PW, IAH + MG * 2)
                logger.info("Panel '%s' ok from '%s'", label, img_path)
            except Exception as exc:
                logger.error("Panel '%s' failed: %s", label, exc)
                # Fall through to placeholder
                if is_diag:
                    _draw_placeholder_schematic(draw, px + MG, ZT + MG,
                                                PW - MG * 2, IAH, oem_text)
                else:
                    _photo_stub(draw, px, ZT, PW, ZH - LBH)
        else:
            if is_diag:
                _draw_placeholder_schematic(draw, px + MG, ZT + MG,
                                            PW - MG * 2, IAH, oem_text)
            else:
                _photo_stub(draw, px, ZT, PW, ZH - LBH)

        # Panel label
        lw = draw.textbbox((0, 0), label, font=LBL_FNT)[2]
        draw.text((px + (PW - lw) // 2, ZB - LBH), label, fill=LABEL_COL, font=LBL_FNT)

    def _photo_stub(draw, px, zy, pw, ph):
        """Grey stub for missing product photo."""
        fnt = get_system_font(14, bold=False)
        lbl = "PHOTO N/A"
        lw  = draw.textbbox((0, 0), lbl, font=fnt)[2]
        draw.text((px + (pw - lw) // 2, zy + ph // 2 - 10), lbl,
                  fill=(190, 200, 218), font=fnt)

    # Left panel = EXPLODED VIEW (diagram or placeholder)
    _draw_panel(0,  diag_path,  "EXPLODED VIEW", is_diag=True)
    # Right panel = PRODUCT PHOTO (photo or grey stub)
    _draw_panel(PW, photo_path, "PRODUCT PHOTO", is_diag=False)

    # ── Mandatory blue divider line at x=400 (proof of 50/50 split) ──
    draw.line([(PW, ZT), (PW, ZB)], fill=(49, 130, 206), width=4)

    # Separator above footer
    draw.line([(30, ZB + 4), (width - 30, ZB + 4)], fill=(210, 220, 235), width=1)

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    ffnt   = get_system_font(29, bold=True)
    sfnt   = get_system_font(15, bold=False)
    footer_y = ZB + 14
    draw.text((30, footer_y), brand_text, fill=(0, 0, 0), font=ffnt)
    sub = "*ONLY HIGHLIGHTED RED ITEM INCLUDED"
    sw  = draw.textbbox((0, 0), sub, font=sfnt)[2]
    draw.text((width - 30 - sw, footer_y + 36), sub, fill=(100, 100, 100), font=sfnt)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    if not output_path:
        output_path = os.path.join("media", "catalogs", f"{clean_oem}.jpg")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    canvas.save(output_path, "JPEG", quality=95)
    logger.info("Dual-view card saved → '%s'", output_path)
    return output_path
