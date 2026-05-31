# FBV3 over USB — footswitch LED control

A firmware patch for the **Line 6 FBV3 (MK3)** foot controller that lets you set the
footswitch **LED colors over USB** from a computer — standalone, with no Line 6 amp
attached. Send a MIDI **Control Change** and the corresponding LED lights up in the
color you choose.

Stock firmware already sends MIDI **out** (knobs, expression pedal, switches) but
ignores almost all inbound USB MIDI, so the LEDs stay dark without a host amp. This
patch repurposes the dropped inbound Control Change messages and routes them to the
firmware's existing LED routine. The image is patched in place (same size), so the
device's boot integrity check still passes.

Status: **working** on firmware v1.02.00. Patched build reports version `1.0.2.0.1`.

## Requirements

- Line 6 **FBV3 (MK3)**, connected by USB.
- macOS (tested) with [`sendmidi`](https://github.com/gbevin/SendMIDI):
  `brew install sendmidi` (and `receivemidi` to read replies).
- The **Line 6 FBV3 Updater** (or your usual method) to flash a `.hxf` file.

## Installation (flash the firmware)

1. Flash **`firmware/Fbv3_ledcc_v3.hxf`** with the Line 6 Updater, the same way you'd
   apply an official update.
2. The Updater may show a one-time **error → restart**; let it retry. (Our zlib stream
   isn't byte-identical to Line 6's, but the device verifies the *decompressed* image,
   which is correct, so it boots.)
3. After it reboots, the pedal enumerates as the MIDI device **`FBV 3`**.

> If you don't already have it, build the patched firmware yourself — see
> [Building from source](#building-from-source).

## Usage

```
sendmidi dev "FBV 3" cc <LED> <value>
```

**LED index** (the CC number):

| idx | LED   | idx | LED      | idx | LED  |
|----:|-------|----:|----------|----:|------|
| 0–4 | FS1–FS5 | 5–8 | ToneA–ToneD | 9 | Pedal Volume |
| 10  | Pedal Wah | 11 | Tap Tempo | 12 | FUNC |
| 13  | Diagnostic |   |          |     |      |

**Value** = `state × 8 + color`:

- `state`: `0` = off, `1` = steady (values **8–15**), `2`+ = blink (values **16+**)
- `color` (low 3 bits): `0` red · `1` green · `2` blue · `3` cyan · `4` yellow · `5` pink · `6` orange · `7` white

So a **steady color** is `8 + color`:

| value | color  | value | color  |
|------:|--------|------:|--------|
| 8     | red    | 12    | yellow |
| 9     | green  | 13    | pink   |
| 10    | blue   | 14    | orange |
| 11    | cyan   | 15    | white  |

**Examples:**

```sh
sendmidi dev "FBV 3" cc 0 9      # FS1  -> steady green
sendmidi dev "FBV 3" cc 12 15    # FUNC -> steady white
sendmidi dev "FBV 3" cc 2 18     # FS3  -> blinking blue   (16 + 2)
sendmidi dev "FBV 3" cc 3 0      # FS4  -> off
```

## Verify the build

The patched firmware answers a standard MIDI Identity Request and reports its version.
With `receivemidi` (or any MIDI monitor) listening to `FBV 3`:

```sh
sendmidi dev "FBV 3" syx hex 7E 7F 06 01     # identity request
# reply includes ASCII "L6Version:1.0.2.0.1"  <- the modded-build marker
```

## Building from source

The patched `.hxf` is reproducible from the stock firmware:

```sh
# place your stock firmware here first:  firmware/Fbv3_v1_02_00.hxf
python3 build/build_firmware.py            # writes firmware/Fbv3_ledcc_v3.hxf
pip install capstone                        # optional: also disassemble-verifies the patch
```

`build/build_firmware.py` documents exactly what it changes (a 4-byte detour, a 46-byte
handler placed in dead space inside the factory self-test routine, and a 1-byte version
bump). The reverse-engineering notes are in [`docs/FBV_LED_FINDINGS.md`](docs/FBV_LED_FINDINGS.md).

## What this patch changes (and what it costs)

Every edit is made in place, so the firmware image stays the same size and the device's
boot integrity check still passes (51 bytes changed total).

**Kept — nothing player-facing is lost:**
- MIDI **out** from the knobs, expression pedal, and footswitches.
- Inbound USB **SysEx** handling (device identity / firmware updater), left intact.
- Normal LED behavior — we only *add* a way to drive the LEDs over USB.

**Removed:**
- The **factory manufacturing self-test** (the "NITEST" button/LCD self-test routine).
  The 46-byte LED handler is tucked inside that routine's code, so the self-test no
  longer functions. It's an assembly-line diagnostic with no documented end-user way to
  trigger it, so in normal use you don't lose anything you can reach.

**Changed:**
- Reported firmware version `1.0.2.0.0` → `1.0.2.0.1` (a build marker).

Reverting is just reflashing the stock firmware (see below).

## Recovery

Flashing is reversible. If a build misbehaves, restore the stock firmware:

1. Hold **FS1 + A** while plugging in USB → the LCD shows **Update Mode**.
2. Flash **`firmware/Fbv3_v1_02_00.hxf`** with the Line 6 Updater.

The recovery bootloader lives in a separate flash region that this patch never touches.

## Notes

- The firmware images are Line 6's copyrighted property (the patched one is a
  derivative). They're for **personal use** — don't redistribute them. They are
  gitignored here for that reason; the build script regenerates the patched image
  from your own copy of the stock firmware.
- Use at your own risk. This is an unofficial modification with no warranty.
