# FBV Chroma LED Editor (web app)

A single-page Web MIDI app that controls the Line 6 FBV3 footswitch **LEDs**, and can
build the patched firmware in-browser. It pairs with the firmware patch in this repo;
see [`../README.md`](../README.md) for the MIDI protocol (the Usage section) and for
flashing.

No build step, no dependencies, just static files: `index.html`, `styles.css`, `app.js`,
plus `patch.js` (in-browser firmware patcher) and `md5.js` (container checksum).

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

## Building the firmware (in-browser)

The **"Build the patched firmware"** section at the top turns a stock
`Fbv3_v1_02_00.hxf` into `Fbv3_Chroma_1.1.hxf` entirely client-side (via `patch.js` +
`md5.js` and the browser's native `CompressionStream`). The file is never uploaded. It
applies the exact same byte edits as `manual/build/build_firmware.py` and verifies the result
against the known-good image checksum before offering the download.

## Using it

- The LEDs are laid out like the pedal. **Click a lamp to select it**, then pick a
  **color** swatch and a **Steady / Blink** state in the editor below. Every change is
  sent to the pedal immediately as a Control Change.
- **Behavior** (per LED) controls how a switch LED reacts to its footswitch: *On at rest*
  (lit when not pressed, the default), *On when pressed*, *Always on*, or *Always off*. Pick
  it in the editor for the selected lamp, or use **Apply to all** in the toolbar to set every
  LED at once. Sent as `CC 16` (`value = LED index * 4 + behavior`); the choice persists and is
  re-sent on connect (the firmware resets every LED to "on at rest" on power-up).
- **Presets** (Rainbow, All white) fill the board with a quick layout.
- **Scenes** are saved in `localStorage` with *Save current…* and appear as chips on the
  toolbar next to the presets. Click a chip to apply that scene (sends every LED); click
  its **×** to delete it.
- Your current layout is remembered across reloads.

## Requirements

- A Chromium browser (Chrome/Edge). Safari and Firefox have no Web MIDI API.
- The FBV3 running the **patched** firmware (**FBV Chroma 1.1**). Stock firmware
  ignores these CCs, so the app does nothing on an unpatched pedal.

## Scope

LED control only. Configuring what each footswitch *sends* lives in Line 6's editor over a
separate, un-reverse-engineered protocol and is out of scope.

The editor covers the LEDs you'd actually set by hand: FS1-5, A-D, and FUNC. The firmware
also accepts LED indices 9, 10, 11, and 13 (Pedal Volume, Pedal Wah, Tap Tempo,
Diagnostic) over the same CC scheme; drive those directly with `sendmidi` if you need them
(see the main README's Usage table).
