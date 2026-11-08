"""Step 1 — Character Planning & Reusable Visual Asset Generator (Flow MCP Pipeline).

Enforces the "Asset Generation First" paradigm:
Before any animated video clips are generated, all recurring characters, backgrounds,
and props are planned, generated, watermark-cleaned, and locked into reusable assets.

Commands (run from the project folder):
    python <skill>/scripts/assets.py init [--look flat_daylight] [--force]
        Initialize ASSETS.json, STYLE.txt, and project folders (img/, assets/, keyframes/, clips/, frames/).

    python <skill>/scripts/assets.py validate
        Validate characters, backgrounds, and props against 2D cel-shaded invariants.

    python <skill>/scripts/assets.py prompt [--type all|characters|backgrounds|props] [--id <asset_id>]
        Print Flow MCP payloads for generating characters, backgrounds, or props.

    python <skill>/scripts/assets.py generate [--type all|characters|backgrounds|props] [--id <asset_id>] [--wait] [--dry]
        Generate reusable visual assets via Flow MCP (flow_generate), watermark-clean via delama_video.py.

    python <skill>/scripts/assets.py refs <sheet.png> --names char1,char2 [--cuts 0.5]
        Clean watermark from a multi-character sheet and split it into img/ref_<name>.png anchors.

    python <skill>/scripts/assets.py --selfcheck
        Run full offline validation and asset generation test.
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


def load_assets(path: str = None) -> dict:
    candidates = [path] if path else ["ASSETS.json", "CHARACTER_BIBLE.json"]
    for c in candidates:
        if c and os.path.exists(c):
            with open(c, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("characters", {})
            data.setdefault("backgrounds", {})
            data.setdefault("props", {})
            data.setdefault("expression_presets", {})
            return data
    sys.exit("Missing ASSETS.json (or CHARACTER_BIBLE.json). Run: python <skill>/scripts/assets.py init")


def format_character_spec(char_obj: dict) -> str:
    """Compile a character's immutable visual anchor specification into a dense prompt clause."""
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


def format_multi_character_spec(assets: dict, char_ids: list) -> str:
    """Compile multiple character specifications with distinct identities and positioning guidelines."""
    chars = assets.get("characters", {})
    clauses = []
    for idx, cid in enumerate(char_ids, 1):
        if cid in chars:
            c = chars[cid]
            name = c.get("display_name", cid)
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


def build_single_character_prompt(assets: dict, char_id: str) -> str:
    if char_id not in assets["characters"]:
        sys.exit(f"Character '{char_id}' not found in assets registry (available: {', '.join(assets['characters'])})")
    tpl = shot_templates()["single_character_anchor_template"]
    spec = format_character_spec(assets["characters"][char_id])
    prompt = tpl.format(char_spec=spec)
    return f"{prompt} {style_lock()} {negative_guardrails()}"


def build_master_sheet_prompt(assets: dict, char_ids=None) -> str:
    tpl = shot_templates()["master_sheet_template"]
    chars = assets["characters"]
    selected = [chars[cid] for cid in (char_ids or list(chars.keys())) if cid in chars]
    descs = [f"({idx}) {format_character_spec(c)}" for idx, c in enumerate(selected, 1)]
    prompt = tpl.format(count=len(selected), cast_descriptions="; ".join(descs))
    return f"{prompt} {style_lock()} {negative_guardrails()}"


def build_background_prompt(assets: dict, bg_id: str) -> str:
    if bg_id not in assets["backgrounds"]:
        sys.exit(f"Background '{bg_id}' not found in assets registry (available: {', '.join(assets['backgrounds'])})")
    bg = assets["backgrounds"][bg_id]
    tpl = shot_templates()["background_asset_template"]
    prompt = tpl.format(
        bg_name=bg.get("name", bg_id),
        bg_desc=bg.get("description", "Simple 2D cartoon background"),
        style_lock=style_lock(),
        negative_guardrails=negative_guardrails(),
    )
    return prompt


