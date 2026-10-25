// Component contract test against the compiled upstream build in the image
// (CitrineOS v2.1.0 from source). Actual routing/schema code; inert endpoint
// handlers; NO server.run/listen. This proves route compatibility and the
// permission each route declares, not auth, storage, broker or OCPP delivery.
// CITRINE_APP selects another ocpp-server folder (a local pnpm deploy).
import {createRequire} from 'node:module';
import {dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const APP = process.env.CITRINE_APP || '/usr/local/apps/citrineos/apps/ocpp-server';
const requireApp = createRequire(join(APP, 'package.json'));
const ocppRoot = dirname(requireApp.resolve('@citrineos/ocpp'));
const requireOcpp = createRequire(join(ocppRoot, 'index.js'));
const load = path => import(pathToFileURL(join(ocppRoot, 'src', path)).href);
const {createContainer, asValue} = requireOcpp('awilix');
const fastify = requireOcpp('fastify')({logger: false});
const {OCPPValidator} = await import(
  pathToFileURL(requireApp.resolve('@citrineos/base')).href);
// Match CitrineOSServer.registerAjv without constructing its server/dependencies.
const ajv = OCPPValidator.createServerAjvInstance();
fastify.setValidatorCompiler(({schema}) => ajv.compile(schema));
const {Logger} = requireOcpp('tslog');
const logger = new Logger({type: 'hidden'});
const {registerApiServices} = await load('apis/register.js');
const container = createContainer();
let handlerCalls = 0;
container.register({moduleScope: asValue({
  build: () => ({handle: async () => {handlerCalls++; return [];}}),
}), config: asValue({auth: {mode: 'jwt'}})});
registerApiServices(container);
const routes = [];
fastify.addHook('onRoute', route => {
  const methods = Array.isArray(route.method) ? route.method : [route.method];
  for (const method of methods)
    routes.push({method, url: route.url, permission: route.config?.permission ?? null});
});
for (const [file, name, key] of [
  ['admin-api.js', 'AdminApi', 'adminEndpoints'],
  ['commands-api.js', 'CommandsApi', 'commandEndpoints'],
  ['web-payment-api.js', 'WebPaymentApi', 'webPaymentEndpoints'],
  ['ocpp-message-api.js', 'OcppMessageApi', 'messageEndpoints'],
  ['permissions-api.js', 'PermissionsApi', 'permissionEndpoints'],
  // auth.mode jwt (the lab's setting): the token-minting /dev routes are not built.
  ['dev-api.js', 'DevApi', 'devEndpoints'],
]) {
  const module = await load(`apis/${file}`);
  new module[name]({
    server: fastify, logger, config: {swagger: {exposeMessage: false}},
    [key]: container.resolve(key),
  });
}
assert.ok(routes.length > 50, 'Expected real upstream API registration');
assert.equal(routes.some(r => r.url.startsWith('/data/')), false);
assert.equal(fastify.hasRoute({
  method: 'GET', url: '/data/ocpprouter/systemConfig',
}), false);
for (const version of ['1.6', '2.0.1', '2.1']) {
  assert.ok(fastify.hasRoute({
    method: 'POST', url: `/ocpp/${version}/smartcharging/setChargingProfile`,
  }), `missing ${version} profile route`);
}
assert.equal(routes.some(r => r.url.startsWith('/dev')), false, 'No /dev route in jwt mode');
// Every route declares the permission CitrineOS's JWT authorisation checks.
assert.deepEqual(routes.filter(r => !r.permission), []);
const permission = (method, url) => routes.find(r => r.method === method && r.url === url)?.permission;
assert.equal(permission('GET', '/commands/tariff'), 'commands.tariff.get');
assert.equal(permission('POST', '/ocpp/2.1/smartcharging/setChargingProfile'),
  'ocpp.smartcharging.setChargingProfile');
assert.equal(handlerCalls, 0, 'No control handler may run');
// Retain, rather than mask, the failure observed when compiling the upstream
// inline-schema path with its own server AJV. This is NOT a claim about a full
// deployment with default exposeMessage=true. A changed result needs review.
await assert.rejects(fastify.ready(), error =>
  error.code === 'FST_ERR_SCH_VALIDATION_BUILD' &&
  error.message.includes('MessageQuerystring') &&
  error.message.includes('already exists'));
const report = {
  assessment: 'blocked',
  test_scope: 'compiled_api_route_registration_with_inert_handlers',
  dev_routes_registered: false,
  legacy_ping_registered: false,
  inline_schema_compilation: 'blocked_duplicate_MessageQuerystring',
  inline_schema_setting: {swagger: {exposeMessage: false}},
  default_schema_mode_verified: false,
  actual_station_commands: 0,
  full_stack_verified: false,
  authentication_verified: false,
  routes,
};
writeFileSync(process.env.ROUTE_REPORT || '/tmp/citrine-routes.json',
  JSON.stringify(report, null, 2));
console.log(JSON.stringify({assessment: report.assessment,
  legacy_ping_registered: false, registered_routes: routes.length,
  inline_schema_compilation: report.inline_schema_compilation}));
await fastify.close();
