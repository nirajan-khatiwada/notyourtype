# 2D Cel-Shaded Storytime Video Animation Playbook (Flow MCP Pipeline)

This playbook documents the complete architecture, visual specification, frame-chaining protocol, anti-morphing guardrails, and CLI operations for generating **continuous 2D cel-shaded storytime character animations** using **Google Flow MCP (`flow-connector`)** and **FFmpeg**.

---

## Part 1: Google Flow MCP Architecture & Tool Specification

### 1.1 Standalone Pipeline Design & The 10-Second Google Flow Clip Limit
This skill operates as a completely self-contained 2D animation pipeline. It relies exclusively on:
1. **Google Flow MCP (`flow-connector`)** for zero-cost image and continuous video generation in the browser session (`https://flow.google.com`).
2. **Local Python & FFmpeg utilities** (`scripts/*.py`) for character anchor preparation, anti-morphing tail-frame inspection and trimming, last-frame extraction, watermark removal, resolution/frame-rate normalization, and final MP4 concatenation.

#### Critical Hardware/API Constraint: Maximum 10 Seconds Per Clip
Google Flow **cannot** generate a video longer than **10 seconds** in a single call:
- Allowed `duration` values in `flow_generate`: `"4"`, `"6"`, `"8"`, or `"10"` seconds (`omni-flash` supports `4`, `6`, `8`, or `10` seconds; `veo-3.1-lite`, `veo-3.1-fast`, and `veo-3.1-quality` generate up to `8` seconds per clip).
- **Recommended per-clip duration:** `6` seconds (or `8` seconds). At 6 seconds, the model maintains crisp 2D black ink outlines without mid-clip melting; after trimming the final 3–5 tail frames (~0.15s), each clip yields ~5.85 seconds of clean animation.
- **Multi-Clip Segmentation Math:**
  To build a full video of duration $T_{\text{total}}$ seconds, segment the script into $N = \lceil T_{\text{total}} / d_{\text{clip}} \rceil$ sequential shots in `SHOTS.tsv`:
  - **30-second video:** 5 clips × `6s` (or 3 clips × `10s`)
  - **60-second (1-minute) video:** 10 clips × `6s` (or 8 clips × `8s`, or 6 clips × `10s`)
  - **120-second (2-minute) video:** 20 clips × `6s` (or 15 clips × `8s`, or 12 clips × `10s`)
  - **300-second (5-minute) video:** 50 clips × `6s` (or 30 clips × `10s`)
- If a single scene or monologue lasts 18 seconds in the script, break it into **three consecutive 6-second rows** in `SHOTS.tsv` where Shot 1 has `continuity = new_scene`, Shot 2 has `continuity = chain`, and Shot 3 has `continuity = chain`.

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
| `flow-text-to-image` | Text prompt | `nano-banana-2`, `nano-banana-pro`, `nano-banana-2-lite` | Generates the **Master Character Turnaround Sheet** (`img/master_sheet.png`) or standalone **Master Character Reference** (`img/ref_<char>.png`). |
| `flow-image-to-image` | `image_paths` (1–10 images) | `nano-banana-2`, `nano-banana-pro` | Generates **Anchor-Locked Starting Keyframes** (`keyframes/sNN_start.png`) conditioned on `img/ref_<char>.png` for initial shots and hard scene cuts. |
| `flow-create-character` | `prompt`, `character_name` | Flow Character Engine | Registers a named reusable character inside the Flow project for `character_refs`. |
| `flow-ingredients-to-video` | `image_paths` + `asset_refs` (up to **7 refs** on `omni-flash`; up to **3 refs** on `veo-3.1-fast` / `veo-3.1-lite`) | `omni-flash`, `veo-3.1-fast`, `veo-3.1-lite` | **Dual-Anchor Frame-Chaining**: Conditions Clip `N` on `["frames/chain/s{N-1:02d}_last.png", "img/ref_<char>.png"]` to preserve both exact pose/scene continuity and Master Character identity. |
| `flow-frame-to-video` | `image_paths` (1st = Start Frame, optional 2nd = End Frame, max 2) | `veo-3.1-fast`, `veo-3.1-lite`, `omni-flash`, `veo-3.1-quality` | **First-Frame / Last-Frame Interpolation**: Animates `keyframes/sNN_start.png` or `frames/chain/s{N-1:02d}_last.png` directly, or interpolates between a Start Frame and an End Frame (`continuity = interp`). |
| `flow-extend-video` | `prompt` | Veo 3.1 models | Extends the currently open clip in the Flow project editor. |

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
   - Distinctive hair silhouette and solid-color unpatterned outfit (e.g., solid pullover hoodie or solid crewneck shirt with zero logos or text) remain **100% identical across every frame and clip**.