def build_prop_prompt(assets: dict, prop_id: str) -> str:
    if prop_id not in assets["props"]:
        sys.exit(f"Prop '{prop_id}' not found in assets registry (available: {', '.join(assets['props'])})")
    p = assets["props"][prop_id]
    tpl = shot_templates()["prop_asset_template"]
    prompt = tpl.format(
        prop_name=p.get("name", prop_id),
        prop_desc=p.get("description", "2D cartoon prop"),
        style_lock=style_lock(),
        negative_guardrails=negative_guardrails(),
    )
    return prompt


def submit_via_mcp_bridge(mcp_args: dict, wait: bool = True) -> dict:
    """Submit a generation job directly to the local Flow MCP bridge."""
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


def _dispatch_mcp_image_job(mcp_args: dict, out_target: str, wait: bool):
    try:
        job = submit_via_mcp_bridge(mcp_args, wait=wait)
        files = job.get("files") or []
        if files and os.path.exists(files[0]["path"]):
            cleaned = unmark_image(Image.open(files[0]["path"]))
            os.makedirs(os.path.dirname(os.path.abspath(out_target)), exist_ok=True)
            cleaned.save(out_target)
            print(f"[Flow MCP] Saved watermark-cleaned asset -> {os.path.abspath(out_target)}")
            return
        print(f"[Flow MCP] Job submitted: {json.dumps(job)}")
    except Exception as exc:
        sys.exit(f"Flow MCP submission failed: {exc}")


def cmd_init(args):
    look = args.look or "flat_daylight"
    look_file = os.path.join(LOOKS_DIR, f"{look}.md")
    if not os.path.exists(look_file):
        sys.exit(f"Unknown look '{look}'. Available: flat_daylight, warm_interior, high_contrast_focus, minimal_backdrop")

    for d in ("img", "assets", "keyframes", "clips/raw", "clips/clean", "clips/norm", "frames/chain", "frames/qc"):
        os.makedirs(d, exist_ok=True)

    src_json = os.path.join(PROMPTS_DIR, "assets.json")
    if not os.path.exists("ASSETS.json") or args.force:
        shutil.copy(src_json, "ASSETS.json")
        print("Created ASSETS.json")
    else:
        print("ASSETS.json already exists (use --force to overwrite)")

    if not os.path.exists("CHARACTER_BIBLE.json") or args.force:
        shutil.copy(src_json, "CHARACTER_BIBLE.json")
        print("Created CHARACTER_BIBLE.json")

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
    assets = load_assets()
    errors = []
    warnings = []

    if assets.get("style_preset") != "2d_cel_storytime_animation":
        errors.append("style_preset must be '2d_cel_storytime_animation'")

    # Validate characters
    chars = assets.get("characters", {})
    if not chars:
        errors.append("ASSETS.json must define at least one character")
    required_char_keys = {"id", "display_name", "head_and_face", "hair_silhouette", "outfit", "proportions"}
    for cid, cobj in chars.items():
        missing = required_char_keys - set(cobj.keys())
        if missing:
            errors.append(f"Character '{cid}' is missing required fields: {', '.join(sorted(missing))}")
        for field in ("head_and_face", "hair_silhouette", "outfit", "proportions"):
            val = str(cobj.get(field, "")).lower()
            if "3d" in val and "zero 3d" not in val and "no 3d" not in val and "not 3d" not in val:
                errors.append(f"Character '{cid}' field '{field}' mentions 3D (strictly 2D cel-shaded cartoon only)")

    # Validate backgrounds
    bgs = assets.get("backgrounds", {})
    for bid, bobj in bgs.items():
        if "description" not in bobj:
            errors.append(f"Background '{bid}' missing 'description'")
        desc = bobj.get("description", "").lower()
        # Ensure it does not request characters in the background, while allowing "empty of people" or "zero people"
        cleaned_desc = re.sub(r"\b(empty of|zero|without|no)\s+(people|persons|characters|people)\b", "", desc)
        if any(w in cleaned_desc for w in ("person", "people", "character", "man", "woman", "boy", "girl")):
            warnings.append(
                f"Background '{bid}' description mentions people/characters. "
                f"Reusable background assets should be empty environments to maintain clean figure-ground separation."
            )

    # Validate props
    props = assets.get("props", {})
    for pid, pobj in props.items():
        if "description" not in pobj:
            errors.append(f"Prop '{pid}' missing 'description'")

    # Validate STYLE.txt
    if os.path.exists("STYLE.txt"):
        st = open("STYLE.txt", encoding="utf-8").read().lower()
        if "2d" not in st or "black ink" not in st:
            errors.append("STYLE.txt must specify '2D' cartoon animation and 'black ink' outlines")
    else:
        errors.append("Missing STYLE.txt in project directory")

    if errors:
        print("ASSET VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}")

    print(
        f"ASSETS.json & STYLE.txt validated: {len(chars)} character(s) ({', '.join(chars.keys())}), "
        f"{len(bgs)} background(s) ({', '.join(bgs.keys())}), {len(props)} prop(s) ({', '.join(props.keys())}) "
        f"locked to 2D cel-shaded storytime specification."
    )


