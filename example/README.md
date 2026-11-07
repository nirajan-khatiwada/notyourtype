# Generic Reference Project: `sample_sequence`

`sample_sequence/` is a generic template demonstrating the file schemas for a continuous 2D cel-shaded storytime animation sequence generated via **Google Flow MCP**.

## Files in `sample_sequence/`

| File | Description |
| :--- | :--- |
| `CHARACTER_BIBLE.json` | Locked Character Specifications (`protagonist`, `secondary_character`, `supporting_character`) with explicit head geometry, eye/brow style, hair silhouette, solid outfit color, and 2D proportions. |
| `STYLE.txt` | Active environment look (`look: flat_daylight`) enforcing 2D cel-shaded cartoon aesthetics. |
| `SHOTS.tsv` | 6 sequential continuous 2D animated video shots (`6s` each) demonstrating:<br>• `new_scene`: Anchor-locked starting keyframe (`keyframes/sNN_start.png`) + continuous video generation<br>• `chain`: Temporal continuity chaining from `frames/chain/s{N-1:02d}_last.png` + `img/ref_<char>.png`<br>• `interp`: First-frame to Last-frame pose interpolation |
| `SCENES.tsv` | Optional word-timed clip mapping (`cue, clip, note, continuity`). |
| `PICK.tsv` | Optional swap mapping file (`shot, file`) for reordering downloaded clips. |

## Validation & Flow MCP Manifest Export
From inside `example/sample_sequence/`, run:
```powershell
python ../../scripts/character_bible.py validate
python ../../scripts/video_clips.py validate
python ../../scripts/video_clips.py export-mcp
```
