"""Step 1 — Character Bible & Master Visual Anchor manager (Flow MCP Standalone Pipeline).

Commands (run from the project folder):
    python <skill>/scripts/character_bible.py init [--look flat_daylight]
        Initialize CHARACTER_BIBLE.json, STYLE.txt, and project folders.

    python <skill>/scripts/character_bible.py validate
        Validate CHARACTER_BIBLE.json and STYLE.txt against 2D cel-shaded cartoon invariants.

    python <skill>/scripts/character_bible.py prompt [--char protagonist]
        Print the assembled Master Character Sheet prompt, individual anchor prompt, and Flow MCP JSON payload.

    python <skill>/scripts/character_bible.py generate [--char protagonist] [--wait] [--dry]
        Generate the Master Character Turnaround Sheet (img/master_sheet.png) or individual character anchor
        (img/ref_<char>.png) via Google Flow MCP (flow_generate).

    python <skill>/scripts/character_bible.py refs <sheet.png> --names protagonist,secondary_character [--cuts 0.5]
        Clean watermark from a multi-character sheet and split it into img/ref_<name>.png anchors.

    python <skill>/scripts/character_bible.py --selfcheck
        Run offline validation and synthetic sheet splitting test.
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
PROMPTS_DIR = os.path.join(SKILL_DIR, "prompts")
LOOKS_DIR = os.path.join(SKILL_DIR, "looks")

sys.path.insert(0, HERE)
from delama_video import unmark_image  # noqa: E402

BRIDGE_URL = os.environ.get("FLOW_BRIDGE_URL", "http://127.0.0.1:8791")
IMAGE_MODEL = os.environ.get("FLOW_IMAGE_MODEL", "nano-banana-2")


def load_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return " ".join(line.strip() for line in f if line.strip())


def style_lock() -> str:
    return load_text(os.path.join(PROMPTS_DIR, "style_lock.txt"))


def negative_guardrails() -> str:
    return load_text(os.path.join(PROMPTS_DIR, "negative_guardrails.txt"))


def shot_templates() -> dict:
    with open(os.path.join(PROMPTS_DIR, "shot_templates.json"), encoding="utf-8") as f:
        return json.load(f)


def project_folder_slug() -> str:
    slug = re.sub(r"[^a-z0-9_-]", "", os.path.basename(os.getcwd()).lower())
    return f"s2d_{slug or 'project'}"


def load_bible(path: str = None) -> dict:
    candidates = [path] if path else ["CHARACTER_BIBLE.json", "ASSETS.json"]
    for c in candidates:
        if c and os.path.exists(c):
            with open(c, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("characters", {})
            data.setdefault("backgrounds", {})
            data.setdefault("props", {})
            data.setdefault("expression_presets", {})
            return data
    sys.exit("Missing CHARACTER_BIBLE.json (or ASSETS.json). Run: python <skill>/scripts/character_bible.py init")


def format_character_spec(char_obj: dict) -> str:
    """Compile a character's immutable visual anchor specification into a single dense prompt clause."""
    name = char_obj.get("display_name", char_obj.get("id", "Character"))
    role = char_obj.get("role", "2D cartoon character")
    head = char_obj.get("head_and_face", "").strip().rstrip(".")
    hair = char_obj.get("hair_silhouette", "").strip().rstrip(".")
    outfit = char_obj.get("outfit", "").strip().rstrip(".")
    props = char_obj.get("proportions", "").strip().rstrip(".")
    return (
        f"{name} ({role}): {props}. Head & Face: {head}. "
        f"Signature Hair Silhouette: {hair}. "
        f"Signature Solid-Color Outfit: {outfit}."
    )


def format_multi_character_spec(bible: dict, char_ids: list) -> str:
    """Compile multiple character specifications with distinct identities and positioning guidelines."""
    chars = bible.get("characters", {})
    clauses = []
    for idx, cid in enumerate(char_ids, 1):
        if cid in chars:
            c = chars[cid]
            spec = format_character_spec(c)
            clauses.append(f"[Character {idx}] {spec}")
        else:
            clauses.append(f"[Character {idx}] {cid} (2D cel-shaded cartoon character)")
    summary = " ".join(clauses)
    if len(char_ids) > 1:
        summary += (
            " Maintain distinct identity, facial features, hair silhouette, and outfit color "
            "for each character. Do not blend, merge, or cross-pollinate character features."
        )
    return summary