def cmd_prompt(args):
    assets = load_assets()
    target_type = args.type or "all"
    target_id = args.id

    def print_job(name, prompt, folder, aspect="16:9"):
        mcp_call = {
            "ServerName": "flow-connector",
            "ToolName": "flow_generate",
            "Arguments": {
                "mode": "flow-text-to-image",
                "prompt": prompt,
                "aspect_ratio": aspect,
                "image_model": IMAGE_MODEL,
                "outputs": 1,
                "folder": folder,
                "wait": True,
            },
        }
        print(f"\n=== ASSET: {name} ===")
        print(prompt)
        print("\nFlow MCP Call:")
        print(json.dumps(mcp_call, indent=2))

    if target_type in ("all", "characters"):
        chars = [target_id] if target_id and target_id in assets["characters"] else list(assets["characters"].keys())
        for cid in chars:
            p = build_single_character_prompt(assets, cid)
            print_job(f"Character Anchor [{cid}]", p, f"{project_folder_slug()}_ref_{cid}")

    if target_type in ("all", "backgrounds"):
        bgs = [target_id] if target_id and target_id in assets["backgrounds"] else list(assets["backgrounds"].keys())
        for bid in bgs:
            p = build_background_prompt(assets, bid)
            print_job(f"Background Asset [{bid}]", p, f"{project_folder_slug()}_bg_{bid}")

    if target_type in ("all", "props"):
        props = [target_id] if target_id and target_id in assets["props"] else list(assets["props"].keys())
        for pid in props:
            p = build_prop_prompt(assets, pid)
            print_job(f"Prop Asset [{pid}]", p, f"{project_folder_slug()}_prop_{pid}", aspect="16:9")


