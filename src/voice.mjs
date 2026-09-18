import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import tls from "node:tls";
import { spawn, spawnSync } from "node:child_process";

/**
 * Voice I/O for the CLI. Zero npm dependencies:
 * - mic + playback need the ffmpeg/ffplay binaries on PATH
 * - speech-to-text uses Groq's Whisper API (needs GROQ_API_KEY)
 * - text-to-speech uses Microsoft Edge's free endpoint (no key) over a
 *   WebSocket, which Node 22+ provides globally
 */

export const DEFAULT_STT_MODEL = "whisper-large-v3-turbo";
export const DEFAULT_TTS_MODEL = "canopylabs/orpheus-v1-english";
export const DEFAULT_GROQ_VOICE = "tara";
export const DEFAULT_EDGE_VOICE = "en-US-AriaNeural";
export const GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions";
export const GROQ_SPEECH_URL = "https://api.groq.com/openai/v1/audio/speech";

/** Orpheus English voices (Groq TTS). */
export const GROQ_VOICES = [
  { id: "tara", gender: "Female" },
  { id: "leah", gender: "Female" },
  { id: "jess", gender: "Female" },
  { id: "mia", gender: "Female" },
  { id: "zoe", gender: "Female" },
  { id: "leo", gender: "Male" },
  { id: "dan", gender: "Male" },
  { id: "zac", gender: "Male" },
  { id: "austin", gender: "Male" },
];

/** "auto" picks groq when a key exists, else edge. */
export function resolveTtsProvider(config) {
  const want = String(config.ttsProvider || "auto").toLowerCase();
  if (want === "groq" || want === "edge") return want;
  return config.groqApiKey ? "groq" : "edge";
}

export function resolveTtsVoice(config, provider) {
  if (config.ttsVoice) return config.ttsVoice;
  return provider === "groq" ? DEFAULT_GROQ_VOICE : DEFAULT_EDGE_VOICE;
}
const EDGE_VOICES_URL =
  "https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/voices/list?trustedclienttoken=6A5AA1D4EAFF4E9FB37E23D68491D6F4";

export function voiceRuntimeCheck() {
  // Speech runs over node:tls/net + fetch — available on every supported Node.
  // The mic and playback still need the ffmpeg/ffplay binaries (checked separately).
  return null;
}

function which(cmd) {
  try {
    if (process.platform === "win32") {
      return spawnSync("where", [cmd], { windowsHide: true, stdio: "ignore" }).status === 0;
    }
    return spawnSync("which", [cmd], { stdio: "ignore" }).status === 0;
  } catch {
    return false;
  }
}

/** { ffmpeg, ffplay } — both ship in standard ffmpeg builds (winget Gyan.FFmpeg). */
export function audioDeps() {
  return { ffmpeg: which("ffmpeg"), ffplay: which("ffplay") };
}

export function tmpVoiceFile(ext) {
  return path.join(os.tmpdir(), `ankita-voice-${process.pid}-${crypto.randomBytes(4).toString("hex")}.${ext}`);
}

/* ------------------------------------------------------------------ */
/* mic                                                                 */
/* ------------------------------------------------------------------ */

/** Parse `ffmpeg -list_devices` stderr into [{ name, alt }]. */
export function parseMicList(stderr) {
  const names = [...String(stderr).matchAll(/"([^"]+)"\s*\(audio\)/g)].map((m) => m[1]);
  const alts = [...String(stderr).matchAll(/Alternative name\s+"([^"]+)"/g)].map((m) => m[1]);
  return names.map((name, i) => ({ name, alt: alts[i] || "" }));
}

