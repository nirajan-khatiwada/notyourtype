"""Step 2 & 3 — Tail-End Anti-Morphing Inspector, Frame Trimmer, and Reference Frame Extractor.

Why this script is critical in a Frame-Chained 2D Video Pipeline:
    1. Video generation models (Veo 3.1 / Omni Flash) frequently lose 2D ink-outline crispness or slightly
       morph limbs/faces in the final 3-5 frames of a clip.
    2. If you extract the raw final frame of Clip N-1 and pass it as the First-Frame Reference for Clip N,
       that tail-end blur/morph compounds across every subsequent clip.
    3. `frame_chain.py` automatically:
       - Discards the final `min_trim` frames (default: 4 frames, within the 3-5 frame safety window).
       - Scans a candidate tail window (last 12 frames before `min_trim`) and measures:
           a) 2D Ink-Outline Sharpness (Laplacian edge energy)
           b) Flat Cel-Color Histogram Stability (comparing against the stable mid-clip anchor frame)
       - Picks the optimal crisp frame `best_idx`, trims the video clip cleanly at `best_idx` (`clips/clean/sNN.mp4`),
         removes any corner watermark, and saves `frames/chain/sNN_last.png` for Clip N.

Usage (run from the project folder):
    python <skill>/scripts/frame_chain.py inspect-trim clips/raw/s01.mp4 \
        --out clips/clean/s01.mp4 --extract frames/chain/s01_last.png [--min-trim 4] [--max-trim 12]

    python <skill>/scripts/frame_chain.py extract-first clips/clean/s01.mp4 --out frames/qc/s01_first.png
    python <skill>/scripts/frame_chain.py batch [--min-trim 4]
    python <skill>/scripts/frame_chain.py --selfcheck
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from delama_video import unmark_image, clean_video_file  # noqa: E402


def probe_clip(video_path: str) -> dict:
    """Return width, height, fps, duration, and total frame count of a video clip."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_read_frames,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        video_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    st = data["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    num, den = (int(x) for x in st.get("r_frame_rate", "30/1").split("/"))
    fps = num / max(1, den)
    dur = float(st.get("duration") or data.get("format", {}).get("duration") or 0.0)
    nb = int(st.get("nb_read_frames") or max(1, round(dur * fps)))
    return {"width": w, "height": h, "fps": fps, "duration": dur, "nb_frames": nb}


def decode_frames_rgb(video_path: str, w: int, h: int) -> list:
    """Decode all frames of a short clip (4-10s) as RGB numpy arrays via ffmpeg pipe."""
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        video_path,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frame_bytes = w * h * 3
    n = len(raw) // frame_bytes
    frames = []
    for i in range(n):
        buf = raw[i * frame_bytes : (i + 1) * frame_bytes]
        frames.append(np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 3)))
    return frames


def ink_sharpness_score(rgb: np.ndarray) -> float:
    """Compute 2D Laplacian edge energy on downsampled luminance to measure black-ink outline crispness."""
    lum = (
        0.299 * rgb[::2, ::2, 0].astype(np.float32)
        + 0.587 * rgb[::2, ::2, 1].astype(np.float32)
        + 0.114 * rgb[::2, ::2, 2].astype(np.float32)
    )
    lap = (
        -4.0 * lum[1:-1, 1:-1]
        + lum[:-2, 1:-1]
        + lum[2:, 1:-1]
        + lum[1:-1, :-2]
        + lum[1:-1, 2:]
    )
    return float(np.mean(np.abs(lap)))


def color_histogram_similarity(rgb: np.ndarray, ref_rgb: np.ndarray) -> float:
    """Return [0..1] similarity of flat 2D cel-color distribution relative to the stable mid-clip frame."""
    sim = 0.0
    for c in range(3):
        h1, _ = np.histogram(rgb[::2, ::2, c], bins=32, range=(0, 256), density=True)
        h2, _ = np.histogram(ref_rgb[::2, ::2, c], bins=32, range=(0, 256), density=True)
        l1 = float(np.sum(np.abs(h1 - h2)))
        sim += max(0.0, 1.0 - 0.5 * l1)
    return sim / 3.0


