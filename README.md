# 2D Storytime Character Video Animation Skill (`not-your-type`)

A standalone **Antigravity Skill** that plans, generates, and assembles complete **2D cel-shaded storytime cartoon videos** end to end using **Google Flow MCP (`flow-connector`)** and **FFmpeg**.

---

## Core Refined Capabilities

1. **Character Planning:** Before generating any visual assets or video clips, the skill actively asks how many recurring characters are required and collects each character's name, role, and visual description (facial features, hairstyle silhouette, solid outfit colors, proportions).
2. **Multiple Characters in Any Scene:** Scenes and shots are never limited to one character. Supports single or multi-character scenes with flexible staging, positioning, and continuous 2D interactions.
3. **Strict Character Consistency:** All characters maintain 100% visual identity (hair, clothing, facial features, proportions) across every frame and clip by conditioning directly on established reference anchors (`img/ref_<char>.png`).
4. **Asset Generation First:** Reusable visual assets—including recurring characters, background environments (`assets/bg_<id>.png`), and props (`assets/prop_<id>.png`)—are planned, generated, and watermark-cleaned *first* before generating any video clips.
5. **Scene Planning & Asset Reuse:** Every scene maps required characters, background assets (`bg_id`), props (`props`), and character interactions. Returning to a previous location reuses that exact background asset.
6. **Flexible Clip Durations (4s, 6s, 8s, or 10s — Never Fixed to 6s):** Google Flow video clips can be `4`, `6`, `8`, or `10` seconds per shot. You can choose and mix clip durations according to the narrative pacing (e.g. 4s for quick punchlines/shocks, 6s/8s for standard dialogue, 10s for long monologues).

---

## 1. Setup in Antigravity

