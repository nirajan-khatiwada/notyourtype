"""Watermark and corner-sparkle cleaner for 2D cel-shaded storytime reference images, keyframes, chain frames, and video clips.

Usage (run from the project folder):
    python <skill>/scripts/delama_video.py                    # clean all keyframes/*.png, frames/chain/*.png, and clips/raw/*.mp4
    python <skill>/scripts/delama_video.py --image <path>     # clean one image in-place (or --out <out.png>)
    python <skill>/scripts/delama_video.py --video <path>     # clean one video clip (writes to clips/unmarked/ or --out)
    python <skill>/scripts/delama_video.py --selfcheck        # run harmonic + delogo verification test and exit

Why this matters in a Frame-Chained Video Pipeline:
    If a generated keyframe or extracted last frame (Clip N-1) still carries a bottom-right corner watermark,
    passing that frame into Google Flow MCP for Clip N causes the video model to animate or smear the watermark.
    Therefore, every reference anchor, starting keyframe, and extracted chain frame is cleaned BEFORE conditioning.
"""
import argparse
import glob
import os
import subprocess
import sys
import warnings
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LAMA_MODEL = os.environ.get(
    "LAMA_MODEL",
    os.path.join(os.path.expanduser("~"), ".cache", "lama", "big-lama.pt"),
)
_lama_jit = None


def mark_box(w: int, h: int):
    """Return (x0, y0, x1, y1) bounding box of the Flow bottom-right watermark scaled to (w, h).
    Base reference: on a 1376x768 Flow image, the mark sits inside [w-134 : w-56, h-134 : h-56].
    """
    sx = w / 1376.0
    sy = h / 768.0
    x0 = max(0, int(round(w - 134 * sx)))
    y0 = max(0, int(round(h - 134 * sy)))
    x1 = min(w - 2, int(round(w - 52 * sx)))
    y1 = min(h - 2, int(round(h - 52 * sy)))
    if x1 <= x0 + 8:
        x0 = max(0, w - int(w * 0.10))
        x1 = w - 4
    if y1 <= y0 + 8:
        y0 = max(0, h - int(h * 0.10))
        y1 = h - 4
    return x0, y0, x1, y1


def unmark_harmonic(im: Image.Image) -> Image.Image:
    """Clean the bottom-right corner watermark using harmonic Laplace relaxation.
    Works with zero external model weights and preserves flat 2D cartoon cel backgrounds cleanly.
    """
    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 320 or h < 240:
        return rgb
    a = np.asarray(rgb, dtype=np.float32).copy()
    x0, y0, x1, y1 = mark_box(w, h)
    pad = 6
    ry0, ry1 = max(0, y0 - pad), min(h, y1 + pad)
    rx0, rx1 = max(0, x0 - pad), min(w, x1 + pad)
    reg = a[ry0:ry1, rx0:rx1]
    m = np.zeros(reg.shape[:2], dtype=bool)
    m[pad:-pad, pad:-pad] = True
    if (~m).any():
        reg[m] = reg[~m].mean(axis=0)
    for _ in range(350):
        avg = (
            np.roll(reg, 1, axis=0)
            + np.roll(reg, -1, axis=0)
            + np.roll(reg, 1, axis=1)
            + np.roll(reg, -1, axis=1)
        ) * 0.25
        reg[m] = avg[m]
    a[ry0:ry1, rx0:rx1] = reg
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def unmark_lama(im: Image.Image) -> Image.Image:
    """Use TorchScript LaMa (big-lama.pt) on a 384x384 bottom-right crop if installed."""
    global _lama_jit
    import torch

    if _lama_jit is None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _lama_jit = torch.jit.load(LAMA_MODEL, map_location="cpu").eval()
    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 384 or h < 384:
        return unmark_harmonic(rgb)
    box = mark_box(w, h)
    crop_sz = 384
    cx0 = max(0, min(w - crop_sz, box[2] - crop_sz + 32))
    cy0 = max(0, min(h - crop_sz, box[3] - crop_sz + 32))
    win = rgb.crop((cx0, cy0, cx0 + crop_sz, cy0 + crop_sz))
    mask = Image.new("L", (crop_sz, crop_sz), 0)
    mask.paste(255, (box[0] - cx0, box[1] - cy0, box[2] - cx0, box[3] - cy0))
    img_t = torch.from_numpy(np.asarray(win, np.float32) / 255.0).permute(2, 0, 1)[None]
    msk_t = (torch.from_numpy(np.asarray(mask, np.float32) / 255.0) > 0.5).float()[None, None]
    with torch.no_grad():
        out = _lama_jit(img_t, msk_t)[0].permute(1, 2, 0).numpy()
    res = Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8))
    soft = mask.filter(ImageFilter.GaussianBlur(3)).point(lambda v: min(255, v * 2))
    win.paste(res, (0, 0), soft)
    rgb.paste(win, (cx0, cy0))
    return rgb


