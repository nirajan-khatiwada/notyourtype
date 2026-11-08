---
name: not-your-type
description: Standalone 2D cel-shaded storytime character video animation pipeline powered exclusively by Google Flow MCP and FFmpeg. Trigger whenever the user says "create a not your type", "not your type", "not your type start", "not your type continue", "not your type setup", "2d storytime", "make a 2d storytime video", or "storytime animation". Asks the user for Title/Topic, Language, Length, and Character Planning, generates all reusable visual assets first (characters, backgrounds, props), plans scenes with single or multiple characters, generates continuous 2D video clips (4s-10s per clip via Flow MCP), chains sequential clips with anti-morphing frame inspection, and stitches normalized 1080p clips into a master MP4.
---

# 2D Storytime Character Video Animation Skill (Standalone Flow MCP Pipeline)

You direct, plan, generate, and assemble complete **2D cel-shaded storytime character animation videos** end to end using **Google Flow MCP (`flow-connector`)** and local **FFmpeg** utilities.

This skill is **100% standalone** and depends only on **Google Flow MCP** (`flow_generate`, `flow_get_job`, `flow_list_jobs`, `flow_retry_job`, `flow_cancel_job`, `flow_status`, `flow_doctor`, `flow_stop`), Python, and FFmpeg. It generates **true continuous 2D animated video clips** chained together for temporal and character continuity—never static slideshows.

**Talk to the user in their own language** (English, Hinglish, Hindi, or whichever language they use), simply and directly.

> [!IMPORTANT]
> **Flexible Clip Duration Limits in Google Flow (4s, 6s, 8s, or 10s — Never Fixed to 6s):**
> Google Flow generates video clips in discrete duration options: `"4"`, `"6"`, `"8"`, or `"10"` seconds per clip (`omni-flash` supports all 4 durations; `veo-3.1-*` models generate up to `8` seconds per clip).
> - **Clip duration is NOT fixed to 6 seconds.** You can choose and mix `4s`, `6s`, `8s`, or `10s` based on the scene's narrative pacing:
>   - `4` seconds: Fast-paced comedic reactions, quick cutaways, punchlines, or sudden visual shocks.
>   - `6` seconds: Standard balanced duration for general 2D character actions, gestures, and line delivery.
>   - `8` seconds: Extended dialogue exchanges, multi-character interactions, or continuous character movement.
>   - `10` seconds: Maximum Google Flow single-clip capacity; ideal for continuous storytelling monologues or detailed character acting.
> - **Multi-Clip Segmentation Math:** A video longer than 10 seconds (e.g. 30s, 60s, 2m) is segmented into sequential shots in `SHOTS.tsv` ($\sum d_i = \text{Target Duration}$) chained frame-by-frame and stitched into `<project>.mp4`.

