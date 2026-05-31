# FBV MK3 LED Patch — Session Findings (updated 2026-05-31)

## ★ BREAKTHROUGH (2026-05-31): firmware has full USB-MIDI, incl. a RECEIVE path
This may make firmware patching UNNECESSARY. The stock firmware already enumerates as a
USB-MIDI class device and is wired to RECEIVE MIDI from the host:
- USB device descriptor @file 0x0dfe9: VID 0x0e41 (Line 6), PID 0x5067, bcdUSB 0x0110.
- Config descriptor @0x0e003: wTotalLength=101, 2 interfaces.
  - if#0: Audio Control (class 0x01 sub 0x01)
  - if#1: MIDIStreaming (class 0x01 sub 0x03), 2 endpoints:
    - ENDPOINT 0x02 = OUT (host->device)  <-- computer can SEND into the pedal
    - ENDPOINT 0x81 = IN  (device->host)  <-- pedal sends MIDI out (confirmed by user/FBV Control)
  - MIDI jacks: EMBEDDED IN id=1 + EXTERNAL IN id=2 ; EMBEDDED OUT id=3 + EXTERNAL OUT id=4.
    Embedded IN jack id=1 = host MIDI delivered into firmware => receive path EXISTS at USB level.
- User confirms: pedal sends MIDI over USB; Line6 FBV Control assigns CC / PgmChange / Bank /
  Mackie / MMC per button. User CAN read those assignments.

