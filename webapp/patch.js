'use strict';

/* ----------------------------------------------------------------------------
 * In-browser firmware patcher: stock Line 6 FBV3 v1.02.00 .hxf -> FBV Chroma 1.2.
 *
 * Mirrors manual/build/build_firmware.py exactly (same offsets, same assembled Thumb-2
 * bytes). Runs entirely client-side; the user's firmware never leaves the page.
 *
 * The .hxf is an IFF container: header[:104] + zlib(deflate) of the 57498-byte
 * image. We decompress, patch bytes in place, recompress, and fix the four
 * header fields. The device verifies the *decompressed* MD5 on boot, so any
 * valid deflate stream works (ours need not match Line 6's byte-for-byte).
 *
 * Depends on md5.js (md5, md5hex) being loaded first, and on the browser's
 * native DecompressionStream/CompressionStream('deflate').
 * -------------------------------------------------------------------------- */

const IMAGE_LEN = 57498;

// Verified assembled patch bytes (identical to build_firmware.py output).
const PATCH = {
  // file offset -> hex bytes to write (after asserting the expected stock bytes)
  handler: { off: 0x09b70, hex: '0195032b42f2e886072b42f0ca86c5f30744c5f30766102c40f01f80c6f38300072894bf41f6326241f6d232c1f2000200f007035b0003259d40118821ea050106f003059d402943118006f0010181f00101fff703f802f0a4be0d2c02f2a18606f007012046fff72df82046c6f3c401fef7f4ff02f095be' },
  stub:    { off: 0x09be8, hex: '072894bf41f6326241f6d232c1f2000200f007035b001288da4002f00302530883f00103194002f0010282f001025140fef7d8bf' },
  detour:  { off: 0x0c942, hex: 'fdf715b9' },
  swled:   { off: 0x0c712, hex: 'fdf769ba', expect: 'fcf75bba' }, // redirect switch-LED call -> stub
};
// Same-length string edits (ASCII).
const LCD = { off: 0x00260, old: 'Fbv 3 v1.02.00', neu: 'FBV Chroma 1.2' }; // 14 bytes; terminator at +14
const VER = { off: 0x002ac, old: '1.0.2.0.0', neu: '1.2.0.0.0' };

// Known-good decompressed-image MD5 of the produced firmware (sanity target).
const EXPECT_MD5 = 'c7914e9dee0a05e83c18cc5873ebfc66';

const OUTPUT_NAME = 'Fbv3_Chroma_1.2.hxf';

function hexToBytes(h) {
  const a = new Uint8Array(h.length / 2);
  for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16);
  return a;
}
function ascii(s) { return new TextEncoder().encode(s); }

async function inflate(bytes) {
  const ds = new DecompressionStream('deflate');
  const stream = new Response(bytes).body.pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
async function deflate(bytes) {
  const cs = new CompressionStream('deflate');
  const stream = new Response(bytes).body.pipeThrough(cs);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function bytesEq(a, off, expected) {
  for (let i = 0; i < expected.length; i++) if (a[off + i] !== expected[i]) return false;
  return true;
}

/**
 * Patch a stock .hxf (Uint8Array). Returns { blob, name, md5, ok } or throws a
 * user-readable Error describing what didn't match.
 */
async function patchFirmware(hxfBytes) {
  if (hxfBytes.length < 105) throw new Error('That file is too small to be FBV3 firmware.');

  let img;
  try {
    img = await inflate(hxfBytes.subarray(104));
  } catch {
    throw new Error('Could not read that .hxf. Make sure it is the stock Line 6 FBV3 firmware file.');
  }
  if (img.length !== IMAGE_LEN) {
    throw new Error(
      `Unexpected firmware size (${img.length} bytes, expected ${IMAGE_LEN}). ` +
      'This patcher only supports the stock FBV3 v1.02.00 firmware (Fbv3_v1_02_00.hxf).'
    );
  }

  // Verify the stock anchors before touching anything (refuse wrong firmware).
  if (!bytesEq(img, PATCH.swled.off, hexToBytes(PATCH.swled.expect)) ||
      !bytesEq(img, LCD.off, ascii(LCD.old)) || img[LCD.off + 14] !== 0 ||
      !bytesEq(img, VER.off, ascii(VER.old))) {
    throw new Error(
      'This does not look like the stock FBV3 v1.02.00 firmware (expected bytes not found). ' +
      'Use the original Fbv3_v1_02_00.hxf, not an already-patched file.'
    );
  }

  // Apply the patch (same as build_firmware.py).
  img.set(hexToBytes(PATCH.handler.hex), PATCH.handler.off);
  img.set(hexToBytes(PATCH.stub.hex), PATCH.stub.off);
  img.set(hexToBytes(PATCH.detour.hex), PATCH.detour.off);
  img.set(hexToBytes(PATCH.swled.hex), PATCH.swled.off);
  img.set(ascii(LCD.neu), LCD.off);
  img.set(ascii(VER.neu), VER.off);

  // Correctness check: the decompressed image must match the known-good build.
  const digestHex = md5hex(img);
  const ok = digestHex === EXPECT_MD5;
  if (!ok) {
    throw new Error(
      'Internal check failed: the patched image did not match the expected checksum. ' +
      'Please report this (your firmware version may differ).'
    );
  }

  // Rebuild the container: header[:104] + fresh deflate; fix the 4 fields.
  const comp = await deflate(img);
  const out = new Uint8Array(104 + comp.length);
  out.set(hxfBytes.subarray(0, 104));
  out.set(comp, 104);
  const dv = new DataView(out.buffer);
  dv.setUint32(36, IMAGE_LEN);                 // HEAD decompressed size (BE)
  out.set(md5(img), 40);                       // HEAD MD5 of decompressed image
  dv.setUint32(100, comp.length);              // data-chunk length (BE)
  dv.setUint32(4, out.length - 8);             // FORM size (BE)

  return { blob: new Blob([out], { type: 'application/octet-stream' }), name: OUTPUT_NAME, md5: digestHex, ok };
}

function browserCanPatch() {
  return typeof DecompressionStream === 'function' && typeof CompressionStream === 'function';
}
