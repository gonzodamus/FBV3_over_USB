# FBV3 LED Web Editor — spec

A handoff spec for building a **Web MIDI** app that visually controls the Line 6 FBV3
(MK3) footswitch LEDs. It pairs with the firmware patch in this repo (see
[`README.md`](README.md)), which exposes every LED as a standard MIDI Control Change —
so the app is purely a MIDI sender: no install, no drivers, no native code.

## What it is

A single-page app (runs in Chrome/Edge via the Web MIDI API) with an on-screen layout
of the FBV3's controls. Click a control, pick a **color** + **state**, and it sends the
matching CC to the pedal. Add save/recall of named "scenes" (full LED layouts) and an
"apply all" that sends a whole scene at once.

This is **LED control only** — see [Out of scope](#out-of-scope).

## Protocol (the important part)

- **MIDI output:** a port whose name contains **`FBV 3`** (enumerate `access.outputs`).
  Channel 1.
- **Message:** Control Change. Raw bytes: `[0xB0, ledIndex, value]`.
  - **CC number = LED index**
  - **CC value = `state * 8 + color`**

### LED index (CC number)

| idx | LED          | idx | LED          |
|----:|--------------|----:|--------------|
| 0   | FS1          | 7   | ToneC        |
| 1   | FS2          | 8   | ToneD        |
| 2   | FS3          | 9   | Pedal Volume |
| 3   | FS4          | 10  | Pedal Wah    |
| 4   | FS5          | 11  | Tap Tempo    |
| 5   | ToneA        | 12  | FUNC         |
| 6   | ToneB        | 13  | Diagnostic   |

### Value = `state * 8 + color`

- **state**: `0` = off · `1` = steady (values 8–15) · `2` = blink (values 16–23)
- **color** (low 3 bits):

  | color | name   | color | name   |
  |------:|--------|------:|--------|
  | 0     | red    | 4     | yellow |
  | 1     | green  | 5     | pink   |
  | 2     | blue   | 6     | orange |
  | 3     | cyan   | 7     | white  |

So **steady = `8 + color`** (8=red … 15=white), **blink = `16 + color`**, **off = `0`**.

### Test vectors

| Intent                | CC (num, value) | Raw bytes            |
|-----------------------|-----------------|----------------------|
| FS1 → steady green    | `0, 9`          | `B0 00 09`           |
| FUNC → steady white   | `12, 15`        | `B0 0C 0F`           |
| FS3 → blinking blue   | `2, 18`         | `B0 02 12` (16+2)    |
| FS4 → off             | `3, 0`          | `B0 03 00`           |

Reference: `sendmidi dev "FBV 3" cc 0 9` lights FS1 steady green.

## Suggested scope (MVP → nice-to-have)

1. **MVP:** detect the `FBV 3` output; render the 14 controls; per-control color swatch +
   off/steady/blink toggle; send-on-change; an "all off" button.
2. **Scenes:** save / load / name full 14-LED layouts in `localStorage`; "apply scene"
   sends all 14 CCs.
3. **Nice:** reflect the chosen color on each control in the UI; render blink as a CSS
   pulse; a rainbow / preset generator.

## Gotchas

- **Secure context required.** Web MIDI only works over `https://` or `http://localhost`
  — a `file://` page won't get MIDI access in Chrome. Serve it locally.
- Request access with `navigator.requestMIDIAccess({ sysex: false })`. **SysEx is not
  needed** (LEDs are plain CC); leaving it off avoids an extra permission prompt.
- Output port names vary by OS/driver — **match on substring `"FBV 3"`**, don't assume an
  exact string. Handle the device being absent / hot-plugged (`onstatechange`).
- **Requires the patched firmware** (`Fbv3_ledcc_v7.hxf`, reports version `1.0.2.0.1`).
  Stock firmware ignores these CCs, so the app does nothing on an unpatched pedal.

## Out of scope

- **Switch → MIDI assignment** config (what message each footswitch *sends*) still lives
  in Line 6's "FBV3" editor over a separate vendor-USB protocol that has **not** been
  reverse-engineered. This app does not touch it.
- This app does not flash firmware. Flashing is covered in [`README.md`](README.md).

## Footswitch LED mode (CC #16)

CC number **16** is a reserved global toggle for how footswitch LEDs react to presses
(the LED *color* always comes from the per-LED CCs):

- `cc 16 0` — **inverted** (firmware default): LED lit at rest, dark while pressed.
- `cc 16 1` — **stock**: LED off at rest, lit only while pressed.

The flag lives in RAM and **resets to inverted (0) on power-up**, so the app should send
its desired mode on (re)connect (alongside the layout). Index 16 is not a real control.

## Behavior notes (from the firmware side)

- The CC-set **color** persists (it isn't overwritten by switch presses). The app can
  treat the color it sent as authoritative.
- The on/off the app sends is the LED's *resting* state; the firmware momentarily flips it
  on physical presses according to the CC #16 mode above.
- Two bytes back the firmware: a **color** byte and an **on/blink** byte. The single CC
  value encodes both (`state*8 + color`), so one message fully sets an LED.