HYPOTHESIS (test before any firmware work): LEDs may respond to INBOUND MIDI feedback (common on
foot controllers — DAW echoes the button's CC back and the LED reflects state). If so, sending
the right MIDI from the Mac lights the LEDs = software-only, ZERO brick risk, firmware stays stock.

TEST PLAN (feedback-first, smartest):
 1. In FBV Control read what one button sends (e.g. FS1 -> CC#x val127 chN).
 2. Send that exact message back to the pedal's USB-MIDI input port.
 3. Watch that button's LED. Lights => crack it, then map every LED's feedback msg.
 4. If nothing: try value 0 vs 127 (toggle), then Note-On, then a CC sweep (0..127 each channel).
 5. If still nothing: inbound MIDI isn't used for LEDs -> fall back to firmware, but now patch the
    EXISTING MIDI-receive handler in real executable flash (sidesteps the dead-gap problem).
User's MIDI tool: `midisend` CLI (github c0z3n/mnmlstc-midisend OR npm 'midisend'). Recommend also
installing gbevin SendMIDI (`sendmidi`) + ReceiveMIDI (`receivemidi`) and Snoize MIDI Monitor for
ergonomic crafting/monitoring. Device MIDI port name likely contains "FBV"/"Line 6"/PID 5067.
Manual: line6 fbv-mkii MIDI manual (alfredorecabarren.com/.../line6_fbv-mkii.pdf).

## (firmware path, now FALLBACK) RESOLVED: the gap-injection strategy is dead. Need in-place .text patch.

### The decisive result (2026-05-30)
- `Fbv3_gaponly.hxf` (gap WRITTEN with v2 code, redirect at 0x081b0 LEFT ORIGINAL so the gap
  is never executed) => **BOOTS**.
- `Fbv3_v1_02_00_led_patch_v2.hxf` (identical gap code, redirect CHANGED to jump into the gap)
  => **BRICKS**. These two images differ by EXACTLY 4 bytes (0x081b0).
- Redirect bytes f8f769ff are confirmed = `bl 0x14011086` by THREE sources (original human
  patcher, my encoder, capstone). Not an encoding bug.
- CONCLUSION: writing the gap is harmless; *executing/fetching* from the 0x1086 gap FAULTS.
  Most likely the Updater skips erased (0xFF) regions when programming flash, so our gap code
  never physically lands in flash -> instruction fetch there faults -> red FUNC. The boot
  integrity check also does not cover that region (else gaponly would mismatch & brick).
- => ANY "inject into the erased gap + trampoline" approach cannot work. v1/v2/stub all died
  on this single cause, not on register handling.

### New strategy: modify already-executing .text in place (no gap, no trampoline)
- The hooked init fn 0x1401c774 is NOT the LED color writer: it zeroes 1 byte @0x10081e9c +
  17 contiguous bytes @0x10081e9d..0x10081ead, then sets a few flags, then tail-calls
  0x1401c73c. Its SOLE caller is 0x081b0 (so it runs once at init). The contiguous 17-byte
  block is not the LED color array (LED vars are stride 0x10, non-contiguous).
- LED color vars (0x10081xxx, var=0x10081ead+idx*0x10) are NOT referenced by any pc-relative
  literal, and NOTHING loads the firmware LED pointer-table (flash 0x14010580) via literal pool
  (0 refs). So the real LED writer/render path uses computed addressing (movw/movt or indexed
  table base in a register). Prior session noted a routine near flash ~0x1401cb5a doing many
  strb to 0x10081xxx from computed (=off, standalone) values — that is the prime in-place target:
  patch those store SOURCES to our constant colors. NEEDS confirmation (best via Ghidra GUI).

## (historical) Current decisive test: `Fbv3_gaponly.hxf`

### Established facts (high confidence)
1. **Container/compression pipeline is SOUND.** `Fbv3_noop_lvl9.hxf` = original firmware run
   through our full decompress->recompress(zlib level 9)->recompute MD5/size->rebuild pipeline
   with ZERO code changes. It BOOTS normally. So bricks are caused by our firmware byte changes,
   not the container.
   - Side note: our recompressed stream isn't bit-identical to Line 6's factory deflate, so the
     Updater shows an error and needs a restart, then accepts & boots. Cosmetic, not the brick.
2. **The erased gap is at file 0x01086** (flash 0x14011086), 86 bytes of 0xFF, ends 0x010dc.
   This is where v1/v2/stub placed code. (Earlier mid-session I briefly mis-read this as a live
   function and thought 0x866 was the gap — WRONG. 0x866 is live LED-pointer-table data
   (ISFF=False). Do not put code at 0x866. A bad build "v4" using 0x866 was created then deleted.)
3. **No MPU configured** (0 MPU/SCB region-config literals found), so flash is not marked
   execute-never by software. A plain branch into the gap should not, by itself, fault.
4. **v1, v2, and the passthrough stub all brick IDENTICALLY** (black LCD, red FUNC). They share
   exactly two edits: code in the 0x1086 gap + the redirect at 0x081b0. The register differences
   between v1/v2 are irrelevant (the r0-r4 theory was a dead end). The pure-passthrough stub
   (gap = single `b.w 0x1401c774`, behaviorally identical to stock) STILL bricked.

### Leading hypothesis
Device verifies MD5 over the **flashed** bytes, and the Updater does **not actually program the
erased 0x1086 gap region** (fits the "update errored, needed restart" symptom). Then:
- no-op: gap stays 0xFF in image AND flash -> MD5 matches -> boots.
- any gap write: our HEAD-MD5 expects our code in the gap, but flash stays 0xFF there ->
  MD5 mismatch -> red FUNC halt (the brief's documented MD5-fail behavior).
Alternative (less likely, no MPU): fetching/executing from the gap faults at runtime.

### The test that splits these: `Fbv3_gaponly.hxf`
- Writes the v2 code blob into the 0x1086 gap, but LEAVES 0x081b0 = original `bl 0x1401c774`,
  so the gap code is NEVER executed. diff vs orig = ONLY 0x1086-0x10d1. container_ok=True.
- If it BRICKS (red FUNC): the gap can't be modified at all -> MD5-over-flash + Updater-skips-gap.
  => We must place code in a region the Updater really programs (inside the real .text, not the
     gap), e.g. by overwriting/relocating within 0x2000-0xd000 where actual functions live.
- If it BOOTS: writing the gap is fine; the fault is execution/branch-related -> revisit the
  redirect/branch target and how control reaches the gap.

### Key addresses
- Erased gap: file 0x01086 / flash 0x14011086, 86 bytes (only 76 used).
- Redirect (hook) site: file 0x081b0, original `bl 0x1401c774` (04f0e0fa). r0 holds a pointer
  arg (0x10005dd0, ldr at 0x081ae) that 0x1401c774 dereferences. Next calls: 0x081b4
  bl 0x1401ce74 ; 0x081ba bl 0x1401c160.
- Init fn 0x1401c774 (file 0x0c774): zeroes 0x11 (17) bytes via a loop then sets several flags;
  this is the LED/state init we wanted to run AFTER our writes.
- LED color vars: RAM, addr = 0x10081ead + index*0x10. Firmware pointer table to them:
  flash 0x14010580..~0x854 (80 ptrs). Real executable code: file ~0x2000-0xd000 (push-lr dense).

### Tooling / env
- python capstone, objdump, r2/radare2/rabin2, Ghidra GUI at /Applications/ghidra_12.1_PUBLIC
  (no analyzeHeadless on PATH). NO keystone (hand-assemble Thumb, verify with capstone).
- This chat env truncates/garbles long & multi-line tool output and can interleave my own text;
  write results to files and read SHORT slices; avoid large parallel tool batches.
- Verified Thumb BL/B.W (T4) encoder in /tmp/fbv_stub.py (reproduces redirect f8f769ff exactly).
- Build scripts: /tmp/fbv_noop.py, /tmp/fbv_stub.py, /tmp/fbv_gaponly.py, /tmp/fbv_build_v2.py.
- Recovery if bricked: hold FS1 + A, plug USB -> "Update Mode" -> reflash original .hxf.

### Files in ~/Downloads now
- Fbv3_v1_02_00.hxf (ORIGINAL, keep)
- Fbv3_noop_lvl9.hxf (known-good control: boots)
- Fbv3_stub.hxf (passthrough: bricks)
- Fbv3_gaponly.hxf (NEXT TEST: gap written, never executed)
- Fbv3_v1_02_00_led_patch.hxf (v1, bricks), Fbv3_v1_02_00_led_patch_v2.hxf (v2, bricks)

---

## Static RE pass (2026-05-31, agent)

Analysis-only pass (no flashing/building). Decompressed fw to `/tmp/fbv_fw.bin` (57498 bytes,
verified). Tools: `/usr/bin/python3` + capstone 5.0.7 (homebrew python3.14 has NO capstone),
r2, and Ghidra 12.1 headless (Temurin 25 OK). NOTE: Ghidra 12.1's mac arm64 **decompiler native
binary is missing**, so headless gives disassembly/xrefs/function-graph only — no C output. Most
of this was done with capstone (linear sweep desyncs on interleaved data, so functions were
disassembled individually from known starts). flash_addr = file_off + 0x14010000.

### MAJOR CORRECTIONS to earlier sessions
- **The LED color vars are NOT at 0x10081ead+idx*0x10.** That region (0x10081ead..0x1008238d,
  stride 0x10, all ODD = Thumb ptrs) is a table of 91 **RAM-resident console accessor function
  pointers**, word1 of the (name,fn) console table at flash 0x14010580. The names
  (FUNCR=,FS1R=,...,FS5O=, AR=..DO=) are a serial-console get/set command set, not the storage.
- **The visible `f0 00 01 0c 11 03 7c/7d/7e/7f` SysEx templates are the FIRMWARE-UPDATER / identity
  protocol, NOT LED control.** They sit among "Update complete"/"Patch error sysex" strings and are
  consumed by the patch up/download handler at flash 0x1401ba00 (file 0x0ba00). No byte in the fw
  ever does `cmp #0xf0/#0x11/#0x0c` for an LED command. The real LED control is internal
  (packed code + a HAL), and the host(amp)/RJ45 LED path uses Line6's serial protocol, not raw MIDI.
- The actual **LED color storage is RAM array 0x10001bc4** (1 byte per LED, 14 LEDs, index 0..0x0d).

### Unknown 1(b) — LED command format  (CONFIDENCE: HIGH for the internal model; the over-the-wire
### host SysEx/serial framing is NOT statically pinned)
The ground-truth LED model is the **LED-test encoding table at flash 0x14010dd0 (file 0x00dd0)**,
35 entries of {char* name; u32 code}. Decoded (low byte = LED index, next byte = color channel):
  code = (color_channel << 8) | led_index
  - color_channel: 0x00=Red, 0x01=Green, 0x02=Blue (0x08 used by the "All Off" pseudo-entry)
  - led_index (0..0x0d): FS1..FS5 = 0,1,2,3,4 ; ToneA..ToneD (FSA-D) = 5,6,7,8 ;
    PedalVolume=9, PedalWah=0x0a, TapTempo=0x0b, FUNC=0x0c, Diagnostic=0x0d ; 0x0e = ALL.
Examples (verified bytes): "FS1 Red"={idx0,col0}, "FS1 Green"={idx0,col1}, "FS1 Blue"={idx0,col2},
  "FUNC Red"={idx0x0c,col0}, "FSA Red"={idx5,col0}, "All Off"={idx0x0e,col8}.
A second human-facing model is the console table at 0x14010580: every LED (FUNC, FS1-5, ToneA-D)
has EIGHT color channels named R,G,B,W,T,Y,P,O (so the panel LEDs are RGB driven to named colors;
W/T/Y/P/O = preset white/teal/yellow/purple/orange palette intensities). 14 physical controls/LEDs
total (control/index table at flash 0x14010880: Func,FS1-5,ToneA-D,TapTempo,PedalSW,BankUp/Dn).
Color-name strings live at file 0x00c10+ ("All Off","FUNC Red",...,"FSD Blue").
OPEN: the exact bytes a host (amp over RJ45) sends to set an LED color are NOT in the image as a
decodable SysEx; that path is Line6's proprietary serial protocol parsed by RAM-resident state
functions (see Unknown 2/3). USB-side, inbound SysEx is dispatched to a RAM state machine whose
sub-command bytes can't be fully read statically. **Needs the PacketLogger USB capture to confirm
the real LED-set message bytes.**

### Unknown 2 — the SysEx/host -> LED handler to reuse  (CONFIDENCE: HIGH for the HAL)
The reusable LED writer is a small HAL. **Core entry: flash 0x14018bcc (file 0x08bcc).**
  Calling convention: r0 = LED index (0..0x0d), r1 = color/intensity byte. Validates idx<=0x0d,
  takes the LED mutex (ROM 0x13fa5400 on obj 0x10001b08), does `strb r1, [0x10001bc4 + idx]`
  (write color byte), `str 0, [0x10001b78 + idx*4]` (clear blink), releases (ROM 0x13fa54b4). No
  return value needed.
Related HAL fns:
  - 0x14018c00 (file 0x08c00) "set ALL LEDs": loops idx 0..0xd calling 0x14018bcc(idx, r0). (used by
    "All Off".)
  - 0x14018c34 (file 0x08c34): writes byte array 0x10001e24[idx] (LED attribute/mode).
  - 0x14018c58 (file 0x08c58): writes byte array 0x10001b64[idx].
  - 0x14018c94 (file 0x08c94): PWM/brightness: val*1000/0x858/2 -> dword 0x10001bd4[idx*4].
The "select an LED+color and set it" front door is **0x140195a8 (file 0x095a8)**: r0 = menu index
into the 0x14010dd0 table, r1 = value; it reads [entry+4]=led_index, [entry+5]=color, validates,
then calls 0x14018c34(color) and tail-calls 0x14018bcc(led_index, value).
NON-diagnostic callers of 0x14018bcc (the real control logic, found by encoding-matching every
BL/B.W in the image): 0x1401c3c0 (file 0x0c3c0) processes a received command buffer of 10-byte
records, maps record[0] via flash table 0x140111b4 (id->ledindex: 0e 0e 05 06 07 08 04 02 03 0b 01
00 0c ...) and calls 0x14018bcc; and 0x1401c690-ish switch-state logic ending `b.w 0x14018bcc`.
=> To "reuse the existing handler", the cleanest target is **0x14018bcc(r0=index,r1=color)** or the
table-driven 0x140195a8. The full host-SysEx->these-calls glue runs in RAM state fns (not in flash),
so we can't reuse a single "parse SysEx then set LED" flash function; instead the patch should call
0x14018bcc directly with index+color extracted from the inbound message.

### Unknown 3 — where inbound USB MIDI is received / dropped  (CONFIDENCE: MED-HIGH)
The USB stack + RTOS live in a SEPARATE ROM at 0x13f9xxxx-0x13faxxxx (NOT in this image); the app
registers buffers/calls into it. USB-MIDI descriptors (file 0x0dfe9-0x0e060) define OUT endpoint
**0x05** (host->device, embedded IN jack id=1) and IN endpoint 0x85.
The inbound chain that DOES exist in flash:
  1. **0x1401b494 (file 0x0b494)** = USB-OUT(ep5) reader: loops `movs r0,#5; movs r2,#1;
     bl 0x13fa2db4` (ROM ep-read 1 byte from endpoint 0x05) into a stack buf; once 4 bytes
     collected -> `bl 0x1401cd7c`.
  2. **0x1401cd7c (file 0x0cd7c)** = pushes each received 4-byte USB-MIDI event word into queue
     obj **0x10003d04** (ROM 0x13fa53b4), signals 0x10003d1c.
  3. **0x1401c910 (file 0x0c910)** = consumer task: pops 4-byte packets from 0x10003d04, then
     `and r3, pkt, #0xf; subs r3,#4; cmp r3,#3; tbb` -> **only CIN 4,5,6,7 (SysEx) are handled;
     any other CIN (CC=0xB, Note=0x8/0x9, PgmChange=0xC, etc.) falls through and is DISCARDED.**
     For SysEx packets it calls 0x1401c8ac per data byte.
  4. **0x1401c8ac (file 0x0c8ac)** = enqueues each inbound SysEx byte into queue **0x10004cd8**.
  5. **0x1401b714 (file 0x0b714)** = inbound-SysEx parser task: inits a state-machine object at
     RAM 0x10003b04 (initial state fn 0x10083689), then loops `bl 0x1401cdb4` (get next byte from
     0x10004cd8, file 0x0cdb4) and feeds it to the state machine (ROM driver 0x13fa52e0).
  6. **0x1401b740 (file 0x0b740)** = one SysEx state: dispatches on the sub-command byte
     (cases 0,1,2,6,9,0x5a,0x7a,0x7b,0xf0) returning RAM-resident next-state fns (0x10083xxx).

So inbound USB MIDI is dropped in TWO senses:
  (a) **Non-SysEx USB MIDI (CC/Note/PgmChange) is explicitly discarded** at the CIN switch in
      0x1401c910 — confirms the "USB is outbound-only / inbound CC ignored" reports. Echoing a CC
      back to light an LED CANNOT work (matches established conclusion).
  (b) Inbound USB **SysEx** IS piped into a SysEx state-machine parser. Whether that parser actually
      drives LEDs (it shares structure with the updater/identity parser) is NOT determinable
      statically because the state handlers execute from RAM (region 0x10083xxx-0x10084xxx; their
      flash source/relocation wasn't located — no simple (src,dst,len) .data copy descriptor found).

CONTROL PATH for the patch: the simplest in-place hook is to overwrite the CIN-discard branch in
**0x1401c910** (or its 0x1401c8ac call) so that inbound USB-MIDI packets carrying our LED command
get decoded to (index,color) and call **0x14018bcc** directly — i.e. don't rely on the opaque
RAM SysEx state machine at all. This stays entirely in programmed .text.

### What could NOT be determined statically (needs the PacketLogger USB capture)
1. The exact LED-set message BYTES a real host sends (USB or RJ45). The decodable templates are
   updater/identity only; the LED-set framing is either Line6 serial (RJ45) or a SysEx whose
   sub-command is handled by RAM-resident state code we can't read.
2. Whether the inbound USB RX reader task (0x1401b494) and SysEx parser task (0x1401b714) are
   actually CREATED/RUNNING. Their entry addresses appear NOWHERE as literals/movw-movt in the
   statically-recovered code (neither does the known-good TX pump 0x1401cc90), so the RTOS task
   table is built by means the static sweep can't see — can't prove the inbound tasks run.
3. The internal logic + recognized sub-commands of the inbound SysEx state machine (RAM fns at
   0x10083xxx/0x10084xxx).
A PacketLogger capture of FBV Control doing an LED action will give (1) directly and, by testing
`sendmidi` of that message vs LED response on stock fw, will indirectly answer (2)/(3).

### Key addresses (flash / file offset)
LED HAL:      set-color 0x14018bcc/0x08bcc(r0=idx0-0xd,r1=color) ; set-all 0x14018c00/0x08c00 ;
              attrB 0x14018c34/0x08c34 ; arrC 0x14018c58/0x08c58 ; pwm 0x14018c94/0x08c94.
LED tables:   encoding 0x14010dd0/0x00dd0 (code=(color<<8)|index) ; control/index 0x14010880/0x00880;
              console (name,RAMfn) 0x14010580/0x00580 ; id->ledindex map 0x140111b4/0x011b4.
LED setter front door: 0x140195a8/0x095a8. Protocol-buf->LED: 0x1401c3c0/0x0c3c0.
USB inbound:  ep5 reader 0x1401b494/0x0b494 ; pkt->queue 0x1401cd7c/0x0cd7c ;
              pkt consumer (CIN switch, drops non-SysEx) 0x1401c910/0x0c910 ;
              sysex-byte enqueue 0x1401c8ac/0x0c8ac ; get-sysex-byte 0x1401cdb4/0x0cdb4 ;
              sysex parser task 0x1401b714/0x0b714 ; sysex state dispatch 0x1401b740/0x0b740.
USB outbound (works): TX pump ep0x85 0x1401cc90/0x0cc90 ; MIDIbyte->USBpkt 0x1401c850/0x0c850 ;
              TX enqueue 0x1401c988/0x0c988 ; CC builder 0x1401c4cc/0x0c4cc.
Updater SysEx (NOT LEDs): patch handler 0x1401ba00/0x0ba00.
RAM:          LED color array 0x10001bc4 (1B/LED) ; LED mutex obj 0x10001b08 ;
              LED pwm 0x10001bd4 (4B/LED) ; inbound 4B-pkt queue 0x10003d04 ;
              inbound sysex-byte queue 0x10004cd8 ; sysex parser state obj 0x10003b04.
ROM (not in image, 0x13faxxxx): ep-read 0x13fa2db4 ; ep-write 0x13fa2e74 ; queue
              empty/push/pop 0x13fa5370/0x13fa53b4/0x13fa5398 ; mutex 0x13fa5400/0x13fa54b4 ;
              sem 0x13fa5592/0x13fa553e ; sm-init 0x13fa529c, sm-drive 0x13fa52e0 ; printf 0x13fa137c.

---

## Live device findings (2026-05-31, via MIDI Monitor + sendmidi)

- "FBV 3" enumerates as BOTH a CoreMIDI source AND destination (Mac can send to it).
- FBV Control configures the pedal over a NON-MIDI USB interface: with MIDI Monitor "spy on output"
  ON, changing assignments produces NOTHING outbound to FBV 3 (only the pedal's own status comes
  back). So Line6's editor never uses USB-MIDI; no USB-MIDI handshake/host-emulation shortcut exists.
- Pedal emits `F0 00 01 0C 11 03 07 00 F7` out USB-MIDI on each config change (a status/ack, not LED).
- Footswitch presses send CC (e.g. CC112=127, CC113=127 on ch1) — confirms MIDI-out works.
- **INBOUND USB SysEx IS ALIVE in normal mode** (de-risks the patch): sending the standard MIDI
  Identity Request `F0 7E 7F 06 01 F7` -> reply `F0 7E 7F 06 02 00 01 0C 11 00 03 00 00 00 04 04 F7`
  (Line6 mfr 00 01 0C, family 0x11, model 0x03). Sending `F0 00 01 0C 11 03 07 00 F7` -> version
  dump: `...11 03 7E 7F 06 02` + ASCII "L6ImageType:main / L6Version:1.0.2.0.0 / L6ImageType:
  bootloader / L6Version:1.0.0.0.0". So the USB RX + SysEx parser tasks DO run. (Open Q2 answered.)

## Patch build (2026-05-31): LED-via-CC — candidate `~/Downloads/Fbv3_ledcc_v1.hxf`

Design: repurpose the inbound Control Change packets (currently dropped by the CIN switch at
0x1401c910, CIN 0xB) so that a CC sets an LED. CC number -> LED index, CC value -> color byte;
call the LED HAL 0x14018bcc(r0=idx, r1=color) directly (no reliance on the RAM SysEx parser).
A CC is a single 4-byte USB-MIDI packet (no SysEx reassembly needed). To drive after flashing:
`sendmidi dev "FBV 3" cc <ledindex 0-13> <color 0=R/1=G/2=B>` (e.g. `cc 0 1` = FS1 green).

Code cave: factory-test literal pool at flash 0x14019b70 / file 0x09b70 (32 bytes, between a
`pop {pc}`/nop and the next fn -> never executed as code; only our detour reaches it; the test
routine that referenced these literals is end-user-unreachable). Overwrote 'Buttons test:' pool.

Two edits, 34 bytes total (verified by capstone round-trip + container re-verify):
- Detour @ file 0x0c942 / flash 0x1401c942: `str r5,[sp,#4]; cmp r3,#3` (01 95 03 2b) ->
  `b.w 0x14019b70` (fd f7 15 b9). (r3=CIN-4 and r5=packet are already set at 0x1401c940.)
- Handler @ flash 0x14019b70 (30 bytes):
    str r5,[sp,#4] ; cmp r3,#3 ; bls.w 0x1401c948  (SysEx -> original tbb dispatch)
    cmp r3,#7      ; bne.w 0x1401c912 (not CC -> drop/loop)
    ubfx r0,r5,#16,#8 (cc#->idx) ; ubfx r1,r5,#24,#8 (val->color)
    bl 0x14018bcc  ; b.w 0x1401c912 (loop)
Container: hdr[:104] + zlib(lvl9, 78da); HEAD size@36=57498, md5@40:56=md5(decomp), datalen@100,
FORM@4. Verified: decompresses to 57498, md5 matches, exactly 34 bytes differ from original.
Build scripts: /tmp/fbv_build_patch.py (assemble+verify), /tmp/fbv_make_hxf.py (container).

NOT YET FLASHED. Open risk to confirm at test: firmware may periodically recompute the LED color
array 0x10001bc4 and clobber a single CC-set value (then LED won't "stick" -> would need to also
patch the refresh, or resend). Recovery if bricked: hold FS1+A, plug USB -> Update Mode -> reflash
Fbv3_v1_02_00.hxf.

## RESULT (2026-05-31): SUCCESS — full color confirmed on device

- v1 flashed & booted: CC sets an LED and it STICKS steady (no repaint clobber). But v1 sets only
  the on/blink byte -> all LEDs RED (value 1=steady, 2-4=blink, 0/5+=off). Confirmed the mechanism.
- v2 (`~/Downloads/Fbv3_ledcc_v2.hxf`, build script /tmp/fbv_v2.py) flashed & booted: FULL COLOR.
  v2 handler (46B at cave 0x14019b70, detour same as v1) calls 0x14018c34(idx, value&7) [color ->
  0x10001e24] then 0x14018bcc(idx, value>>3) [on/blink -> 0x10001bc4]. CC value = state*8 + color.
  CONFIRMED COLOR MAP: 0=red 1=green 2=blue 3=cyan 4=yellow 5=pink 6=orange 7=white. state 0=off,
  1=steady(8-15), 2+=blink(16+). Drive: `sendmidi dev "FBV 3" cc <idx 0-13> <value>`.
  Verified live: FS1=red FS2=green FS3=blue FS4=cyan FS5=yellow ToneA=pink ToneB=orange ToneC=white.
- Success-marker option: version string "1.0.2.0.0" at file 0x002ac/flash 0x140102ac (9 bytes,
  in-place same-length edit; reported via SysEx identity F0 00 01 0C 11 03 07 00 F7 query).
