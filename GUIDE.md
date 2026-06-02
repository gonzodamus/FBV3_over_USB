# FBV Chroma: Step-by-Step Guide

This guide is for **everyone**, no coding needed. By the end, your Line 6 FBV3's
footswitch lights will be controllable from your computer. Pick any color for any
switch, right from a web page.

There are two parts:

1. **Flash the firmware** (a one-time update to your pedal).
2. **Use the LED editor** (a web page where you click switches and choose colors).

> **Is this safe?** Flashing is reversible. If anything goes wrong you can put the
> original Line 6 firmware back (see [If something goes wrong](#if-something-goes-wrong)).
> That said, you do this at your own risk. This is an unofficial mod, not made by Line 6.

---

## What you'll need

- A **Line 6 FBV3 (MK3)** foot controller and its **USB cable**.
- A **Mac or Windows PC**.
- The **Line 6 FBV3 Updater** app (the official Line 6 program for updating the pedal).
  If you've ever updated your FBV3, you already have it.
- **Google Chrome** or **Microsoft Edge** (the LED editor needs one of these; Safari
  and Firefox won't work).

---

## Part 1: Flash the firmware

### Step 1: Get the patched firmware file

The patched firmware is a small file (ending in `.hxf`). For legal reasons we can't
hand it to you ready-made, since it's built from Line 6's own firmware, but we've made
building it as easy as a double-click.

1. [Download this project](#downloading-this-project) (see bottom of this guide) and
   unzip it.
2. You also need Line 6's **original** firmware file, named `Fbv3_v1_02_00.hxf`. If
   you've run the Line 6 FBV3 Updater before, it's already on your computer (search
   for `Fbv3_v1_02_00.hxf`). Otherwise download the FBV3 firmware update from Line 6.
3. Put that original file into the project's **`firmware`** folder.
4. Double-click the builder for your system:
   - **Mac:** **`Build Firmware.command`**. If macOS blocks it the first time
     ("unidentified developer"), right-click the file → **Open** → **Open**.
   - **Windows:** **`Build Firmware (Windows).bat`**. (Needs
     [Python 3](https://www.python.org/downloads/); the script tells you if it's missing.)
   - A window opens, does its thing, and says **Success!**
5. Your patched file appears in the `firmware` folder as **`Fbv3_Chroma_1.1.hxf`**.

Prefer the command line? See [Building it yourself](README.md#building-from-source) in
the README; it's two lines on any system.

### Step 2: Flash it with the Line 6 Updater

1. Connect the FBV3 to your computer with the USB cable.
2. Open the **Line 6 FBV3 Updater**.
3. Choose the option to **update from a file**, and pick your **`Fbv3_Chroma_1.1.hxf`**.
4. Let it run.
   - **You may see a brief "error" and a restart partway through. That's expected.**
     Just let it finish; the pedal checks the file a second way and accepts it.
5. When it's done, the pedal restarts. That's it, the firmware is updated.

> Keep your original `Fbv3_v1_02_00.hxf` handy so you can always go back to stock if you
> need to (see [If something goes wrong](#if-something-goes-wrong)).

> How to know it worked: when the pedal restarts, its screen shows **"FBV Chroma 1.1"**.
> (In the Line 6 Updater it lists as version **1.10**.) The lights are controlled from
> the computer now, so move on to Part 2 to see them in action.

---

## Part 2: Use the LED editor

The easiest way is the **online editor**. Just open a link:

### Option A: Open the web editor (easiest)

1. In **Chrome** or **Edge**, go to:

   **https://gonzodamus.github.io/FBV_Chroma/**

2. Make sure your FBV3 is plugged in by USB.
3. The page will ask permission to use **MIDI**. Click **Allow**.
4. The top of the page should say **Connected: FBV 3**. (If it doesn't, see
   [If something goes wrong](#if-something-goes-wrong).)

### Option B: Run it on your own computer (offline)

If you'd rather not use the hosted page, you can run the same editor locally. See
[Run it locally](webapp/README.md#run-it) in the web app's README.

### Using the editor

- You'll see a layout that matches your pedal. **Click a switch**, then **click a
  color**. The light changes instantly. Pick **Steady** or **Blink** for each.
- **Rainbow** / **All white** are one-click starting points.
- **Save current…** stores your layout so you can bring it back later (great for
  different songs or setups).
- **Invert** (top right) changes how the lights react to your foot:
  - **On** (default): the switch is **lit** normally and goes **dark while you press it**.
  - **Off**: the switch is **dark** normally and **lights up while you press it**.

> **Good to know:** the colors live on the pedal, but the **Invert** setting resets to
> "On" each time you unplug/power-cycle the pedal. The editor re-sends your setting
> automatically whenever it reconnects, so just keep the page open.

---

## If something goes wrong

**The editor says "Pedal not found"**
- Make sure the FBV3 is connected by USB and you flashed the patched firmware.
- Use **Chrome** or **Edge** (not Safari/Firefox).
- Try unplugging and replugging the pedal. The page detects it automatically.

**The editor says "Web MIDI not supported"**
- You're in a browser that can't do this. Open the page in **Chrome** or **Edge**.

**The lights don't change**
- Confirm the firmware flashed successfully (re-run the Updater if unsure).
- Reload the editor page and re-allow the MIDI permission.

**I want my pedal back to normal (un-mod it)**
- Flash the **original** `Fbv3_v1_02_00.hxf` with the Line 6 Updater. Done.
- If the pedal ever seems stuck: hold **FS1 + A** while plugging in the USB cable.
  The screen shows **Update Mode**, then flash the original firmware.
- The pedal's built-in recovery is separate and is never touched by this mod, so a
  permanent "brick" is very unlikely.

---

## Downloading this project

On the project's GitHub page, click the green **Code** button → **Download ZIP**, then
unzip it. (If you know Git, you can clone it instead.)

---

## Want the technical details?

- [README.md](README.md): overview, the MIDI protocol the editor speaks, command-line
  usage, and how to build from source.
