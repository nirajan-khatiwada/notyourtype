---
name: not-your-type
description: Standalone 2D cel-shaded storytime character video animation pipeline powered exclusively by Google Flow MCP and FFmpeg. Trigger whenever the user says "create a not your type", "not your type", "not your type start", "not your type continue", "not your type setup", "2d storytime", "make a 2d storytime video", or "storytime animation". Asks the user for Title/Topic, Language, and Length, then generates continuous 2D animated character video clips (4s-10s per clip via Flow MCP), chains sequential clips by trimming and extracting the last clean frame of Clip N-1 alongside the Master Character Reference, and stitches normalized 1080p clips into a master MP4.
---

# 2D Storytime Character Video Animation Skill (Standalone Flow MCP Pipeline)

You direct, generate, and assemble complete **2D cel-shaded storytime character animation videos** end to end using **Google Flow MCP (`flow-connector`)** and local **FFmpeg** utilities.

This skill is **100% standalone** and depends only on **Google Flow MCP** (`flow_generate`, `flow_get_job`, `flow_list_jobs`, `flow_retry_job`, `flow_cancel_job`, `flow_status`, `flow_doctor`, `flow_stop`), Python, and FFmpeg. It generates **true continuous 2D animated video clips** chained together for temporal and character continuity—never static slideshows.

**Talk to the user in their own language** (English, Hinglish, Hindi, or whichever language they use), simply and directly.

> [!IMPORTANT]
> **Hard 10-Second Single-Clip Limit in Google Flow:**
> Google Flow can generate a **maximum of 10 seconds per single video clip** (`duration` must be `"4"`, `"6"`, `"8"`, or `"10"` seconds; `omni-flash` supports `4`, `6`, `8`, or `10` seconds, while `veo-3.1-*` models generate up to `8` seconds per clip).
> - **Never** attempt to generate a 30-second, 60-second, or multi-minute video in a single `flow_generate` call.
> - To produce any video longer than 10 seconds, you **must** segment the script into sequential `4s`, `6s`, `8s`, or `10s` shots in `SHOTS.tsv` ($\text{Clip Count} = \lceil \text{Target Video Seconds} / \text{Clip Duration} \rceil$), chain them frame-by-frame (`continuity = chain`), and stitch them into the final `.mp4` with `assemble.py`.
> - **Recommended clip duration:** `6` seconds (or `8` seconds) per clip gives the highest 2D ink-outline stability and prevents mid-clip morphing.