5. **Snappy Pose-to-Pose Acting & 2D Lip-Sync:**
   - Expressive 2D character motion with snappy pose-to-pose timing, clear anticipation and settles, animated hand gestures, active 2D cartoon mouth movement (open/closed speech shapes), and exaggerated 2D facial expressions (`animated_speaking`, `comedic_rage`, `panic_sweat`, `deadpan_stare`, `confident_grin`, `wide_eyed_shock`).
6. **Clean 2D Illustrated Backgrounds:**
   - Simple, uncluttered 2D illustrated environments with flat color planes and clean black ink outlines that keep visual focus on the foreground character.

---

## Part 3: Continuous Video Generation & Frame-Chaining Pipeline

```
CHARACTER_BIBLE.json + STYLE.txt
  │
  ├─► Step 1: Master Character Reference Anchor (character_bible.py)
  │     └─► flow_generate(mode="flow-text-to-image") ──► delama_video.py ──► img/ref_<char>.png
  │
  ├─► Step 2: Shot Plan Validation & MCP Manifest (video_clips.py validate / export-mcp)
  │     └─► SHOTS.tsv (1 clear physical action + 1 expression shift per clip) ──► mcp_jobs.json
  │
  ├─► Step 3: Frame-Chained Continuous Video Generation (video_clips.py + frame_chain.py)
  │     │
  │     ├── Clip 1 (or any hard cut with continuity = new_scene):
  │     │     1. Anchor-Locked Starting Keyframe:
  │     │        flow_generate(mode="flow-image-to-image", image_paths=["img/ref_<char>.png"])
  │     │        ──► delama_video.py ──► keyframes/sNN_start.png
  │     │     2. Animate Clip:
  │     │        flow_generate(mode="flow-ingredients-to-video", image_paths=["keyframes/sNN_start.png", "img/ref_<char>.png"])
  │     │        (or mode="flow-frame-to-video", image_paths=["keyframes/sNN_start.png"])
  │     │        ──► clips/raw/sNN.mp4
  │     │     3. Inspect & Trim Tail Morphing + Extract Last Clean Frame:
  │     │        frame_chain.py inspect-trim clips/raw/sNN.mp4
  │     │        ──► clips/clean/sNN.mp4 + frames/chain/sNN_last.png
  │     │
  │     ├── Clip N (Temporal Continuity via Previous Frame Reference, continuity = chain):
  │     │     1. Dual-Conditioned Generation:
  │     │        flow_generate(
  │     │          mode="flow-ingredients-to-video",
  │     │          image_paths=["frames/chain/s{N-1:02d}_last.png", "img/ref_<char>.png"],
  │     │          prompt=<1 Action + 1 Expression Shift + Style Lock + Negative Guardrails>
  │     │        ) ──► clips/raw/sNN.mp4
  │     │     2. Inspect & Trim Tail Morphing + Extract Last Clean Frame:
  │     │        frame_chain.py inspect-trim clips/raw/sNN.mp4
  │     │        ──► clips/clean/sNN.mp4 + frames/chain/sNN_last.png
  │     │
  │     └── Clip M (First-Frame to Last-Frame Interpolation, continuity = interp):
  │           1. Start Frame = frames/chain/s{M-1:02d}_last.png (or keyframes/sMM_start.png)
  │           2. End Frame   = keyframes/sMM_end.png (generated via flow-image-to-image from img/ref_<char>.png)
  │           3. Animate via flow_generate(mode="flow-frame-to-video", image_paths=[Start, End])
  │              ──► clips/raw/sMM.mp4 ──► frame_chain.py inspect-trim ──► clips/clean/sMM.mp4
  │
  └─► Step 4: Automated Video Clip Normalization, FFmpeg Assembly & 3-Point QC (assemble.py)
        └─► clips/norm/sNN.mp4 (1920x1080, 16:9, 30fps, yuv420p) ──► <project>.mp4 + qc.jpg
```

---

## Part 4: Anti-Morphing & Quality Guardrails