def analyze_and_select_tail_frame(frames: list, min_trim: int = 4, max_trim: int = 12) -> dict:
    """Inspect the tail of a clip, enforce the 3-5 frame safety trim, and return the sharpest non-morphed frame."""
    total = len(frames)
    if total <= min_trim + 2:
        best_idx = max(0, total - 1)
        return {
            "total_frames": total,
            "best_frame_idx": best_idx,
            "trimmed_tail_frames": total - 1 - best_idx,
            "sharpness_ratio": 1.0,
            "hist_similarity": 1.0,
        }

    mid_idx = total // 2
    mid_frame = frames[mid_idx]
    mid_sharpness = max(1e-4, ink_sharpness_score(mid_frame))

    upper_idx = max(1, total - 1 - min_trim)
    lower_idx = max(1, total - 1 - max(min_trim, max_trim))

    best_idx = upper_idx
    best_score = -1e9
    best_sharp_ratio = 1.0
    best_hist_sim = 1.0

    for idx in range(lower_idx, upper_idx + 1):
        fr = frames[idx]
        sh = ink_sharpness_score(fr) / mid_sharpness
        hs = color_histogram_similarity(fr, mid_frame)
        recency_bonus = 0.015 * (idx - lower_idx)
        morph_penalty = 0.0
        if sh < 0.88:
            morph_penalty += (0.88 - sh) * 4.0
        if hs < 0.90:
            morph_penalty += (0.90 - hs) * 3.0
        score = (0.65 * sh) + (0.35 * hs) + recency_bonus - morph_penalty
        if score > best_score:
            best_score = score
            best_idx = idx
            best_sharp_ratio = sh
            best_hist_sim = hs

    return {
        "total_frames": total,
        "best_frame_idx": best_idx,
        "trimmed_tail_frames": total - 1 - best_idx,
        "sharpness_ratio": round(best_sharp_ratio, 4),
        "hist_similarity": round(best_hist_sim, 4),
    }


def inspect_and_trim_clip(
    in_video: str,
    out_video: str = None,
    extract_last_png: str = None,
    min_trim: int = 4,
    max_trim: int = 12,
    clean_watermark: bool = True,
) -> dict:
    """Run full anti-morphing tail inspection, trim the clip cleanly, and extract the last clean frame."""
    if not os.path.exists(in_video):
        sys.exit(f"Clip not found: {in_video}")

    info = probe_clip(in_video)
    w, h, fps = info["width"], info["height"], info["fps"]
    frames = decode_frames_rgb(in_video, w, h)
    if not frames:
        sys.exit(f"Failed to decode any frames from {in_video}")

    report = analyze_and_select_tail_frame(frames, min_trim=min_trim, max_trim=max_trim)
    best_idx = report["best_frame_idx"]
    cut_duration = max(0.2, (best_idx + 1) / fps)
    report["fps"] = round(fps, 3)
    report["cut_duration_sec"] = round(cut_duration, 3)

    if out_video:
        os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)
        tmp_trimmed = out_video + ".tmp_trim.mp4" if clean_watermark else out_video
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            in_video,
            "-frames:v",
            str(best_idx + 1),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-an",
            tmp_trimmed,
        ]
        subprocess.run(cmd, check=True)
        if clean_watermark:
            clean_video_file(tmp_trimmed, out_video)
            if os.path.exists(tmp_trimmed):
                os.remove(tmp_trimmed)
        report["out_video"] = os.path.abspath(out_video)

    if extract_last_png:
        os.makedirs(os.path.dirname(os.path.abspath(extract_last_png)), exist_ok=True)
        im = Image.fromarray(frames[best_idx])
        if clean_watermark:
            im = unmark_image(im)
        im.save(extract_last_png)
        report["extracted_last_frame"] = os.path.abspath(extract_last_png)

    return report


def cmd_inspect_trim(args):
    rep = inspect_and_trim_clip(
        in_video=args.input,
        out_video=args.out,
        extract_last_png=args.extract,
        min_trim=args.min_trim,
        max_trim=args.max_trim,
    )
    print(
        f"[frame_chain] {os.path.basename(args.input)}: total={rep['total_frames']}f -> "
        f"kept={rep['best_frame_idx'] + 1}f (trimmed {rep['trimmed_tail_frames']} tail frames, "
        f"sharpness={rep['sharpness_ratio']:.2f}, color_sim={rep['hist_similarity']:.2f})"
    )
    if rep.get("extracted_last_frame"):
        print(f"  -> Last clean continuity frame: {rep['extracted_last_frame']}")


def cmd_extract_first(args):
    info = probe_clip(args.input)
    frames = decode_frames_rgb(args.input, info["width"], info["height"])
    im = unmark_image(Image.fromarray(frames[0]))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    im.save(args.out)
    print(f"Extracted first clean frame -> {os.path.abspath(args.out)}")


