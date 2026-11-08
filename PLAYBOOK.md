# 2D Cel-Shaded Storytime Video Animation Playbook (Flow MCP Pipeline)

This playbook documents the complete architecture, visual specification, multi-character conditioning, asset-first generation protocol, anti-morphing guardrails, and CLI operations for generating **continuous 2D cel-shaded storytime character animations** using **Google Flow MCP (`flow-connector`)** and **FFmpeg**.

---

## Part 1: Google Flow MCP Architecture & Tool Specification

### 1.1 Standalone Pipeline Design & Flexible Clip Durations (4s, 6s, 8s, 10s)
This skill operates as a completely self-contained 2D animation pipeline. It relies exclusively on:
1. **Google Flow MCP (`flow-connector`)** for zero-cost image and continuous video generation in the browser session (`https://flow.google.com`).
2. **Local Python & FFmpeg utilities** (`scripts/*.py`) for character and asset preparation, anti-morphing tail-frame inspection and trimming, last-frame extraction, watermark removal, resolution/frame-rate normalization, and final MP4 concatenation.

#### Flexible Clip Durations — Never Fixed to 6 Seconds
Google Flow generates video clips in discrete durations:
- Allowed `duration` values in `flow_generate`: `"4"`, `"6"`, `"8"`, or `"10"` seconds (`omni-flash` supports `4`, `6`, `8`, or `10` seconds; `veo-3.1-lite`, `veo-3.1-fast`, and `veo-3.1-quality` generate up to `8` seconds per clip).
- **Duration is flexible and pacing-dependent:**
  - `4` seconds: Fast comedic beats, sudden surprises, rapid cuts, or punchlines.
  - `6` seconds: Standard balanced duration for general 2D character actions, gestures, and line delivery.
  - `8` seconds: Conversational exchanges, two-character interactions, or extended gestures.
  - `10` seconds: Long-form storytelling monologues or continuous character acting.
- **Multi-Clip Segmentation:**
  To build a full video of duration $T_{\text{total}}$ seconds, segment the script into $N$ sequential shots in `SHOTS.tsv` ($\sum d_i = T_{\text{total}}$):
  - **30-second video:** e.g., 5 clips × `6s`, or [6s + 8s + 6s + 10s]
  - **60-second (1-minute) video:** e.g., 10 clips × `6s`, or [6s × 6 + 8s × 3]
  - **120-second (2-minute) video:** e.g., 20 clips × `6s`, or 12 clips × `10s`

### 1.2 Google Flow MCP Tool Reference (`ServerName: "flow-connector"`)

| MCP Tool | Arguments | Purpose in Pipeline |
| :--- | :--- | :--- |
| `flow_status` | `{}` | Checks local Flow MCP bridge (`127.0.0.1:8791`), browser extension connection, login status, tab visibility, and active job count. |
| `flow_doctor` | `{}` | Runs end-to-end diagnostics on the Flow MCP automation stack. |
| `flow_generate` | `prompt` (required), `mode`, `image_paths`, `aspect_ratio`, `duration`, `image_model`, `outputs`, `folder`, `new_project`, `character_name`, `character_refs`, `asset_refs`, `max_retries`, `wait` | Submits image generation, character creation, starting keyframe, or continuous video generation jobs. |
| `flow_get_job` | `job_id` (required), `timeout_ms` (`1000`–`120000`, default `40000`) | Waits for or queries a specific job and returns local downloaded file paths. |
| `flow_list_jobs` | `limit` (`1`–`100`, default `20`) | Lists recent Flow MCP jobs with their status and downloaded media paths. |
| `flow_retry_job` | `job_id`, `retry_all` (boolean), `wait` (boolean) | Retries a failed/cancelled job or batch-retries all failed jobs. |
| `flow_cancel_job` | `job_id` (required) | Cancels a pending or running job. |
| `flow_stop` | `{}` | Emergency stop: halts and cancels all queued and running generations. |

### 1.3 Conditioning Modes for Continuous 2D Animation

