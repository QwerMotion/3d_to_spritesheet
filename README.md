# Blockbench → Spritesheet Renderer

A single-file, zero-build web tool that loads an animated Blockbench **glTF Binary (`.glb`)**
model, renders it from N evenly spaced horizontal viewing angles, and exports **one PNG
spritesheet per animation clip** for use as 2D directional sprites in a game.

Open `index.html` in Chrome or Firefox (no server, no build step), then drag in a `.glb`.

## Output layout

```
            frame 0      frame 1      frame 2      frame 3
row 0  [ angle 0 ]  [ angle 0 ]  [ angle 0 ]  [ angle 0 ]     ← row 0 = front ({startAngle}°)
row 1  [ angle 1 ]  [ angle 1 ]  [ angle 1 ]  [ angle 1 ]
row 2  …
row N  [ angle N-1 ] …

width  = frameWidth  × framesPerClip
height = frameHeight × directionCount
```

* **One row per direction, one column per frame**, frames left→right in playback order.
* **Row 0** is the model's front: the camera sits on **+Z** and looks at the model's centre
  (glTF's default "towards the viewer" axis). Use **Row 0 offset** to rotate row 0 by any
  angle if your model does not face +Z.
* Rows proceed in the direction chosen by **Row order**:
  * clockwise *(default, S→W→N→E as seen from above)* or
  * counter-clockwise *(S→E→N→W)*.
* As seen from above (north up, east right), a **clockwise** row order puts row 1 to the
  model's **west**. The same convention is used for every exported sheet, so rows are
  comparable across clips.
* Exported PNGs always have a **transparent background**; the *preview* background colour is
  cosmetic and never baked into the file.

### Centering a model that is off-center

Every camera orbits the **bounding-box centre** of the model's animated poses, so anything
that pulls that centre away from the model's body — a pickaxe, a rifle, a wide attack pose —
makes the body slide around its cell: it sits left of centre in one row and right of centre in
another, and the exported sprite appears to jitter when the direction changes.

**Center X / Z** fixes that. The value shifts the model along the matching world axis by that
percentage of its fit radius, identically in every row and frame (the shift is a world-space
upright shift; the model turns in place because the *rotation axis* is what really moves).
Nudge while watching a single row in **capture-angle** preview until the body sits still, then
step through the rows (`Cycle direction`) — a well-aligned model keeps its feet in the same
spot in all of them. `+X` moves the model right in row 0; `+Z` moves it toward the row-0
camera. **Reset center offset** puts the axis back on the bounding-box centre.

Both demo buttons, the self-test's off-center demo and hand-built examples: the built-in
**Run pipeline self-test** measures this exactly — its off-center rig drifts 18 px between rows
with no nudge and 0.0 px once the center offset is set.

## Settings

| Setting | Notes |
|---|---|
| Directions | 4 / 8 / 16 presets or any custom N (evenly spaced, 360°/N) |
| Row 0 offset | Azimuth of row 0 in degrees |
| Row order | Clockwise or counter-clockwise |
| Elevation | Camera pitch, 1–89° (isometric-ish sprites usually 30–45°) |
| Zoom (× fit) | Multiplier on the auto-fit framing (auto-fit = model's animated bounding box) |
| Center X / Z | Nudge the model along a world axis, in % of the fit radius (see below) |
| Frame size | 32/64/128/256 presets or custom W×H per sprite cell |
| Sampling | "N frames per clip" (evenly spaced over the clip) or a fixed sample rate in fps |
| Light frame | Camera-locked (default) or world-fixed — see "Lighting" |
| Light yaw / height | Where the key light sits: compass position and angle above the horizon |
| Key / Fill / Ambient | Light intensities (fill sits opposite the key, low; lowering ambient makes the key read) |
| Shadows | Basic shadow map / soft contact blob / none |
| Preview camera | Free orbit, or the exact capture angle incl. a frame-boundary guide |
| Clips | Checkboxes for the clips to export (all checked by default) |
| Bundle | Export each sheet as its own PNG, or all sheets as one `.zip` |

## Lighting

There is one key light (it casts the shadow), one fill light opposite it and one ambient term;
all three intensities are sliders. **Light yaw** and **Light height** place the key light:
yaw is its compass position, height is its angle above the horizon.

The important setting is **Light frame**, because it decides what "the model turns" means for
the shading:

* **Camera-locked** *(default)* — the light is parked next to the viewer while the model turns
  underneath it. Every direction row is therefore lit the same way and the shadow always falls
the same way in the frame, which is what sprite sheets normally want: the character never
looks backlit, and the sprite is lit identically to its neighbours. Here yaw is relative to the
capture camera: **0° = straight in front of the viewer**, **+90° = the viewer's right**,
**180° = behind the model**.
* **World-fixed** — the sun stays put in the world and the model turns under it, so each
direction gets its own shading and shadow angle (the side facing away goes dark, and the shadow
swings around the model from row to row). Yaw is an absolute world angle here.

Swap between them with a single dropdown to see the difference; the stage line under
**Model** always shows which one is active along with the current yaw/height and intensities.

The defaults (`camera-locked`, yaw 40°, height 50°, key 2.3, fill 0.7, ambient 1.7) reproduce
the look row 0 had before the rig was configurable, so only directions 1…N−1 change when you
switch frames. Ambient is directionless and is what flattens the model — dropping it to ~0.4
is what makes the key light, and with it the shadow, actually read.

The **Run pipeline self-test** measures this rather than eyeballing it: on a rotationally
symmetric test body the shadow drifts **0.0 px** across all 8 rows camera-locked and
**60.7 px** world-fixed; yaw ±60° gives +29.3 / −29.2 luminance to the right half; and light
height 45° vs 80° moves the shadow from 30.3 px to 16.0 px off the model's axis.

Frame sampling uses evenly spaced times `t_i = i · duration / N`, so a looping clip does not
duplicate its first pose at the end.

## Input support

* ✔ **With armature** — `SkinnedMesh` + bone tracks (e.g. `player_1.glb`).
* ✔ **Without armature** — animation baked as per-node translation/rotation/scale tracks on
  the mesh nodes (e.g. `player_2.glb`, `zombie.glb`).
* ✔ **Multiple clips** — detected and listed; one sheet per clip.
* ✔ **No animations** — a static model still exports a single-frame sheet (`model.png`,
  1 column × N direction rows).

Both demo buttons in the UI build models of the first two kinds in-page, and
**Diagnostics → Run pipeline self-test** checks dimensions, transparency, per-frame
differences, per-row angle differences and row ordering for both variants, plus center
alignment and the lighting frame (see "Lighting").

## Offline build (`index-offline.html`)

`index.html` loads `three.js` and `JSZip` from jsDelivr, so the machine needs network access
on first load. If you want a version that needs **no internet at all**, use
**`index-offline.html`**: the same tool with every dependency (three.js r160, GLTFLoader,
OrbitControls, BufferGeometryUtils, JSZip 3.10.1, all MIT) inlined into the single file
(≈1.5 MB). Double-click it anywhere, including offline.

Send **only this file** — it is the whole tool. The recipient needs nothing else: no Python,
no Node, no server, no network, no unzip step, and no build. It contains no `<script src>`,
no importmap and no dynamic import, and the bundled libraries are emitted as **classic
scripts**, not ES modules — so opening it straight from disk (`file://`) cannot hit a
module-CORS block. The one thing it cannot do is bundle your models: send the `.glb` file(s)
too, or they drop their own in.

Regenerate it after editing `index.html`:

```bash
python build-offline.py
```

The generator downloads the pinned versions once (cached in `.offline-build/vendor/`),
rewrites the libraries' ES-module syntax so everything lives in one scope, wraps that scope
in a `'use strict'` IIFE (which reproduces module scoping and module strict-mode semantics
without needing a module script), and runs its own consistency checks that fail the build
on any leftover `import`/`export`, `<script src>`, `type="module"`, importmap, dynamic
`import()`, `import.meta`, NUL byte, or external reference. Only *regenerating* needs
Python + network; running either file needs neither.

## Notes

* Capture uses an **orthographic** camera, and the framing is auto-fitted to the animated
  bounding box once per model, so every cell of every sheet shares one scale.
* The renderer is temporarily resized to the cell size during export (the preview canvas is
  hidden) and only one capture pass can run at a time.
* Sheets are limited to 16384 px per side (browser canvas limit); the export panel shows the
  resulting dimensions before you export and refuses sizes above that.
* Textures embedded in a `.glb` are decoded with `createImageBitmap` (no URL round-trip), so
  the exported PNGs are never tainted by cross-origin content — this holds for `file://` too.
* `index.html` uses ES modules, so a browser that blocks them from `file://` needs a static
  server (`npx serve`, `python -m http.server`). `index-offline.html` does not: it has no
  module script and no external reference, so double-clicking it works as-is.