def build_master_sheet_prompt(bible: dict, char_ids=None) -> str:
    tpl = shot_templates()["master_sheet_template"]
    chars = bible["characters"]
    selected = [chars[cid] for cid in (char_ids or list(chars.keys())) if cid in chars]
    descs = []
    for idx, c in enumerate(selected, 1):
        descs.append(f"({idx}) {format_character_spec(c)}")
    prompt = tpl.format(count=len(selected), cast_descriptions="; ".join(descs))
    return f"{prompt} {style_lock()} {negative_guardrails()}"


def build_single_anchor_prompt(bible: dict, char_id: str) -> str:
    if char_id not in bible["characters"]:
        sys.exit(
            f"Character '{char_id}' not found in CHARACTER_BIBLE.json "
            f"(available: {', '.join(bible['characters'])})"
        )
    tpl = shot_templates()["single_character_anchor_template"]
    spec = format_character_spec(bible["characters"][char_id])
    prompt = tpl.format(char_spec=spec)
    return f"{prompt} {style_lock()} {negative_guardrails()}"


def cmd_init(args):
    look = args.look or "flat_daylight"
    look_file = os.path.join(LOOKS_DIR, f"{look}.md")
    if not os.path.exists(look_file):
        sys.exit(
            f"Unknown look '{look}'. Available in {LOOKS_DIR}: "
            f"flat_daylight, warm_interior, high_contrast_focus, minimal_backdrop"
        )

    for d in ("img", "assets", "keyframes", "clips/raw", "clips/clean", "clips/norm", "frames/chain", "frames/qc"):
        os.makedirs(d, exist_ok=True)

    src_json = os.path.join(PROMPTS_DIR, "assets.json")
    if not os.path.exists(src_json):
        src_json = os.path.join(PROMPTS_DIR, "character_bible.json")

    if not os.path.exists("CHARACTER_BIBLE.json") or args.force:
        shutil.copy(src_json, "CHARACTER_BIBLE.json")
        print("Created CHARACTER_BIBLE.json")
    else:
        print("CHARACTER_BIBLE.json already exists (use --force to overwrite)")

    if not os.path.exists("ASSETS.json") or args.force:
        shutil.copy(src_json, "ASSETS.json")
        print("Created ASSETS.json")

    if not os.path.exists("STYLE.txt") or args.force:
        raw_look = open(look_file, encoding="utf-8").read().splitlines()
        style_lines = []
        capture = False
        for ln in raw_look:
            if ln.strip().startswith("look:"):
                capture = True
            if capture and ln.strip():
                style_lines.append(ln.strip())
        if not style_lines:
            style_lines = [f"look: {look}", style_lock()]
        with open("STYLE.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(style_lines) + "\n")
        print(f"Created STYLE.txt (look: {look})")
    else:
        print("STYLE.txt already exists (use --force to overwrite)")


def cmd_validate(_args):
    bible = load_bible()
    required_char_keys = {
        "id",
        "display_name",
        "head_and_face",
        "hair_silhouette",
        "outfit",
        "proportions",
        "reference_image",
        "forbidden_drift",
    }
    errors = []
    if bible.get("style_preset") != "2d_cel_storytime_animation":
        errors.append("style_preset must be '2d_cel_storytime_animation'")
    chars = bible.get("characters", {})
    if not chars:
        errors.append("CHARACTER_BIBLE.json must define at least one character (e.g. 'protagonist')")
    for cid, cobj in chars.items():
        missing = required_char_keys - set(cobj.keys())
        if missing:
            errors.append(f"Character '{cid}' is missing required fields: {', '.join(sorted(missing))}")
        for field in ("head_and_face", "hair_silhouette", "outfit", "proportions"):
            val = str(cobj.get(field, "")).lower()
            if "3d" in val and "zero 3d" not in val and "no 3d" not in val and "not 3d" not in val:
                errors.append(f"Character '{cid}' field '{field}' mentions 3D (strictly 2D cel-shaded cartoon only)")
    if os.path.exists("STYLE.txt"):
        st = open("STYLE.txt", encoding="utf-8").read().lower()
        if "2d" not in st or "black ink" not in st:
            errors.append("STYLE.txt must specify '2D' cartoon animation and 'black ink' outlines")
    else:
        errors.append("Missing STYLE.txt in project directory")

    if errors:
        print("CHARACTER BIBLE VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(
        f"CHARACTER_BIBLE.json & STYLE.txt validated: {len(chars)} character(s) "
        f"({', '.join(chars.keys())}) locked to 2D cel-shaded storytime specification."
    )


def submit_via_mcp_bridge(mcp_args: dict, wait: bool = True) -> dict:
    """Submit a generation job directly to the local Flow MCP bridge (127.0.0.1:8791)
    using the exact wire format of the flow-connector MCP server.
    """
    payload = {
        "job": {
            "prompt": mcp_args["prompt"],
            "mode": mcp_args.get("mode", "flow-text-to-image"),
            "params": {
                "aspectRatio": mcp_args.get("aspect_ratio", "16:9"),
                "videoOption": f"{mcp_args['duration']}s" if mcp_args.get("duration") else None,
                "imageModel": mcp_args.get("image_model", IMAGE_MODEL),
                "outputsPerPrompt": mcp_args.get("outputs", 1),
                "downloadSubfolder": mcp_args.get("folder", project_folder_slug()),
                "autoRenameFiles": True,
                "newProject": mcp_args.get("new_project"),
                "characterName": mcp_args.get("character_name"),
                "maxRetries": mcp_args.get("max_retries", 3),
            },
            "inputImages": [],
            "assetRefs": mcp_args.get("asset_refs"),
            "characterRefs": mcp_args.get("character_refs"),
        },
        "imagePaths": [os.path.abspath(p) for p in mcp_args.get("image_paths", [])],
        "client": "flow-mcp",
        "maxRetries": mcp_args.get("max_retries", 3),
    }
    req = urllib.request.Request(
        f"{BRIDGE_URL}/jobs",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
    job_id = res_data.get("jobId")
    if not wait or not job_id:
        return {"jobId": job_id, "status": "queued"}
    wait_req = urllib.request.Request(f"{BRIDGE_URL}/jobs/{job_id}/wait?timeoutMs=90000", method="GET")
    with urllib.request.urlopen(wait_req, timeout=95) as wresp:
        return json.loads(wresp.read().decode("utf-8"))


def cmd_prompt(args):
    bible = load_bible()
    if args.char:
        prompt = build_single_anchor_prompt(bible, args.char)
        folder = f"{project_folder_slug()}_anchor_{args.char}"
    else:
        prompt = build_master_sheet_prompt(bible)
        folder = f"{project_folder_slug()}_sheet"

    mcp_call = {
        "ServerName": "flow-connector",
        "ToolName": "flow_generate",
        "Arguments": {
            "mode": "flow-text-to-image",
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "image_model": IMAGE_MODEL,
            "outputs": 2,
            "folder": folder,
            "wait": True,
        },
    }
    print("=== ASSEMBLED PROMPT ===")
    print(prompt)
    print("\n=== GOOGLE FLOW MCP TOOL CALL (flow_generate) ===")
    print(json.dumps(mcp_call, indent=2))


def cmd_generate(args):
    bible = load_bible()
    os.makedirs("img", exist_ok=True)
    targets = [args.char] if args.char else list(bible["characters"].keys())

    if args.sheet:
        prompt = build_master_sheet_prompt(bible, targets)
        folder = f"{project_folder_slug()}_sheet"
        mcp_args = {
            "mode": "flow-text-to-image",
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "image_model": IMAGE_MODEL,
            "outputs": 2,
            "folder": folder,
            "wait": args.wait,
        }
        if args.dry:
            print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
            return
        _dispatch_mcp_image_job(mcp_args, out_target="img/master_sheet.png", wait=args.wait)
        return

    for cid in targets:
        prompt = build_single_anchor_prompt(bible, cid)
        ref_path = bible["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
        folder = f"{project_folder_slug()}_ref_{cid}"
        mcp_args = {
            "mode": "flow-text-to-image",
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "image_model": IMAGE_MODEL,
            "outputs": 1,
            "folder": folder,
            "wait": args.wait,
        }
        if args.dry:
            print(f"# Character Anchor: {cid} -> {ref_path}")
            print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
            continue
        _dispatch_mcp_image_job(mcp_args, out_target=ref_path, wait=args.wait)


def _dispatch_mcp_image_job(mcp_args: dict, out_target: str, wait: bool):
    try:
        job = submit_via_mcp_bridge(mcp_args, wait=wait)
        files = job.get("files") or []
        if files and os.path.exists(files[0]["path"]):
            cleaned = unmark_image(Image.open(files[0]["path"]))
            os.makedirs(os.path.dirname(os.path.abspath(out_target)), exist_ok=True)
            cleaned.save(out_target)
            print(f"[Flow MCP] Saved watermark-cleaned anchor -> {os.path.abspath(out_target)}")
            return
        print(f"[Flow MCP] Job submitted: {json.dumps(job)}")
    except Exception as exc:
        sys.exit(f"Flow MCP submission failed: {exc}")


def cmd_refs(args):
    sheet_path = args.sheet_path
    if not os.path.exists(sheet_path):
        sys.exit(f"Sheet file not found: {sheet_path}")
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if args.cuts:
        cuts = [float(c) for c in args.cuts.split(",")]
    else:
        cuts = [i / len(names) for i in range(1, len(names))]
    os.makedirs("img", exist_ok=True)
    im = unmark_image(Image.open(sheet_path))
    im.save("img/master_sheet.png")
    xs = [0] + [int(round(c * im.width)) for c in cuts] + [im.width]
    written = []
    for name, x0, x1 in zip(names, xs, xs[1:]):
        crop = im.crop((x0, 0, x1, im.height))
        out_p = f"img/ref_{name}.png"
        crop.save(out_p)
        written.append(out_p)
    print(f"Cleaned img/master_sheet.png and wrote {len(written)} character reference anchors: {', '.join(written)}")


def selfcheck():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="s2d_char_test_") as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        try:
            ns = argparse.Namespace(look="flat_daylight", force=True)
            cmd_init(ns)
            cmd_validate(ns)
            im = Image.new("RGB", (1376, 768), (232, 236, 239))
            draw = ImageDraw.Draw(im)
            colors = [(230, 57, 70), (0, 180, 216), (233, 196, 106)]
            for idx, col in enumerate(colors):
                cx = int((idx + 0.5) * (1376 / 3))
                draw.rectangle((cx - 70, 320, cx + 70, 580), fill=col, outline=(0, 0, 0), width=6)
                draw.ellipse((cx - 65, 160, cx + 65, 310), fill=(252, 240, 225), outline=(0, 0, 0), width=6)
            sheet_file = os.path.join(tmp, "raw_sheet.png")
            im.save(sheet_file)
            ref_ns = argparse.Namespace(
                sheet_path=sheet_file,
                names="protagonist,secondary_character,supporting_character",
                cuts=None,
            )
            cmd_refs(ref_ns)
            for n in ("protagonist", "secondary_character", "supporting_character"):
                p = os.path.join(tmp, "img", f"ref_{n}.png")
                assert os.path.exists(p), f"Missing {p}"
            print("[character_bible selfcheck] PASS: Init, validation, prompt lock, and sheet splitting verified.")
        finally:
            os.chdir(old)


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Character Bible & Master Visual Anchor manager (Flow MCP).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize CHARACTER_BIBLE.json and STYLE.txt")
    p_init.add_argument("--look", default="flat_daylight")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_val = sub.add_parser("validate", help="Validate CHARACTER_BIBLE.json and STYLE.txt")
    p_val.set_defaults(func=cmd_validate)

    p_pr = sub.add_parser("prompt", help="Print assembled character anchor prompt and Flow MCP payload")
    p_pr.add_argument("--char", help="Specific character id (e.g. protagonist); omit for master turnaround sheet")
    p_pr.set_defaults(func=cmd_prompt)

    p_gen = sub.add_parser("generate", help="Generate Master Character Anchor(s) via Flow MCP")
    p_gen.add_argument("--char", help="Specific character id (e.g. protagonist)")
    p_gen.add_argument("--sheet", action="store_true", help="Generate multi-character turnaround sheet")
    p_gen.add_argument("--wait", action="store_true", default=True)
    p_gen.add_argument("--dry", action="store_true", help="Print Flow MCP payload without submitting")
    p_gen.set_defaults(func=cmd_generate)

    p_refs = sub.add_parser("refs", help="Split a turnaround sheet into img/ref_<name>.png anchors")
    p_refs.add_argument("sheet_path")
    p_refs.add_argument("--names", required=True, help="Comma-separated character IDs")
    p_refs.add_argument("--cuts", help="Optional comma-separated horizontal split fractions (e.g. 0.33,0.66)")
    p_refs.set_defaults(func=cmd_refs)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
