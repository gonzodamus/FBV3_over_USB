# manual/firmware/

Firmware images live here. They are **not** committed to the repo: the stock image is
Line 6's copyrighted property, and the patched image is a derivative of it.

**You provide:**

- `Fbv3_v1_02_00.hxf`: the stock Line 6 FBV3 firmware (v1.02.00). If you've run the
  Line 6 FBV3 Updater before, it's already on your computer; otherwise download the FBV3
  firmware update from Line 6.

**The build produces:**

- `Fbv3_Chroma_1.3.hxf`: the patched firmware (boots as **FBV Chroma 1.3**), written here
  by `build/build_firmware.py` (or the double-click `Build Firmware.command`), both in
  this `manual/` folder. v1.3 adds **persistent LED settings** (a CC #17 "save" command plus
  a boot-time restore) on top of v1.2's USB LED color + per-LED behavior control.

See the top-level [README](../../README.md) for the full build and flashing steps.
