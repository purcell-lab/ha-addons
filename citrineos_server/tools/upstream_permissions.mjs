// Lists every API route a CitrineOS build registers, with the permission
// name its JWT authorisation checks, as tests/fixtures/citrineos-routes.v2.1.0.json.
// The control-policy tests check the roles seed against it.
//
// Usage, against a build of the pinned source with patches/ applied (as the
// Dockerfile builds it):
//
//   git -C /tmp/core checkout 4fd7599b91c2fb6e6065e7c9b94be69880cced27
//   git -C /tmp/core apply citrineos_server/patches/*.patch
//   (cd /tmp/core && corepack enable && pnpm install --frozen-lockfile \
//     && pnpm --filter "@citrineos/ocpp-server..." build)
//   node citrineos_server/tools/upstream_permissions.mjs /tmp/core \
//     > citrineos_server/tests/fixtures/citrineos-routes.v2.1.0.json
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const core = path.resolve(process.argv[2] ?? '');
const load = file => import(pathToFileURL(path.join(core, file)).href);
const register = await load('packages/ocpp/dist/src/apis/register.js');
const {messagePermissionName, commandPermissionName} = await load('packages/base/dist/index.js');
const routes = {};
for (const endpoint of register.MESSAGE_ENDPOINTS) {
  const route = endpoint.route;
  const action = String(route.action);
  for (const version of route.protocols) {
    // Upstream skips a version whose schema is not available (no route).
    let schema = null;
    try { schema = route.bodySchema(version); } catch { schema = null; }
    if (!schema) continue;
    const url = `/ocpp/${version.replace(/^ocpp/, '')}/${route.eventGroup}/${action[0].toLowerCase()}${action.slice(1)}`;
    routes[`POST ${url}`] = messagePermissionName(route);
  }
}
for (const [prefix, endpoints] of register.COMMAND_SURFACES) {
  for (const endpoint of endpoints) {
    const url = `/${[prefix, endpoint.route.path].join('/').split('/').filter(Boolean).join('/')}`;
    routes[`${endpoint.route.method.toUpperCase()} ${url}`] = commandPermissionName(prefix, endpoint.route);
  }
}
const sorted = Object.fromEntries(Object.entries(routes).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
console.log(JSON.stringify({
  release: 'v2.1.0',
  commit: '4fd7599b91c2fb6e6065e7c9b94be69880cced27',
  routes: sorted,
}, null, 1));
