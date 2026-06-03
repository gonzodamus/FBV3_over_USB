#!/usr/bin/env python3
"""
Build the patched Line 6 FBV3 (MK3) firmware that adds USB LED control.

Input : firmware/Fbv3_v1_02_00.hxf   (stock Line 6 firmware, v1.02.00)
Output: firmware/Fbv3_Chroma_1.1.hxf (patched: USB MIDI CC -> footswitch LED color,
                                       with a switchable LED behavior mode; boots as
                                       "FBV Chroma 1.1")

WHAT THE PATCH DOES
-------------------
Stock firmware drops all inbound USB MIDI except SysEx. We repurpose inbound
Control Change messages so that a CC sets a footswitch LED's color/state:

    CC number  -> LED index   (FS1-5=0-4, ToneA-D=5-8, PedalVol=9, Wah=10,
                               Tap=11, FUNC=12, Diag=13)
    CC value   -> state*8 + color
                   color (low 3 bits): 0 red, 1 green, 2 blue, 3 cyan,
                                       4 yellow, 5 pink, 6 orange, 7 white
                   state (value>>3):   0 off, 1 steady (8-15), 2+ blink (16+)

CC #16 is a reserved "behavior" command that sets, PER LED, how a switch-driven
LED reacts to its footswitch (color still comes from the per-LED CCs above):

    cc 16 value   ,  value = ledIndex*4 + behavior   (ledIndex 0..13, beh 0..3)
        behavior 0  on at rest (inverted, DEFAULT): lit when NOT pressed
        behavior 1  on when pressed (stock): lit only while pressed
        behavior 2  always on
        behavior 3  always off

The behavior bits live in RAM (2 bits/LED), so every LED resets to 0 (on at
rest) on power-up -- i.e. a fresh boot behaves exactly like the unpatched build.
The host re-sends the desired per-LED behavior on connect.

Mechanism (all edits land in already-programmed .text; image size is unchanged):
  * Detour at flash 0x1401c942 (file 0x0c942): the 4 bytes `str r5,[sp,#4];
    cmp r3,#3` are replaced with `b.w 0x14019b70`.
  * A CC handler (0x78 bytes) is written into a dead literal pool + body inside
    the factory self-test routine at flash 0x14019b70 (file 0x09b70) -- never
    executed as code (the routine has no callers), only reached via our detour.
    It preserves the SysEx path; for CC #16 it decodes idx+behavior, writes that
    LED's 2 behavior bits, and applies the new rest state immediately; for a
    normal CC it bounds-checks idx<=13 and calls 0x14018c34(idx,color) then
    0x14018bcc(idx,state).
  * Mode stub (0x34 bytes) right after the handler: the switch-event handler's
    LED tail-call (flash 0x1401c712 `b.w 0x14018bcc`) is redirected here. It
    reads this LED's 2 behavior bits and computes the on/off byte branchlessly:
    out = (sw & ~b1) ^ ~b0  (sw = switch state), giving inverted / stock /
    always-on / always-off for behavior 0 / 1 / 2 / 3. It tail-calls 0x14018bcc.

Per-LED behavior storage: 2 bits/LED in two 16-bit fields placed in proven-free,
zero-at-boot .bss padding -- the unused tails of two 14-byte LED arrays
(0x10001e32 for idx 0..7, 0x10001bd2 for idx 8..15). The low .bss has no free
contiguous 4-byte word (every 4-aligned slot is an array/struct element), but
these odd-length-array tails are never indexed and are zeroed at boot.
  * LCD boot banner "Fbv 3 v1.02.00" -> "FBV Chroma 1.1" (file 0x00260), and the
    SysEx version field "1.0.2.0.0" -> "1.1.0.0.0" (file 0x002ac), which the Line 6
    Updater shows as 1.10.00.

The .hxf is an IFF container: header[:104] + zlib(level 9) of the 57498-byte
image. We rebuild it and fix HEAD decompressed-size@36, HEAD MD5@40:56,
data-chunk length@100, and FORM size@4 (the device verifies the decompressed
MD5 on boot).
"""
import os, struct, zlib, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "firmware", "Fbv3_v1_02_00.hxf")
DST  = os.path.join(ROOT, "firmware", "Fbv3_Chroma_1.1.hxf")

