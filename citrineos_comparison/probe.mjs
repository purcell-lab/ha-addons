// Compiled API components only. No server.run/listen, auth plugin or real handlers.
import {createRequire} from 'node:module';
import {dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {existsSync, writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const app = createRequire('/usr/local/apps/citrineos/apps/ocpp-server/package.json');
const root = dirname(app.resolve('@citrineos/ocpp'));
const req = createRequire(join(root, 'index.js'));
const load = path => import(pathToFileURL(join(root, 'src', path)).href);
const {createContainer, asValue} = req('awilix');
const Fastify = req('fastify');
const {Logger} = req('tslog');
const baseUrl = pathToFileURL(app.resolve('@citrineos/base')).href;
const {OCPPValidator} = await import(baseUrl);
const {registerApiServices} = await load('apis/register.js');
const logger = new Logger({type: 'hidden'});
let handlerCalls = 0;

async function inspect(exposeMessage) {
  const server = Fastify({logger: false});
  const ajv = OCPPValidator.createServerAjvInstance();
  server.setValidatorCompiler(({schema}) => ajv.compile(schema));
  const container = createContainer();
  container.register({moduleScope: asValue({
    build: () => ({handle: async () => {handlerCalls++; throw Error('Handler invocation forbidden');}}),
  })});
  registerApiServices(container);
  const routes = [];
  server.addHook('onRoute', route => {
    for (const method of [].concat(route.method)) {
      routes.push({method, url: route.url,
        staleAfterSeconds: !!route.schema?.querystring?.properties?.staleAfterSeconds});
    }
  });
  for (const [file, name, key] of [
    ['admin-api.js', 'AdminApi', 'adminEndpoints'],
    ['commands-api.js', 'CommandsApi', 'commandEndpoints'],
    ['web-payment-api.js', 'WebPaymentApi', 'webPaymentEndpoints'],
    ['ocpp-message-api.js', 'OcppMessageApi', 'messageEndpoints'],
  ]) {
    const module = await load(`apis/${file}`);
    new module[name]({server, logger, config: {swagger: {exposeMessage}},
      [key]: container.resolve(key)});
  }
  let compilation = {status: 'passed'};
  try {
    await server.ready();
  } catch (error) {
    // Schema failures are findings, not silently substituted validators.
    // Unexpected loader/dependency/program errors must fail the CI job.
    if (!String(error.code).startsWith('FST_ERR_SCH_')) throw error;
    compilation = {status: 'failed', code: error.code,
      detail: error.message.slice(0, 600)};
  } finally {
    await server.close();
  }
  assert.equal(handlerCalls, 0);
  return {exposeMessage, compilation, routes};
}

const inline = await inspect(false);
const shared = await inspect(true);
assert.ok(inline.routes.length > 50, 'Incomplete compiled API catalogue');
const has = (method, url) => inline.routes.some(r => r.method === method && r.url === url);
assert.ok(has('GET', '/commands/tariff'), 'Protected-read route missing');
for (const version of ['1.6', '2.0.1', '2.1']) {
  assert.ok(has('POST', `/ocpp/${version}/smartcharging/setChargingProfile`));
}

const stalenessFile = join(dirname(app.resolve('@citrineos/base')), 'src/util/staleness.js');
let staleness = {available: false, helper_checks_passed: false};
if (existsSync(stalenessFile)) {
  const {outboundDeadline} = await import(pathToFileURL(stalenessFile).href);
  const {MessageOrigin, MessageState} = await import(
    pathToFileURL(app.resolve('@citrineos/types')).href);
  const start = Date.parse('2026-10-10T00:00:00Z');
  const timeouts = {staleCallMaxAgeSeconds: 40, maxCallLengthSeconds: 20};
  const request = {origin: MessageOrigin.ChargingStationManagementSystem,
    state: MessageState.Request, context: {timestamp: new Date(start).toISOString()}};
  assert.equal(outboundDeadline(timeouts, request), start + 40_000);
  assert.equal(outboundDeadline(timeouts, {...request, context: {...request.context, staleAfterSeconds: 5}}), start + 5_000);
  assert.equal(outboundDeadline(timeouts, {...request, context: {...request.context, staleAfterSeconds: 0}}), undefined);
  assert.equal(outboundDeadline(timeouts, {...request, origin: MessageOrigin.ChargingStation}), undefined);
  assert.equal(outboundDeadline(timeouts, {...request, state: MessageState.Response}), start + 20_000);
  staleness = {available: true, helper_checks_passed: true, checks: 5};
}
const report = {
  schema_version: 1,
  commit: process.env.SOURCE_COMMIT,
  scope: 'compiled_components_with_inert_handlers',
  legacy_ping_registered: has('GET', '/data/ocpprouter/systemConfig'),
  legacy_data_routes: inline.routes.filter(r => r.url.startsWith('/data/')),
  tariff_read_registered: has('GET', '/commands/tariff'),
  inline, shared, staleness,
  station_commands: handlerCalls,
  full_stack_verified: false, authentication_verified: false,
  default_server_boot_verified: false, deployment_allowed: false,
};
assert.match(report.commit, /^[a-f0-9]{40}$/);
writeFileSync(process.env.REPORT_PATH, JSON.stringify(report, null, 2));
console.log(JSON.stringify({commit: report.commit,
  inline: inline.compilation, shared: shared.compilation,
  legacy_ping_registered: report.legacy_ping_registered, staleness}));
