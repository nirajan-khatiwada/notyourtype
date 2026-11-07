# Prompt Architecture & Style Lock Templates

This directory contains the hardcoded visual style modifiers, negative anti-morphing constraints, generic Character Bible schema, and structured shot prompt templates used by `scripts/character_bible.py` and `scripts/video_clips.py`.

## Files

| File | Purpose |
| :--- | :--- |
| `style_lock.txt` | Objective **2D Cel-Shaded Storytime Cartoon Animation** visual specification appended to every keyframe and video generation call. |
| `negative_guardrails.txt` | Strict **Anti-Morphing, Anti-3D, Anti-Slideshow, and Anti-Text Negative Constraints** appended to every Flow MCP call. |
| `character_bible.json` | Generic **Character Specification Schema** locking exact head geometry, eye/brow style, hair silhouette, solid outfit color, and 2D proportions (`protagonist`, `secondary_character`, `supporting_character`). |
| `shot_templates.json` | Deterministic prompt assembly formulas for: (1) Master Character Turnaround Sheet, (2) Single Character Reference Anchor, (3) Anchor-Locked Scene Starting Keyframe (`new_scene`), (4) Frame-Chained Video Clip (`chain`), and (5) First-to-Last Frame Interpolation (`interp`). |

## Prompt Assembly Formula

Every video generation prompt sent to `flow_generate` on the `flow-connector` MCP server is constructed from five deterministic blocks:

```
[1. CONTINUITY & REFERENCE BINDING]
  + [2. LOCKED CHARACTER SPECIFICATION (from CHARACTER_BIBLE.json)]
  + [3. SCOPED ACTING BEAT: ONE PHYSICAL ACTION + ONE EXPRESSION SHIFT + 2D LIP-SYNC]
  + [4. CLEAN 2D ILLUSTRATED SETTING & CAMERA FRAMING (from STYLE.txt / looks/)]
  + [5. HARDCODED STYLE LOCK (style_lock.txt) + NEGATIVE GUARDRAILS (negative_guardrails.txt)]
```
