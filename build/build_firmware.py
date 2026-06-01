#!/usr/bin/env python3
"""
Build the patched Line 6 FBV3 (MK3) firmware that adds USB LED control.

Input : firmware/Fbv3_v1_02_00.hxf   (stock Line 6 firmware, v1.02.00)
Output: firmware/Fbv3_ledcc_v7.hxf   (patched: USB MIDI CC -> footswitch LED color,
                                       with a switchable LED behavior mode)

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

CC #16 is a reserved "mode" command (a global flag in RAM at 0x10001e32):
    cc 16 0   inverted mode (DEFAULT): footswitch LED lit (in its USB-set color)
              when NOT pressed, dark while pressed.
    cc 16 1   stock mode: footswitch LED off at rest, lit (in its USB-set color)
              only while the switch is pressed.
The flag lives in RAM, so it resets to inverted (0) on power-up; the host should
resend `cc 16 1` on connect if stock mode is wanted.

Mechanism (all edits land in already-programmed .text; image size is unchanged):
  * Detour at flash 0x1401c942 (file 0x0c942): the 4 bytes `str r5,[sp,#4];
    cmp r3,#3` are replaced with `b.w 0x14019b70`.
  * A CC handler (0x48 bytes) is written into a dead literal pool + body inside
    the factory self-test routine at flash 0x14019b70 (file 0x09b70) -- never
    executed as code, only reached via our detour. It preserves the SysEx path;
    intercepts CC #16 to write the mode flag; bounds-checks idx<=13; and for a
    normal CC calls 0x14018c34(idx,color) then 0x14018bcc(idx,state).
  * Mode stub (0x1a bytes) at flash 0x14019bb8: the switch-event handler's LED
    tail-call (flash 0x1401c712 `b.w 0x14018bcc`) is redirected here. It reads
    the mode flag: flag==0 -> invert the switch state (clz/lsr) then set LED
    (inverted mode); flag!=0 -> pass the switch state straight through (stock
    mode). Either way it tail-calls 0x14018bcc.
  * One-byte version-marker bump: "1.0.2.0.0" -> "1.0.2.0.1" at file 0x002ac.

The .hxf is an IFF container: header[:104] + zlib(level 9) of the 57498-byte
image. We rebuild it and fix HEAD decompressed-size@36, HEAD MD5@40:56,
data-chunk length@100, and FORM size@4 (the device verifies the decompressed
MD5 on boot).
"""
import os, struct, zlib, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "firmware", "Fbv3_v1_02_00.hxf")
DST  = os.path.join(ROOT, "firmware", "Fbv3_ledcc_v7.hxf")

IMAGE_LEN  = 57498
BASE       = 0x14010000   # flash base: flash_addr = file_offset + BASE

CAVE       = 0x14019b70   # CC handler (flash)
CAVE_FOFF  = 0x09b70      #   "        (file offset)
STUB       = 0x14019bb8   # mode stub (flash) -- right after the 0x48-byte CC handler
STUB_FOFF  = 0x09bb8      #   "        (file offset)
HOOK_FOFF  = 0x0c942      # CC-handler detour site (file offset)
SWLED_FOFF = 0x0c712      # switch-event LED tail-call site (file offset)
VER_FOFF   = 0x002b4      # last byte of "1.0.2.0.0"

# firmware entry points / data we call or reference
SYSEX   = 0x1401c948      # original SysEx dispatch (tbb) in the inbound consumer
LOOP    = 0x1401c912      # inbound consumer loop top (return point)
SETCOL  = 0x14018c34      # HAL: set LED color    -> 0x10001e24[idx]
LED_ONOFF = 0x14018bcc    # HAL: set LED on/blink -> 0x10001bc4[idx]
FLAG    = 0x10001e32      # mode flag: unused tail of the 16-byte color-array slot

MODE_CC = 16              # CC number reserved for the mode command
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


def cbnz(pc, target, rn):
    """Encode Thumb CBNZ (forward only, 0..126)."""
    off = target - (pc + 4)
    assert 0 <= off <= 126 and off % 2 == 0, f"cbnz range {off}"
    i = (off >> 6) & 1; imm5 = (off >> 1) & 0x1F
    return struct.pack("<H", 0xB900 | (i << 9) | (imm5 << 3) | rn)


def movw(rd, imm):
    imm4 = (imm >> 12) & 0xF; i = (imm >> 11) & 1; imm3 = (imm >> 8) & 7; imm8 = imm & 0xFF
    return struct.pack("<HH", 0xF240 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)


def movt(rd, imm):
    imm4 = (imm >> 12) & 0xF; i = (imm >> 11) & 1; imm3 = (imm >> 8) & 7; imm8 = imm & 0xFF
    return struct.pack("<HH", 0xF2C0 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)


# ---- patch code ------------------------------------------------------------

