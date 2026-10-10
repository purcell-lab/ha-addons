// Component contract test against the compiled, digest-pinned upstream image.
// Actual routing/schema code; inert endpoint handlers; NO server.run/listen.
// This proves route compatibility only, not auth, storage, broker or OCPP delivery.
import {createRequire} from 'node:module';
import {dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';

const requireApp = createRequire(
  '/usr/local/apps/citrineos/apps/ocpp-server/package.json');
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
})});
registerApiServices(container);
const routes = [];
fastify.addHook('onRoute', route => {
  const methods = Array.isArray(route.method) ? route.method : [route.method];
  for (const method of methods) routes.push({method, url: route.url});
});
for (const [file, name, key] of [
  ['admin-api.js', 'AdminApi', 'adminEndpoints'],
  ['commands-api.js', 'CommandsApi', 'commandEndpoints'],
  ['web-payment-api.js', 'WebPaymentApi', 'webPaymentEndpoints'],
  ['ocpp-message-api.js', 'OcppMessageApi', 'messageEndpoints'],
]) {
  const module = await load(`apis/${file}`);
  new module[name]({
    server: fastify, logger, config: {swagger: {exposeMessage: false}},
    [key]: container.resolve(key),
  });
}
await fastify.ready();
assert.ok(routes.length > 50, 'Expected real upstream API registration');
assert.equal(routes.some(r => r.url.startsWith('/data/')), false);
const ping = await fastify.inject({method: 'GET', url: '/data/ocpprouter/systemConfig'});
assert.equal(ping.statusCode, 404);
for (const version of ['1.6', '2.0.1', '2.1']) {
  assert.ok(fastify.hasRoute({
    method: 'POST', url: `/ocpp/${version}/smartcharging/setChargingProfile`,
  }), `missing ${version} profile route`);
}
assert.equal(handlerCalls, 0, 'No control handler may run');
const report = {
  assessment: 'blocked',
  test_scope: 'compiled_api_route_registration_with_inert_handlers',
  legacy_ping_http_status: ping.statusCode,
  actual_station_commands: 0,
  full_stack_verified: false,
  authentication_verified: false,
  routes,
};
writeFileSync(process.env.ROUTE_REPORT || '/tmp/citrine-routes.json',
  JSON.stringify(report, null, 2));
console.log(JSON.stringify({assessment: report.assessment,
  legacy_ping_http_status: ping.statusCode, registered_routes: routes.length}));
await fastify.close();