IMAGE_LEN  = 57498
BASE       = 0x14010000   # flash base: flash_addr = file_offset + BASE

CAVE       = 0x14019b70   # CC handler (flash); the mode stub follows immediately
CAVE_FOFF  = 0x09b70      #   "        (file offset)
CAVE_END   = 0x09c34      # end (exclusive) of the dead self-test fn we may overwrite:
                          #   the fn body + its pools + trailing nop, no live callers
HOOK_FOFF  = 0x0c942      # CC-handler detour site (file offset)
SWLED_FOFF = 0x0c712      # switch-event LED tail-call site (file offset)

# Branding / version strings (both fixed-size, edited in place).
LCD_FOFF   = 0x00260      # 14-byte LCD boot banner slot
LCD_OLD    = b"Fbv 3 v1.02.00"   # stock banner (sanity-checked before overwrite)
LCD_NEW    = b"FBV Chroma 1.1"   # 14 bytes, same length
VERSTR_FOFF = 0x002ac     # the "1.0.2.0.0" digits inside "L6Version:..." (9 bytes)
VERSTR_OLD = b"1.0.2.0.0"        # stock version field
VERSTR_NEW = b"1.1.0.0.0"        # Line 6 Updater collapses A.B.C.D.E -> A.BC.DE = 1.10.00

# firmware entry points / data we call or reference
SYSEX   = 0x1401c948      # original SysEx dispatch (tbb) in the inbound consumer
LOOP    = 0x1401c912      # inbound consumer loop top (return point)
SETCOL  = 0x14018c34      # HAL: set LED color    -> 0x10001e24[idx]
LED_ONOFF = 0x14018bcc    # HAL: set LED on/blink -> 0x10001bc4[idx]
# Per-LED behavior: 2 bits/LED in two 16-bit fields living in proven-free,
# zero-at-boot .bss padding (the unused tails of two 14-byte LED arrays).
BEH_A   = 0x10001e32      # behavior bits for LED idx 0..7  (colorattr-array tail)
BEH_B   = 0x10001bd2      # behavior bits for LED idx 8..15 (onblink-array tail)
                          # (both share upper half 0x1000, so one movt covers both)

MODE_CC = 16              # CC number reserved for the per-LED behavior command
LS, NE, HI = 9, 1, 8      # Thumb condition codes


# ---- Thumb-2 encoders ------------------------------------------------------