def cmd_generate(args):
    assets = load_assets()
    target_type = args.type or "all"
    target_id = args.id

    # 1. Characters
    if target_type in ("all", "characters"):
        chars = [target_id] if target_id and target_id in assets["characters"] else list(assets["characters"].keys())
        for cid in chars:
            ref_path = assets["characters"][cid].get("reference_image", f"img/ref_{cid}.png")
            p = build_single_character_prompt(assets, cid)
            mcp_args = {
                "mode": "flow-text-to-image",
                "prompt": p,
                "aspect_ratio": "16:9",
                "image_model": IMAGE_MODEL,
                "outputs": 1,
                "folder": f"{project_folder_slug()}_ref_{cid}",
                "wait": args.wait,
            }
            if args.dry:
                print(f"# Character: {cid} -> {ref_path}")
                print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
                continue
            _dispatch_mcp_image_job(mcp_args, out_target=ref_path, wait=args.wait)

    # 2. Backgrounds
    if target_type in ("all", "backgrounds"):
        bgs = [target_id] if target_id and target_id in assets["backgrounds"] else list(assets["backgrounds"].keys())
        for bid in bgs:
            bg_path = assets["backgrounds"][bid].get("file", f"assets/bg_{bid}.png")
            p = build_background_prompt(assets, bid)
            mcp_args = {
                "mode": "flow-text-to-image",
                "prompt": p,
                "aspect_ratio": "16:9",
                "image_model": IMAGE_MODEL,
                "outputs": 1,
                "folder": f"{project_folder_slug()}_bg_{bid}",
                "wait": args.wait,
            }
            if args.dry:
                print(f"# Background: {bid} -> {bg_path}")
                print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
                continue
            _dispatch_mcp_image_job(mcp_args, out_target=bg_path, wait=args.wait)

    # 3. Props
    if target_type in ("all", "props"):
        props = [target_id] if target_id and target_id in assets["props"] else list(assets["props"].keys())
        for pid in props:
            prop_path = assets["props"][pid].get("file", f"assets/prop_{pid}.png")
            p = build_prop_prompt(assets, pid)
            mcp_args = {
                "mode": "flow-text-to-image",
                "prompt": p,
                "aspect_ratio": "16:9",
                "image_model": IMAGE_MODEL,
                "outputs": 1,
                "folder": f"{project_folder_slug()}_prop_{pid}",
                "wait": args.wait,
            }
            if args.dry:
                print(f"# Prop: {pid} -> {prop_path}")
                print(json.dumps({"ServerName": "flow-connector", "ToolName": "flow_generate", "Arguments": mcp_args}, indent=2))
                continue
            _dispatch_mcp_image_job(mcp_args, out_target=prop_path, wait=args.wait)


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

    with tempfile.TemporaryDirectory(prefix="s2d_assets_test_") as tmp:
        old = os.getcwd()
        os.chdir(tmp)
        try:
            ns = argparse.Namespace(look="flat_daylight", force=True)
            cmd_init(ns)
            cmd_validate(ns)

            assets = load_assets()
            assert "characters" in assets and len(assets["characters"]) >= 2
            assert "backgrounds" in assets and len(assets["backgrounds"]) >= 1
            assert "props" in assets and len(assets["props"]) >= 1

            # Test prompt compilation
            p_single = build_single_character_prompt(assets, "protagonist")
            p_multi = format_multi_character_spec(assets, ["protagonist", "secondary_character"])
            p_bg = build_background_prompt(assets, "bedroom")
            p_prop = build_prop_prompt(assets, "smartphone")

            assert "Protagonist" in p_single
            assert "Secondary Character" in p_multi
            assert "bedroom" in p_bg.lower() or "bedroom" in assets["backgrounds"]["bedroom"]["name"].lower()
            assert "smartphone" in p_prop.lower()

            # Test sheet splitter
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

            print("[assets selfcheck] PASS: Init, validation, multi-character prompt formatting, asset generation, and sheet splitting verified.")
        finally:
            os.chdir(old)


def main():
    if "--selfcheck" in sys.argv:
        return selfcheck()
    ap = argparse.ArgumentParser(description="Character Planning & Reusable Visual Asset Generator (Flow MCP).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize ASSETS.json, STYLE.txt, and asset directories")
    p_init.add_argument("--look", default="flat_daylight")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_val = sub.add_parser("validate", help="Validate ASSETS.json and STYLE.txt against 2D invariants")
    p_val.set_defaults(func=cmd_validate)

    p_pr = sub.add_parser("prompt", help="Print Flow MCP payloads for characters, backgrounds, or props")
    p_pr.add_argument("--type", choices=["all", "characters", "backgrounds", "props"], default="all")
    p_pr.add_argument("--id", help="Specific asset ID")
    p_pr.set_defaults(func=cmd_prompt)

    p_gen = sub.add_parser("generate", help="Generate reusable visual assets via Flow MCP")
    p_gen.add_argument("--type", choices=["all", "characters", "backgrounds", "props"], default="all")
    p_gen.add_argument("--id", help="Specific asset ID")
    p_gen.add_argument("--wait", action="store_true", default=True)
    p_gen.add_argument("--dry", action="store_true", help="Print Flow MCP payload without submitting")
    p_gen.set_defaults(func=cmd_generate)

    p_refs = sub.add_parser("refs", help="Split a turnaround sheet into img/ref_<name>.png anchors")
    p_refs.add_argument("sheet_path")
    p_refs.add_argument("--names", required=True, help="Comma-separated character IDs")
    p_refs.add_argument("--cuts", help="Optional comma-separated horizontal split fractions")
    p_refs.set_defaults(func=cmd_refs)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
