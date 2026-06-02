'use strict';

/* ----------------------------------------------------------------------------
 * Minimal MD5 (RFC 1321) for Uint8Array input -> 16-byte Uint8Array digest.
 *
 * Needed because the FBV3 .hxf container stores an MD5 of the decompressed
 * firmware image, and Web Crypto (SubtleCrypto) does not provide MD5. MD5 is
 * used here only as a container checksum the device expects, not for security.
 *
 * Compact public-domain-style implementation; operates on bytes, returns bytes.
 * -------------------------------------------------------------------------- */

function md5(bytes) {
  const s = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
  ];
  const K = new Int32Array(64);
  for (let i = 0; i < 64; i++) {
    K[i] = (Math.floor(Math.abs(Math.sin(i + 1)) * 4294967296)) | 0;
  }

  // Pre-processing: append 0x80, pad to 56 mod 64, append 64-bit bit-length (LE).
  const origLen = bytes.length;
  const bitLen = origLen * 8;
  const padded = new Uint8Array(((origLen + 8) >> 6) * 64 + 64);
  padded.set(bytes);
  padded[origLen] = 0x80;
  // bit length as 64-bit little-endian (we only fill low 32 bits + next 32)
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, bitLen >>> 0, true);
  dv.setUint32(padded.length - 4, Math.floor(bitLen / 4294967296) >>> 0, true);

  let a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
  const M = new Int32Array(16);

  for (let off = 0; off < padded.length; off += 64) {
    for (let j = 0; j < 16; j++) M[j] = dv.getUint32(off + j * 4, true);

    let A = a0, B = b0, C = c0, D = d0;
    for (let i = 0; i < 64; i++) {
      let F, g;
      if (i < 16) { F = (B & C) | (~B & D); g = i; }
      else if (i < 32) { F = (D & B) | (~D & C); g = (5 * i + 1) & 15; }
      else if (i < 48) { F = B ^ C ^ D; g = (3 * i + 5) & 15; }
      else { F = C ^ (B | ~D); g = (7 * i) & 15; }

      F = (F + A + K[i] + M[g]) | 0;
      A = D; D = C; C = B;
      const sh = s[i];
      B = (B + ((F << sh) | (F >>> (32 - sh)))) | 0;
    }
    a0 = (a0 + A) | 0; b0 = (b0 + B) | 0; c0 = (c0 + C) | 0; d0 = (d0 + D) | 0;
  }

  const out = new Uint8Array(16);
  const od = new DataView(out.buffer);
  od.setUint32(0, a0 >>> 0, true);
  od.setUint32(4, b0 >>> 0, true);
  od.setUint32(8, c0 >>> 0, true);
  od.setUint32(12, d0 >>> 0, true);
  return out;
}

function md5hex(bytes) {
  return Array.from(md5(bytes), (b) => b.toString(16).padStart(2, '0')).join('');
}