`<skill>` refers to this skill's directory:
- `C:\Users\Nirajan\.gemini\config\skills\not-your-type\`

**Before planning or executing a video project, read `<skill>/README.md`, `<skill>/PLAYBOOK.md`, and `<skill>/prompts/README.md`.**

---

## 0. Interactive Startup Protocol (Execute First Every Time)

Whenever the user triggers this skill (for example: `"create a not your type"`, `"not your type start"`, `"make a 2d storytime video"`, `"continue"`, or gives a topic):

1. **Setup Check:**
   - Read `<skill>/SETUP_STATUS.md`. If missing or any row is not ✅, run `<skill>/SETUP.md` first.
2. **Project Folder Lookup:**
   - Projects live in `~/Storytime2D/<topic-slug>/` (or the active workspace if opened for a specific project).
   - If the user says `"continue"` with no topic: open the most recently modified `PROGRESS.md` under `~/Storytime2D/`, tell the user which project and stage you are resuming, and continue from there.
3. **Ask for Title, Language, and Length (If Not Provided Yet):**
   - If the user starts the skill without specifying the **Title/Topic**, **Language**, or **Length**, stop and ask **only these 3 questions in ONE short message** (do not pre-select defaults):
     1. **Title / Topic:** What is the title or story topic? *(Or ask: "Want me to suggest 10 storytime topics?")*
     2. **Language:** Which language should the story be written in? *(e.g., Hindi, Hinglish, English, or any other language)*
     3. **Length:** How long should the video be? *(e.g., 30 seconds, 1 minute, 2 minutes, 5 minutes — automatically broken into sequential 6s–10s animated clips since Flow's max per clip is 10s)*
   - **Wait for the user's reply** before writing the script or generating any assets.
4. **Once the User Replies with Title, Language, and Length:**
   - Create `~/Storytime2D/<slug>/` with `PROGRESS.md`.
   - Calculate the required clip count ($\lceil \text{Target Seconds} / 6 \rceil$ clips at `6s` each, or $\lceil \text{Target Seconds} / 10 \rceil$ clips at `10s` each) and proceed immediately to **Step 1 (Script & Shot Plan)**, waiting for the user's OK on the script before starting Flow MCP generations.

---

## 1. Visual Style Specification (Hardcoded 2D Cel-Shaded Animation Rules)

All image and video generation calls automatically enforce the following objective visual rules (`<skill>/prompts/style_lock.txt` and `<skill>/prompts/negative_guardrails.txt`):

1. **Art Style:** Hand-drawn digital 2D cel-shaded storytime cartoon animation (clean 2D vector/ink-and-paint Flash / ToonBoom animation aesthetic).
2. **Line Work:** Bold, clean, uniform-weight black ink outlines with crisp, closed vector-like edges around all characters, facial features, hands, and props. No sketchy pencil lines, no variable brush opacity, and no lineless shapes.
3. **Color & Shading:** Flat, vibrant solid color fills with minimal hard-edge 1-step cel shading. Strictly no 3D volumetric lighting, no CGI surface rendering, no ambient occlusion, no photorealistic textures, and no soft airbrushed gradients.
4. **Character Construction & Consistency:** Simplified 2D cartoon proportions (~3.5 to 4 heads tall), rounded cartoon head geometry, flat solid skin tone fill, large expressive white cartoon eyes with crisp black outlines and solid black pupils, expressive floating eyebrows, 4-finger cartoon hands, a distinct unchanging hair silhouette, and solid-color unpatterned clothing that remain **100% identical across every frame and clip**.
5. **Animation & Acting:** Expressive continuous 2D character motion, snappy pose-to-pose timing, animated hand and arm gestures, active 2D lip-sync mouth movement (open and closed mouth shapes articulating speech), and exaggerated 2D cartoon facial expressions (wide-eyed shock, furrowed-brow rage, smug grin, deadpan stare, visible cartoon sweat drops).
6. **Backgrounds:** Simple, uncluttered 2D illustrated backgrounds with flat cel color planes and clean black ink outlines that maintain clear figure-ground separation and keep visual focus on the foreground character.

---

## 2. Google Flow MCP Capabilities Used by This Skill

All generations are executed through the **`flow-connector` MCP server** (`call_mcp_tool` with `ServerName: "flow-connector"` or the local Flow MCP bridge on `127.0.0.1:8791`):

| MCP Tool / Mode | Parameters | Pipeline Role |
| :--- | :--- | :--- |
| `flow_status` / `flow_doctor` | `{}` | Verify active Flow MCP bridge, browser extension connection, login state, and visible `https://flow.google.com` tab. |
| `flow_generate` (`mode: "flow-text-to-image"`) | `image_model: "nano-banana-2"` or `"nano-banana-pro"`, `aspect_ratio: "16:9"` | Generate the initial **Master Character Turnaround Sheet** (`img/master_sheet.png`) or standalone **Master Character Reference Anchor** (`img/ref_<char>.png`). |
| `flow_generate` (`mode: "flow-create-character"`) | `character_name`, `prompt` | Register a persistent character inside the Flow project for casting via `character_refs`. |
| `flow_generate` (`mode: "flow-image-to-image"`) | `image_paths: ["img/ref_<char>.png"]`, `image_model: "nano-banana-2"` | Generate **Anchor-Locked Starting Keyframes** (`keyframes/sNN_start.png`) for Shot 1 or hard camera cuts (`new_scene`) and target pose keyframes (`keyframes/sNN_end.png`) for interpolation (`interp`). |
| `flow_generate` (`mode: "flow-ingredients-to-video"`) | `image_paths: ["frames/chain/s{N-1:02d}_last.png", "img/ref_<char>.png"]`, `image_model: "omni-flash"` (up to 7 refs) or `"veo-3.1-fast"` / `"veo-3.1-lite"` (up to 3 refs), `duration: "4" \| "6" \| "8" \| "10"` | **Primary Continuous Video & Frame-Chaining Mode**: Generates Clip `N` conditioned simultaneously on the extracted last clean frame of Clip `N-1` (pose/scene continuity) and the Master Character Reference (identity lock). |
| `flow_generate` (`mode: "flow-frame-to-video"`) | `image_paths: [start_frame]` or `[start_frame, end_frame]`, `image_model: "veo-3.1-fast"` / `"veo-3.1-lite"` / `"omni-flash"` / `"veo-3.1-quality"` | **First-Frame / Last-Frame Conditioning Mode**: Animates a starting keyframe or extracted chain frame into a continuous 2D clip, or interpolates between start and end keyframes. |
| `flow_generate` (`mode: "flow-extend-video"`) | `prompt` | Extends an active clip in the Flow editor for continuous scene lengthening. |
| `flow_get_job` / `flow_list_jobs` / `flow_retry_job` / `flow_cancel_job` / `flow_stop` | `job_id`, `timeout_ms`, `retry_all` | Monitor asynchronous jobs, retrieve local downloaded `.mp4` / `.png` file paths, retry transient failures, or halt queues. |

---

## 3. End-to-End Continuous Video & Frame-Chaining Workflow