export async function detectMic(preferred = "") {
  const args =
    process.platform === "win32"
      ? ["-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
      : ["-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""];
  const out = await new Promise((resolve) => {
    const child = spawn("ffmpeg", args, { windowsHide: true, stdio: "ignore" });
    let stderr = "";
    child.stderr?.on("data", (d) => (stderr += d.toString()));
    child.on("error", () => resolve(""));
    child.on("close", () => resolve(stderr));
  });
  const mics = parseMicList(out);
  if (preferred) {
    const hit =
      mics.find((m) => m.name.toLowerCase().includes(preferred.toLowerCase())) ||
      mics.find((m) => m.alt.toLowerCase().includes(preferred.toLowerCase()));
    if (hit) return hit;
  }
  return mics[0] || null;
}

function micInputArgs(device) {
  if (process.platform === "win32") {
    return ["-f", "dshow", "-rtbufsize", "100M", "-i", `audio=${device}`];
  }
  if (process.platform === "darwin") {
    return ["-f", "avfoundation", "-i", `:${device || "0"}`];
  }
  return ["-f", "alsa", "-i", device || "default"];
}

/**
 * Start recording the mic to 16kHz mono WAV. Returns { stop() } — stop()
 * quits ffmpeg gracefully ('q') so the WAV header is valid, and resolves
 * true when the file is usable.
 */
export async function startRecording(outFile, device) {
  const args = [
    "-hide_banner",
    "-loglevel",
    "error",
    ...micInputArgs(device),
    "-ac",
    "1",
    "-ar",
    "16000",
    "-c:a",
    "pcm_s16le",
    "-y",
    outFile,
  ];
  const child = spawn("ffmpeg", args, { windowsHide: true, stdio: ["pipe", "ignore", "pipe"] });

  const earlyExit = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 1200);
    child.once("error", (err) => {
      clearTimeout(timer);
      resolve(err);
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      resolve(new Error(`ffmpeg exited immediately (code ${code}) — bad mic device?`));
    });
  });
  if (earlyExit) {
    try {
      child.kill("SIGKILL");
    } catch {}
    throw earlyExit;
  }

  let stderr = "";
  child.stderr?.on("data", (d) => (stderr += d.toString()));

  return {
    child,
    stop: () =>
      new Promise((resolve) => {
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          try {
            const stat = fs.statSync(outFile);
            resolve(stat.size > 1000);
          } catch {
            resolve(false);
          }
        };
        child.once("close", finish);
        try {
          child.stdin.write("q");
        } catch {}
        setTimeout(() => {
          if (!done) {
            try {
              child.kill("SIGKILL");
            } catch {}
            setTimeout(finish, 400);
          }
        }, 3000);
      }),
  };
}

/* ------------------------------------------------------------------ */
/* Groq Whisper STT                                                    */
/* ------------------------------------------------------------------ */