`<skill>` refers to this skill's directory:
- `C:\Users\Nirajan\.gemini\config\skills\not-your-type\`

**Before planning or executing a video project, read `<skill>/README.md`, `<skill>/PLAYBOOK.md`, and `<skill>/prompts/README.md`.**

---

## 0. Interactive Startup & Character Planning Protocol (Execute First)

Whenever the user triggers this skill (for example: `"create a not your type"`, `"not your type start"`, `"make a 2d storytime video"`, `"continue"`, or gives a topic):

### Step 0.1 — Setup & Resume Check
1. **Setup Check:** Read `<skill>/SETUP_STATUS.md`. If missing or any row is not ✅, run `<skill>/SETUP.md` first.
2. **Resume Check:** If the user says `"continue"` with no topic, open the most recently modified `PROGRESS.md` under `~/Storytime2D/`, state which project and stage you are resuming, and continue from there.

### Step 0.2 — Ask for Title, Language, Length, and Character Planning
If starting a new project without parameters, ask the user **in ONE concise message**:
1. **Title / Topic:** What is the story title or topic? *(Or: "Want me to suggest 10 storytime topics?")*
2. **Language:** What language should the story be written in? *(e.g. Hindi, Hinglish, English, or any other)*
3. **Length & Pacing:** Target video duration? *(e.g. 30 seconds, 1 minute, 2 minutes — segmented into 4s, 6s, 8s, or 10s clips)*
4. **Character Planning:** How many recurring characters are required, and what are their names, roles, and visual descriptions?
   *(e.g., Character 1: Alex [Lead, spiky black hair, red hoodie], Character 2: Sam [Friend, curly hair, round glasses, teal shirt]. If the user wants suggestions, propose a tailored 2-3 character cast based on the topic!)*

**Wait for the user's confirmation** before generating any assets or writing project files.

---

## 1. Five Core Architectural Pillars

### Pillar 1 — Character Planning & Cast Definition
- Before generating any assets or video clips, establish all recurring characters in `ASSETS.json` / `CHARACTER_BIBLE.json`.
- For each character, lock:
  - `id` & `display_name`
  - `role` (Lead storyteller, Best friend, Teacher, Rival, Parent)
  - `head_and_face` (Bean-shaped head, skin tone, eye style, eyebrows, mouth)
  - `hair_silhouette` (Unchanging geometric hair shape)
  - `outfit` (Signature solid-color clothing, zero logos/text/patterns)
  - `proportions` (~3.5 to 4 heads tall, clean 4-finger cartoon hands)

### Pillar 2 — Multiple Characters Support
- Scenes and shots are **never** restricted to a single character.
- Both `SCENES.tsv` and `SHOTS.tsv` support single or multiple characters in the `characters` / `chars` column (e.g., `protagonist, secondary_character`).
- In multi-character scenes:
  - Staging and interaction are explicitly described (e.g., *"Alex gestures frantically on the left while Sam listens with crossed arms on the right"*).
  - Prompts compile each character's identity lock (`{chars_spec}`) so each character retains their distinct hair and outfit colors.
  - Video and keyframe generation condition on the established reference anchors of **all** characters present in that shot (Flow MCP `omni-flash` supports up to 7 reference images; `veo-3.1` supports up to 3).

### Pillar 3 — Strict Character Consistency
- Every character has an established reference anchor (`img/ref_<char_id>.png` or turnaround sheet `img/master_sheet.png`).
- Once established in the Asset Generation phase, these exact references are immutable.
- In every keyframe, scene start, or chained clip, the pipeline **always** inputs the established reference image(s) into Flow MCP.
- Never generate new or ad-hoc interpretations of recurring characters during scene generation.

### Pillar 4 — Asset Generation First (Characters, Backgrounds, Props)
**Before generating any video clips**, generate and establish all required reusable visual assets:
1. **Characters:** `img/ref_<char>.png` (or master sheet `img/master_sheet.png` split via `refs`).
2. **Backgrounds:** `assets/bg_<bg_id>.png` (clean, text-free, unpeopled 2D cel-shaded illustrated environments for every unique location).
3. **Props & Objects:** `assets/prop_<prop_id>.png` (recurring story props like phones, backpacks, test papers, mugs).
All reusable assets are tracked in `ASSETS.json` and generated via `python <skill>/scripts/assets.py generate --type all`.

### Pillar 5 — Scene Planning & Asset Reuse
- In `SCENES.tsv`: For every scene, determine the required characters, reusable background (`bg_id`), props (`props`), and target duration.
- Across scenes: Maintain continuity by reusing established background assets and character anchors whenever a location or character returns (e.g. returning to the bedroom reuses `assets/bg_bedroom.png` and `img/ref_protagonist.png`).

---

## 2. Visual Style Specification (Hardcoded 2D Cel-Shaded Rules)

All image and video calls automatically enforce `<skill>/prompts/style_lock.txt` and `<skill>/prompts/negative_guardrails.txt`:

1. **Art Style:** Hand-drawn digital 2D cel-shaded storytime cartoon animation (clean 2D vector/ink-and-paint Flash / ToonBoom animation aesthetic).
2. **Line Work:** Bold, clean, uniform-weight black ink outlines with crisp closed vector edges around all characters, facial features, hands, and props. No sketchy pencil lines, no variable brush opacity, no lineless shapes.
3. **Color & Shading:** Flat, vibrant solid colors with minimal hard-edge 1-step cel shading. Strictly zero 3D volumetric lighting, zero CGI surface rendering, zero photorealistic textures, zero soft gradients.
4. **Character Consistency:** Simplified 2D cartoon proportions (~3.5 to 4 heads tall), rounded cartoon head geometry, flat solid skin tone fill, large expressive white cartoon eyes with crisp black outlines and solid black pupils, expressive floating eyebrows, 4-finger cartoon hands, distinct unchanging hair silhouette, and solid-color unpatterned clothing that remain **100% identical across every frame and clip**.
5. **Animation & Acting:** Expressive continuous 2D character motion, snappy pose-to-pose timing, animated hand and arm gestures, active 2D lip-sync mouth movement (open/closed speech shapes), and exaggerated 2D cartoon facial expressions (`animated_speaking`, `comedic_rage`, `panic_sweat`, `deadpan_stare`, `confident_grin`, `wide_eyed_shock`).
6. **Backgrounds:** Clean, uncluttered 2D illustrated environments with flat cel planes and clean black ink outlines, maintaining clear figure-ground separation.

---

## 3. Google Flow MCP Capabilities Used by This Skill

All generations are executed through the **`flow-connector` MCP server** (`call_mcp_tool` with `ServerName: "flow-connector"` or the local Flow MCP bridge on `127.0.0.1:8791`):

| MCP Tool / Mode | Parameters | Pipeline Role |
| :--- | :--- | :--- |
| `flow_status` / `flow_doctor` | `{}` | Verify active Flow MCP bridge, browser extension connection, login state, and visible `https://flow.google.com` tab. |
| `flow_generate` (`mode: "flow-text-to-image"`) | `image_model: "nano-banana-2"` or `"nano-banana-pro"`, `aspect_ratio: "16:9"` | Generate **Master Character Turnaround Sheet** (`img/master_sheet.png`), individual **Character Reference Anchors** (`img/ref_<char>.png`), reusable **Backgrounds** (`assets/bg_<id>.png`), and **Props** (`assets/prop_<id>.png`). |
| `flow_generate` (`mode: "flow-image-to-image"`) | `image_paths: [bg_asset, ref_char1, ref_char2, ...]`, `image_model: "nano-banana-2"` | Generate **Anchor-Locked Starting Keyframes** (`keyframes/sNN_start.png`) for initial shots and hard scene cuts (`new_scene`). |
| `flow_generate` (`mode: "flow-ingredients-to-video"`) | `image_paths: [prev_last_frame, ref_char1, ref_char2, ...]`, `image_model: "omni-flash"` (up to 7 refs) or `"veo-3.1-fast"` / `"veo-3.1-lite"` (up to 3 refs), `duration: "4" \| "6" \| "8" \| "10"` | **Primary Continuous Video & Frame-Chaining Mode**: Generates Clip `N` conditioned simultaneously on the extracted last clean frame of Clip `N-1` and the Master Character References of all characters in the shot. |
| `flow_generate` (`mode: "flow-frame-to-video"`) | `image_paths: [start_frame]` or `[start_frame, end_frame]`, `image_model: "veo-3.1-fast"` / `"veo-3.1-lite"` / `"omni-flash"` / `"veo-3.1-quality"` | **First-Frame / Last-Frame Conditioning Mode**: Animates a starting keyframe or extracted chain frame, or interpolates between start and end keyframes. |
| `flow_get_job` / `flow_list_jobs` / `flow_retry_job` / `flow_cancel_job` / `flow_stop` | `job_id`, `timeout_ms`, `retry_all` | Monitor asynchronous jobs, retrieve local downloaded `.mp4` / `.png` file paths, retry transient failures, or halt queues. |

