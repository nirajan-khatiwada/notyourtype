# 2D Background & Environment Looks Catalog

Each look defines a clean, generic 2D background color palette and lighting mood while enforcing **2D digital cel-shaded cartoon animation rules** (bold uniform black ink outlines, flat solid color fills, minimal hard-edge cel shading, zero 3D volumetric lighting).

| Look Name | Best Used For | Background Palette & Composition |
| :--- | :--- | :--- |
| `flat_daylight` | **Default look**: everyday interior or exterior scenes, bright daytime storytelling, clear character acting | Flat pastel walls or clean sky tones (soft cream, light blue, mint), simple furniture/props, balanced neutral daylight |
| `warm_interior` | Indoor rooms, desks, workspaces, classrooms, living areas | Flat warm-ochre and cream tones, simple wooden surfaces, clean black ink outlines |
| `high_contrast_focus` | Nighttime scenes, dramatic realization beats, high-tension comedic reactions | Flat deep slate-navy background planes with crisp hard-edge 2D light shapes keeping the foreground character bright and readable |
| `minimal_backdrop` | Fast-paced reaction cuts, exaggerated expression close-ups, punchline beats | Clean two-tone flat graphic 2D background with zero background clutter, keeping 100% focus on the character's pose and facial expression |

## Usage
`STYLE.txt` begins with `look: <look_name>` on line 1, followed by the look's environment description. `character_bible.py` and `video_clips.py` combine `STYLE.txt` with `prompts/style_lock.txt` and `prompts/negative_guardrails.txt`.