export async function transcribeGroq({ apiKey, model = DEFAULT_STT_MODEL, wavPath, language = "en" }) {
  if (!apiKey) throw new Error("set GROQ_API_KEY in .env (free key at console.groq.com)");
  const buf = fs.readFileSync(wavPath);
  const form = new FormData();
  form.append("file", new Blob([buf], { type: "audio/wav" }), "mic.wav");
  form.append("model", model);
  form.append("response_format", "json");
  form.append("temperature", "0");
  if (language) form.append("language", language);

  const res = await fetch(GROQ_TRANSCRIBE_URL, {
    method: "POST",
    headers: { Authorization: `Bearer ${apiKey}` },
    body: form,
  });
  if (!res.ok) throw new Error(`Groq STT ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const data = await res.json();
  return String(data.text || "").trim();
}

/* ------------------------------------------------------------------ */
/* Edge TTS                                                            */
/* ------------------------------------------------------------------ */

export function escapeXml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

export function buildSsml({ voice, rate = "+0%", pitch = "+0Hz", volume = "+0%", text }) {
  return (
    `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>` +
    `<voice name='${voice}'><prosody pitch='${pitch}' rate='${rate}' volume='${volume}'>${escapeXml(text)}</prosody></voice></speak>`
  );
}

/* ------------------------------------------------------------------ */
/* Edge handshake: Sec-MS-GEC token + raw WebSocket over TLS           */
/*                                                                     */
/* Microsoft requires a time-windowed SHA-256 token, a ConnectionId and */
/* browser-like handshake headers (mirrors the edge-tts package). The  */
/* global WebSocket cannot set those headers, so the minimal framing   */
/* needed here (masked text frames out, text/binary frames in) is      */
/* implemented directly on node:tls with zero dependencies.            */
/* ------------------------------------------------------------------ */

const EDGE_HOST = "speech.platform.bing.com";
const EDGE_PATH = "/consumer/speech/synthesize/readaloud/edge/v1";
const EDGE_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const EDGE_GEC_VERSION = "1-143.0.3650.75";
const EDGE_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0";
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const WIN_EPOCH = 11644473600;

let clockSkewSec = 0;

/**
 * Replicates edge-tts DRM.generate_sec_ms_gec float-for-float:
 * windows-epoch seconds, floored to a 5-minute window, scaled to
 * 100ns ticks, hashed with the trusted client token.
 */
export function generateSecMsGec(nowSec = Date.now() / 1000) {
  let ticks = nowSec + clockSkewSec + WIN_EPOCH;
  ticks -= ticks % 300;
  ticks *= 10000000;
  const str = `${ticks.toFixed(0)}${EDGE_TOKEN}`;
  return crypto.createHash("sha256").update(str, "ascii").digest("hex").toUpperCase();
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Javascript-style date string, matching edge-tts date_to_string(). */
export function edgeDateString(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return (
    `${DAYS[d.getUTCDay()]} ${MONTHS[d.getUTCMonth()]} ${p(d.getUTCDate())} ${d.getUTCFullYear()} ` +
    `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} GMT+0000 (Coordinated Universal Time)`
  );
}

export function edgeWsTarget() {
  const connectionId = crypto.randomUUID().replace(/-/g, "");
  const path =
    `${EDGE_PATH}?TrustedClientToken=${EDGE_TOKEN}` +
    `&ConnectionId=${connectionId}` +
    `&Sec-MS-GEC=${generateSecMsGec()}` +
    `&Sec-MS-GEC-Version=${EDGE_GEC_VERSION}`;
  const headers = {
    Pragma: "no-cache",
    "Cache-Control": "no-cache",
    Origin: "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": EDGE_UA,
    Cookie: `muid=${crypto.randomBytes(16).toString("hex").toUpperCase()};`,
  };
  return { host: EDGE_HOST, path, headers };
}

function encodeTextFrame(str) {
  const payload = Buffer.from(str, "utf8");
  const mask = crypto.randomBytes(4);
  let header;
  if (payload.length < 126) {
    header = Buffer.from([0x81, 0x80 | payload.length]);
  } else if (payload.length < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 0x80 | 126;
    header.writeUInt16BE(payload.length, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 0x80 | 127;
    header.writeBigUInt64BE(BigInt(payload.length), 2);
  }
  const masked = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i++) masked[i] = payload[i] ^ mask[i % 4];
  return Buffer.concat([header, mask, masked]);
}

function parseRfc2616Date(date) {
  const ms = Date.parse(date);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

/** Opens the Edge speech socket. Resolves { sendText, onMessage, close }. */
function edgeSocket(timeoutMs, skewRetries = 1) {
  return new Promise((resolve, reject) => {
    const finish = (fn, value) => {
      clearTimeout(timer);
      fn(value);
    };
    const fail = (message, headers) => {
      // Clock-skew retry, mirroring edge-tts handle_client_response_error.
      const serverDate = headers?.date ? parseRfc2616Date(headers.date) : null;
      if (serverDate !== null && skewRetries > 0) {
        clockSkewSec += serverDate - Date.now() / 1000;
        clearTimeout(timer);
        resolve(edgeSocket(timeoutMs, skewRetries - 1));
        return;
      }
      finish(reject, new Error(message));
    };

    const { host, path, headers } = edgeWsTarget();
    const key = crypto.randomBytes(16).toString("base64");
    const head = [
      `GET ${path} HTTP/1.1`,
      `Host: ${host}`,
      "Upgrade: websocket",
      "Connection: Upgrade",
      `Sec-WebSocket-Key: ${key}`,
      "Sec-WebSocket-Version: 13",
      ...Object.entries(headers).map(([k, v]) => `${k}: ${v}`),
      "",
      "",
    ].join("\r\n");

    const sock = tls.connect({ host, port: 443, servername: host }, () => sock.write(head));
    const timer = setTimeout(() => {
      sock.destroy();
      finish(reject, new Error("Edge TTS handshake timed out"));
    }, Math.max(5000, timeoutMs));

    let open = false;
    let buf = Buffer.alloc(0);
    let fragOpcode = 0;
    let fragParts = [];
    const api = { sendText: null, onMessage: null, close: () => sock.destroy() };

    const emit = (opcode, payload) => {
      if (opcode === 0x8) {
        sock.destroy();
        api.onMessage?.({ type: "close" });
        return;
      }
      if (opcode === 0x9) {
        const pong = Buffer.from([0x8a, payload.length > 125 ? 126 : payload.length]);
        sock.write(pong);
        return;
      }
      if (opcode === 0x1 || opcode === 0x2) {
        api.onMessage?.({ type: opcode === 0x1 ? "text" : "binary", data: payload });
      }
    };

    const pump = () => {
      while (true) {
        if (buf.length < 2) return;
        const b0 = buf[0];
        const b1 = buf[1];
        const fin = b0 & 0x80;
        const opcode = b0 & 0x0f;
        let len = b1 & 0x7f;
        let off = 2;
        if (len === 126) {
          if (buf.length < 4) return;
          len = buf.readUInt16BE(2);
          off = 4;
        } else if (len === 127) {
          if (buf.length < 10) return;
          len = Number(buf.readBigUInt64BE(2));
          off = 10;
        }
        const masked = b1 & 0x80 ? 4 : 0;
        if (buf.length < off + masked + len) return;
        let payload = buf.subarray(off + masked, off + masked + len);
        if (masked) {
          const mask = buf.subarray(off, off + 4);
          const out = Buffer.from(payload);
          for (let i = 0; i < out.length; i++) out[i] ^= mask[i % 4];
          payload = out;
        }
        buf = buf.subarray(off + masked + len);

        if (opcode === 0x0) {
          fragParts.push(payload);
          if (fin) {
            emit(fragOpcode, Buffer.concat(fragParts));
            fragParts = [];
          }
          continue;
        }
        if (!fin && (opcode === 0x1 || opcode === 0x2)) {
          fragOpcode = opcode;
          fragParts = [payload];
          continue;
        }
        emit(opcode, payload);
      }
    };

    let head_text = "";
    sock.on("data", (chunk) => {
      if (!open) {
        head_text += chunk.toString("latin1");
        const end = head_text.indexOf("\r\n\r\n");
        if (end === -1) return;
        const [statusLine, ...headerLines] = head_text.slice(0, end).split("\r\n");
        const status = Number((statusLine.match(/^HTTP\/\S+\s+(\d+)/) || [])[1]);
        const responseHeaders = {};
        for (const line of headerLines) {
          const i = line.indexOf(":");
          if (i > 0) responseHeaders[line.slice(0, i).trim().toLowerCase()] = line.slice(i + 1).trim();
        }
        const rest = Buffer.from(head_text.slice(end + 4), "latin1");
        if (status !== 101) {
          sock.destroy();
          const detail =
            status === 403 && skewRetries > 0 ? " (retrying with clock-skew correction)" : "";
          fail(`Edge TTS handshake failed: HTTP ${status || "?"}${detail}`, responseHeaders);
          return;
        }
        const expected = crypto
          .createHash("sha1")
          .update(key + WS_GUID, "ascii")
          .digest("base64");
        if (responseHeaders["sec-websocket-accept"] !== expected) {
          sock.destroy();
          finish(reject, new Error("Edge TTS handshake failed: bad accept key"));
          return;
        }
        open = true;
        api.sendText = (text) => sock.write(encodeTextFrame(text));
        buf = rest;
        finish(resolve, api);
        if (buf.length) pump();
        return;
      }
      buf = Buffer.concat([buf, chunk]);
      pump();
    });
    sock.on("error", (err) => {
      if (!open) finish(reject, new Error(`Edge TTS connection failed: ${err.message}`));
    });
    sock.on("close", () => {
      if (!open) finish(reject, new Error("Edge TTS connection closed before handshake"));
      else api.onMessage?.({ type: "close" });
    });
  });
}

export function synthesizeEdge({ voice, rate = "+0%", text, timeoutMs = 60000 }) {
  return new Promise((resolve, reject) => {
    const clean = stripForSpeech(text);
    if (!clean) {
      reject(new Error("nothing speakable in that text"));
      return;
    }
    let settled = false;
    const chunks = [];
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try {
          api?.close();
        } catch {}
        reject(new Error("Edge TTS timed out"));
      }
    }, Math.max(8000, timeoutMs));
    const done = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        api?.close();
      } catch {}
      fn(value);
    };

    let api = null;
    const requestId = crypto.randomUUID().replace(/-/g, "");
    edgeSocket(timeoutMs)
      .then((socket) => {
        api = socket;
        socket.onMessage = (msg) => {
          if (msg.type === "text") {
            if (msg.data.toString("utf8").includes("Path:turn.end")) {
              done(resolve, Buffer.concat(chunks));
            }
            return;
          }
          if (msg.type === "binary") {
            const buf = msg.data;
            if (buf.length < 2) return;
            const headerLen = buf.readUInt16BE(0);
            const header = buf.subarray(2, 2 + headerLen).toString("utf8");
            const audio = buf.subarray(2 + headerLen);
            if (header.includes("Path:audio") && audio.length) chunks.push(audio);
            return;
          }
          if (msg.type === "close" && !chunks.length) {
            done(reject, new Error("Edge TTS closed before any audio (empty text?)"));
          }
        };
        socket.sendText(
          `X-Timestamp:${edgeDateString()}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n` +
            `{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},` +
            `"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n`
        );
        socket.sendText(
          `X-RequestId:${requestId}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${edgeDateString()}Z\r\nPath:ssml\r\n\r\n` +
            buildSsml({ voice, rate, text: clean })
        );
      })
      .catch((err) => done(reject, err));
  });
}

