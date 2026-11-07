"""Step 2 & 3 — Dynamic Scene-to-Shot Planner & Frame-Chained Continuous 2D Video Generator via Google Flow MCP.

How Scenes and Shots work dynamically for each project:
    1. When a user starts a new video project (Title, Language, Length), the agent creates a dedicated
       project folder (`~/Storytime2D/<project-slug>/`) and writes:
       - `SCRIPT.md`: The story script.
       - `CHARACTER_BIBLE.json`: The characters dynamically defined for this story.
       - `SCENES.tsv` (`scene_id, setting, duration_sec, summary`): The narrative scenes of the story.
       - `SHOTS.tsv` (`id, scene_id, char, continuity, duration, action, expression, setting, camera`):
         Because Google Flow generates a maximum of 10 seconds per video clip (4s, 6s, 8s, or 10s),
         each Scene in `SCENES.tsv` is broken into one or more sequential 4s-10s Shots in `SHOTS.tsv`:
           * First Shot of a Scene (`continuity = new_scene`):
             Generates an Anchor-Locked Starting Keyframe (`keyframes/sNN_start.png`) conditioned on
             `img/ref_<char>.png`, then animates it into a continuous 2D video clip (`clips/raw/sNN.mp4`).
           * Continuation Shots within the SAME Scene (`continuity = chain`):
             Inspects & trims the final 3-5 frames of Shot N-1 (`frame_chain.py`), extracts the last
             clean frame (`frames/chain/s{N-1:02d}_last.png`), and passes BOTH `frames/chain/s{N-1:02d}_last.png`
             and `img/ref_<char>.png` into Google Flow MCP (`flow-ingredients-to-video` or `flow-frame-to-video`)
             so the scene continues seamlessly without character drift or morphing.

Commands (run from the project folder):
    python <skill>/scripts/video_clips.py validate
    python <skill>/scripts/video_clips.py export-mcp [--model omni-flash]
    python <skill>/scripts/video_clips.py keyframes [ids...] [--wait] [--dry]
    python <skill>/scripts/video_clips.py chain [ids...] [--model omni-flash] [--wait] [--dry]
    python <skill>/scripts/video_clips.py review
    python <skill>/scripts/video_clips.py pick
    python <skill>/scripts/video_clips.py --selfcheck
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from character_bible import (  # noqa: E402
    IMAGE_MODEL,
    cmd_init,
    format_character_spec,
    load_bible,
    negative_guardrails,
    project_folder_slug,
    shot_templates,
    style_lock,
    submit_via_mcp_bridge,
)
from delama_video import unmark_image  # noqa: E402
from frame_chain import decode_frames_rgb, inspect_and_trim_clip, probe_clip  # noqa: E402

VIDEO_MODEL = os.environ.get("FLOW_VIDEO_MODEL", "omni-flash")
VALID_CONTINUITY = {"new_scene", "chain", "interp", "extend"}
VALID_DURATIONS = {"4", "6", "8", "10"}

OVERLOAD_PATTERNS = [
    r"\band then\b",
    r"\bafterwards\b",
    r"\bsubsequently\b",
    r"\bwhile simultaneously\b",
    r"\bfirst .* then .* finally\b",
    r";.*;",
]

FORBIDDEN_STYLE_TERMS = [
    "photorealistic",
    "unreal engine",
    "octane render",
    "3d volumetric",
    "pixar 3d",
    "slideshow",
    "subtitle",
    "speech bubble",
]


def parse_id_filter(raw_args: list) -> set:
    out = set()
    for a in raw_args:
        if "-" in a and not a.startswith("-"):
            x, y = a.split("-", 1)
            out.update(range(int(x), int(y) + 1))
        elif a.isdigit():
            out.add(int(a))
    return out


def load_shots(path: str = "SHOTS.tsv") -> list:
    if not os.path.exists(path):
        sys.exit(f"Missing {path} in current project folder. Create SHOTS.tsv for this project's scenes first.")
    with open(path, encoding="utf-8-sig") as f:
        lines = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def load_project_style() -> str:
    if not os.path.exists("STYLE.txt"):
        return ""
    lines = open("STYLE.txt", encoding="utf-8").read().splitlines()
    return " ".join(ln.strip() for ln in lines if ln.strip() and not ln.lower().startswith("look:"))


def resolve_expression(bible: dict, expr_text: str) -> str:
    presets = bible.get("expression_presets", {})
    key = expr_text.strip().lower()
    if key in presets:
        return presets[key]
    return expr_text.strip()


def build_keyframe_prompt(row: dict, bible: dict) -> str:
    tpl = shot_templates()["starting_keyframe_template"]
    cid = row["char"].strip()
    char_spec = format_character_spec(bible["characters"][cid])
    expr = resolve_expression(bible, row["expression"])
    env_style = load_project_style()
    setting = f"{row['setting'].strip().rstrip('.')}. {env_style}".strip()
    return tpl.format(
        char_spec=char_spec,
        setting=setting,
        action=row["action"].strip(),
        expression=expr,
        camera=row.get("camera", "Medium 2D cartoon shot, eye level").strip(),
        style_lock=style_lock(),
        negative_guardrails=negative_guardrails(),
    )


def build_video_prompt(row: dict, bible: dict) -> str:
    tpls = shot_templates()
    cont = row["continuity"].strip().lower()
    if cont == "chain":
        tpl = tpls["video_clip_chained_template"]
    elif cont == "interp":
        tpl = tpls["video_clip_interp_template"]
    else:
        tpl = tpls["video_clip_new_scene_template"]

    cid = row["char"].strip()
    char_spec = format_character_spec(bible["characters"][cid])
    expr = resolve_expression(bible, row["expression"])
    env_style = load_project_style()
    setting = f"{row['setting'].strip().rstrip('.')}. {env_style}".strip()
    return tpl.format(
        char_spec=char_spec,
        setting=setting,
        camera=row.get("camera", "Medium 2D cartoon shot, eye level").strip(),
        action=row["action"].strip(),
        expression=expr,
        style_lock=style_lock(),
        negative_guardrails=negative_guardrails(),
    )


def build_video_mcp_call(row: dict, bible: dict, video_model: str = VIDEO_MODEL) -> dict:
    sid = int(row["id"])
    scene_id = str(row.get("scene_id", "1")).strip() or "1"
    cid = row["char"].strip()
    cont = row["continuity"].strip().lower()
    dur = str(row.get("duration", "6")).strip() or "6"
    ref_anchor = bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
    prompt = build_video_prompt(row, bible)
    folder = f"{project_folder_slug()}_clips"

    if cont == "chain" and sid > 1:
        prev_last = f"frames/chain/s{sid - 1:02d}_last.png"
        if video_model in ("omni-flash", "veo-3.1-fast", "veo-3.1-lite"):
            mode = "flow-ingredients-to-video"
            image_paths = [prev_last, ref_anchor]
        else:
            mode = "flow-frame-to-video"
            image_paths = [prev_last]
    elif cont == "interp":
        start_img = f"frames/chain/s{sid - 1:02d}_last.png" if sid > 1 else f"keyframes/s{sid:02d}_start.png"
        end_img = f"keyframes/s{sid:02d}_end.png"
        mode = "flow-frame-to-video"
        image_paths = [start_img, end_img]
    elif cont == "extend":
        mode = "flow-extend-video"
        image_paths = []
    else:
        start_kf = f"keyframes/s{sid:02d}_start.png"
        if video_model in ("omni-flash", "veo-3.1-fast", "veo-3.1-lite"):
            mode = "flow-ingredients-to-video"
            image_paths = [start_kf, ref_anchor]
        else:
            mode = "flow-frame-to-video"
            image_paths = [start_kf]

    return {
        "shot_id": sid,
        "scene_id": scene_id,
        "continuity": cont,
        "ServerName": "flow-connector",
        "ToolName": "flow_generate",
        "Arguments": {
            "mode": mode,
            "prompt": prompt,
            "image_paths": image_paths,
            "aspect_ratio": bible.get("aspect_ratio", "16:9"),
            "duration": dur,
            "image_model": video_model,
            "outputs": 1,
            "folder": folder,
            "max_retries": 3,
            "wait": True,
        },
    }


def cmd_validate(_args):
    bible = load_bible()
    shots = load_shots()
    if not shots:
        sys.exit("SHOTS.tsv contains no shot rows.")

    required_cols = {"id", "char", "continuity", "duration", "action", "expression", "setting", "camera"}
    missing_cols = required_cols - set(shots[0].keys())
    if missing_cols:
        sys.exit(f"SHOTS.tsv is missing required columns: {', '.join(sorted(missing_cols))}")

    errors = []
    warnings = []
    prev_id = 0
    prev_scene = None
    for idx, r in enumerate(shots, 1):
        sid = int(r["id"])
        if sid != prev_id + 1:
            warnings.append(f"Row {idx}: shot id {sid:02d} is not sequential after {prev_id:02d}")
        prev_id = sid

        scene_id = str(r.get("scene_id", "")).strip()
        cid = r["char"].strip()
        if cid not in bible["characters"]:
            errors.append(f"Shot {sid:02d}: unknown character '{cid}' (not in CHARACTER_BIBLE.json)")

        cont = r["continuity"].strip().lower()
        if cont not in VALID_CONTINUITY:
            errors.append(f"Shot {sid:02d}: invalid continuity '{cont}' (must be one of {sorted(VALID_CONTINUITY)})")
        if sid == 1 and cont == "chain":
            errors.append("Shot 01 cannot have continuity='chain' (Shot 01 has no previous clip N-1; use 'new_scene')")
        if scene_id and prev_scene is not None and scene_id != prev_scene and cont == "chain":
            warnings.append(
                f"Shot {sid:02d} starts a new scene (scene_id={scene_id} after {prev_scene}) "
                f"but uses continuity='chain'. Consider continuity='new_scene' for hard scene cuts."
            )
        if scene_id:
            prev_scene = scene_id

        dur = str(r["duration"]).strip()
        if dur not in VALID_DURATIONS:
            try:
                num_dur = float(dur)
                if num_dur > 10:
                    errors.append(
                        f"Shot {sid:02d}: duration '{dur}s' exceeds Google Flow's hard 10-second maximum per clip! "
                        f"Allowed values are {sorted(VALID_DURATIONS)} seconds. "
                        f"To animate a {dur}s scene, split it into multiple 6s or 8s shots with continuity='chain'."
                    )
                else:
                    errors.append(
                        f"Shot {sid:02d}: invalid duration '{dur}' "
                        f"(Google Flow only accepts exact strings: '4', '6', '8', or '10' seconds)"
                    )
            except ValueError:
                errors.append(
                    f"Shot {sid:02d}: invalid duration '{dur}' "
                    f"(Google Flow only accepts '4', '6', '8', or '10' seconds; max 10s per clip)"
                )

        action = r["action"].strip()
        expr = r["expression"].strip()
        if not action:
            errors.append(f"Shot {sid:02d}: 'action' cannot be empty")
        if not expr:
            errors.append(f"Shot {sid:02d}: 'expression' cannot be empty")

        for pat in OVERLOAD_PATTERNS:
            if re.search(pat, action, flags=re.IGNORECASE):
                errors.append(
                    f"Shot {sid:02d}: action is overloaded ({pat!r} matched). "
                    f"Scope each clip to ONE clear character action + ONE expression shift to prevent 2D morphing."
                )
        if len(action.split()) > 36:
            warnings.append(
                f"Shot {sid:02d}: action is {len(action.split())} words long "
                f"(recommend <= 30 words for crisp 2D line integrity)"
            )

        combined_text = f"{action} {expr} {r['setting']} {r['camera']}".lower()
        for bad_term in FORBIDDEN_STYLE_TERMS:
            if bad_term in combined_text:
                errors.append(f"Shot {sid:02d}: contains forbidden term '{bad_term}' (violates 2D cel-shaded guardrails)")

    if warnings:
        for w in warnings:
            print(f"WARNING: {w}")
    if errors:
        print("SHOTS.tsv VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    total_sec = sum(int(r["duration"]) for r in shots)
    scenes_seen = {str(r.get("scene_id", i)).strip() for i, r in enumerate(shots, 1)}
    chain_count = sum(1 for r in shots if r["continuity"].strip().lower() == "chain")
    new_count = sum(1 for r in shots if r["continuity"].strip().lower() == "new_scene")
    interp_count = sum(1 for r in shots if r["continuity"].strip().lower() == "interp")
    print(
        f"SHOTS.tsv validated: {len(shots)} continuous 2D video shots across {len(scenes_seen)} scene(s) "
        f"({total_sec}s total duration; {new_count} anchor-locked scene starts, "
        f"{chain_count} frame-chained continuations, {interp_count} interpolated transitions)."
    )


def cmd_export_mcp(args):
    bible = load_bible()
    shots = load_shots()
    manifest = {
        "project": os.path.basename(os.getcwd()),
        "style_preset": "2d_cel_storytime_animation",
        "video_model": args.model,
        "keyframes": [],
        "video_clips": [],
    }
    for r in shots:
        sid = int(r["id"])
        scene_id = str(r.get("scene_id", "1")).strip() or "1"
        cid = r["char"].strip()
        cont = r["continuity"].strip().lower()
        ref_anchor = bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
        if cont in ("new_scene", "interp"):
            kf_prompt = build_keyframe_prompt(r, bible)
            manifest["keyframes"].append(
                {
                    "shot_id": sid,
                    "scene_id": scene_id,
                    "target_path": f"keyframes/s{sid:02d}_start.png",
                    "ServerName": "flow-connector",
                    "ToolName": "flow_generate",
                    "Arguments": {
                        "mode": "flow-image-to-image",
                        "prompt": kf_prompt,
                        "image_paths": [ref_anchor],
                        "aspect_ratio": bible.get("aspect_ratio", "16:9"),
                        "image_model": IMAGE_MODEL,
                        "outputs": 1,
                        "folder": f"{project_folder_slug()}_keyframes",
                        "wait": True,
                    },
                }
            )
        manifest["video_clips"].append(build_video_mcp_call(r, bible, video_model=args.model))

    out_file = args.out or "mcp_jobs.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(
        f"Exported Flow MCP manifest -> {os.path.abspath(out_file)} "
        f"({len(manifest['keyframes'])} keyframe jobs, {len(manifest['video_clips'])} continuous video jobs)."
    )


def _execute_flow_mcp_job(mcp_args: dict, index: int, wait: bool) -> str:
    """Dispatch a single image or video job via the local Flow MCP server bridge and return downloaded path."""
    try:
        job = submit_via_mcp_bridge(mcp_args, wait=wait)
        files = job.get("files") or []
        if files and os.path.exists(files[0]["path"]):
            return files[0]["path"]
        return ""
    except Exception as exc:
        sys.exit(f"Flow MCP bridge error on shot {index:02d}: {exc}")


def cmd_keyframes(args):
    bible = load_bible()
    shots = load_shots()
    want = parse_id_filter(args.ids)
    os.makedirs("keyframes", exist_ok=True)
    count = 0
    for r in shots:
        sid = int(r["id"])
        if want and sid not in want:
            continue
        cont = r["continuity"].strip().lower()
        if cont not in ("new_scene", "interp") and not want:
            continue
        cid = r["char"].strip()
        ref_anchor = bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
        prompt = build_keyframe_prompt(r, bible)
        mcp_args = {
            "mode": "flow-image-to-image" if os.path.exists(ref_anchor) else "flow-text-to-image",
            "prompt": prompt,
            "image_paths": [ref_anchor] if os.path.exists(ref_anchor) else [],
            "aspect_ratio": bible.get("aspect_ratio", "16:9"),
            "image_model": IMAGE_MODEL,
            "outputs": 1,
            "folder": f"{project_folder_slug()}_keyframes",
            "wait": args.wait,
        }
        target_kf = f"keyframes/s{sid:02d}_start.png"
        if args.dry:
            print(f"# Keyframe Shot {sid:02d} -> {target_kf}")
            print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
            count += 1
            continue
        dl_path = _execute_flow_mcp_job(mcp_args, index=sid, wait=args.wait)
        if dl_path and os.path.exists(dl_path):
            cleaned = unmark_image(Image.open(dl_path))
            cleaned.save(target_kf)
            print(f"Saved watermark-cleaned keyframe -> {target_kf}")
        count += 1
    print(f"Processed {count} starting keyframe(s).")


def cmd_chain(args):
    bible = load_bible()
    shots = load_shots()
    want = parse_id_filter(args.ids)
    for d in ("keyframes", "clips/raw", "clips/clean", "frames/chain"):
        os.makedirs(d, exist_ok=True)

    count = 0
    for r in shots:
        sid = int(r["id"])
        if want and sid not in want:
            continue
        call_spec = build_video_mcp_call(r, bible, video_model=args.model)
        mcp_args = call_spec["Arguments"]

        if args.dry:
            print(f"# Shot {sid:02d} (scene {call_spec['scene_id']}, {call_spec['continuity']}) -> clips/raw/s{sid:02d}.mp4")
            print(json.dumps({k: call_spec[k] for k in ("ServerName", "ToolName", "Arguments")}, indent=2))
            count += 1
            continue

        for req_img in mcp_args["image_paths"]:
            if not os.path.exists(req_img):
                sys.exit(
                    f"Shot {sid:02d} ({call_spec['continuity']}) requires reference image '{req_img}', which is missing.\n"
                    f"Run previous shots first (or run `video_clips.py keyframes` for new_scene shots)."
                )

        print(f"Submitting Shot {sid:02d} [scene {call_spec['scene_id']}, {call_spec['continuity']}] via Flow MCP {mcp_args['mode']} ({args.model})...")
        dl_path = _execute_flow_mcp_job(mcp_args, index=sid, wait=args.wait)
        raw_target = f"clips/raw/s{sid:02d}.mp4"
        if dl_path and os.path.exists(dl_path):
            shutil.copy(dl_path, raw_target)
            clean_target = f"clips/clean/s{sid:02d}.mp4"
            chain_target = f"frames/chain/s{sid:02d}_last.png"
            rep = inspect_and_trim_clip(
                in_video=raw_target,
                out_video=clean_target,
                extract_last_png=chain_target,
                min_trim=4,
                max_trim=12,
            )
            print(
                f"  -> Chained Shot {sid:02d} ready: trimmed {rep['trimmed_tail_frames']} tail frames, "
                f"extracted {chain_target} (sharpness={rep['sharpness_ratio']:.2f})"
            )
        count += 1
    print(f"Processed {count} continuous 2D video clip(s).")


def find_downloaded_clips() -> dict:
    root = os.environ.get("FLOW_DOWNLOADS") or os.path.join(os.path.expanduser("~"), "Downloads")
    folder_name = f"{project_folder_slug()}_clips"
    hits = []
    for depth in range(4):
        hits.extend(glob.glob(os.path.join(root, *(["*"] * depth), folder_name, "*.mp4")))
    out = {}
    for p in sorted(hits):
        m = re.match(r"(\d+)\s*-\s*", os.path.basename(p))
        if m:
            out.setdefault(int(m.group(1)), []).append(p)
    return out


def cmd_review(_args):
    dl = find_downloaded_clips()
    if not dl:
        for p in sorted(glob.glob("clips/raw/s*.mp4")):
            m = re.search(r"s(\d+)\.mp4", os.path.basename(p))
            if m:
                dl.setdefault(int(m.group(1)), []).append(p)
    if not dl:
        sys.exit("No downloaded video clips found to review yet.")

    tw, th = 384, 216
    keys = sorted(dl.keys())
    canvas = Image.new("RGB", (tw * 2, th * len(keys)), (24, 24, 28))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    for row_idx, k in enumerate(keys):
        vp = dl[k][0]
        info = probe_clip(vp)
        frames = decode_frames_rgb(vp, info["width"], info["height"])
        if not frames:
            continue
        f_start = Image.fromarray(frames[0]).resize((tw, th), Image.LANCZOS)
        f_end = Image.fromarray(frames[-1]).resize((tw, th), Image.LANCZOS)
        y = row_idx * th
        canvas.paste(f_start, (0, y))
        canvas.paste(f_end, (tw, y))
        draw.rectangle((0, y, 165, y + 32), fill=(0, 0, 0))
        draw.text((8, y + 4), f"#{k:02d} START", fill=(255, 230, 0), font=font)
        draw.rectangle((tw, y, tw + 165, y + 32), fill=(0, 0, 0))
        draw.text((tw + 8, y + 4), f"#{k:02d} END", fill=(0, 230, 255), font=font)

    canvas.save("review.jpg", quality=90)
    print(f"Wrote video review contact sheet -> {os.path.abspath('review.jpg')} ({len(keys)} clips)")


def cmd_pick(_args):
    dl = find_downloaded_clips()
    swaps = {}
    if os.path.exists("PICK.tsv"):
        with open("PICK.tsv", encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                swaps[int(r["shot"])] = int(r["file"])
    os.makedirs("clips/raw", exist_ok=True)
    shots = load_shots()
    seen_hashes = {}
    copied = 0
    missing = []
    for r in shots:
        sid = int(r["id"])
        file_num = swaps.get(sid, sid)
        if file_num not in dl:
            missing.append(sid)
            continue
        src = dl[file_num][0]
        h = hashlib.md5(open(src, "rb").read()).hexdigest()
        if h in seen_hashes:
            print(f"WARNING: Shot {sid:02d} clip is byte-identical to Shot {seen_hashes[h]:02d}!")
        seen_hashes[h] = sid
        shutil.copy(src, f"clips/raw/s{sid:02d}.mp4")
        copied += 1
    print(
        f"Copied {copied} video clips to clips/raw/"
        + (f"; missing: {' '.join(f'{m:02d}' for m in missing)}" if missing else "")
    )


def selfcheck():
    """Verify dynamic Scene -> Shot validation and Flow MCP manifest generation in a temporary project."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="s2d_shots_test_") as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        try:
            cmd_init(argparse.Namespace(look="flat_daylight", force=True))
            # Dynamically create a 2-scene, 3-shot SHOTS.tsv (Scene 1 has 2 chained shots; Scene 2 has 1 new_scene shot)
            shots_content = (
                "id\tscene_id\tchar\tcontinuity\tduration\taction\texpression\tsetting\tcamera\n"
                "01\t1\tprotagonist\tnew_scene\t6\tstands facing the camera and gestures with both hands while speaking\tanimated_speaking\tSimple 2D room interior with flat warm-cream wall\tMedium 2D shot\n"
                "02\t1\tprotagonist\tchain\t6\tplaces both hands on head in sudden surprise\twide_eyed_shock\tSame 2D room interior with flat warm-cream wall\tMedium close-up 2D shot\n"
                "03\t2\tsecondary_character\tnew_scene\t6\tcrosses both arms and nods calmly while responding\tconfident_grin\tSimple 2D room with flat light-blue background wall\tMedium 2D shot\n"
            )
            with open("SHOTS.tsv", "w", encoding="utf-8") as f:
                f.write(shots_content)
            cmd_validate(argparse.Namespace())
            cmd_export_mcp(argparse.Namespace(model="omni-flash", out="mcp_jobs.json"))
            assert os.path.exists("mcp_jobs.json")
            data = json.load(open("mcp_jobs.json", encoding="utf-8"))
            assert len(data["keyframes"]) == 2
            assert len(data["video_clips"]) == 3
            assert data["video_clips"][1]["Arguments"]["image_paths"] == [
                "frames/chain/s01_last.png",
                "img/ref_protagonist.png",
            ]
            print("[video_clips selfcheck] PASS: Dynamic Scene->Shot validation and Flow MCP chaining verified.")
        finally:
            os.chdir(old)


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Dynamic Scene-to-Shot Frame-Chained 2D Video Generator via Flow MCP.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate SHOTS.tsv anti-morphing scope and continuity chain")
    p_val.set_defaults(func=cmd_validate)

    p_exp = sub.add_parser("export-mcp", help="Export Google Flow MCP job manifest (mcp_jobs.json)")
    p_exp.add_argument("--model", default=VIDEO_MODEL)
    p_exp.add_argument("--out", default="mcp_jobs.json")
    p_exp.set_defaults(func=cmd_export_mcp)

    p_kf = sub.add_parser("keyframes", help="Generate starting keyframes for new_scene / interp shots")
    p_kf.add_argument("ids", nargs="*")
    p_kf.add_argument("--wait", action="store_true", default=True)
    p_kf.add_argument("--dry", action="store_true")
    p_kf.set_defaults(func=cmd_keyframes)

    p_ch = sub.add_parser("chain", help="Execute continuous frame-chained 2D video generation")
    p_ch.add_argument("ids", nargs="*")
    p_ch.add_argument("--model", default=VIDEO_MODEL)
    p_ch.add_argument("--wait", action="store_true", default=True)
    p_ch.add_argument("--dry", action="store_true")
    p_ch.set_defaults(func=cmd_chain)

    p_rev = sub.add_parser("review", help="Build review.jpg showing Start & End frames of downloaded clips")
    p_rev.set_defaults(func=cmd_review)

    p_pk = sub.add_parser("pick", help="Apply PICK.tsv swaps and copy downloaded clips to clips/raw/sNN.mp4")
    p_pk.set_defaults(func=cmd_pick)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
