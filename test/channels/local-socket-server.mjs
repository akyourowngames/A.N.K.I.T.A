import http from 'node:http';
import { createHash } from 'node:crypto';

// Test-only RFC 6455 fixture: real native clients, ephemeral loopback, small JSON frames.
const WEBSOCKET_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
const frame = (data, opcode = 1) => {
  const body = Buffer.isBuffer(data) ? data : Buffer.from(JSON.stringify(data));
  const header = Buffer.alloc(body.length < 126 ? 2 : 4); header[0] = 0x80 | opcode;
  if (header.length === 2) header[1] = body.length; else { header[1] = 126; header.writeUInt16BE(body.length, 2); }
  return Buffer.concat([header, body]);
};
export async function localSocketServer(t, { request, connect }) {
  const sockets = new Set();
  const server = http.createServer(async (req, res) => { const chunks = []; for await (const chunk of req) chunks.push(chunk); await request(req, res, Buffer.concat(chunks)); });
  server.on('upgrade', (req, socket, head) => {
    sockets.add(socket); socket.on('close', () => sockets.delete(socket)); socket.on('error', () => {});
    const accept = createHash('sha1').update(req.headers['sec-websocket-key'] + WEBSOCKET_GUID).digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
    const client = { send: packet => socket.write(frame(packet)), onMessage: () => {}, close: () => socket.end(frame(Buffer.alloc(0), 8)) }; let pending = head;
    const parse = chunk => {
      pending = Buffer.concat([pending, chunk]);
      while (pending.length >= 2) {
        const opcode = pending[0] & 0xf, masked = Boolean(pending[1] & 0x80); let length = pending[1] & 0x7f, offset = 2;
        if (length === 127) { socket.destroy(); return; }
        if (length === 126) { if (pending.length < 4) return; length = pending.readUInt16BE(2); offset = 4; }
        if (pending.length < offset + (masked ? 4 : 0) + length) return;
        const mask = masked ? pending.subarray(offset, offset + 4) : null; if (masked) offset += 4;
        const data = Buffer.from(pending.subarray(offset, offset + length)); pending = pending.subarray(offset + length);
        if (mask) for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4];
        if (opcode === 8) { socket.end(frame(data, 8)); return; }
        if (opcode === 9) { socket.write(frame(data, 10)); continue; }
        if (opcode === 1) client.onMessage(JSON.parse(data));
      }
    };
    socket.on('data', parse); connect(client, req); if (head.length) parse(Buffer.alloc(0));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { for (const socket of sockets) socket.destroy(); server.closeAllConnections(); server.close(resolve); }));
  const origin = `http://127.0.0.1:${server.address().port}`; return { origin, socketUrl: origin.replace('http:', 'ws:') };
}
