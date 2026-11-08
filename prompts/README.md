# Prompt Architecture & Style Lock Templates

This directory contains the hardcoded visual style modifiers, negative anti-morphing constraints, reusable asset schemas, and structured shot prompt templates used by `scripts/assets.py`, `scripts/character_bible.py`, and `scripts/video_clips.py`.

## Files

| File | Purpose |
| :--- | :--- |
| `style_lock.txt` | Objective **2D Cel-Shaded Storytime Cartoon Animation** visual specification appended to every keyframe and video generation call. |
| `negative_guardrails.txt` | Strict **Anti-Morphing, Anti-3D, Anti-Slideshow, and Anti-Text Negative Constraints** appended to every Flow MCP call. |
| `assets.json` / `character_bible.json` | Reusable **Asset Specification Schemas** locking characters (face, hair silhouette, outfit color, proportions), backgrounds (clean illustrated 2D environments), and props (isolated story objects). |
| `shot_templates.json` | Deterministic prompt assembly formulas for: (1) Master Character Turnaround Sheet, (2) Single Character Reference Anchor, (3) Reusable Background Asset, (4) Reusable Prop Asset, (5) Multi-Character Scene Keyframe (`new_scene`), (6) Frame-Chained Video Clip (`chain`), and (7) First-to-Last Frame Interpolation (`interp`). |

## Prompt Assembly Formula

Every video generation prompt sent to `flow_generate` on the `flow-connector` MCP server is constructed from five deterministic blocks:

```
[1. CONTINUITY & REFERENCE BINDING]
  + [2. LOCKED MULTI-CHARACTER SPECIFICATIONS (from ASSETS.json / CHARACTER_BIBLE.json)]
  + [3. SCOPED ACTING BEAT: PHYSICAL ACTIONS + EXPRESSION SHIFTS + 2D LIP-SYNC]
  + [4. CLEAN 2D ILLUSTRATED BACKGROUND & PROPS (from assets/ & STYLE.txt)]
  + [5. HARDCODED STYLE LOCK (style_lock.txt) + NEGATIVE GUARDRAILS (negative_guardrails.txt)]
```