export async function listEdgeVoices() {
  const res = await fetch(EDGE_VOICES_URL, {
    headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" },
  });
  if (!res.ok) throw new Error(`voice list ${res.status}`);
  return res.json();
}

/* ------------------------------------------------------------------ */
/* Groq TTS (Orpheus — fast, natural, same key as STT)                 */
/* ------------------------------------------------------------------ */

/** Split text into sentence chunks of at most maxChars (Orpheus caps input). */
export function chunkSentences(text, maxChars = 190) {
  const sentences = String(text ?? "")
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const chunks = [];
  let current = "";
  const push = () => {
    if (current) chunks.push(current);
    current = "";
  };
  for (const sentence of sentences) {
    if (sentence.length > maxChars) {
      push();
      const words = sentence.split(/\s+/);
      let part = "";
      for (const word of words) {
        if ((part + " " + word).trim().length > maxChars && part) {
          chunks.push(part);
          part = word;
        } else {
          part = (part + " " + word).trim();
        }
      }
      if (part) chunks.push(part);
      continue;
    }
    if ((current + " " + sentence).trim().length > maxChars) push();
    current = (current + " " + sentence).trim();
  }
  push();
  return chunks.length ? chunks : [String(text ?? "").slice(0, maxChars)];
}

function parseWav(buf) {
  if (buf.length < 44 || buf.subarray(0, 4).toString() !== "RIFF" || buf.subarray(8, 12).toString() !== "WAVE") {
    throw new Error("not a WAV file");
  }
  let off = 12;
  let fmt = null;
  let pcm = null;
  while (off + 8 <= buf.length) {
    const id = buf.subarray(off, off + 4).toString();
    const size = buf.readUInt32LE(off + 4);
    const data = buf.subarray(off + 8, off + 8 + size);
    if (id === "fmt ") fmt = Buffer.from(data);
    else if (id === "data" && pcm === null) pcm = Buffer.from(data);
    off += 8 + size + (size % 2);
  }
  if (!fmt || !pcm) throw new Error("WAV is missing fmt/data chunks");
  return { fmt, pcm };
}

