"""Step 4 — Automated Video Clip Normalization, Timeline Alignment, FFmpeg Stitcher, and 3-Point QC.

Usage (run from the project folder):
    python <skill>/scripts/assemble.py                          # Normalize clips, stitch via FFmpeg, mux audio, write qc.jpg
    python <skill>/scripts/assemble.py --fps 30 --out final.mp4
    python <skill>/scripts/assemble.py --pacing                 # Check word-timed clip pacing if SCENES.tsv / WORDS.tsv exist
    python <skill>/scripts/assemble.py --selfcheck              # Full end-to-end verification of normalization, stitching & QC

Pipeline Responsibilities:
    1. Resolves each shot's cleaned clip (`clips/clean/sNN.mp4` -> `clips/unmarked/sNN.mp4` -> `clips/raw/sNN.mp4`).
       If only `clips/raw/sNN.mp4` exists, automatically runs `frame_chain.inspect_and_trim_clip` first so tail-end
       morphing (final 3-5 frames) and corner watermarks are removed before assembly.
    2. Normalizes every clip to uniform resolution (`1920x1080`), aspect ratio (`16:9`, `setsar=1`),
       frame rate (`30` or `24` fps), and pixel format (`yuv420p`).
    3. Optionally aligns clip durations to spoken word cues (`SCENES.tsv` + `WORDS.tsv`) and muxes audio if present.
    4. Concatenates all normalized clips seamlessly via FFmpeg into `<project>.mp4`.
    5. Generates a 3-point (`FIRST`, `MID`, `LAST`) visual QC contact sheet (`qc.jpg`) for every clip.
"""
import argparse
import csv
import glob
import os
import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from frame_chain import decode_frames_rgb, inspect_and_trim_clip, probe_clip  # noqa: E402

TARGET_W = 1920
TARGET_H = 1080
DEFAULT_FPS = 30


def load_words(path: str = "WORDS.tsv") -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {f"{r['line']}.{r['i']}": max(0.0, float(r["start"])) for r in csv.DictReader(f, delimiter="\t")}


def load_scenes(path: str = "SCENES.tsv") -> list:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.reader(f, delimiter="\t"):
            if not r or not r[0].strip() or r[0].strip().startswith("#") or r[0].strip().lower() == "cue":
                continue
            r = r + [""] * (4 - len(r))
            rows.append(
                {
                    "cue": r[0].strip(),
                    "clip": r[1].strip(),
                    "note": r[2].strip(),
                    "continuity": r[3].strip(),
                }
            )
    return rows


def probe_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        audio_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(res.stdout.strip().splitlines()[0])


def resolve_clean_clip(clip_rel_path: str, auto_trim: bool = True) -> str:
    """Locate the cleaned/trimmed version of a clip, or automatically run frame_chain tail trimming if only raw exists."""
    if os.path.exists(clip_rel_path):
        return clip_rel_path
    stem = os.path.splitext(os.path.basename(clip_rel_path))[0]
    clean_p = os.path.join("clips", "clean", f"{stem}.mp4")
    unmarked_p = os.path.join("clips", "unmarked", f"{stem}.mp4")
    raw_p = os.path.join("clips", "raw", f"{stem}.mp4")

    if os.path.exists(clean_p):
        return clean_p
    if os.path.exists(unmarked_p):
        return unmarked_p
    if os.path.exists(raw_p):
        if auto_trim:
            os.makedirs(os.path.join("clips", "clean"), exist_ok=True)
            os.makedirs(os.path.join("frames", "chain"), exist_ok=True)
            chain_png = os.path.join("frames", "chain", f"{stem}_last.png")
            inspect_and_trim_clip(
                in_video=raw_p,
                out_video=clean_p,
                extract_last_png=chain_png,
                min_trim=4,
                max_trim=12,
            )
            return clean_p
        return raw_p
    sys.exit(f"Missing video clip for '{stem}' (checked {clean_p}, {unmarked_p}, {raw_p})")


def check_pacing(scenes: list, words: dict, total_dur: float) -> bool:
    if not scenes or not words:
        print("No SCENES.tsv / WORDS.tsv found; assembling clips at their native trimmed durations.")
        return True
    starts = []
    for idx, sc in enumerate(scenes):
        cue = sc["cue"]
        if cue not in words:
            sys.exit(f"SCENES.tsv row {idx + 1}: cue '{cue}' not found in WORDS.tsv")
        starts.append(0.0 if idx == 0 else words[cue])
    ends = starts[1:] + [total_dur]
    durations = [b - a for a, b in zip(starts, ends)]
    avg_dur = sum(durations) / max(1, len(durations))
    long_shots = [(i + 1, sc["cue"], d) for i, (sc, d) in enumerate(zip(scenes, durations)) if d > 8.5]
    print(
        f"[pacing] {len(scenes)} animated video shots over {total_dur:.1f}s "
        f"(mean clip window: {avg_dur:.2f}s, min: {min(durations):.2f}s, max: {max(durations):.2f}s)"
    )
    if long_shots:
        print("WARNING — Shots exceeding 8.5s window (consider adding a chained continuation clip):")
        for idx, cue, d in long_shots:
            print(f"  Shot {idx:02d} (cue {cue}): {d:.2f}s")
        return False
    print("[pacing] OK: All animated video shots are within optimal 2D storytime duration bounds.")
    return True


