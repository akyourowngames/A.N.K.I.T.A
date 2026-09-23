import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

/**
 * Dependency-free app icon generator.
 *
 * Renders the ankita mark — a gold four-point sparkle on a dark rounded tile —
 * and writes desktop/build/icon.png (1024²) plus a multi-size icon.ico for the
 * Windows installer. Hand-rolled PNG/ICO encoding keeps the repo zero-dep: the
 * desktop package only adds build tooling, never runtime modules.
 *
 * Run: node desktop/scripts/make-icon.mjs
 */

const SIZE = 1024;
const SUPERSAMPLE = 2;
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../build');

const hex = value => [parseInt(value.slice(1, 3), 16), parseInt(value.slice(3, 5), 16), parseInt(value.slice(5, 7), 16)];
const mix = (a, b, t) => a + (b - a) * t;
const clamp01 = value => (value < 0 ? 0 : value > 1 ? 1 : value);

const BG_TOP = hex('#262b30');
const BG_BOTTOM = hex('#131619');
const GOLD_TOP = hex('#f0d8aa');
const GOLD_BOTTOM = hex('#bf9b5f');
const EDGE = hex('#c7aa79');

const SPARKLE = [[12, 2], [14.3, 9.7], [22, 12], [14.3, 14.3], [12, 22], [9.7, 14.3], [2, 12], [9.7, 9.7]];

function pointInPolygon(x, y, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function roundedRectDistance(px, py, cx, cy, halfW, halfH, radius) {
  const qx = Math.abs(px - cx) - (halfW - radius);
  const qy = Math.abs(py - cy) - (halfH - radius);
  const ax = Math.max(qx, 0);
  const ay = Math.max(qy, 0);
  return Math.hypot(ax, ay) + Math.min(Math.max(qx, qy), 0) - radius;
}

function render() {
  const width = SIZE * SUPERSAMPLE;
  const tile = { cx: width / 2, cy: width / 2, halfW: width * 0.47, halfH: width * 0.47, radius: width * 0.22 };
  const scale = (width * 0.31) / 10;
  const star = SPARKLE.map(([x, y]) => [tile.cx + (x - 12) * scale, tile.cy + (y - 12) * scale]);
  const buffer = new Uint8ClampedArray(SIZE * SIZE * 4);

  for (let py = 0; py < SIZE; py++) {
    for (let px = 0; px < SIZE; px++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SUPERSAMPLE; sy++) {
        for (let sx = 0; sx < SUPERSAMPLE; sx++) {
          const sampleX = px * SUPERSAMPLE + sx + 0.5;
          const sampleY = py * SUPERSAMPLE + sy + 0.5;
          const distance = roundedRectDistance(sampleX, sampleY, tile.cx, tile.cy, tile.halfW, tile.halfH, tile.radius);
          if (distance > 0) continue;
          const gradient = clamp01(sampleY / width);
          let cr = mix(BG_TOP[0], BG_BOTTOM[0], gradient);
          let cg = mix(BG_TOP[1], BG_BOTTOM[1], gradient);
          let cb = mix(BG_TOP[2], BG_BOTTOM[2], gradient);
          if (distance > -SUPERSAMPLE * 1.4) {
            const edge = clamp01(-distance / (SUPERSAMPLE * 1.4));
            cr = mix(EDGE[0], cr, edge);
            cg = mix(EDGE[1], cg, edge);
            cb = mix(EDGE[2], cb, edge);
          }
          if (pointInPolygon(sampleX, sampleY, star)) {
            const glow = clamp01((sampleY - tile.cy + width * 0.32) / (width * 0.64));
            cr = mix(GOLD_TOP[0], GOLD_BOTTOM[0], glow);
            cg = mix(GOLD_TOP[1], GOLD_BOTTOM[1], glow);
            cb = mix(GOLD_TOP[2], GOLD_BOTTOM[2], glow);
          }
          r += cr; g += cg; b += cb; a += 255;
        }
      }
      const total = SUPERSAMPLE * SUPERSAMPLE;
      const index = (py * SIZE + px) * 4;
      if (a === 0) continue;
      const alpha = a / total;
      buffer[index] = Math.round((r / total) * (255 / (alpha || 1)));
      buffer[index + 1] = Math.round((g / total) * (255 / (alpha || 1)));
      buffer[index + 2] = Math.round((b / total) * (255 / (alpha || 1)));
      buffer[index + 3] = Math.round(alpha);
    }
  }
  return buffer;
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer) {
  let c = 0xffffffff;
  for (let i = 0; i < buffer.length; i++) c = CRC_TABLE[(c ^ buffer[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuffer = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 0);
  return Buffer.concat([length, typeBuffer, data, crc]);
}

function encodePng(rgba, size) {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  const raw = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y++) {
    raw[y * (size * 4 + 1)] = 0;
    Buffer.from(rgba.buffer, y * size * 4, size * 4).copy(raw, y * (size * 4 + 1) + 1);
  }
  return Buffer.concat([signature, chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]);
}

function downsample(rgba, size, target) {
  const out = new Uint8ClampedArray(target * target * 4);
  const ratio = size / target;
  for (let y = 0; y < target; y++) {
    for (let x = 0; x < target; x++) {
      let r = 0, g = 0, b = 0, a = 0, count = 0;
      for (let sy = 0; sy < ratio; sy++) {
        for (let sx = 0; sx < ratio; sx++) {
          const index = ((y * ratio + sy) * size + (x * ratio + sx)) * 4;
          r += rgba[index]; g += rgba[index + 1]; b += rgba[index + 2]; a += rgba[index + 3]; count++;
        }
      }
      const index = (y * target + x) * 4;
      out[index] = Math.round(r / count);
      out[index + 1] = Math.round(g / count);
      out[index + 2] = Math.round(b / count);
      out[index + 3] = Math.round(a / count);
    }
  }
  return out;
}

function encodeIco(rgba, size, sizes) {
  const images = sizes.map(target => ({ target, png: encodePng(downsample(rgba, size, target), target) }));
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  const entries = [];
  let offset = 6 + images.length * 16;
  for (const image of images) {
    const entry = Buffer.alloc(16);
    entry[0] = image.target >= 256 ? 0 : image.target;
    entry[1] = image.target >= 256 ? 0 : image.target;
    entry.writeUInt16LE(1, 4);
    entry.writeUInt16LE(32, 6);
    entry.writeUInt32LE(image.png.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += image.png.length;
    entries.push(entry);
  }
  return Buffer.concat([header, ...entries, ...images.map(image => image.png)]);
}

const pixels = render();
fs.mkdirSync(outDir, { recursive: true });
fs.writeFileSync(path.join(outDir, 'icon.png'), encodePng(pixels, SIZE));
fs.writeFileSync(path.join(outDir, 'icon.ico'), encodeIco(pixels, SIZE, [16, 24, 32, 48, 64, 128, 256]));
console.log(`wrote ${path.join(outDir, 'icon.png')} and icon.ico`);
