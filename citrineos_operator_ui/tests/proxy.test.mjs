import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createProxy, rewrite, rewriteLocation, ingressPrefix, BASE} from '../rootfs/opt/operator-ui-ha/proxy.mjs';
import {validate} from '../rootfs/opt/operator-ui-ha/run.mjs';

const TOKEN = 'a'.repeat(64);
const PREFIX = '/api/hassio_ingress/AbC_123-xyz';

function listen(server) {
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(server.address().port)));
}

async function harness(commands) {
  const seen = {next: [], gateway: []};
  const next = http.createServer((req, res) => {
    seen.next.push({url: req.url, auth: req.headers.authorization, enc: req.headers['accept-encoding']});
    if (req.url === `${BASE}/old`) {
      res.writeHead(307, {location: `${BASE}/overview?x=1`});
      return res.end();
    }
    if (req.url.endsWith('.png')) {
      res.writeHead(200, {'content-type': 'image/png'});
      return res.end(Buffer.from([0x89, 0x50, BASE.length]));
    }
    const html = `<script src="${BASE}/_next/a.js"></script><img src="/_next/image?url=${encodeURIComponent(BASE)}%2Fx.png">`;
    // Chunked like Next.js; the length changes when the placeholder is rewritten.
    res.writeHead(200, {'content-type': 'text/html; charset=utf-8',
      link: `<${BASE}/_next/static/media/f.woff2>; rel=preload; as="font"`});
    res.write(html.slice(0, 10));
    res.end(html.slice(10));
  });
  const gateway = http.createServer(async (req, res) => {
    let body = '';
    for await (const c of req) body += c;
    seen.gateway.push({url: req.url, auth: req.headers.authorization, body});
    res.writeHead(200, {'content-type': 'application/json'});
    res.end('{"data":{}}');
  });
  const nextPort = await listen(next);
  const gatewayPort = await listen(gateway);
  const proxy = createProxy({gatewayUrl: `http://127.0.0.1:${gatewayPort}`, token: TOKEN, commands,
    nextPort, peer: '127.0.0.1'});
  const port = await listen(proxy);
  const call = async (path, init = {}) => {
    const r = await fetch(`http://127.0.0.1:${port}${path}`, {redirect: 'manual', ...init,
      headers: {'x-ingress-path': PREFIX, ...(init.headers || {})}});
    return {status: r.status, location: r.headers.get('location'), link: r.headers.get('link'),
      length: r.headers.get('content-length'), chunked: r.headers.get('transfer-encoding'), text: await r.text()};
  };
  const close = () => [next, gateway, proxy].forEach((s) => s.close());
  return {call, seen, close};
}

test('Ingress prefix is validated and placeholders are rewritten', () => {
  assert.equal(ingressPrefix(PREFIX), PREFIX);
  for (const bad of ['/api/hassio_ingress/', '/evil', '/api/hassio_ingress/a/b', '/api/hassio_ingress/a"b', undefined])
    assert.equal(ingressPrefix(bad), '');
  assert.equal(rewrite(`"${BASE}/x" ${encodeURIComponent(BASE)}`, PREFIX), `"${PREFIX}/x" ${encodeURIComponent(PREFIX)}`);
  assert.equal(rewriteLocation(`${BASE}/login?e=1`, PREFIX), `${PREFIX}/login?e=1`);
  const names = ['gradient.svg', 'logo_white.png', 'locales'];
  assert.equal(rewrite(`icon:"/gradient.svg",url('/logo_white.png') "/locales/en.json" "/gradient.svgz" "/other.svg"`, PREFIX, names),
    `icon:"${PREFIX}/gradient.svg",url('${PREFIX}/logo_white.png') "${PREFIX}/locales/en.json" "/gradient.svgz" "/other.svg"`);
  assert.equal(rewrite('[\\"$\\",\\"link\\",{\\"href\\":\\"/gradient.svg\\"}] "/videos/help.mp4"', PREFIX, names),
    `[\\"$\\",\\"link\\",{\\"href\\":\\"${PREFIX}/gradient.svg\\"}] "${PREFIX}/videos/help.mp4"`);
  assert.equal(rewriteLocation(`http://127.0.0.1:3000${BASE}`, PREFIX), PREFIX);
  assert.equal(rewriteLocation('https://example.com/x', PREFIX), 'https://example.com/x');
});