| `flow_generate` Mode | Input Conditioning | Supported Models | Pipeline Usage |
| :--- | :--- | :--- | :--- |
| `flow-text-to-image` | Text prompt | `nano-banana-2`, `nano-banana-pro`, `nano-banana-2-lite` | Generates **Master Character Turnaround Sheet** (`img/master_sheet.png`), standalone **Character Reference Anchors** (`img/ref_<char>.png`), reusable **Backgrounds** (`assets/bg_<id>.png`), and **Props** (`assets/prop_<id>.png`). |
| `flow-image-to-image` | `image_paths` (1–10 images) | `nano-banana-2`, `nano-banana-pro` | Generates **Starting Keyframes** (`keyframes/sNN_start.png`) conditioned on reusable background and all involved character reference anchors. |
| `flow-ingredients-to-video` | `image_paths` (up to **7 refs** on `omni-flash`; up to **3 refs** on `veo-3.1-fast` / `veo-3.1-lite`) | `omni-flash`, `veo-3.1-fast`, `veo-3.1-lite` | **Multi-Reference Frame-Chaining**: Conditions Clip `N` on `[prev_last_frame, ref_char1, ref_char2, ...]` to preserve exact pose/scene continuity and all character identities without morphing. |
| `flow-frame-to-video` | `image_paths` (1st = Start Frame, optional 2nd = End Frame, max 2) | `veo-3.1-fast`, `veo-3.1-lite`, `omni-flash`, `veo-3.1-quality` | **First-Frame / Last-Frame Interpolation**: Animates starting keyframe directly or interpolates between Start Frame and End Frame. |

---

## Part 2: Visual Style Specification (2D Cel-Shaded Storytime Animation)

Every prompt generated by this skill enforces six explicit, objective visual rules:

1. **2D Digital Cel-Shaded Animation Aesthetic:**
   - Hand-drawn digital 2D cartoon animation look (clean vector/ink-and-paint Flash / ToonBoom keyframe animation).
   - Strictly 2D flat planar perspective.
2. **Bold, Uniform Black Ink Outlines:**
   - All characters, limbs, facial features, and foreground props are enclosed in bold, clean, uniform-weight black ink outlines with crisp vector-like edges.
   - Outlines must remain closed, sharp, and uniform in thickness across all frames without flickering or dissolving.
3. **Flat Solid Color Fills & Minimal Hard-Edge Cel Shading:**
   - High-contrast, flat vibrant solid colors with at most one hard-edged cel shadow step.
   - Strictly zero 3D volumetric lighting, zero raytracing, zero ambient occlusion, zero photorealistic textures, and zero soft gradients.
4. **Immutable Character Consistency:**
   - Simplified 2D cartoon anatomy (~3.5 to 4 heads tall), rounded cartoon head shape, flat solid skin fill, large white cartoon eyes with crisp black outlines and solid black pupils, expressive floating eyebrows, and 4-finger cartoon hands.
   - Distinctive hair silhouette and solid-color unpatterned outfit remain **100% identical across every frame and clip**.
5. **Snappy Pose-to-Pose Acting & 2D Lip-Sync:**
   - Expressive 2D character motion with snappy pose-to-pose timing, clear anticipation and settles, animated hand gestures, active 2D cartoon mouth movement (open/closed speech shapes), and exaggerated 2D facial expressions (`animated_speaking`, `comedic_rage`, `panic_sweat`, `deadpan_stare`, `confident_grin`, `wide_eyed_shock`).
6. **Clean 2D Illustrated Backgrounds:**
   - Simple, uncluttered 2D illustrated environments with flat color planes and clean black ink outlines that maintain clear figure-ground separation.

---

## Part 3: Architecture & Execution Pipeline