def b_t4(pc, target, is_bl):
    """Encode Thumb-2 BL (is_bl=True) or B.W (T4) from instr addr `pc` to `target`."""
    off = target - (pc + 4)
    o = off & 0x1FFFFFF
    S = (o >> 24) & 1; I1 = (o >> 23) & 1; I2 = (o >> 22) & 1
    imm10 = (o >> 12) & 0x3FF; imm11 = (o >> 1) & 0x7FF
    J1 = ((~I1) & 1) ^ S; J2 = ((~I2) & 1) ^ S
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = (0xD000 if is_bl else 0x9000) | (J1 << 13) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def bcc_w(pc, target, cond):
    """Encode Thumb-2 conditional B<c>.W (T3) from instr addr `pc` to `target`."""
    off = target - (pc + 4)
    o = off & 0x1FFFFF
    S = (o >> 20) & 1; J2 = (o >> 19) & 1; J1 = (o >> 18) & 1
    imm6 = (o >> 12) & 0x3F; imm11 = (o >> 1) & 0x7FF
    hw1 = 0xF000 | (S << 10) | (cond << 6) | imm6
    hw2 = 0x8000 | (J1 << 13) | (J2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def movw(rd, imm):
    imm4 = (imm >> 12) & 0xF; i = (imm >> 11) & 1; imm3 = (imm >> 8) & 7; imm8 = imm & 0xFF
    return struct.pack("<HH", 0xF240 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)


def movt(rd, imm):
    imm4 = (imm >> 12) & 0xF; i = (imm >> 11) & 1; imm3 = (imm >> 8) & 7; imm8 = imm & 0xFF
    return struct.pack("<HH", 0xF2C0 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)


# ---- patch code ------------------------------------------------------------

def assemble(base, items):
    """Two-pass assembler so internal branches resolve from live offsets.

    Each item is one of:
      ("raw", hexstr)      pre-encoded bytes (verified with capstone)
      ("movw"/"movt", rd, imm)
      ("b",   target, is_bl)   BL/B.W   via b_t4
      ("bcc", target, cond)    B<c>.W   via bcc_w
      ("label", name)          zero-size marker
    `target` is an int flash address or a label name (str)."""
    def size(it):
        if it[0] == "raw":   return len(bytes.fromhex(it[1]))
        if it[0] == "label": return 0
        return 4
    labels, off = {}, 0
    for it in items:                          # pass 1: label offsets
        if it[0] == "label": labels[it[1]] = base + off
        off += size(it)
    buf, off = bytearray(), 0                  # pass 2: emit
    for it in items:
        pc = base + off
        if   it[0] == "raw":   buf += bytes.fromhex(it[1])
        elif it[0] == "movw":  buf += movw(it[1], it[2])
        elif it[0] == "movt":  buf += movt(it[1], it[2])
        elif it[0] == "b":     buf += b_t4(pc, labels.get(it[1], it[1]), it[2])
        elif it[0] == "bcc":   buf += bcc_w(pc, labels.get(it[1], it[1]), it[2])
        off += size(it)
    return bytes(buf)


def build_handler(cave):
    """CC handler at `cave`. r3 = CIN-4, r5 = 4-byte USB-MIDI event word (already
    set by the inbound consumer at 0x1401c940). The mode stub follows it."""
    return assemble(cave, [
        ("raw", "0195"),                  # str  r5,[sp,#4]    replicate overwritten insn
        ("raw", "032b"),                  # cmp  r3,#3
        ("bcc", SYSEX, LS),               # bls.w SYSEX        SysEx -> original dispatch
        ("raw", "072b"),                  # cmp  r3,#7         CC? (CIN 0xB -> r3=7)
        ("bcc", LOOP, NE),                # bne.w LOOP         not CC -> drop/loop
        ("raw", "c5f30744"),              # ubfx r4,r5,#16,#8  r4 = CC number (idx)
        ("raw", "c5f30766"),              # ubfx r6,r5,#24,#8  r6 = CC value
        ("raw", "102c"),                  # cmp  r4,#16        behavior command?
        ("bcc", "Lnormal", NE),           # bne.w .Lnormal
        # ---- CC #16: set this LED's 2 behavior bits (value = idx*4 + behavior) ----
        ("raw", "c6f38300"),              # ubfx r0,r6,#2,#4   r0 = idx = value>>2 (0..15)
        ("raw", "0728"),                  # cmp  r0,#7         } base = BEH_A if idx<=7
        ("raw", "94bf"),                  # ite  ls           }        else BEH_B
        ("movw", 2, BEH_A & 0xFFFF),      # movwls r2,#:lower16:BEH_A
        ("movw", 2, BEH_B & 0xFFFF),      # movwhi r2,#:lower16:BEH_B
        ("movt", 2, (BEH_A >> 16) & 0xFFFF),  # movt r2,#0x1000  (BEH_A,BEH_B share upper half)
        ("raw", "00f00703"),              # and  r3,r0,#7      } shift = (idx & 7) * 2
        ("raw", "5b00"),                  # lsls r3,r3,#1      }
        ("raw", "0325"),                  # movs r5,#3         } mask = 3 << shift
        ("raw", "9d40"),                  # lsls r5,r3         }
        ("raw", "1188"),                  # ldrh r1,[r2]       old field halfword
        ("raw", "21ea0501"),              # bic  r1,r1,r5      clear this LED's slot
        ("raw", "06f00305"),              # and  r5,r6,#3      } set slot = behavior
        ("raw", "9d40"),                  # lsls r5,r3         }   (behavior << shift)
        ("raw", "2943"),                  # orrs r1,r5         }
        ("raw", "1180"),                  # strh r1,[r2]       store field
        ("raw", "06f00101"),              # and  r1,r6,#1      } rest state = !(behavior & 1)
        ("raw", "81f00101"),              # eor  r1,r1,#1      }   (apply immediately)
        ("b", LED_ONOFF, True),           # bl   LED_ONOFF(idx, rest)
        ("b", LOOP, False),               # b.w  LOOP
        # ---- normal CC: set color + on/blink state ----
        ("label", "Lnormal"),
        ("raw", "0d2c"),                  # cmp  r4,#13        idx in range?
        ("bcc", LOOP, HI),                # bhi.w LOOP         out of range -> drop
        ("raw", "06f00701"),              # and  r1,r6,#7      r1 = color
        ("raw", "2046"),                  # mov  r0,r4
        ("b", SETCOL, True),              # bl   SETCOL        set color
        ("raw", "2046"),                  # mov  r0,r4
        ("raw", "c6f3c401"),              # ubfx r1,r6,#3,#5   r1 = state = value>>3
        ("b", LED_ONOFF, True),           # bl   LED_ONOFF     set on/blink
        ("b", LOOP, False),               # b.w  LOOP
    ])


def build_mode_stub(stub):
    """Mode stub at `stub`. Entered (tail-call, lr preserved) from the switch
    handler with r0 = LED index, r1 = switch state (0/1). Reads this LED's 2
    behavior bits and computes the on/off byte branchlessly:
        out = (sw & ~b1) ^ ~b0     -> inverted / stock / always-on / always-off
    for behavior 0 / 1 / 2 / 3. Tail-calls LED_ONOFF(idx, out). Uses only
    r1/r2/r3 (r0 preserved; no bl, so lr stays valid for the tail-call)."""
    return assemble(stub, [
        ("raw", "0728"),                  # cmp  r0,#7         } base = BEH_A if idx<=7
        ("raw", "94bf"),                  # ite  ls           }        else BEH_B
        ("movw", 2, BEH_A & 0xFFFF),      # movwls r2,#:lower16:BEH_A
        ("movw", 2, BEH_B & 0xFFFF),      # movwhi r2,#:lower16:BEH_B
        ("movt", 2, (BEH_A >> 16) & 0xFFFF),  # movt r2,#0x1000
        ("raw", "00f00703"),              # and  r3,r0,#7      } shift = (idx & 7) * 2
        ("raw", "5b00"),                  # lsls r3,r3,#1      }
        ("raw", "1288"),                  # ldrh r2,[r2]       field halfword
        ("raw", "da40"),                  # lsrs r2,r3         r2 >>= shift
        ("raw", "02f00302"),              # and  r2,r2,#3      r2 = behavior (0..3)
        ("raw", "5308"),                  # lsrs r3,r2,#1      } r3 = ~b1 (bit0)
        ("raw", "83f00103"),              # eor  r3,r3,#1      }
        ("raw", "1940"),                  # ands r1,r3         r1 = sw & ~b1
        ("raw", "02f00102"),              # and  r2,r2,#1      } r2 = ~b0
        ("raw", "82f00102"),              # eor  r2,r2,#1      }
        ("raw", "5140"),                  # eors r1,r2         r1 = out = (sw & ~b1) ^ ~b0
        ("b", LED_ONOFF, False),          # b.w  LED_ONOFF(idx, out)
    ])


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing stock firmware: {SRC}\n"
                 f"Place your Line 6 'Fbv3_v1_02_00.hxf' there (see README).")
    raw = open(SRC, "rb").read()
    img = bytearray(zlib.decompress(raw[104:]))
    assert len(img) == IMAGE_LEN, f"unexpected image size {len(img)}"

    handler = build_handler(CAVE)
    STUB      = CAVE + len(handler)        # mode stub follows the handler
    STUB_FOFF = CAVE_FOFF + len(handler)
    stub = build_mode_stub(STUB)
    assert CAVE_FOFF + len(handler) + len(stub) <= CAVE_END, \
        f"handler+stub ({len(handler)+len(stub)} bytes) overruns the dead self-test fn"

    img[CAVE_FOFF:CAVE_FOFF + len(handler)] = handler             # CC handler
    img[STUB_FOFF:STUB_FOFF + len(stub)] = stub                  # mode stub
    img[HOOK_FOFF:HOOK_FOFF + 4] = b_t4(0x1401c942, CAVE, False)  # CC-handler detour
    # redirect the switch-event LED tail-call (stock: b.w 0x14018bcc) through the stub
    assert bytes(img[SWLED_FOFF:SWLED_FOFF + 4]) == b_t4(0x1401c712, LED_ONOFF, False), \
        "unexpected bytes at switch-LED tail-call; firmware not the expected v1.02.00"
    img[SWLED_FOFF:SWLED_FOFF + 4] = b_t4(0x1401c712, STUB, False)
    # LCD boot banner (14-byte slot, same-length swap; terminator at +14 stays put)
    assert bytes(img[LCD_FOFF:LCD_FOFF + len(LCD_OLD)]) == LCD_OLD and img[LCD_FOFF + 14] == 0, \
        "unexpected LCD banner; firmware not the expected v1.02.00"
    assert len(LCD_NEW) == len(LCD_OLD) == 14
    img[LCD_FOFF:LCD_FOFF + 14] = LCD_NEW
    # version string in the SysEx identity field (Updater shows it as 1.10.00)
    assert bytes(img[VERSTR_FOFF:VERSTR_FOFF + len(VERSTR_OLD)]) == VERSTR_OLD
    assert len(VERSTR_NEW) == len(VERSTR_OLD)
    img[VERSTR_FOFF:VERSTR_FOFF + len(VERSTR_NEW)] = VERSTR_NEW
    img = bytes(img)
    assert len(img) == IMAGE_LEN

    comp = zlib.compress(img, 9)
    out = bytearray(raw[:104])
    out[36:40]  = struct.pack(">I", len(img))          # HEAD decompressed size
    out[40:56]  = hashlib.md5(img).digest()            # HEAD MD5 (of decompressed image)
    out += comp
    out[100:104] = struct.pack(">I", len(comp))        # data-chunk length
    out[4:8]     = struct.pack(">I", len(out) - 8)     # FORM size
    open(DST, "wb").write(out)

    # verify round-trip
    v = open(DST, "rb").read()
    vd = zlib.decompress(v[104:])
    ok = (vd == img and v[40:56] == hashlib.md5(vd).digest()
          and struct.unpack(">I", v[100:104])[0] == len(comp)
          and struct.unpack(">I", v[4:8])[0] == len(v) - 8)
    print(f"built {DST}")
    print(f"  decompressed size : {len(vd)}  md5 {hashlib.md5(vd).hexdigest()}")
    print(f"  version string    : {vd[0x2a2:0x2b5].decode()}")
    print(f"  container verified : {ok}")

    # values to mirror into webapp/patch.js (it hard-codes these, byte-for-byte)
    print("  webapp/patch.js mirror:")
    print(f"    handler.off 0x{CAVE_FOFF:05x}  hex {handler.hex()}")
    print(f"    stub.off    0x{STUB_FOFF:05x}  hex {stub.hex()}")
    print(f"    swled.hex   {b_t4(0x1401c712, STUB, False).hex()}  (expect {b_t4(0x1401c712, LED_ONOFF, False).hex()})")
    print(f"    EXPECT_MD5  {hashlib.md5(vd).hexdigest()}")

    # optional disassembly check + branch-boundary validation
    try:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        region = bytes(vd[CAVE_FOFF:STUB_FOFF + len(stub)])
        instrs = list(md.disasm(region, CAVE))
        addrs = {i.address for i in instrs}
        known = {SYSEX, LOOP, SETCOL, LED_ONOFF}
        bad = []
        print("  patch disassembly:")
        for i in instrs:
            print(f"    0x{i.address:08x}: {i.mnemonic}\t{i.op_str}")
            if i.op_str.startswith("#"):
                t = int(i.op_str[1:], 16)
                if t not in addrs and t not in known:
                    bad.append((i.address, t))
        if bad:
            ok = False
            for a, t in bad:
                print(f"  !! branch at 0x{a:08x} -> 0x{t:08x} not an instr boundary/known target")
    except ImportError:
        print("  (install 'capstone' to also disassemble-verify the patch)")
    if not ok:
        sys.exit("VERIFICATION FAILED")


if __name__ == "__main__":
    main()