function buildWav(fmt, pcm) {
  const head = Buffer.alloc(12 + 8 + fmt.length + 8);
  head.write("RIFF", 0);
  head.writeUInt32LE(4 + 8 + fmt.length + 8 + pcm.length, 4);
  head.write("WAVE", 8);
  let off = 12;
  head.write("fmt ", off);
  head.writeUInt32LE(fmt.length, off + 4);
  fmt.copy(head, off + 8);
  off += 8 + fmt.length;
  head.write("data", off);
  head.writeUInt32LE(pcm.length, off + 4);
  return Buffer.concat([head, pcm]);
}

/** Join per-sentence WAVs into one. Falls back to the first chunk. */
export function concatWav(buffers) {
  if (!buffers.length) throw new Error("nothing to join");
  if (buffers.length === 1) return buffers[0];
  try {
    const parts = buffers.map(parseWav);
    const fmt = parts[0].fmt;
    for (const part of parts.slice(1)) {
      if (!part.fmt.equals(fmt)) throw new Error("mismatched WAV formats");
    }
    return buildWav(fmt, Buffer.concat(parts.map((p) => p.pcm)));
  } catch {
    return buffers[0];
  }
}

export async function synthesizeGroq({ apiKey, model = DEFAULT_TTS_MODEL, voice = DEFAULT_GROQ_VOICE, text, timeoutMs = 60000 }) {
  if (!apiKey) throw new Error("set GROQ_API_KEY in .env (free key at console.groq.com)");
  const clean = stripForSpeech(text);
  if (!clean) throw new Error("nothing speakable in that text");
  const parts = chunkSentences(clean);
  const wavs = [];
  for (const part of parts) {
    let res;
    try {
      res = await fetch(GROQ_SPEECH_URL, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ model, input: part, voice, response_format: "wav" }),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (err) {
      if (err.name === "TimeoutError" || err.name === "AbortError") {
        throw new Error(`Groq TTS timeout after ${timeoutMs}ms`);
      }
      throw err;
    }
    if (!res.ok) {
      const body = await res.text();
      if (/terms acceptance/i.test(body)) {
        throw new Error(
          `Groq TTS model "${model}" needs its terms accepted first - open ` +
            `https://console.groq.com/playground?model=${encodeURIComponent(model)} and accept them, ` +
            `or set TTS_PROVIDER=edge (no key needed).`
        );
      }
      throw new Error(`Groq TTS ${res.status}: ${body.slice(0, 200)}`);
    }
    wavs.push(Buffer.from(await res.arrayBuffer()));
  }
  return concatWav(wavs);
}