```
ASSETS.json (Characters, Backgrounds, Props) + STYLE.txt
  │
  ├─► Stage 1: Asset Generation First (assets.py)
  │     ├─► Characters:  flow_generate(text-to-image) ──► delama_video.py ──► img/ref_<char>.png
  │     ├─► Backgrounds: flow_generate(text-to-image) ──► delama_video.py ──► assets/bg_<id>.png
  │     └─► Props:       flow_generate(text-to-image) ──► delama_video.py ──► assets/prop_<id>.png
  │
  ├─► Stage 2: Scene & Multi-Character Shot Planning (video_clips.py validate / export-mcp)
  │     ├─► SCENES.tsv (characters, bg_id, props, target duration, summary)
  │     └─► SHOTS.tsv  (id, scene_id, chars, bg_id, props, continuity, duration, action, expression, camera)
  │
  ├─► Stage 3: Frame-Chained Continuous Video Generation (video_clips.py + frame_chain.py)
  │     │
  │     ├── Scene Start Shot (continuity = new_scene):
  │     │     1. Keyframe Generation:
  │     │        flow_generate(image-to-image, [bg_asset, ref_char1, ref_char2]) ──► keyframes/sNN_start.png
  │     │     2. Continuous Video Animation:
  │     │        flow_generate(ingredients-to-video, [start_kf, ref_char1, ref_char2], dur=4|6|8|10) ──► clips/raw/sNN.mp4
  │     │     3. Tail Trimming & Continuity Extraction:
  │     │        frame_chain.py inspect-trim clips/raw/sNN.mp4 ──► clips/clean/sNN.mp4 + frames/chain/sNN_last.png
  │     │
  │     └── Chained Shot N within Same Scene (continuity = chain):
  │           1. Multi-Conditioned Generation:
  │              flow_generate(
  │                ingredients-to-video,
  │                [frames/chain/s{N-1}_last.png, ref_char1, ref_char2],
  │                dur=4|6|8|10
  │              ) ──► clips/raw/sNN.mp4
  │           2. Tail Trimming & Continuity Extraction:
  │              frame_chain.py inspect-trim clips/raw/sNN.mp4 ──► clips/clean/sNN.mp4 + frames/chain/sNN_last.png
  │
  └─► Stage 4: Clip Normalization, FFmpeg Assembly & 3-Point QC (assemble.py)
        └─► clips/norm/sNN.mp4 (1920x1080, 16:9, 30fps, yuv420p) ──► <project>.mp4 + qc.jpg
```

---

## Part 4: Anti-Morphing & Quality Guardrails

### 4.1 Prompt Scoping Guardrail
Video models lose 2D line integrity when asked to perform multiple sequential actions in a single clip.
- `SHOTS.tsv` separates `action` and `expression` into distinct columns.
- `video_clips.py validate` enforces that each clip specifies **one clear physical action per character** and **one clear facial expression shift**, and rejects multi-action chains (`"and then"`, `"afterwards"`, `"while simultaneously"`) or forbidden 3D/photorealistic terms.

### 4.2 Multi-Reference Conditioning (Preventing Identity Drift)
Chaining solely from Clip `N-1`'s last frame causes gradual drift in character proportions, hair geometry, and outfit shade over multiple generations.
- By passing **both** `frames/chain/s{N-1:02d}_last.png` (continuity reference) and **all** involved character anchors (`img/ref_<char>.png`) into `flow-ingredients-to-video`, Clip `N` begins from the exact ending pose of Clip `N-1` while remaining locked to the original character design.

### 4.3 Automated Tail-Frame Inspection & Trimming (`frame_chain.py`)
Video models frequently exhibit outline softening or geometric distortion in the final 3–5 frames of a clip.
- `frame_chain.py` decodes clip frames and:
  1. Discards the final `min_trim` frames (default `4` frames, configurable `3`–`5` frames).
  2. Evaluates candidate tail frames (`-12` to `-min_trim`) using **2D Laplacian Ink-Outline Sharpness** and **RGB Histogram Stability** (compared against the stable mid-clip anchor frame).
  3. Selects the sharpest, non-morphed frame `best_frame_idx`, trims the video cleanly at that frame (`clips/clean/sNN.mp4`), cleans any corner watermark, and exports `frames/chain/sNN_last.png`.

---

## Part 5: Command Reference

Run all commands from the project directory:

```powershell
# 1. Initialize project structure, ASSETS.json, and STYLE.txt
python <skill>/scripts/assets.py init --look flat_daylight
python <skill>/scripts/assets.py validate

# 2. Generate reusable visual assets FIRST (characters, backgrounds, props)
python <skill>/scripts/assets.py generate --type all

# 3. Validate scene and shot plan (multi-character, flexible durations 4s-10s)
python <skill>/scripts/video_clips.py validate
python <skill>/scripts/video_clips.py export-mcp --model omni-flash

# 4. Generate starting keyframes and frame-chained video clips
python <skill>/scripts/video_clips.py keyframes
python <skill>/scripts/video_clips.py chain --model omni-flash

# 5. Review downloaded clips and inspect contact sheet
python <skill>/scripts/video_clips.py review

# 6. Normalize clips, assemble via FFmpeg, and verify QC sheet
python <skill>/scripts/assemble.py --fps 30 --out final.mp4
```