def build_handler():
    """CC handler at CAVE. r3 = CIN-4, r5 = 4-byte USB-MIDI event word (already set
    by the inbound consumer at 0x1401c940). 0x48 bytes; ends at STUB."""
    c = CAVE
    L_normal = c + 0x2a                       # normal-CC path
    return (
        bytes.fromhex("0195")                 # str  r5,[sp,#4]   (replicate overwritten insn)
        + bytes.fromhex("032b")               # cmp  r3,#3
        + bcc_w(c + 0x04, SYSEX, LS)          # bls.w SYSEX       SysEx -> original dispatch
        + bytes.fromhex("072b")               # cmp  r3,#7        CC? (CIN 0xB -> r3=7)
        + bcc_w(c + 0x0a, LOOP, NE)           # bne.w LOOP        not CC -> drop/loop
        + bytes.fromhex("c5f30744")           # ubfx r4,r5,#16,#8  r4 = CC number (idx)
        + bytes.fromhex("c5f30766")           # ubfx r6,r5,#24,#8  r6 = CC value
        + bytes.fromhex("102c")               # cmp  r4,#16        mode command?
        + bcc_w(c + 0x18, L_normal, NE)       # bne.w .Lnormal
        + movw(2, FLAG & 0xFFFF)              # movw r2,#:lower16:FLAG
        + movt(2, (FLAG >> 16) & 0xFFFF)      # movt r2,#:upper16:FLAG
        + bytes.fromhex("1670")               # strb r6,[r2]       mode flag = value
        + b_t4(c + 0x26, LOOP, False)         # b.w  LOOP
        # .Lnormal (c+0x2a):
        + bytes.fromhex("0d2c")               # cmp  r4,#13        idx in range?
        + bcc_w(c + 0x2c, LOOP, HI)           # bhi.w LOOP         out of range -> drop
        + bytes.fromhex("06f00701")           # and  r1,r6,#7      r1 = color
        + bytes.fromhex("2046")               # mov  r0,r4
        + b_t4(c + 0x36, SETCOL, True)        # bl   SETCOL        set color
        + bytes.fromhex("2046")               # mov  r0,r4
        + bytes.fromhex("c6f3c401")           # ubfx r1,r6,#3,#5   r1 = state = value>>3
        + b_t4(c + 0x40, LED_ONOFF, True)     # bl   LED_ONOFF     set on/blink
        + b_t4(c + 0x44, LOOP, False)         # b.w  LOOP
    )


def build_mode_stub():
    """Mode stub at STUB. Entered from the switch handler with r0 = LED index,
    r1 = switch state. 0x1a bytes."""
    s = STUB
    L_stock = s + 0x16                        # stock-mode path
    return (
        movw(2, FLAG & 0xFFFF)                # movw r2,#:lower16:FLAG
        + movt(2, (FLAG >> 16) & 0xFFFF)      # movt r2,#:upper16:FLAG
        + bytes.fromhex("1378")               # ldrb r3,[r2]       r3 = mode flag
        + cbnz(s + 0x0a, L_stock, 3)          # cbnz r3,.Lstock    flag!=0 -> stock
        + bytes.fromhex("b1fa81f1")           # clz  r1,r1         } invert the
        + bytes.fromhex("4909")               # lsrs r1,r1,#5      } switch state
        + b_t4(s + 0x12, LED_ONOFF, False)    # b.w  LED_ONOFF     inverted: set LED
        # .Lstock (s+0x16):
        + b_t4(s + 0x16, LED_ONOFF, False)    # b.w  LED_ONOFF     stock: pass state through
    )


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing stock firmware: {SRC}\n"
                 f"Place your Line 6 'Fbv3_v1_02_00.hxf' there (see README).")
    raw = open(SRC, "rb").read()
    img = bytearray(zlib.decompress(raw[104:]))
    assert len(img) == IMAGE_LEN, f"unexpected image size {len(img)}"

    handler = build_handler()
    stub = build_mode_stub()
    assert len(handler) == 0x48, hex(len(handler))
    assert len(stub) == 0x1a, hex(len(stub))
    assert CAVE_FOFF + len(handler) == STUB_FOFF, "handler overruns stub"

    img[CAVE_FOFF:CAVE_FOFF + len(handler)] = handler             # CC handler
    img[STUB_FOFF:STUB_FOFF + len(stub)] = stub                  # mode stub
    img[HOOK_FOFF:HOOK_FOFF + 4] = b_t4(0x1401c942, CAVE, False)  # CC-handler detour
    # redirect the switch-event LED tail-call (stock: b.w 0x14018bcc) through the stub
    assert bytes(img[SWLED_FOFF:SWLED_FOFF + 4]) == b_t4(0x1401c712, LED_ONOFF, False), \
        "unexpected bytes at switch-LED tail-call; firmware not the expected v1.02.00"
    img[SWLED_FOFF:SWLED_FOFF + 4] = b_t4(0x1401c712, STUB, False)
    assert img[VER_FOFF] == ord("0")
    img[VER_FOFF] = ord("1")                                    # 1.0.2.0.0 -> 1.0.2.0.1
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