test('options fail closed', () => {
  const good = {gateway_url: 'http://31ac84d3-citrineos-server:8080', operator_token: TOKEN};
  assert.deepEqual(validate(good), {gatewayUrl: good.gateway_url, token: TOKEN, commands: false});
  assert.equal(validate({...good, commands_enabled: true}).commands, true);
  for (const bad of [{}, {...good, gateway_url: 'https://x:8080'}, {...good, gateway_url: 'http://x:8080/v1'},
    {...good, operator_token: 'short'}, {...good, commands_enabled: 'yes'}])
    assert.throws(() => validate(bad));
});

test('UI pages are served under the Ingress prefix', async () => {
  const h = await harness(false);
  try {
    const page = await h.call('/charging-stations', {headers: {authorization: 'Bearer browser'}});
    assert.equal(page.status, 200);
    assert.match(page.text, new RegExp(`src="${PREFIX}/_next/a.js"`));
    assert.ok(page.text.includes(encodeURIComponent(PREFIX)));
    assert.ok(!page.text.includes(BASE));
    assert.equal(page.link, `<${PREFIX}/_next/static/media/f.woff2>; rel=preload; as="font"`);
    assert.equal(Number(page.length), Buffer.byteLength(page.text));
    assert.equal(page.chunked, null);
    assert.deepEqual(h.seen.next.at(-1), {url: `${BASE}/charging-stations`, auth: undefined, enc: 'identity'});
    await h.call('/');
    assert.equal(h.seen.next.at(-1).url, BASE);
    await h.call('/?tab=1');
    assert.equal(h.seen.next.at(-1).url, `${BASE}?tab=1`);
    const moved = await h.call('/old');
    assert.equal(moved.status, 307);
    assert.equal(moved.location, `${PREFIX}/overview?x=1`);
    const png = await h.call('/x.png');
    assert.equal(png.status, 200);
    assert.equal((await h.call(`${BASE}/x`)).status, 404);
  } finally {
    h.close();
  }
});

test('GraphQL goes to the gateway with the operator token, never the browser token', async () => {
  const h = await harness(false);
  try {
    const r = await h.call('/hasura/v1/graphql', {method: 'POST', body: '{"query":"{ ChargingStations { id } }"}',
      headers: {authorization: 'Bearer browser', 'content-type': 'application/json'}});
    assert.equal(r.status, 200);
    assert.deepEqual(h.seen.gateway.at(-1), {url: '/v1/graphql', auth: `Bearer ${TOKEN}`,
      body: '{"query":"{ ChargingStations { id } }"}'});
    assert.equal((await h.call('/hasura/v1/graphql')).status, 405);
    const big = await h.call('/hasura/v1/graphql', {method: 'POST', body: 'x'.repeat(300000)});
    assert.equal(big.status, 413);
  } finally {
    h.close();
  }
});

test('commands are refused unless enabled, then forwarded to the gateway', async () => {
  const off = await harness(false);
  try {
    const r = await off.call('/core/ocpp/2.0.1/configuration/reset?identifier=A&tenantId=1', {method: 'POST', body: '{}'});
    assert.equal(r.status, 403);
    assert.equal(off.seen.gateway.length, 0);
  } finally {
    off.close();
  }
  const on = await harness(true);
  try {
    const r = await on.call('/core/ocpp/2.0.1/configuration/reset?identifier=A&tenantId=1',
      {method: 'POST', body: '{"type":"Immediate"}'});
    assert.equal(r.status, 200);
    assert.deepEqual(on.seen.gateway.at(-1), {url: '/ocpp/2.0.1/configuration/reset?identifier=A&tenantId=1',
      auth: `Bearer ${TOKEN}`, body: '{"type":"Immediate"}'});
  } finally {
    on.close();
  }
});

test('only the Supervisor Ingress peer may connect', async () => {
  const proxy = createProxy({gatewayUrl: 'http://127.0.0.1:9', token: TOKEN, commands: true,
    nextPort: 9, peer: '172.30.32.2'});
  const port = await listen(proxy);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/hasura/v1/graphql`, {method: 'POST', body: '{}'});
    assert.equal(r.status, 403);
  } finally {
    proxy.close();
  }
});