### Automatic Skill Location
The skill is installed in your global Antigravity skills folder:
```text
C:\Users\Nirajan\.gemini\config\skills\not-your-type\
```
*(Mirrored in `C:\Users\Nirajan\.claude\skills\not-your-type\` and version-controlled at `https://github.com/nirajan-khatiwada/notyourtype.git`.)*

### Prerequisites Check
1. **Google Flow Browser Tab:** Open `https://flow.google.com` in Chrome or Edge, sign in to your Google account, and keep the tab **visible on screen** with the **Flow Connector** extension enabled.
2. **One-Time Setup Verification:**
   In Antigravity chat, type:
   ```text
   not your type setup
   ```
   Or run the self-checks manually in PowerShell:
   ```powershell
   python scripts/delama_video.py --selfcheck
   python scripts/assets.py --selfcheck
   python scripts/character_bible.py --selfcheck
   python scripts/video_clips.py --selfcheck
   python scripts/frame_chain.py --selfcheck
   python scripts/assemble.py --selfcheck
   ```

---

## 2. How to Start a Video in Antigravity

### Step 1 — Trigger the Skill
Open any chat in Antigravity and type any of these trigger phrases:
- `create a not your type`
- `not your type start`
- `make a 2d storytime video`
- `not your type continue` *(resumes your most recent project where it left off)*

### Step 2 — Answer the Startup & Character Planning Questions
When you trigger the skill, the agent will ask:

> 1. **Title / Topic:** What is the story title or topic? *(Or say "suggest topics" for 10 ideas)*
> 2. **Language:** Which language should the script/story be in? *(Hindi, Hinglish, English, etc.)*
> 3. **Length & Pacing:** Target video duration? *(e.g., 30s, 1m, 2m — segmented into 4s, 6s, 8s, or 10s clips)*
> 4. **Character Planning:** How many recurring characters are required, and what are their names, roles, and visual descriptions? *(If you want suggestions, the agent will propose a tailored 2–3 character cast!)*

### Step 3 — Reply with Your Input
You simply reply with your details:
- `"Title: Roommate Drama, Language: Hinglish, Length: 1 minute. Characters: Alex (lead, messy black hair, red hoodie) and Rahul (roommate, curly hair, glasses, blue shirt)."`
- Or provide everything in one trigger prompt:
  `"create a not your type video on Late Night Study in English, 1 minute, 2 characters"`

---

## 3. The 4-Stage Execution Pipeline

Every project creates an isolated project workspace (`~/Storytime2D/<project-slug>/`):

| Stage | What the Pipeline Generates | What You Do |
| :--- | :--- | :--- |
| **Stage 1: Asset Generation First (`assets.py`)** | • Writes `SCRIPT.md` based on your topic and length.<br>• Creates `ASSETS.json` establishing recurring characters, unique backgrounds (`bedroom`, `hallway`), and props (`smartphone`, `backpack`).<br>• Generates and watermark-cleans all character anchors (`img/ref_<char>.png`), backgrounds (`assets/bg_<id>.png`), and props (`assets/prop_<id>.png`) via Flow MCP. | Review & confirm script and character/asset visual anchors. |
| **Stage 2: Scene & Multi-Character Shot Planning (`video_clips.py`)** | • Creates `SCENES.tsv` defining narrative scenes with assigned characters, background asset IDs, and props.<br>• Creates `SHOTS.tsv` dividing each scene into sequential `4s`–`10s` shots with single or multi-character actions and expression shifts. | Review scene breakdown and shot flow. |
| **Stage 3: Frame-Chained Video Generation via Flow MCP** | • **Scene Start Shot (`new_scene`)**: Generates scene starting keyframe (`keyframes/sNN_start.png`) conditioned on the background asset and all involved character anchors, then animates it into `clips/raw/sNN.mp4`.<br>• **Continuation Shot `N` in that Scene (`chain`)**: Trims final 3–5 frames of Shot `N-1` (`frame_chain.py`), extracts `frames/chain/s{N-1:02d}_last.png`, and conditions Flow MCP on **both** the last clean frame and all active character anchors so identities and settings remain 100% consistent without morphing. | Agent runs Flow MCP jobs and builds `review.jpg`. |
| **Stage 4: Normalization, FFmpeg Stitching & QC (`assemble.py`)** | Cleans corner watermarks (`delama_video.py`), normalizes all clips to `1920x1080` (`16:9`, `30fps`, `yuv420p`), seamlessly stitches them via FFmpeg into `<project>.mp4`, and compiles 3-point visual QC contact sheet `qc.jpg`. | **Watch your completed master video!** |

---

## 4. Repository Structure

```text
not-your-type/
├── README.md                     # This documentation & quickstart guide
├── SKILL.md                      # Antigravity skill instructions & interactive startup protocol
├── PLAYBOOK.md                   # Complete architectural specification & 2D cel-shaded rules
├── SETUP.md                      # Setup and verification runbook
├── SETUP_STATUS.md               # Machine verification status
├── prompts/                      # 2D style lock, anti-morphing guardrails, assets & shot templates
│   ├── assets.json               # Reusable characters, backgrounds & props schema
│   ├── character_bible.json      # Character Bible specification
│   ├── shot_templates.json       # Multi-character prompts & asset-first templates
│   ├── style_lock.txt            # Objective 2D cel-shaded visual rules
│   └── negative_guardrails.txt   # Anti-3D and anti-morphing negative constraints
├── looks/                        # 2D cel-shaded background environment lighting styles
└── scripts/                      # Standalone Python + FFmpeg pipeline scripts
    ├── assets.py                 # Asset Generation First manager (characters, backgrounds, props)
    ├── character_bible.py        # Character Bible & Master Reference Anchor generator
    ├── frame_chain.py            # Anti-morphing tail-trimmer (3-5 frames) & last clean frame extractor
    ├── video_clips.py            # Multi-character Scene & Shot validator and Flow MCP video generator
    ├── delama_video.py           # Image & video corner watermark cleaner
    └── assemble.py               # 1080p clip normalizer, FFmpeg stitcher & 3-point QC sheet builder
```