/* ------------------------------------------------------------------ */
/* playback                                                            */
/* ------------------------------------------------------------------ */

let currentPlayer = null;

export function stopPlayback() {
  try {
    currentPlayer?.kill("SIGKILL");
  } catch {}
  currentPlayer = null;
}

export async function playMp3(mp3, { signal } = {}) {
  stopPlayback();
  const file = tmpVoiceFile("mp3");
  fs.writeFileSync(file, mp3);
  try {
    await new Promise((resolve) => {
      let child;
      try {
        child = spawn("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet", file], {
          windowsHide: true,
          stdio: "ignore",
        });
      } catch {
        return resolve();
      }
      currentPlayer = child;
      const done = () => {
        if (currentPlayer === child) currentPlayer = null;
        resolve();
      };
      child.on("error", done);
      child.on("close", done);
      signal?.addEventListener("abort", () => {
        try {
          child.kill("SIGKILL");
        } catch {}
      }, { once: true });
    });
  } finally {
    try {
      fs.unlinkSync(file);
    } catch {}
  }
}

/* ------------------------------------------------------------------ */
/* audio conversion (ffmpeg)                                           */
/* ------------------------------------------------------------------ */

/**
 * Runs ffmpeg over an in-memory buffer, returning the converted buffer.
 * Used to turn Telegram voice notes (OGG/Opus) into the 16 kHz WAV that
 * Whisper wants, and Edge MP3 into the OGG/Opus that sendVoice wants.
 */
export async function convertAudio(input, { to = "wav", timeoutMs = 60000 } = {}) {
  const src = tmpVoiceFile("in");
  const dst = tmpVoiceFile(to);
  const args =
    to === "wav"
      ? ["-hide_banner", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", dst]
      : ["-hide_banner", "-loglevel", "error", "-i", src, "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1", "-y", dst];
  try {
    fs.writeFileSync(src, input);
    const { code, stderr } = await new Promise((resolve) => {
      const child = spawn("ffmpeg", args, { windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
      let err = "";
      const timer = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {}
      }, Math.max(5000, timeoutMs));
      child.stderr?.on("data", (d) => (err += d.toString()));
      child.on("error", (e) => {
        clearTimeout(timer);
        resolve({ code: -1, stderr: e.message });
      });
      child.on("close", (c) => {
        clearTimeout(timer);
        resolve({ code: c, stderr: err });
      });
    });
    if (code !== 0) throw new Error(`ffmpeg exited ${code}: ${stderr.slice(0, 200)}`);
    return fs.readFileSync(dst);
  } finally {
    for (const f of [src, dst]) {
      try {
        fs.unlinkSync(f);
      } catch {}
    }
  }
}

/* ------------------------------------------------------------------ */
/* markdown -> speakable text                                          */
/* ------------------------------------------------------------------ */

export function stripForSpeech(md, maxChars = 1800) {
  let s = String(md ?? "");
  s = s.replace(/```[\s\S]*?```/g, " ");
  s = s.replace(/`([^`]+)`/g, "$1");
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  s = s.replace(/^#{1,6}\s+/gm, "");
  s = s.replace(/(\*\*|__)(.*?)\1/g, "$2");
  s = s.replace(/(^|\W)\*([^*\n]+)\*/g, "$1$2");
  s = s.replace(/(^|\W)_([^_\n]+)_/g, "$1$2");
  s = s.replace(/~~([^~]+)~~/g, "$1");
  s = s.replace(/^\s*>\s?/gm, "");
  s = s.replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, ". ");
  s = s.replace(/\|/g, " ");
  s = s.replace(/[ \t]+/g, " ");
  s = s.replace(/\n{2,}/g, "\n").replace(/\n/g, " ");
  s = s.trim().replace(/\s+/g, " ");
  if (s.length > maxChars) {
    const cut = s.lastIndexOf(". ", maxChars);
    s = cut > maxChars * 0.4 ? s.slice(0, cut + 1) : s.slice(0, maxChars);
  }
  return s;
}