def normalize_clip(
    src_mp4: str,
    out_mp4: str,
    fps: int = DEFAULT_FPS,
    target_duration: float = None,
) -> dict:
    """Normalize a clip to 1920x1080, 16:9 (setsar=1), uniform fps, and yuv420p."""
    info = probe_clip(src_mp4)
    src_dur = max(0.2, info["duration"])
    vf_parts = []

    if target_duration and target_duration > 0.2:
        ratio = target_duration / src_dur
        clamped_ratio = max(0.65, min(1.45, ratio))
        if abs(clamped_ratio - 1.0) > 0.02:
            vf_parts.append(f"setpts={clamped_ratio:.5f}*PTS")

    vf_parts.extend(
        [
            f"fps={fps}",
            f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            "format=yuv420p",
        ]
    )
    vf = ",".join(vf_parts)
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        src_mp4,
        "-vf",
        vf,
    ]
    if target_duration and target_duration > 0.2:
        cmd += ["-t", f"{target_duration:.3f}"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-threads",
        "3",
        "-an",
        out_mp4,
    ]
    subprocess.run(cmd, check=True)
    out_info = probe_clip(out_mp4)
    return out_info


def build_qc_contact_sheet(norm_clips: list, out_jpg: str = "qc.jpg"):
    """Extract FIRST, MID, and LAST frames from every normalized clip and build a 3-column QC grid."""
    tw, th = 384, 216
    cols = 3
    rows = len(norm_clips)
    if rows == 0:
        return
    canvas = Image.new("RGB", (tw * cols, th * rows), (18, 18, 22))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        font = ImageFont.load_default()

    os.makedirs(os.path.join("frames", "qc"), exist_ok=True)
    for r_idx, cp in enumerate(norm_clips):
        stem = os.path.splitext(os.path.basename(cp))[0]
        info = probe_clip(cp)
        frames = decode_frames_rgb(cp, info["width"], info["height"])
        if not frames:
            continue
        picks = [
            ("FIRST", frames[0]),
            ("MID", frames[len(frames) // 2]),
            ("LAST", frames[-1]),
        ]
        for c_idx, (tag, arr) in enumerate(picks):
            im = Image.fromarray(arr)
            if tag == "LAST":
                im.save(os.path.join("frames", "qc", f"{stem}_last.png"))
            tile = im.resize((tw, th), Image.LANCZOS)
            x, y = c_idx * tw, r_idx * th
            canvas.paste(tile, (x, y))
            draw.rectangle((x, y, x + 172, y + 30), fill=(0, 0, 0))
            color = (255, 225, 0) if tag == "FIRST" else ((120, 255, 160) if tag == "MID" else (0, 220, 255))
            draw.text((x + 8, y + 4), f"{stem} {tag}", fill=color, font=font)

    canvas.save(out_jpg, quality=90)
    print(f"Wrote 3-point (FIRST/MID/LAST) visual QC sheet -> {os.path.abspath(out_jpg)}")


def assemble_project(fps: int = DEFAULT_FPS, audio_override: str = None, out_override: str = None, pacing_only: bool = False):
    audio = audio_override
    if not audio:
        if os.path.exists("mix.wav"):
            audio = "mix.wav"
        elif os.path.exists("VO.wav"):
            audio = "VO.wav"

    words = load_words()
    scenes = load_scenes()
    total_audio_dur = probe_audio_duration(audio) if (audio and os.path.exists(audio)) else 0.0

    if pacing_only:
        check_pacing(scenes, words, total_audio_dur)
        return

    os.makedirs(os.path.join("clips", "norm"), exist_ok=True)
    norm_clips = []

    if scenes and words and total_audio_dur > 0:
        check_pacing(scenes, words, total_audio_dur)
        starts = [0.0 if i == 0 else words[sc["cue"]] for i, sc in enumerate(scenes)]
        ends = starts[1:] + [total_audio_dur]
        for idx, (sc, t0, t1) in enumerate(zip(scenes, starts, ends), 1):
            src_clip = resolve_clean_clip(sc["clip"], auto_trim=True)
            norm_p = os.path.join("clips", "norm", f"s{idx:02d}.mp4")
            normalize_clip(src_clip, norm_p, fps=fps, target_duration=max(0.4, t1 - t0))
            norm_clips.append(norm_p)
    else:
        candidates = sorted(glob.glob("clips/clean/s*.mp4")) or sorted(glob.glob("clips/raw/s*.mp4"))
        if not candidates:
            sys.exit("No video clips found in clips/clean/ or clips/raw/ to assemble.")
        for idx, cp in enumerate(candidates, 1):
            src_clip = resolve_clean_clip(cp, auto_trim=True)
            norm_p = os.path.join("clips", "norm", f"s{idx:02d}.mp4")
            normalize_clip(src_clip, norm_p, fps=fps, target_duration=None)
            norm_clips.append(norm_p)

    concat_txt = os.path.join("clips", "norm", "concat_list.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for cp in norm_clips:
            abs_cp = os.path.abspath(cp).replace("\\", "/")
            f.write(f"file '{abs_cp}'\n")

    out_mp4 = out_override or (os.path.basename(os.getcwd()).replace(" ", "_") + ".mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_txt,
    ]
    if audio and os.path.exists(audio):
        cmd += [
            "-i",
            audio,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            out_mp4,
        ]
    else:
        cmd += ["-c:v", "copy", out_mp4]

    subprocess.run(cmd, check=True)
    build_qc_contact_sheet(norm_clips, "qc.jpg")
    final_info = probe_clip(out_mp4)
    print(
        f"Assembled master 2D animation -> {os.path.abspath(out_mp4)}: "
        f"{len(norm_clips)} normalized clips, {final_info['duration']:.2f}s, "
        f"{final_info['width']}x{final_info['height']} @ {final_info['fps']:.0f}fps"
    )


def selfcheck():
    """Synthesize 3 continuous 2D cartoon clips with differing input resolutions/frame rates,
    run the full tail-trimmer + normalizer + FFmpeg stitcher + 3-point QC contact sheet pipeline,
    and verify the final master MP4.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="s2d_assemble_test_") as tmp:
        old_cwd = os.getcwd()
        os.chdir(tmp)
        try:
            os.makedirs("clips/raw", exist_ok=True)
            specs = [
                ("s01", 1280, 720, 24, (242, 236, 218)),
                ("s02", 1920, 1080, 30, (224, 242, 233)),
                ("s03", 1280, 720, 30, (236, 228, 248)),
            ]
            for stem, w, h, fps, bg in specs:
                raw_p = os.path.join("clips", "raw", f"{stem}.mp4")
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
                        "18",
                        "-pix_fmt",
                        "yuv420p",
                        raw_p,
                    ],
                    stdin=subprocess.PIPE,
                )
                for fi in range(int(fps * 1.5)):
                    im = Image.new("RGB", (w, h), bg)
                    d = ImageDraw.Draw(im)
                    cx = int(w * 0.35 + fi * 6)
                    cy = int(h * 0.55)
                    d.rectangle((cx - 60, cy, cx + 60, cy + 160), fill=(230, 57, 70), outline=(0, 0, 0), width=6)
                    d.ellipse((cx - 55, cy - 110, cx + 55, cy + 5), fill=(252, 240, 225), outline=(0, 0, 0), width=6)
                    mouth_h = 8 + (fi % 5) * 4
                    d.ellipse((cx - 18, cy - 38, cx + 18, cy - 38 + mouth_h), fill=(180, 30, 40), outline=(0, 0, 0), width=4)
                    ff.stdin.write(im.tobytes())
                ff.stdin.close()
                ff.wait()

            assemble_project(fps=30, out_override="selfcheck_master.mp4")
            info = probe_clip("selfcheck_master.mp4")
            assert info["width"] == 1920 and info["height"] == 1080, f"Unexpected dims: {info}"
            assert round(info["fps"]) == 30, f"Unexpected fps: {info['fps']}"
            assert os.path.exists("qc.jpg"), "Missing qc.jpg"
            print(f"[assemble selfcheck] PASS: 3 clips normalized to 1080p@30fps and stitched ({info['duration']:.2f}s).")
        finally:
            os.chdir(old_cwd)


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Normalize, align, and stitch 2D animated clips into a master MP4.")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS, choices=[24, 30])
    ap.add_argument("--audio", help="Optional audio file path (defaults to mix.wav or VO.wav)")
    ap.add_argument("--out", help="Output master MP4 filename")
    ap.add_argument("--pacing", action="store_true", help="Only validate word-timed clip pacing")
    args = ap.parse_args()
    assemble_project(fps=args.fps, audio_override=args.audio, out_override=args.out, pacing_only=args.pacing)


if __name__ == "__main__":
    main()