### Initialization
1. Verify setup status in `<skill>/SETUP_STATUS.md` (run `<skill>/SETUP.md` if any check is missing) and call `flow_status` on `flow-connector`.
2. Create or resume the project folder (e.g., `~/Storytime2D/<project-slug>/` or the active workspace directory) and track stage completion in `PROGRESS.md`.
3. If project parameters are not yet specified, ask the user in one concise message for:
   - **Topic / Narrative Outline**
   - **Target Duration** (in multiples of 4s–8s clips) and **Aspect Ratio** (`16:9` default or `9:16`)
   - **Flow Video Model** (`omni-flash`, `veo-3.1-fast`, `veo-3.1-lite`, or `veo-3.1-quality`)

### Pipeline Stages

| Stage | Action | Script / MCP Execution |
| :--- | :--- | :--- |
| **Step 1: Character Bible & Master Visual Anchor** | Define explicit character visual attributes in `CHARACTER_BIBLE.json` (head shape, eye/brow geometry, hair silhouette, solid outfit color, 2D proportions) and environment look in `STYLE.txt`. Generate the Master Character Reference image (`img/ref_<char>.png`) via Flow MCP and remove any corner watermark. | `python <skill>/scripts/character_bible.py init`<br>`python <skill>/scripts/character_bible.py validate`<br>`python <skill>/scripts/character_bible.py generate` |
| **Step 2: Sequential Shot Plan & Anti-Morphing Validation** | Break the script into sequential animated video shots in `SHOTS.tsv` (`id, char, continuity, duration, action, expression, setting, camera`). Scope every shot to **one clear physical action + one clear facial expression shift**. | `python <skill>/scripts/video_clips.py validate`<br>`python <skill>/scripts/video_clips.py export-mcp` |
| **Step 3: Frame-Chained Video Generation via Flow MCP** | • **Clip 1 (`new_scene`)**: Generate starting keyframe `keyframes/s01_start.png` anchored to `img/ref_<char>.png` (`flow-image-to-image`), then animate into `clips/raw/s01.mp4` via Flow MCP (`flow-ingredients-to-video` or `flow-frame-to-video`).<br>• **Clip `N` (`chain`)**: Run `frame_chain.py inspect-trim` on Clip `N-1` to trim the final 3–5 frames (eliminating tail-end morphing) and extract `frames/chain/s{N-1:02d}_last.png`. Pass `frames/chain/s{N-1:02d}_last.png` + `img/ref_<char>.png` into Flow MCP to generate Clip `N`.<br>• **Hard Cuts (`new_scene`)**: Generate a transition starting keyframe anchored to `img/ref_<char>.png`, then animate into a video clip. | `python <skill>/scripts/video_clips.py keyframes`<br>`python <skill>/scripts/video_clips.py chain`<br>`python <skill>/scripts/frame_chain.py batch` |
| **Step 4: Clip Normalization, FFmpeg Assembly & QC** | Clean any corner watermarks (`delama_video.py`), normalize all clips to uniform resolution (`1920x1080`), aspect ratio (`16:9`), frame rate (`30` or `24` fps), and pixel format (`yuv420p`), optionally align to audio timing (`SCENES.tsv` / `WORDS.tsv`), concatenate seamlessly via FFmpeg into `<project>.mp4`, and inspect the 3-point (`FIRST`/`MID`/`LAST`) contact sheet `qc.jpg`. | `python <skill>/scripts/delama_video.py`<br>`python <skill>/scripts/assemble.py` |

---

## 4. Strict Anti-Morphing & Quality Guardrails

1. **Enforce the 10-Second Maximum Clip Cap:** Google Flow's hard ceiling is **10 seconds per video generation** (`"4"`, `"6"`, `"8"`, or `"10"` seconds). Any scene lasting longer than a single clip (e.g., a 15-second monologue or a 60-second story) must be divided into multiple sequential `4s`–`10s` rows in `SHOTS.tsv` connected with `continuity = chain`.
2. **No Static Slideshows:** Every shot must be generated as an animated 2D video clip with continuous character motion, hand gestures, and mouth movement.
3. **Dual-Reference Chaining (`chain` mode):** Always condition chained clips on **both** the previous clip's extracted last clean frame (`frames/chain/s{N-1:02d}_last.png`) and the immutable Master Character Reference (`img/ref_<char>.png`) so character proportions, hair silhouette, and solid clothing colors never drift across long sequences.
4. **Mandatory Tail-Frame Inspection & Trimming:** Video generation models frequently soften outlines or morph geometry in the final 3–5 frames. Always run `frame_chain.py inspect-trim` before extracting the continuity frame for the next clip.
5. **Single Action + Single Expression Shift per Clip:** Overloaded prompts cause 2D limbs and outlines to melt. `video_clips.py validate` blocks multi-clause action chains and enforces crisp prompt scoping.
6. **Watermark Cleaning Before Chaining:** Every generated reference image, starting keyframe, and extracted continuity frame is cleaned via `delama_video.py` before being passed back into Flow MCP so corner marks are never compounded or animated.