---

## 4. End-to-End Pipeline Workflow (All Project Files Created Dynamically)

Every project creates an isolated workspace `~/Storytime2D/<project-slug>/`.

| Stage | Action | Script / MCP Execution |
| :--- | :--- | :--- |
| **Step 1: Character Planning & Asset Generation First** | 1. Write `SCRIPT.md` based on user parameters.<br>2. Define recurring characters, reusable backgrounds, and props in `ASSETS.json` & `STYLE.txt`.<br>3. Generate and watermark-clean all character anchors (`img/ref_<char>.png`), backgrounds (`assets/bg_<id>.png`), and props (`assets/prop_<id>.png`) via Flow MCP. | `python <skill>/scripts/assets.py init`<br>`python <skill>/scripts/assets.py validate`<br>`python <skill>/scripts/assets.py generate --type all` |
| **Step 2: Dynamic Scene & Multi-Character Shot Planning** | 1. Break script into narrative scenes in `SCENES.tsv` (`scene_id, setting_name, bg_id, characters, props, duration_target, summary`).<br>2. Break each scene into sequential `4s`–`10s` shots in `SHOTS.tsv` (`id, scene_id, chars, bg_id, props, continuity, duration, action, expression, camera`).<br>• Scene start shots use `continuity = new_scene`.<br>• Continuation shots within the same scene use `continuity = chain`.<br>• Multi-character shots list all active characters in `chars`. | `python <skill>/scripts/video_clips.py validate`<br>`python <skill>/scripts/video_clips.py export-mcp` |
| **Step 3: Frame-Chained Video Generation via Flow MCP** | • **Scene Start Shot (`new_scene`)**: Generate starting keyframe `keyframes/sNN_start.png` conditioned on the background asset and all involved character anchors (`flow-image-to-image`), then animate into `clips/raw/sNN.mp4` (`flow-ingredients-to-video` or `flow-frame-to-video`).<br>• **Continuation Shot `N` in Same Scene (`chain`)**: Run `frame_chain.py inspect-trim` on Shot `N-1` to trim final 3–5 frames (preventing tail-end morphing) and extract `frames/chain/s{N-1:02d}_last.png`. Pass `frames/chain/s{N-1:02d}_last.png` + all involved character reference anchors into Flow MCP to generate Shot `N`. | `python <skill>/scripts/video_clips.py keyframes`<br>`python <skill>/scripts/video_clips.py chain`<br>`python <skill>/scripts/frame_chain.py batch` |
| **Step 4: Normalization, FFmpeg Assembly & QC** | Clean any corner marks (`delama_video.py`), normalize all clips to uniform resolution (`1920x1080`), aspect ratio (`16:9`), frame rate (`30` or `24` fps), concatenate seamlessly via FFmpeg into `<project>.mp4`, and inspect 3-point visual QC contact sheet `qc.jpg`. | `python <skill>/scripts/delama_video.py`<br>`python <skill>/scripts/assemble.py` |

