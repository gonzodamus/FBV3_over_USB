#!/bin/bash
# Double-click this file in Finder to build the patched FBV3 firmware.
# It turns your own copy of the stock Line 6 firmware into the patched version
# that adds USB LED control. Nothing is sent anywhere; it all happens on your Mac.

# Work from the folder this script lives in (so double-clicking "just works").
cd "$(dirname "$0")" || exit 1

BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'

echo ""
echo "${BOLD}FBV3 over USB: firmware builder${OFF}"
echo "==================================="
echo ""

STOCK="firmware/Fbv3_v1_02_00.hxf"

# 1. Make sure the stock firmware is present.
if [ ! -f "$STOCK" ]; then
  echo "${YELLOW}I need the original Line 6 firmware first.${OFF}"
  echo ""
  echo "  1. Download the FBV3 firmware update from Line 6 (file name like"
  echo "     'Fbv3_v1_02_00.hxf'). If you've ever run the Line 6 FBV3 Updater,"
  echo "     it's already on your computer."
  echo "  2. Put that file into this folder:"
  echo ""
  echo "       ${BOLD}$(pwd)/firmware/${OFF}"
  echo ""
  echo "     and make sure it's named exactly:  ${BOLD}Fbv3_v1_02_00.hxf${OFF}"
  echo "  3. Then double-click this script again."
  echo ""
  echo "Press Return to close."
  read -r _
  exit 1
fi

# 2. Find Python 3.
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "${RED}Python 3 isn't installed.${OFF}"
  echo ""
  echo "macOS usually has it. To install it: open the App Store or run"
  echo "'xcode-select --install' in Terminal, then double-click this script again."
  echo ""
  echo "Press Return to close."
  read -r _
  exit 1
fi

# 3. Build.
echo "Building the patched firmware..."
echo ""
if "$PY" build/build_firmware.py; then
  echo ""
  echo "${GREEN}${BOLD}Success!${OFF}"
  echo ""
  echo "Your patched firmware is here:"
  echo "  ${BOLD}$(pwd)/firmware/Fbv3_Chroma_1.1.hxf${OFF}"
  echo ""
  echo "Next: flash it with the Line 6 FBV3 Updater (see the README's"
  echo "\"Flash the firmware\" steps). You can leave this window open or close it."
else
  echo ""
  echo "${RED}Something went wrong.${OFF} Please copy the messages above and open an"
  echo "issue on the project's GitHub page."
fi

echo ""
echo "Press Return to close."
read -r _
