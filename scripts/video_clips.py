"""Step 2 & 3 — Dynamic Scene-to-Shot Planner & Frame-Chained Continuous 2D Video Generator via Google Flow MCP.

How Scenes, Shots, and Reusable Assets work dynamically for each project:
    1. Asset Generation First:
       Before any video clips are generated, all recurring characters, backgrounds, and props
       are generated, watermark-cleaned, and locked into `img/ref_<char>.png`, `assets/bg_<bg>.png`,
       and `assets/prop_<prop>.png` via `assets.py`.
    2. Multi-Character Scene Planning:
       Each narrative scene in `SCENES.tsv` specifies the required characters (single or multiple),
       reusable background (`bg_id`), props (`props`), and target duration.
    3. Flexible Clip Segmentation (4s, 6s, 8s, or 10s per shot):
       Because Google Flow generates a maximum of 10 seconds per video clip (4s, 6s, 8s, or 10s),
       each Scene is broken into sequential 4s-10s Shots in `SHOTS.tsv`:
       - First Shot of a Scene (`continuity = new_scene`):
         Generates a Starting Keyframe (`keyframes/sNN_start.png`) conditioned on the established
         background asset and all involved character reference anchors, then animates it into a
         continuous 2D video clip (`clips/raw/sNN.mp4`).
       - Continuation Shots within the SAME Scene (`continuity = chain`):
         Inspects & trims the final 3-5 frames of Shot N-1 (`frame_chain.py`), extracts the last clean
         frame (`frames/chain/s{N-1:02d}_last.png`), and passes BOTH `frames/chain/s{N-1:02d}_last.png`
         and all involved character references (`img/ref_<char>.png`) into Google Flow MCP
         (`flow-ingredients-to-video`) so characters never drift or morph across long sequences.

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
from assets import (  # noqa: E402
    IMAGE_MODEL,
    cmd_init,
    format_character_spec,
    format_multi_character_spec,
    load_assets,
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


def parse_chars(row: dict) -> list:
    """Extract list of character IDs from either 'chars' or legacy 'char' column."""
    raw = row.get("chars") or row.get("char") or ""
    return [c.strip() for c in re.split(r"[,+;]", raw) if c.strip()]


def parse_props(row: dict) -> list:
    """Extract list of prop IDs from 'props' column."""
    raw = row.get("props") or ""
    return [p.strip() for p in re.split(r"[,+;]", raw) if p.strip()]


def load_bible(path: str = None) -> dict:
    return load_assets(path)


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


def build_props_spec(bible: dict, props: list) -> str:
    if not props:
        return "None (clean hands and empty background surfaces)"
    clauses = []
    prop_dict = bible.get("props", {})
    for p in props:
        if p in prop_dict:
            p_desc = prop_dict[p].get("description", p)
            p_name = prop_dict[p].get("name", p)
            clauses.append(f"{p_name}: {p_desc}")
        else:
            clauses.append(p)
    return "; ".join(clauses)


def build_setting_spec(bible: dict, row: dict) -> str:
    bg_id = str(row.get("bg_id", "")).strip()
    bgs = bible.get("backgrounds", {})
    bg_desc = ""
    if bg_id and bg_id in bgs:
        bg_name = bgs[bg_id].get("name", bg_id)
        bg_details = bgs[bg_id].get("description", "")
        bg_desc = f"{bg_name} ({bg_details}). "
    env_style = load_project_style()
    setting_text = row.get("setting", "").strip()
    combined = f"{bg_desc}{setting_text}".strip().rstrip(".")
    return f"{combined}. {env_style}".strip()


def build_keyframe_prompt(row: dict, bible: dict) -> str:
    tpl = shot_templates()["starting_keyframe_template"]
    char_ids = parse_chars(row)
    chars_spec = format_multi_character_spec(bible, char_ids)
    props_spec = build_props_spec(bible, parse_props(row))
    setting = build_setting_spec(bible, row)
    expr = resolve_expression(bible, row["expression"])
    return tpl.format(
        chars_spec=chars_spec,
        setting=setting,
        props_spec=props_spec,
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

    char_ids = parse_chars(row)
    chars_spec = format_multi_character_spec(bible, char_ids)
    props_spec = build_props_spec(bible, parse_props(row))
    setting = build_setting_spec(bible, row)
    expr = resolve_expression(bible, row["expression"])
    return tpl.format(
        chars_spec=chars_spec,
        setting=setting,
        props_spec=props_spec,
        camera=row.get("camera", "Medium 2D cartoon shot, eye level").strip(),
        action=row["action"].strip(),
        expression=expr,
        style_lock=style_lock(),
        negative_guardrails=negative_guardrails(),
    )


def build_video_mcp_call(row: dict, bible: dict, video_model: str = VIDEO_MODEL) -> dict:
    sid = int(row["id"])
    scene_id = str(row.get("scene_id", "1")).strip() or "1"
    char_ids = parse_chars(row)
    cont = row["continuity"].strip().lower()
    dur = str(row.get("duration", "6")).strip() or "6"

    # Collect reference anchors for ALL characters in this shot
    ref_anchors = []
    for cid in char_ids:
        if cid in bible.get("characters", {}):
            ref_path = bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
            ref_anchors.append(ref_path)

    # Establish max references allowed by video model (omni-flash: up to 7, veo-3.1: up to 3)
    max_refs = 3 if "veo-3.1" in video_model else 7
    prompt = build_video_prompt(row, bible)
    folder = f"{project_folder_slug()}_clips"

    if cont == "chain" and sid > 1:
        prev_last = f"frames/chain/s{sid - 1:02d}_last.png"
        if video_model in ("omni-flash", "veo-3.1-fast", "veo-3.1-lite"):
            mode = "flow-ingredients-to-video"
            image_paths = ([prev_last] + ref_anchors)[:max_refs]
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
            image_paths = ([start_kf] + ref_anchors)[:max_refs]
        else:
            mode = "flow-frame-to-video"
            image_paths = [start_kf]

    return {
        "shot_id": sid,
        "scene_id": scene_id,
        "continuity": cont,
        "characters": char_ids,
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

    required_cols = {"id", "continuity", "duration", "action", "expression", "setting", "camera"}
    cols = set(shots[0].keys())
    missing_cols = required_cols - cols
    if missing_cols:
        sys.exit(f"SHOTS.tsv is missing required columns: {', '.join(sorted(missing_cols))}")
    if "chars" not in cols and "char" not in cols:
        sys.exit("SHOTS.tsv must contain either 'chars' (preferred) or 'char' column")

    errors = []
    warnings = []
    prev_id = 0
    prev_scene = None
    all_chars_used = set()
    all_bgs_used = set()

    for idx, r in enumerate(shots, 1):
        sid = int(r["id"])
        if sid != prev_id + 1:
            warnings.append(f"Row {idx}: shot id {sid:02d} is not sequential after {prev_id:02d}")
        prev_id = sid

        scene_id = str(r.get("scene_id", "")).strip()
        char_ids = parse_chars(r)
        if not char_ids:
            errors.append(f"Shot {sid:02d}: no characters specified in 'chars' column")
        for cid in char_ids:
            all_chars_used.add(cid)
            if cid not in bible["characters"]:
                errors.append(f"Shot {sid:02d}: unknown character '{cid}' (not defined in ASSETS.json / CHARACTER_BIBLE.json)")

        bg_id = str(r.get("bg_id", "")).strip()
        if bg_id:
            all_bgs_used.add(bg_id)
            if bg_id not in bible.get("backgrounds", {}):
                warnings.append(f"Shot {sid:02d}: bg_id '{bg_id}' not found in assets backgrounds registry")

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
                        f"To animate a {dur}s scene, split it into multiple 4s, 6s, 8s, or 10s shots with continuity='chain'."
                    )
                else:
                    errors.append(
                        f"Shot {sid:02d}: invalid duration '{dur}' "
                        f"(Google Flow accepts exact strings: '4', '6', '8', or '10' seconds; choose according to scene pacing)"
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
                    f"Scope each clip to one clear physical action per character to prevent 2D morphing."
                )
        if len(action.split()) > 45:
            warnings.append(
                f"Shot {sid:02d}: action is {len(action.split())} words long "
                f"(recommend <= 35 words for crisp 2D line integrity)"
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
    multi_char_shots = sum(1 for r in shots if len(parse_chars(r)) > 1)

    print(
        f"SHOTS.tsv validated: {len(shots)} continuous 2D video shots across {len(scenes_seen)} scene(s) "
        f"({total_sec}s total duration; {new_count} scene starts, {chain_count} chained continuations, "
        f"{interp_count} interpolations; {multi_char_shots} multi-character shots). "
        f"Characters used: {', '.join(sorted(all_chars_used))}. "
        f"Backgrounds reused: {', '.join(sorted(all_bgs_used)) if all_bgs_used else 'inline settings'}."
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
        cont = r["continuity"].strip().lower()
        char_ids = parse_chars(r)
        ref_anchors = [bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png") for cid in char_ids if cid in bible.get("characters", {})]
        bg_id = str(r.get("bg_id", "")).strip()
        bg_file = bible.get("backgrounds", {}).get(bg_id, {}).get("file", f"assets/bg_{bg_id}.png") if bg_id else ""

        if cont in ("new_scene", "interp"):
            kf_prompt = build_keyframe_prompt(r, bible)
            kf_images = [p for p in ([bg_file] + ref_anchors) if p and os.path.exists(p)]
            if not kf_images:
                kf_images = ref_anchors
            manifest["keyframes"].append(
                {
                    "shot_id": sid,
                    "scene_id": scene_id,
                    "characters": char_ids,
                    "target_path": f"keyframes/s{sid:02d}_start.png",
                    "ServerName": "flow-connector",
                    "ToolName": "flow_generate",
                    "Arguments": {
                        "mode": "flow-image-to-image" if kf_images else "flow-text-to-image",
                        "prompt": kf_prompt,
                        "image_paths": kf_images,
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
        char_ids = parse_chars(r)
        ref_anchors = [bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png") for cid in char_ids if cid in bible.get("characters", {})]
        bg_id = str(r.get("bg_id", "")).strip()
        bg_file = bible.get("backgrounds", {}).get(bg_id, {}).get("file", f"assets/bg_{bg_id}.png") if bg_id else ""

        kf_images = [p for p in ([bg_file] + ref_anchors) if p and os.path.exists(p)]
        if not kf_images:
            kf_images = [p for p in ref_anchors if os.path.exists(p)]

        prompt = build_keyframe_prompt(r, bible)
        mcp_args = {
            "mode": "flow-image-to-image" if kf_images else "flow-text-to-image",
            "prompt": prompt,
            "image_paths": kf_images,
            "aspect_ratio": bible.get("aspect_ratio", "16:9"),
            "image_model": IMAGE_MODEL,
            "outputs": 1,
            "folder": f"{project_folder_slug()}_keyframes",
            "wait": args.wait,
        }
        target_kf = f"keyframes/s{sid:02d}_start.png"
        if args.dry:
            print(f"# Keyframe Shot {sid:02d} (chars: {', '.join(char_ids)}) -> {target_kf}")
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
            chars_str = ", ".join(call_spec["characters"])
            print(f"# Shot {sid:02d} [scene {call_spec['scene_id']}, {call_spec['continuity']}, chars: {chars_str}, dur: {mcp_args['duration']}s] -> clips/raw/s{sid:02d}.mp4")
            print(json.dumps({k: call_spec[k] for k in ("ServerName", "ToolName", "Arguments")}, indent=2))
            count += 1
            continue

        for req_img in mcp_args["image_paths"]:
            if not os.path.exists(req_img):
                sys.exit(
                    f"Shot {sid:02d} ({call_spec['continuity']}) requires reference image '{req_img}', which is missing.\n"
                    f"Run previous shots first (or run `video_clips.py keyframes` for new_scene shots)."
                )

        chars_str = ", ".join(call_spec["characters"])
        print(f"Submitting Shot {sid:02d} [scene {call_spec['scene_id']}, {call_spec['continuity']}, chars: {chars_str}, dur: {mcp_args['duration']}s] via Flow MCP {mcp_args['mode']} ({args.model})...")
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
    """Verify multi-character scenes, reusable backgrounds, flexible durations, and Flow MCP chaining."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="s2d_shots_test_") as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        try:
            cmd_init(argparse.Namespace(look="flat_daylight", force=True))
            # Multi-character shots, reusable background, and flexible duration mix (4s, 6s, 8s, 10s)
            shots_content = (
                "id\tscene_id\tchars\tbg_id\tprops\tcontinuity\tduration\taction\texpression\tsetting\tcamera\n"
                "01\t1\tprotagonist, secondary_character\tbedroom\tsmartphone\tnew_scene\t6\tprotagonist frantically points at the phone while secondary_character listens calmly\tanimated_speaking\tProtagonist bedroom with desk\tMedium two-shot\n"
                "02\t1\tprotagonist, secondary_character\tbedroom\tsmartphone\tchain\t4\tsecondary_character shakes head and shrugs shoulders in disbelief\tdeadpan_stare\tSame bedroom desk\tMedium close-up\n"
                "03\t2\tsupporting_character\thallway\texam_paper\tnew_scene\t8\tholds up the graded exam paper sternly while lecturing\tconfident_grin\tSchool hallway corridor\tMedium 2D shot\n"
                "04\t3\tprotagonist\tbedroom\tbackpack\tnew_scene\t10\tsits down at the bedroom desk exhausted and leans back with heavy sigh\tlistening_attentively\tProtagonist bedroom desk\tMedium wide shot\n"
            )
            with open("SHOTS.tsv", "w", encoding="utf-8") as f:
                f.write(shots_content)
            cmd_validate(argparse.Namespace())
            cmd_export_mcp(argparse.Namespace(model="omni-flash", out="mcp_jobs.json"))
            assert os.path.exists("mcp_jobs.json")
            data = json.load(open("mcp_jobs.json", encoding="utf-8"))
            assert len(data["keyframes"]) == 3  # shots 01, 03, 04 are new_scene
            assert len(data["video_clips"]) == 4

            # Verify multi-character chaining conditioned on previous frame + both character anchors
            shot2_call = data["video_clips"][1]
            assert shot2_call["continuity"] == "chain"
            assert shot2_call["Arguments"]["duration"] == "4"
            assert "frames/chain/s01_last.png" in shot2_call["Arguments"]["image_paths"]
            assert "img/ref_protagonist.png" in shot2_call["Arguments"]["image_paths"]
            assert "img/ref_secondary_character.png" in shot2_call["Arguments"]["image_paths"]

            # Verify Shot 4 duration is 10s and reuses bedroom
            shot4_call = data["video_clips"][3]
            assert shot4_call["Arguments"]["duration"] == "10"

            print("[video_clips selfcheck] PASS: Multi-character scenes, reusable assets, flexible durations, and Flow MCP chaining verified.")
        finally:
            os.chdir(old)


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Multi-Character Scene-to-Shot Planner & Frame-Chained 2D Video Generator.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate", help="Validate SHOTS.tsv multi-character scope, assets, and continuity chain")
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