---

## 5. Strict Anti-Morphing & Quality Guardrails

1. **Flexible Duration per Shot (4s, 6s, 8s, or 10s):** Google Flow allows `"4"`, `"6"`, `"8"`, or `"10"` seconds per video clip. Segment scenes into sequential shots matching the story's comedic or dramatic pacing. Never exceed 10 seconds in a single clip.
2. **No Static Slideshows:** Every shot must be generated as an animated 2D video clip with continuous character motion, hand gestures, and mouth movement.
3. **Multi-Reference Conditioning (`chain` mode):** Always condition chained clips on **both** the previous clip's extracted last clean frame (`frames/chain/s{N-1:02d}_last.png`) and the immutable Master Character References (`img/ref_<char>.png`) so character features, hair geometry, and clothing colors never drift across shots.
4. **Mandatory Tail-Frame Inspection & Trimming:** Video models soften outlines in the final 3–5 frames. Always run `frame_chain.py inspect-trim` before extracting the continuity frame for the next clip.
5. **Prompt Scoping Guardrail:** Scope each clip to clear character actions and expression shifts. `video_clips.py validate` blocks overloaded action chains (`"and then"`, `"while simultaneously"`) and 3D/photorealistic keywords.
6. **Watermark Cleaning Before Chaining:** Every generated reference asset, starting keyframe, and extracted continuity frame is cleaned via `delama_video.py` before being passed back into Flow MCP so corner marks are never compounded or animated.
