#!/usr/bin/env python3
"""
Build the patched Line 6 FBV3 (MK3) firmware that adds USB LED control.

Input : firmware/Fbv3_v1_02_00.hxf   (stock Line 6 firmware, v1.02.00)
Output: firmware/Fbv3_ledcc_v5.hxf   (patched: USB MIDI CC -> footswitch LED color,
                                       with inverted switch LEDs)

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

Plus an inverted footswitch-LED behavior: the LED is lit (in its USB-set color)
when the switch is NOT pressed, and dark while it IS pressed (momentary).

Mechanism (all edits land in already-programmed .text; image size is unchanged):
  * Detour at flash 0x1401c942 (file 0x0c942): the 4 bytes `str r5,[sp,#4];
    cmp r3,#3` are replaced with `b.w 0x14019b70`.
  * A 46-byte CC handler is written into a dead literal pool inside the factory
    self-test routine at flash 0x14019b70 (file 0x09b70) -- never executed as
    code, only reached via our detour. It preserves the SysEx path, and for a
    CC calls 0x14018c34(idx,color) then 0x14018bcc(idx,state).
  * Inverted switch LED: the switch-event handler's tail-call that sets the LED
    on/off from the switch state (flash 0x1401c712 `b.w 0x14018bcc`) is
    redirected to a 10-byte stub at flash 0x14019b9e (in the same sacrificed
    self-test body, right after the CC handler). The stub flips the state
    (`clz r1,r1; lsrs r1,r1,#5` -> 1 if released/0, else 0) and tail-calls
    0x14018bcc. So pressed=off, released=on. (The CC-set color persists.)
  * One-byte version-marker bump: "1.0.2.0.0" -> "1.0.2.0.1" at file 0x002ac.

The .hxf is an IFF container: header[:104] + zlib(level 9) of the 57498-byte
image. We rebuild it and fix HEAD decompressed-size@36, HEAD MD5@40:56,
data-chunk length@100, and FORM size@4 (the device verifies the decompressed
MD5 on boot).
"""
import os, struct, zlib, hashlib, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "firmware", "Fbv3_v1_02_00.hxf")
DST  = os.path.join(ROOT, "firmware", "Fbv3_ledcc_v5.hxf")

IMAGE_LEN  = 57498
CAVE       = 0x14019b70   # CC handler location (flash); file off = flash - 0x14010000
HOOK_FOFF  = 0x0c942      # CC-handler detour site (file offset)
CAVE_FOFF  = 0x09b70      # CC handler site (file offset)
STUB       = 0x14019b9e   # invert stub location (flash), right after the 46B CC handler
STUB_FOFF  = 0x09b9e      # invert stub site (file offset)
SWLED_FOFF = 0x0c712      # switch-event LED tail-call (file offset); stock = b.w 0x14018bcc
LED_ONOFF  = 0x14018bcc   # HAL: set LED on/blink state -> 0x10001bc4[idx]
VER_FOFF   = 0x002b4      # last byte of "1.0.2.0.0"


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


LS, NE = 9, 1


def build_handler():
    c = CAVE
    return (
        bytes.fromhex("0195")              # str  r5,[sp,#4]      (replicate overwritten)
        + bytes.fromhex("032b")            # cmp  r3,#3
        + bcc_w(c + 4, 0x1401c948, LS)     # bls.w 0x1401c948     SysEx -> original dispatch
        + bytes.fromhex("072b")            # cmp  r3,#7           CC?  (CIN 0xB -> r3=7)
        + bcc_w(c + 10, 0x1401c912, NE)    # bne.w 0x1401c912     not CC -> drop/loop
        + bytes.fromhex("c5f30744")        # ubfx r4,r5,#16,#8    r4 = CC number  (LED idx)
        + bytes.fromhex("c5f30766")        # ubfx r6,r5,#24,#8    r6 = CC value
        + bytes.fromhex("06f00701")        # and  r1,r6,#7        r1 = color = value & 7
        + bytes.fromhex("2046")            # mov  r0,r4
        + b_t4(c + 28, 0x14018c34, True)   # bl   0x14018c34      set color  -> 0x10001e24[idx]
        + bytes.fromhex("2046")            # mov  r0,r4
        + bytes.fromhex("c6f3c401")        # ubfx r1,r6,#3,#5     r1 = state = value >> 3
        + b_t4(c + 38, 0x14018bcc, True)   # bl   0x14018bcc      set on/blink -> 0x10001bc4[idx]
        + b_t4(c + 42, 0x1401c912, False)  # b.w  0x1401c912      loop
    )


def build_invert_stub():
    s = STUB
    return (
        bytes.fromhex("b1fa81f1")          # clz  r1, r1          32 if state==0(released), else <=31
        + bytes.fromhex("4909")            # lsrs r1, r1, #5      -> 1 if released, 0 if pressed
        + b_t4(s + 6, LED_ONOFF, False)    # b.w  0x14018bcc      set LED on/off (tail-call)
    )


def main():
    if not os.path.exists(SRC):
        sys.exit(f"missing stock firmware: {SRC}\n"
                 f"Place your Line 6 'Fbv3_v1_02_00.hxf' there (see README).")
    raw = open(SRC, "rb").read()
    img = bytearray(zlib.decompress(raw[104:]))
    assert len(img) == IMAGE_LEN, f"unexpected image size {len(img)}"

    handler = build_handler()
    stub = build_invert_stub()
    img[CAVE_FOFF:CAVE_FOFF + len(handler)] = handler             # CC handler
    img[HOOK_FOFF:HOOK_FOFF + 4] = b_t4(0x1401c942, CAVE, False)  # CC-handler detour
    img[STUB_FOFF:STUB_FOFF + len(stub)] = stub                  # invert stub
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

    # optional disassembly check
    try:
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        print("  CC handler disassembly:")
        for i in md.disasm(handler, CAVE):
            print(f"    0x{i.address:08x}: {i.mnemonic}\t{i.op_str}")
        print("  invert stub disassembly:")
        for i in md.disasm(stub, STUB):
            print(f"    0x{i.address:08x}: {i.mnemonic}\t{i.op_str}")
    except ImportError:
        print("  (install 'capstone' to also disassemble-verify the patch)")
    if not ok:
        sys.exit("VERIFICATION FAILED")


if __name__ == "__main__":
    main()
