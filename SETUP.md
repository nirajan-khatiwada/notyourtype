# Standalone Setup & Verification Guide

This guide verifies the required environment for running the standalone **2D Storytime Character Video Animation Skill** via **Google Flow MCP** and **FFmpeg**.

---

## Step 1: Google Flow MCP Server (`flow-connector`)
*Purpose: Zero-cost 2D character reference, keyframe, and continuous video generation (`omni-flash`, `veo-3.1-fast`, `veo-3.1-lite`, `veo-3.1-quality`, `nano-banana-2`) through Google Flow.*

1. Verify the Flow MCP bridge and browser connection by calling the MCP tool `flow_status` or `flow_doctor` on server `flow-connector`.
2. Ensure `https://flow.google.com` is open in Chrome/Edge, signed in, and visible on screen during active generation runs (Chromium throttles minimized background tabs).

---

## Step 2: FFmpeg & FFprobe
*Purpose: Frame decoding, tail-end frame trimming, `delogo` watermark removal, uniform clip normalization (`1920x1080`, `16:9`, `24/30fps`, `yuv420p`), audio muxing, and seamless MP4 concatenation.*

1. Verify `ffmpeg` and `ffprobe` are available in `PATH`:
   ```powershell
   ffmpeg -version
   ffprobe -version
   ```
2. Verify required filters (`scale`, `pad`, `fps`, `delogo`, `concat`):
   ```powershell
   ffmpeg -hide_banner -filters | Select-String "delogo|concat|scale|fps"
   ```

---

## Step 3: Python 3.11+ & Scientific / Image Packages
*Purpose: Runs `character_bible.py`, `frame_chain.py`, `video_clips.py`, `delama_video.py`, and `assemble.py`.*

1. Verify Python packages (`numpy`, `pillow`):
   ```powershell
   python -c "import numpy, PIL; print('OK:', numpy.__version__, PIL.__version__)"
   ```
2. Run the built-in self-check suite for all pipeline scripts:
   ```powershell
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\delama_video.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\character_bible.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\frame_chain.py --selfcheck
   python C:\Users\Nirajan\.gemini\config\skills\not-your-type\scripts\assemble.py --selfcheck
   ```