### 4.1 Prompt Scoping Guardrail (1 Action + 1 Expression Shift)
Video models lose 2D line integrity when asked to perform multiple sequential actions in a single clip.
- `SHOTS.tsv` separates `action` and `expression` into distinct columns.
- `video_clips.py validate` enforces that each clip specifies **one clear physical action** and **one clear facial expression shift**, and rejects multi-action chains (`"and then"`, `"afterwards"`, `"while simultaneously"`, etc.) or forbidden 3D/photorealistic terms.

### 4.2 Dual-Reference Conditioning (Preventing Identity Drift)
Chaining solely from Clip `N-1`'s last frame causes gradual drift in character proportions, hair geometry, and outfit shade over multiple generations.
- By passing **both** `frames/chain/s{N-1:02d}_last.png` (First-Frame Continuity Reference) and `img/ref_<char>.png` (Master Character Reference) into `flow-ingredients-to-video`, Clip `N` begins from the exact ending pose and background of Clip `N-1` while remaining locked to the original character sheet.

### 4.3 Automated Tail-Frame Inspection & Trimming (`frame_chain.py`)
Video models frequently exhibit motion deceleration, outline softening, or facial distortion in the final 3–5 frames of a clip.
- `frame_chain.py` decodes the clip frames and:
  1. Discards the final `min_trim` frames (default `4` frames, configurable `3`–`5` frames).
  2. Evaluates candidate tail frames (`-12` to `-min_trim`) using **2D Laplacian Ink-Outline Sharpness** and **RGB Histogram Stability** (compared against the stable mid-clip frame).
  3. Selects the sharpest, non-morphed frame `best_frame_idx`, trims the video cleanly at that frame (`clips/clean/sNN.mp4`), cleans any corner watermark, and exports `frames/chain/sNN_last.png`.

---

## Part 5: Command Reference

Run all commands from the project directory:

```powershell
# 1. Initialize project structure, CHARACTER_BIBLE.json, and STYLE.txt
python <skill>/scripts/character_bible.py init --look flat_daylight
python <skill>/scripts/character_bible.py validate

# 2. Generate Master Character Reference Anchor(s) via Flow MCP (or --dry to inspect MCP JSON)
python <skill>/scripts/character_bible.py generate --wait
# Or split a multi-character turnaround sheet into individual anchors:
python <skill>/scripts/character_bible.py refs img/master_sheet.png --names protagonist,secondary_character

# 3. Validate SHOTS.tsv and export Flow MCP job manifest (mcp_jobs.json)
python <skill>/scripts/video_clips.py validate
python <skill>/scripts/video_clips.py export-mcp --model omni-flash

# 4. Generate anchor-locked starting keyframes for new_scene / interp shots via Flow MCP
python <skill>/scripts/video_clips.py keyframes --wait

# 5. Execute continuous frame-chained video generation (Clip 1 -> trim & extract last frame -> Clip 2 -> ...)
python <skill>/scripts/video_clips.py chain --model omni-flash --wait

# 6. Inspect/trim all raw clips and extract clean continuity frames in batch mode
python <skill>/scripts/frame_chain.py batch --min-trim 4

# 7. Clean watermarks, normalize all clips (1080p, 16:9, 30fps, yuv420p), stitch via FFmpeg, and generate qc.jpg
python <skill>/scripts/delama_video.py
python <skill>/scripts/assemble.py --fps 30 --out master_animation.mp4
```

---

## Part 6: Quality Verification Checklist

- [ ] `CHARACTER_BIBLE.json` and `STYLE.txt` pass `character_bible.py validate`.
- [ ] `img/ref_<char>.png` Master Character Reference images exist and have been cleaned of any corner watermarks.
- [ ] `SHOTS.tsv` passes `video_clips.py validate` (1 clear action + 1 expression shift per clip, valid continuity chain).
- [ ] Every clip in `clips/clean/sNN.mp4` is a continuous animated 2D video clip trimmed of tail-end morphing via `frame_chain.py`.
- [ ] All clips are normalized to uniform resolution (`1920x1080`), aspect ratio (`16:9`), and frame rate (`30` or `24` fps) and concatenated seamlessly via `assemble.py`.
- [ ] `qc.jpg` (First, Middle, and Last frames of every clip) has been inspected to confirm consistent character proportions, solid outfit colors, and crisp black ink outlines.
