import http from 'node:http';
import { randomUUID } from 'node:crypto';

const HOST = '127.0.0.1'; // Disposable loopback authentication system.
export const LOGIN_USER = 'scheduled-fixture-user';
export const LOGIN_PASSWORD = 'fixture-only-complex-password';
const SESSION_SECONDS = 3600; // Test cookie persists across closed browser contexts.

export async function complexLoginFixture() {
  const audit = { usernames: 0, passwords: 0, posts: [], wrongCredentials: 0, leakedQueries: 0, mfa: 0 };
  const states = new Map(), validSessions = new Set();
  const cookies = request => Object.fromEntries(String(request.headers.cookie || '').split(';').map(value => value.trim().split('=')));
  const server = http.createServer(async (request, response) => {
    const url = new URL(request.url, `http://${HOST}`), cookie = cookies(request);
    response.setHeader('content-type', 'text/html; charset=utf-8');
    if (url.href.includes(LOGIN_PASSWORD)) audit.leakedQueries++;
    const bodyChunks = []; for await (const chunk of request) bodyChunks.push(chunk);
    const fields = new URLSearchParams(Buffer.concat(bodyChunks).toString());
    if (url.pathname === '/expire') { validSessions.clear(); return response.end('Session expired'); }
    if (url.pathname === '/begin' || url.pathname === '/mfa') {
      if (validSessions.has(cookie.session) && url.pathname !== '/mfa') { response.writeHead(302, { location: '/dashboard' }); return response.end(); }
      const nonce = randomUUID(); states.set(nonce, { mfa: url.pathname === '/mfa', username: false });
      response.setHeader('set-cookie', `flow=${nonce}; HttpOnly; SameSite=Lax; Path=/`);
      return response.end('<title>Workspace identity</title><main><h1>Sign in to your workspace</h1><form method="post" action="/identify"><label>Account email<input name="username" autocomplete="username"></label><button>Continue</button></form></main>');
    }
    if (url.pathname === '/identify' && request.method === 'POST') {
      const state = states.get(cookie.flow); audit.usernames++;
      if (!state || fields.get('username') !== LOGIN_USER) { audit.wrongCredentials++; response.statusCode = 401; return response.end('Wrong account'); }
      state.username = true; response.writeHead(302, { location: '/challenge' }); return response.end();
    }
    if (url.pathname === '/challenge') return response.end('<title>Workspace password</title><main><h1>Continue securely</h1><iframe title="Workspace password step" src="/password-panel"></iframe></main>');
    if (url.pathname === '/password-panel') {
      const state = states.get(cookie.flow);
      if (!state?.username) { response.statusCode = 401; return response.end('Start sign-in again'); }
      return response.end(`<title>Password challenge</title><form method="post" action="/authenticate" target="_top"><input type="hidden" name="csrf" value="${cookie.flow}"><label>Account password<input name="password" type="password" autocomplete="current-password"></label><button>Sign in</button></form><script>setTimeout(()=>{const input=document.querySelector('[name=password]');const next=input.cloneNode(true);next.value=input.value;input.replaceWith(next)},100)</script>`);
    }
    if (url.pathname === '/authenticate' && request.method === 'POST') {
      const state = states.get(cookie.flow); audit.passwords++;
      if (!state?.username || fields.get('csrf') !== cookie.flow || fields.get('password') !== LOGIN_PASSWORD) { audit.wrongCredentials++; response.statusCode = 401; return response.end('Wrong password or CSRF token'); }
      if (state.mfa) { audit.mfa++; return response.end('<title>Verification required</title><h1>Two-step verification</h1><label>Verification code<input name="otp" autocomplete="one-time-code"></label><p>A fresh code from your authenticator is required. No code is saved in the credential store.</p>'); }
      const session = randomUUID(); validSessions.add(session);
      response.setHeader('set-cookie', `session=${session}; Max-Age=${SESSION_SECONDS}; HttpOnly; SameSite=Lax; Path=/`);
      response.writeHead(302, { location: '/dashboard' }); return response.end();
    }
    if (url.pathname === '/dashboard' || url.pathname === '/publish') {
      if (!validSessions.has(cookie.session)) { response.writeHead(302, { location: '/begin' }); return response.end(); }
      if (request.method === 'POST') { audit.posts.push(fields.get('message')); return response.end('<title>Report confirmed</title><main><h1>Report published once</h1><p>Scheduled verification complete.</p></main>'); }
      return response.end('<title>Workspace dashboard</title><main><h1>Signed in</h1><form method="post" action="/publish"><label>Report text<input name="message"></label><button>Publish report</button></form></main>');
    }
    response.statusCode = 404; response.end('Not found');
  });
  await new Promise(resolve => server.listen(0, HOST, resolve));
  return { base: `http://${HOST}:${server.address().port}`, audit, expire: () => validSessions.clear(), close: async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); } };
}
