"""Corner logo watermark + selfie mirror for try-on images."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

MAX_SIDE = 1024  # Perfect Corp limit + VPS RAM (iPhone can be 100MP+)

# Single SOCO mark in the bottom-right corner (~5% of photo area).
WATERMARK_AREA_RATIO = 0.05
WATERMARK_OPACITY = 0.82
WATERMARK_MARGIN_RATIO = 0.025  # padding from edges

_STATIC = Path(__file__).resolve().parent.parent / "static"
_LOGO_CANDIDATES = (
    _STATIC / "logo-soco-2x.png",
    _STATIC / "logo-soco@2x.png",
    _STATIC / "logo-soco.png",
)


def _logo_path() -> Path | None:
    for path in _LOGO_CANDIDATES:
        if path.is_file():
            return path
    return None


def _load_rgb_downscaled(path: Path, max_side: int = MAX_SIDE) -> Image.Image:
    """Open image with low peak memory (JPEG draft) and downscale."""
    Image.MAX_IMAGE_PIXELS = 200_000_000
    with Image.open(path) as src:
        # For JPEG, draft reduces decode resolution before full rasterization.
        try:
            src.draft("RGB", (max_side, max_side))
        except Exception:
            pass
        im = ImageOps.exif_transpose(src)
        if im.mode != "RGB":
            im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        # Detach from file handle
        return im.copy()


def mirror_selfie(path: Path) -> Path:
    """
    Horizontal flip after EXIF orientation. Always writes JPEG without EXIF.
    Returns the final path (may change extension to .jpg).
    """
    im = _load_rgb_downscaled(path)
    try:
        flip = Image.Transpose.FLIP_LEFT_RIGHT
    except AttributeError:  # pragma: no cover
        flip = Image.FLIP_LEFT_RIGHT
    im = im.transpose(flip)
    target = path if path.suffix.lower() in {".jpg", ".jpeg"} else path.with_suffix(".jpg")
    tmp = target.with_name(target.stem + ".mirror_tmp.jpg")
    im.save(tmp, "JPEG", quality=90, optimize=True)
    im.close()
    tmp.replace(target)
    if path.resolve() != target.resolve() and path.exists():
        path.unlink(missing_ok=True)
    return target


def downscale_jpeg(path: Path, max_side: int = MAX_SIDE) -> Path:
    """Downscale any upload in-place to JPEG to protect VPS RAM."""
    im = _load_rgb_downscaled(path, max_side=max_side)
    target = path if path.suffix.lower() in {".jpg", ".jpeg"} else path.with_suffix(".jpg")
    tmp = target.with_name(target.stem + ".ds_tmp.jpg")
    im.save(tmp, "JPEG", quality=90, optimize=True)
    im.close()
    tmp.replace(target)
    if path.resolve() != target.resolve() and path.exists():
        path.unlink(missing_ok=True)
    return target


def apply_watermark(path: Path, text: str = "") -> None:
    """One SOCO logo in the bottom-right corner (~5% of image area)."""
    logo_file = _logo_path()
    if not logo_file:
        return

    with Image.open(path) as src:
        im = src.convert("RGBA")
    w, h = im.size

    with Image.open(logo_file) as logo_src:
        logo = logo_src.convert("RGBA")

    target_area = max(1.0, w * h * WATERMARK_AREA_RATIO)
    lw, lh = logo.size
    scale = (target_area / max(1, lw * lh)) ** 0.5
    new_w = max(24, int(round(lw * scale)))
    new_h = max(24, int(round(lh * scale)))
    # Keep within frame with margin room
    margin = max(8, int(round(min(w, h) * WATERMARK_MARGIN_RATIO)))
    max_w = max(24, w - 2 * margin)
    max_h = max(24, h - 2 * margin)
    if new_w > max_w or new_h > max_h:
        fit = min(max_w / new_w, max_h / new_h)
        new_w = max(24, int(round(new_w * fit)))
        new_h = max(24, int(round(new_h * fit)))

    logo = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
    if WATERMARK_OPACITY < 1.0:
        alpha = logo.getchannel("A")
        alpha = alpha.point(lambda a: int(a * WATERMARK_OPACITY))
        logo.putalpha(alpha)

    x = w - new_w - margin
    y = h - new_h - margin
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.alpha_composite(logo, (x, y))
    Image.alpha_composite(im, overlay).convert("RGB").save(path, "JPEG", quality=90, optimize=True)