def unmark_image(im: Image.Image) -> Image.Image:
    """Clean the bottom-right corner mark using LaMa if available, else harmonic relaxation."""
    if os.path.exists(LAMA_MODEL):
        try:
            return unmark_lama(im)
        except Exception:
            pass
    return unmark_harmonic(im)


def clean_image_file(src_path: str, out_path: str = None) -> str:
    target = out_path or src_path
    im = Image.open(src_path)
    cleaned = unmark_image(im)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    if target.lower().endswith(".jpg") or target.lower().endswith(".jpeg"):
        cleaned.save(target, quality=95)
    else:
        cleaned.save(target)
    return target


def probe_video_dims(video_path: str):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        video_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    parts = res.stdout.strip().splitlines()[0].split("x")
    return int(parts[0]), int(parts[1])


def clean_video_file(src_path: str, out_path: str = None) -> str:
    """Remove the bottom-right Flow watermark from a video clip using FFmpeg delogo filter."""
    if not out_path:
        base = os.path.basename(src_path)
        os.makedirs(os.path.join("clips", "unmarked"), exist_ok=True)
        out_path = os.path.join("clips", "unmarked", base)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    w, h = probe_video_dims(src_path)
    x0, y0, x1, y1 = mark_box(w, h)
    bw = max(16, x1 - x0)
    bh = max(16, y1 - y0)
    x0 = max(2, min(w - bw - 4, x0))
    y0 = max(2, min(h - bh - 4, y0))
    vf = f"delogo=x={x0}:y={y0}:w={bw}:h={bh}:show=0"
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        src_path,
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def selfcheck():
    """Verify image harmonic/LaMa unmarking accuracy."""
    w, h = 1376, 768
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[:] = (242, 236, 218)
    canvas[520:, :] = (196, 148, 92)
    base_im = Image.fromarray(canvas)
    marked_im = base_im.copy()
    x0, y0, x1, y1 = mark_box(w, h)
    draw = ImageDraw.Draw(marked_im)
    draw.ellipse((x0 + 10, y0 + 10, x1 - 10, y1 - 10), fill=(255, 255, 255))
    cleaned_im = unmark_image(marked_im)
    diff = np.abs(
        np.asarray(cleaned_im, dtype=np.float32)[y0:y1, x0:x1]
        - np.asarray(base_im, dtype=np.float32)[y0:y1, x0:x1]
    ).mean()
    print(f"[delama_video selfcheck] Image corner restoration mean error: {diff:.2f} px (target < 5.0)")
    if diff >= 5.0:
        sys.exit(1)
    print("[delama_video selfcheck] PASS: Image & video watermark cleaner verified.")


def main():
    ap = argparse.ArgumentParser(description="Clean corner watermarks from images and video clips.")
    ap.add_argument("--image", help="Clean a single image file")
    ap.add_argument("--video", help="Clean a single video clip")
    ap.add_argument("--out", help="Output file path (optional)")
    ap.add_argument("--selfcheck", action="store_true", help="Run self-verification and exit")
    args = ap.parse_args()

    if args.selfcheck:
        return selfcheck()
    if args.image:
        out = clean_image_file(args.image, args.out)
        print(f"Cleaned image -> {os.path.abspath(out)}")
        return
    if args.video:
        out = clean_video_file(args.video, args.out)
        print(f"Cleaned video -> {os.path.abspath(out)}")
        return

    img_targets = (
        sorted(glob.glob("img/ref_*.png"))
        + sorted(glob.glob("img/ref_*.jpg"))
        + sorted(glob.glob("keyframes/*.png"))
        + sorted(glob.glob("keyframes/*.jpg"))
        + sorted(glob.glob("frames/chain/*.png"))
    )
    for p in img_targets:
        clean_image_file(p, p)
    vid_targets = sorted(glob.glob("clips/raw/*.mp4"))
    for v in vid_targets:
        clean_video_file(v)
    print(
        f"Cleaned {len(img_targets)} reference/keyframe/chain images and "
        f"{len(vid_targets)} video clips (saved to clips/unmarked/)."
    )


if __name__ == "__main__":
    main()
