# 2D Storytime Character Video Animation Skill (`not-your-type`)

A standalone **Antigravity Skill** that generates complete **2D cel-shaded storytime cartoon videos** end to end using **Google Flow MCP (`flow-connector`)** and **FFmpeg**.

Because Google Flow generates a **maximum of 10 seconds per video clip** (`4s`, `6s`, `8s`, or `10s`), this skill automatically splits your story into sequential `6s`–`10s` animated shots, locks a **Master Character Reference Anchor**, chains each clip from the **last clean frame of the previous clip**, trims tail-end morphing, and stitches all normalized `1080p` clips into a single master `.mp4`.

---

## 1. Setup in Antigravity

### Automatic Skill Location
The skill is installed in your global Antigravity skills folder:
```text
C:\Users\Nirajan\.gemini\config\skills\not-your-type\
```
*(If setting up on a new machine, copy this folder into `C:\Users\<YourUsername>\.gemini\config\skills\not-your-type\`.)*

### Prerequisites Check
1. **Google Flow Browser Tab:** Open `https://flow.google.com` in Chrome or Edge, sign in to your Google account, and keep the tab **visible on screen** (not minimized) with the **Flow Connector** extension enabled.
2. **One-Time Setup Verification:**
   In Antigravity chat, type:
   ```text
   not your type setup
   ```
   Or run the self-checks manually in PowerShell:
   ```powershell
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\delama_video.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\character_bible.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\frame_chain.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\assemble.py --selfcheck
   ```

---

## 2. How to Start a Video in Antigravity

### Step 1 — Trigger the Skill
Open any chat in Antigravity and type any of these trigger phrases:
- `create a not your type`
- `not your type start`
- `make a 2d storytime video`
- `not your type continue` *(resumes your most recent project where it left off)*

### Step 2 — Answer the 3 Startup Questions
When you say `create a not your type` (without specifying details yet), the agent will immediately ask you **only 3 things in one short message**:

> 1. **Title / Topic:** What is the story or topic? *(Or say "suggest topics" for 10 storytime ideas)*
> 2. **Language:** Which language should the script/story be in? *(Hindi, Hinglish, English, or any other language)*
> 3. **Length:** How long should the full video be? *(e.g., 30 seconds, 1 minute, 2 minutes, 5 minutes — automatically segmented into 6s–10s chained Flow MCP video clips)*

### Step 3 — Reply with Your Input
You simply reply in one line, for example:
- `"Title: Last Bench in School, Language: Hinglish, Length: 1 minute"`
- Or give all three directly right from the start:
  `"create a not your type video on Night Before Exam in Hindi, 2 minutes"`

---

## 3. What Happens Next (Automated 4-Stage Checkpoints)

Once you give the **Title, Language, and Length**, the agent creates your project folder under `~/Storytime2D/<slug>/` and runs the pipeline:

| Stage | What the Agent Does | What You Do |
| :--- | :--- | :--- |
| **1. Script & Clip Plan** | Writes `SCRIPT.md` and calculates the exact number of `6s`–`10s` clips needed for your target length (since Flow's max clip length is 10s: e.g., 1 min = ten 6s clips or six 10s clips). | **Approve the script** (say `"OK"` or ask for edits). |
| **2. Master Character Anchor** | Locks `CHARACTER_BIBLE.json` and generates the **Master Character Reference Image** (`img/ref_protagonist.png`) via Flow MCP (`flow-text-to-image`) with bold black ink outlines, flat solid colors, and zero watermark. | **Confirm the character look** (or proceed automatically). |
| **3. Frame-Chained Video Clips** | Generates each `6s`–`10s` animated clip sequentially via Flow MCP (`flow_generate`):<br>• **Clip 1:** Animated from the Master Character Reference + Scene 1 starting keyframe.<br>• **Clip `N`:** Trims the final 3–5 frames of Clip `N-1`, extracts `frames/chain/s{N-1}_last.png`, and passes it + `img/ref_protagonist.png` into Flow MCP so the character never morphs. | Agent runs this automatically and checks `review.jpg`. |
| **4. Stitch & Final MP4** | Cleans corner watermarks (`delama_video.py`), normalizes all clips to `1920x1080` (`16:9`, `30fps`), stitches them seamlessly via FFmpeg (`assemble.py`), verifies `qc.jpg`, and gives you the final `.mp4` path. | **Watch your finished `.mp4` video!** |

---

## 4. Folder Structure

```text
not-your-type/
├── README.md                     # This quickstart & Antigravity usage guide
├── SKILL.md                      # Main Antigravity skill instructions & interactive startup flow
├── PLAYBOOK.md                   # Complete architecture, 2D cel-shaded style rules, and Flow MCP reference
├── SETUP.md                      # Environment verification runbook
├── SETUP_STATUS.md               # Machine verification status
├── prompts/                      # Hardcoded 2D cel-shaded style lock, anti-morphing guardrails & JSON schemas
├── looks/                        # Reusable 2D background environment palettes
├── scripts/                      # Standalone Python + FFmpeg pipeline scripts
│   ├── character_bible.py        # Character Bible & Master Reference Anchor generator
│   ├── frame_chain.py            # Anti-morphing tail trimmer (3-5 frames) & last-clean-frame extractor
│   ├── video_clips.py            # Sequential frame-chained Flow MCP video generator
│   ├── delama_video.py           # Image & video corner watermark remover
│   └── assemble.py               # 1080p clip normalizer, FFmpeg stitcher & 3-point QC sheet builder
└── example/
    └── sample_sequence/          # Complete example project with pre-validated SHOTS.tsv & mcp_jobs.json
```