def cmd_batch(args):
    raw_clips = sorted(glob.glob("clips/raw/s*.mp4"))
    if not raw_clips:
        sys.exit("No clips found in clips/raw/s*.mp4")
    os.makedirs("clips/clean", exist_ok=True)
    os.makedirs("frames/chain", exist_ok=True)
    for p in raw_clips:
        stem = os.path.splitext(os.path.basename(p))[0]
        out_v = f"clips/clean/{stem}.mp4"
        out_f = f"frames/chain/{stem}_last.png"
        rep = inspect_and_trim_clip(
            in_video=p,
            out_video=out_v,
            extract_last_png=out_f,
            min_trim=args.min_trim,
            max_trim=args.max_trim,
        )
        print(
            f"{stem}: trimmed {rep['trimmed_tail_frames']} tail frames -> {out_v} "
            f"& extracted {out_f} (sharpness={rep['sharpness_ratio']:.2f})"
        )


def selfcheck():
    """Synthesize a 30-frame 2D cartoon clip where the final 6 frames intentionally blur/morph,
    run inspect_and_trim_clip, and verify that the morphed tail frames are automatically removed.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="s2d_chain_test_") as tmp:
        w, h, fps = 640, 360, 30
        raw_mp4 = os.path.join(tmp, "test_raw.mp4")
        clean_mp4 = os.path.join(tmp, "test_clean.mp4")
        last_png = os.path.join(tmp, "test_last.png")

        ff = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{w}x{h}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "16",
                "-pix_fmt",
                "yuv420p",
                raw_mp4,
            ],
            stdin=subprocess.PIPE,
        )
        for fi in range(30):
            im = Image.new("RGB", (w, h), (242, 236, 218))
            d = ImageDraw.Draw(im)
            cx = 220 + fi * 4
            d.rectangle((cx - 50, 180, cx + 50, 330), fill=(230, 57, 70), outline=(0, 0, 0), width=5)
            d.ellipse((cx - 45, 80, cx + 45, 175), fill=(252, 240, 225), outline=(0, 0, 0), width=5)
            d.ellipse((cx - 20, 110, cx - 8, 126), fill=(0, 0, 0))
            d.ellipse((cx + 8, 110, cx + 20, 126), fill=(0, 0, 0))
            if fi >= 24:
                im = im.filter(ImageFilter.GaussianBlur(radius=6))
            ff.stdin.write(im.tobytes())
        ff.stdin.close()
        ff.wait()

        rep = inspect_and_trim_clip(
            in_video=raw_mp4,
            out_video=clean_mp4,
            extract_last_png=last_png,
            min_trim=4,
            max_trim=10,
        )
        print(f"[frame_chain selfcheck] Report: {json.dumps(rep)}")
        assert rep["best_frame_idx"] <= 23, f"Expected cut at or before frame 23, got {rep['best_frame_idx']}"
        assert os.path.exists(clean_mp4) and os.path.exists(last_png)
        print("[frame_chain selfcheck] PASS: Tail-end morphing detected, trimmed, and crisp reference frame extracted.")


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Inspect, trim tail-end morphing, and extract chain reference frames.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_it = sub.add_parser("inspect-trim", help="Inspect and trim tail frames of a clip and extract its last clean frame")
    p_it.add_argument("input")
    p_it.add_argument("--out", help="Output cleaned/trimmed MP4 path")
    p_it.add_argument("--extract", help="Output PNG path for extracted last clean frame")
    p_it.add_argument("--min-trim", type=int, default=4, help="Minimum tail frames to trim (default: 4)")
    p_it.add_argument("--max-trim", type=int, default=12, help="Maximum tail search window (default: 12)")
    p_it.set_defaults(func=cmd_inspect_trim)

    p_ef = sub.add_parser("extract-first", help="Extract the first clean frame of a clip")
    p_ef.add_argument("input")
    p_ef.add_argument("--out", required=True)
    p_ef.set_defaults(func=cmd_extract_first)

    p_ba = sub.add_parser("batch", help="Inspect, trim, and extract chain frames for all clips/raw/s*.mp4")
    p_ba.add_argument("--min-trim", type=int, default=4)
    p_ba.add_argument("--max-trim", type=int, default=12)
    p_ba.set_defaults(func=cmd_batch)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
