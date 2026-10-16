// Ingress proxy for the CitrineOS Operator UI.
//
// Home Assistant Ingress serves the App under /api/hassio_ingress/<token>/
// and sends the prefix in X-Ingress-Path. Next.js fixes its base path at
// build time, so the UI is built with the placeholder BASE and this proxy:
// - forwards UI requests to Next.js under BASE, rewriting BASE in text
//   responses (HTML, JS, RSC, JSON, CSS) and redirects to the real prefix;
// - forwards the UI's GraphQL to the lab gateway with the operator token
//   (Hasura role operator_ro: read-only);
// - forwards the UI's OCPP command calls to the gateway only when commands
//   are enabled; the gateway enforces the fixed command set.
// The browser never sees a token. Only the Supervisor Ingress peer may
// connect.
import http from 'node:http';

export const BASE = '/__ha_ingress_base__';
// Root paths upstream references but does not ship in public/; kept inside
// the App (they answer 404 there) rather than reaching Home Assistant.
export const MISSING_PUBLIC = ['videos', 'video-poster.jpg'];
const ENCODED_BASE = encodeURIComponent(BASE);
const PREFIX = /^\/api\/hassio_ingress\/[A-Za-z0-9_-]{1,128}$/;
const TEXT = /^(text\/(html|css|plain|javascript|x-component)|application\/(javascript|json))\b/;
const MAX_BODY = 262144;

export function ingressPrefix(header) {
  return typeof header === 'string' && PREFIX.test(header) ? header : '';
}

// Upstream also references some public/ files by root path ("/gradient.svg");
// those references are prefixed too. publicNames lists public/'s entries.
export function rewrite(text, prefix, publicNames = []) {
  publicNames = publicNames.length ? [...publicNames, ...MISSING_PUBLIC] : publicNames;
  let out = text.split(BASE).join(prefix).split(ENCODED_BASE).join(encodeURIComponent(prefix));
  if (publicNames.length) {
    const names = publicNames.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    // The lookahead also allows a backslash: references inside escaped RSC JSON.
    out = out.replace(new RegExp(`(["'(\`])/(${names})(?=["'?#)/\`\\\\])`, 'g'), `$1${prefix}/$2`);
  }
  return out;
}

export function rewriteLocation(location, prefix) {
  if (!location) return location;
  try {
    const u = new URL(location, 'http://ingress.invalid');
    if (u.pathname === BASE || u.pathname.startsWith(BASE + '/')) {
      return prefix + u.pathname.slice(BASE.length) + u.search + u.hash;
    }
  } catch {
    // Not a URL: leave it to the browser.
  }
  return location;
}

function peerAddress(socket) {
  return (socket.remoteAddress || '').replace(/^::ffff:/, '');
}

async function readBody(req) {
  let size = 0;
  const chunks = [];
  for await (const c of req) {
    size += c.length;
    if (size > MAX_BODY) return null;
    chunks.push(c);
  }
  return Buffer.concat(chunks);
}

function json(res, status, body) {
  res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  res.end(JSON.stringify(body));
}

export function createProxy({gatewayUrl, token, commands, nextPort = 3000, peer = '172.30.32.2', publicNames = []}) {
  async function toGateway(req, res, path) {
    if (req.method !== 'POST') return json(res, 405, {error: 'POST only'});
    const body = await readBody(req);
    if (body === null) return json(res, 413, {error: 'Request too large'});
    try {
      const r = await fetch(gatewayUrl + path, {
        method: 'POST', body, redirect: 'error', signal: AbortSignal.timeout(20000),
        headers: {'Content-Type': 'application/json', Authorization: `Bearer ${token}`},
      });
      res.writeHead(r.status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
      res.end(await r.text());
    } catch {
      json(res, 502, {error: 'CitrineOS lab gateway unavailable; a command outcome may be unknown.'});
    }
  }

  function toNext(req, res, prefix) {
    // Next.js serves the base path itself without a trailing slash.
    const path = req.url === '/' || req.url.startsWith('/?') ? BASE + req.url.slice(1) : BASE + req.url;
    const headers = {...req.headers, 'accept-encoding': 'identity'};
    delete headers.authorization;
    const upstream = http.request({host: '127.0.0.1', port: nextPort, method: req.method, path, headers}, (r) => {
      const out = {};
      for (const [k, v] of Object.entries(r.headers)) {
        // Preload Link headers and redirects carry the base path too.
        out[k] = k === 'location' ? rewriteLocation(v, prefix)
          : typeof v === 'string' ? rewrite(v, prefix) : v;
      }
      const type = String(out['content-type'] || '');
      if (!TEXT.test(type)) {
        res.writeHead(r.statusCode, out);
        r.pipe(res);
        return;
      }
      const chunks = [];
      r.on('data', (c) => chunks.push(c));
      r.on('end', () => {
        const body = Buffer.from(rewrite(Buffer.concat(chunks).toString('utf8'), prefix, publicNames), 'utf8');
        // The body is re-sent whole: one exact length, no chunking.
        delete out['content-length'];
        delete out['transfer-encoding'];
        delete out.etag;
        out['content-length'] = String(body.length);
        res.writeHead(r.statusCode, out);
        res.end(body);
      });
      r.on('error', () => res.destroy());
    });
    upstream.on('error', () => {
      if (!res.headersSent) json(res, 502, {error: 'Operator UI starting'});
      else res.destroy();
    });
    req.pipe(upstream);
  }

  const server = http.createServer((req, res) => {
    if (peerAddress(req.socket) !== peer) return json(res, 403, {error: 'Ingress only'});
    const prefix = ingressPrefix(req.headers['x-ingress-path']);
    const url = req.url || '/';
    if (url === '/hasura/v1/graphql') return void toGateway(req, res, '/v1/graphql');
    if (url.startsWith('/core/')) {
      if (!commands) return json(res, 403, {error: 'Commands are disabled in this App (commands_enabled: false).'});
      return void toGateway(req, res, url.slice('/core'.length));
    }
    if (url.startsWith(BASE)) return json(res, 404, {});
    toNext(req, res, prefix);
  });
  server.on('upgrade', (req, socket) => socket.destroy());
  return server;
}
