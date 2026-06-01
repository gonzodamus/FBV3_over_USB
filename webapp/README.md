# FBV3 LED Editor (web app)

A single-page Web MIDI app that controls the Line 6 FBV3 footswitch **LEDs**. It pairs
with the firmware patch in this repo — see [`../WEB_APP_SPEC.md`](../WEB_APP_SPEC.md) for
the protocol and [`../README.md`](../README.md) for flashing.

No build step, no dependencies — just three static files (`index.html`, `styles.css`,
`app.js`).

## Run it

Web MIDI only works in a **secure context**, so a `file://` page won't get MIDI access.
Serve the folder over `localhost` (or `https`) and open it in **Chrome or Edge**:

```sh
cd webapp
python3 -m http.server 8000
# then open http://localhost:8000
```

Any static server works (`npx serve`, `php -S localhost:8000`, etc.).

When prompted, allow the **MIDI** permission. The app finds the output port whose name
contains `FBV 3` automatically, and whenever the pedal (re)connects it pushes the current
on-screen layout so the hardware matches the editor.

## Using it

- The LEDs are laid out like the pedal. **Click a lamp to select it**, then pick a
  **color** swatch and a **Steady / Blink** state in the editor below. Every change is
  sent to the pedal immediately as a Control Change.
- **Invert** (toolbar, far right) is a global toggle sent as `CC 16`. *On* (default, `value 0`) is the
  inverted behavior — LED lit at rest, dark while the switch is pressed; *Off* (`value 1`)
  is stock — LED off at rest, lit only while pressed. The choice persists and is re-sent on
  connect (the firmware flag resets to inverted on power-up).
- **Presets** (Rainbow, All white) fill the board with a quick layout.
- **Scenes** are saved in `localStorage` with *Save current…* and appear as chips on the
  toolbar next to the presets. Click a chip to apply that scene (sends every LED); click
  its **×** to delete it.
- Your current layout is remembered across reloads.

## Requirements

- A Chromium browser (Chrome/Edge). Safari and Firefox have no Web MIDI API.
- The FBV3 running the **patched** firmware (reports version `1.0.2.0.1`). Stock firmware
  ignores these CCs, so the app does nothing on an unpatched pedal.

## Scope

LED control only. Configuring what each footswitch *sends* lives in Line 6's editor over a
separate, un-reverse-engineered protocol and is out of scope (see the spec).
