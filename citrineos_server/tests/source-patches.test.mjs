// Source patches (patches/*.patch) against CitrineOS v2.1.0, which the image
// build applies with `git apply` (Dockerfile) and fails on any that does not
// apply. These tests use the exact upstream files at the pinned commit
// (fixtures/*.v2.1.0.ts, checked by git blob ID): each patch applies cleanly
// and only once, and the patched TypeScript, with its imports replaced by
// small fakes and its types stripped by Node, behaves as the compiled-JS
// patches of 0.7.4 to 0.7.7 did. CI also compiles the patched source and runs
// upstream's own tests for both handlers (citrineos.yml, upstream-patches).
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

const ROOT = new URL('..', import.meta.url);
const COMMIT = '4fd7599b91c2fb6e6065e7c9b94be69880cced27';
const DIR = 'packages/ocpp/src/handlers/requests/2';
// patch -> the upstream file it changes and that file's git blob at COMMIT.
// A patch that changes several files lists them in `files` (each as above) and
// the files it adds in `creates`; markers counts its tags in each file.
const H = 'packages/ocpp/src/handlers';
const PATCHES = {
  '0001-ocpp21-charging-needs.patch': {
    file: `${DIR}/notify-ev-charging-needs-request-ocpp-2-handler.ts`,
    blob: '4db548aa871b81c3c482d35c940aee16ca2b5c34',
    fixture: 'notify-ev-charging-needs-request-ocpp-2-handler.v2.1.0.ts',
    markers: 3,
  },
  '0002-ocpp21-allowed-energy-transfer.patch': {
    file: `${DIR}/authorize-request-ocpp-21-handler.ts`,
    blob: '4535d0ed5d30fe64aeb58451c7aedbe47fab2a21',
    fixture: 'authorize-request-ocpp-21-handler.v2.1.0.ts',
    markers: 1,
  },
  '0003-ocpp21-der-control.patch': {
    files: [
      {file: 'packages/base/src/interfaces/schema/mapping-schema.ts',
        blob: 'b26a9929ea7f2d97907f1bafd448fbc11aa86dd9', fixture: 'mapping-schema.v2.1.0.ts', markers: 2},
      {file: 'packages/base/src/ocpp/rpc/2/schemas.ts',
        blob: '35d2a042bc7b07aaeb219a20181a4e2b7d65561e', fixture: 'rpc-2-schemas.v2.1.0.ts', markers: 0},
      {file: 'packages/ocpp/src/apis/ocpp/2/smart-charging.ts',
        blob: 'b8ee306446dd069903615355b9c1065c42caaaaf', fixture: 'smart-charging.v2.1.0.ts', markers: 1},
      {file: `${H}/index.ts`,
        blob: '98ad9da8528d0b10dae026f62743d83bf8fb524e', fixture: 'handlers-index.v2.1.0.ts', markers: 1},
      {file: 'packages/ocpp/src/modules/smart-charging/register.ts',
        blob: '68a129689a1c92c5867680f4c1f412df824e25ad', fixture: 'smart-charging-register.v2.1.0.ts', markers: 1},
      {file: 'packages/ocpp/test/apis/ocpp/smart-charging-endpoint-list.test.ts',
        blob: '02f6846234dd47c20447e40babbfebd4dff7b6fe', fixture: 'smart-charging-endpoint-list.test.v2.1.0.ts', markers: 0},
    ],
    creates: [
      ...['report-der-control', 'notify-der-start-stop', 'notify-der-alarm']
        .map(a => ({file: `${H}/requests/2/${a}-request-ocpp-21-handler.ts`, markers: 1})),
      ...['set-der-control', 'get-der-control', 'clear-der-control']
        .map(a => ({file: `${H}/responses/2/${a}-response-ocpp-21-handler.ts`, markers: 1})),
      {file: 'packages/ocpp/test/handlers/requests/2/der-control-ocpp-21-handlers.test.ts', markers: 0},
    ],
  },
};
// The upstream files a patch changes, and every file it touches.
const changes = entry => entry.files ?? [entry];
const touched = entry => [...changes(entry), ...(entry.creates ?? [])];
const read = rel => fs.readFileSync(new URL(rel, ROOT), 'utf8');
const gitBlob = text => {
  const body = Buffer.from(text);
  return crypto.createHash('sha1').update(`blob ${body.length}\0`).update(body).digest('hex');
};
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'citrine-src-'));
test.after(() => fs.rmSync(tmp, {recursive: true, force: true}));

// A scratch tree holding the pinned upstream files at their paths.
function tree(name) {
  const dir = path.join(tmp, name);
  for (const {file, fixture} of Object.values(PATCHES).flatMap(changes)) {
    fs.mkdirSync(path.join(dir, path.dirname(file)), {recursive: true});
    fs.writeFileSync(path.join(dir, file), read(`tests/fixtures/${fixture}`));
  }
  return dir;
}
const gitApply = (dir, args) => spawnSync('git', ['apply', ...args], {cwd: dir, encoding: 'utf8'});
function patched(name) {
  const {file} = PATCHES[name];
  const dir = tree(`patched-${name}`);
  const r = gitApply(dir, [fileURLPath(`patches/${name}`)]);
  assert.equal(r.status, 0, r.stderr);
  return fs.readFileSync(path.join(dir, file), 'utf8');
}
const fileURLPath = rel => new URL(rel, ROOT).pathname;

test('fixtures are the upstream files at the pinned commit', () => {
  const lock = JSON.parse(read('compatibility-lock.json'));
  assert.equal(lock.server.commit, COMMIT);
  assert.deepEqual(lock.server.patches, Object.keys(PATCHES));
  for (const {fixture, blob} of Object.values(PATCHES).flatMap(changes))
    assert.equal(gitBlob(read(`tests/fixtures/${fixture}`)), blob, fixture);
});
test('patches/ holds exactly these patches, each changing only its listed files', () => {
  assert.deepEqual(fs.readdirSync(new URL('patches/', ROOT)).sort(), Object.keys(PATCHES));
  for (const [name, entry] of Object.entries(PATCHES)) {
    const text = read(`patches/${name}`);
    assert.deepEqual([...text.matchAll(/^diff --git a\/(\S+) b\/(\S+)$/gm)].map(m => [m[1], m[2]]).sort(),
      touched(entry).map(({file}) => [file, file]).sort(), name);
    for (const {file} of entry.creates ?? [])
      assert.match(text, new RegExp(`^diff --git a/${file} b/${file}\\nnew file mode`, 'm'), file);
    assert.match(text, new RegExp(`^ha-citrine source patch \\d{4} against CitrineOS v2\\.1\\.0\\n\\(${COMMIT}\\)`), name);
  }
});
test('every patch applies cleanly to the pinned source, and only once', () => {
  const dir = tree('all');
  for (const name of Object.keys(PATCHES)) {
    const patch = fileURLPath(`patches/${name}`);
    const check = gitApply(dir, ['--check', patch]);
    assert.equal(check.status, 0, `${name}: ${check.stderr}`);
    assert.equal(gitApply(dir, [patch]).status, 0, name);
    // Applied twice it fails, as the build would on an already patched tree.
    assert.notEqual(gitApply(dir, ['--check', patch]).status, 0, name);
  }
  for (const [name, entry] of Object.entries(PATCHES)) {
    const tag = `ha-citrine patch (${name.replace(/\.patch$/, '')})`;
    for (const {file, markers} of touched(entry)) {
      const text = fs.readFileSync(path.join(dir, file), 'utf8');
      assert.equal(text.split(tag).length - 1, markers, `${name} ${file}`);
    }
  }
});
test('a patch that no longer matches upstream fails to apply', () => {
  const dir = tree('drift');
  const {file} = PATCHES['0001-ocpp21-charging-needs.patch'];
  const target = path.join(dir, file);
  fs.writeFileSync(target, fs.readFileSync(target, 'utf8')
    .replace('givenNeeds.requestedEnergyTransfer === EnergyTransferModeEnum.DC', 'givenNeeds.requestedEnergyTransfer == EnergyTransferModeEnum.DC'));
  assert.notEqual(gitApply(dir, ['--check', fileURLPath('patches/0001-ocpp21-charging-needs.patch')]).status, 0);
});

// Loads a handler class from TypeScript: imports are replaced by the fakes in
// stubs and the decorator is dropped; Node strips the type annotations.
async function load(source, stubs, name, className) {
  const body = source.replace(/^import [\s\S]*?;$/gm, '').replace(/^@AsRequestHandler\(.*\)$/m, '');
  const file = path.join(tmp, `${name}.ts`);
  fs.writeFileSync(file, stubs + body);
  return (await import(pathToFileURL(file).href))[className];
}

const NEEDS_STUBS = `class AbstractHandler{constructor(logger){this._logger=logger;}createHandlerReceivedMessageLog(n){return n;}}
const EnergyTransferModeEnum={DC:'DC'};
const EventGroup={SmartCharging:'SmartCharging'};
const NotifyEVChargingNeedsStatusEnum={Accepted:'Accepted',Rejected:'Rejected'};
const OCPP_2_VER_LIST=[];const OCPP_CallAction={NotifyEVChargingNeeds:'NotifyEVChargingNeeds',SetChargingProfile:'SetChargingProfile'};
const OCPP2_0_1_Mapper={ChargingProfileMapper:{fromChargingProfileType:p=>p}};
`;
const NEEDS = '0001-ocpp21-charging-needs.patch';
const upstreamNeeds = () => load(read(`tests/fixtures/${PATCHES[NEEDS].fixture}`), NEEDS_STUBS, `up-${Math.random()}`,
  'NotifyEVChargingNeedsRequestOcpp2Handler');
const patchedNeeds = () => load(patched(NEEDS), NEEDS_STUBS, `patched-${Math.random()}`,
  'NotifyEVChargingNeedsRequestOcpp2Handler');
function harness(Handler, {transaction = {id: 7}, storeFails = false} = {}) {
  const log = {results: [], calls: [], needs: [], profiles: []};
  const handler = new Handler({
    logger: {info() {}, error() {}},
    ocppSender: {
      async sendCallResultWithMessage(_m, payload) { log.results.push(payload.status); },
      async sendCall(call) { log.calls.push(call); },
    },
    transactionRepository: {async getActiveTransactionByStationIdAndEvseId() { return transaction; }},
    chargingProfileRepository: {
      async createChargingNeeds(_t, request) {
        if (storeFails) throw new Error('db');
        log.needs.push(request.chargingNeeds.requestedEnergyTransfer); return {id: 1};
      },
      async createOrUpdateChargingProfile(_t, p) { log.profiles.push(p); return p; },
    },
    smartChargingService: {async calculateChargingProfile(request) {
      if (!['AC_single_phase', 'AC_two_phase', 'AC_three_phase', 'DC'].includes(request.chargingNeeds.requestedEnergyTransfer))
        throw new Error('Unsupported energy transfer mode');
      return {id: 1, stackLevel: 2};
    }},
  });
  return {handler, log};
}
const msg = needs => ({payload: {evseId: 1, chargingNeeds: needs}, context: {tenantId: 1, ocppConnectionName: 'TRIALOG-201'}});
// Trialog's NotifyEVChargingNeeds at 10:19:01 AEDT, 23 October 2026 (trimmed).
const trialog = {controlMode: 'DynamicControl', requestedEnergyTransfer: 'DC_BPT', availableEnergyTransfer: ['DC_BPT'],
  dcChargingParameters: {evMaxPower: 50000, evMaxCurrent: 100000, evMaxVoltage: 500},
  v2xChargingParameters: {maxChargePower: 50000, maxDischargePower: -50000}};

test('charging needs: upstream rejects DC_BPT; patched, it accepts, stores the needs and sends no profile', async () => {
  const up = harness(await upstreamNeeds());
  await up.handler.handle(msg(trialog));
  assert.deepEqual(up.log.results, ['Rejected']);

  const Patched = await patchedNeeds();
  const p = harness(Patched);
  await p.handler.handle(msg(trialog));
  assert.deepEqual(p.log.results, ['Accepted']);
  assert.deepEqual(p.log.needs, ['DC_BPT']);
  assert.equal(p.log.calls.length, 0);
  assert.equal(p.log.profiles.length, 0);
  // The other OCPP 2.1 DC modes, with dcChargingParameters only.
  for (const mode of ['DC_BPT', 'DC_ACDP', 'DC_ACDP_BPT']) {
    const h = harness(Patched);
    await h.handler.handle(msg({requestedEnergyTransfer: mode, dcChargingParameters: trialog.dcChargingParameters}));
    assert.deepEqual(h.log.results, ['Accepted'], mode);
    assert.deepEqual(h.log.needs, [mode], mode);
    assert.equal(h.log.calls.length, 0, mode);
  }
});
test('charging needs: OCPP 2.1 V2X needs with only v2xChargingParameters (OCTT AC_BPT, AC) are accepted without a profile', async () => {
  const Patched = await patchedNeeds();
  // OCTT's NotifyEVChargingNeeds at 12:26:15 AEDT, 23 October 2026.
  const octt = {controlMode: 'ScheduledControl', requestedEnergyTransfer: 'AC_BPT',
    availableEnergyTransfer: ['AC_single_phase', 'AC_two_phase', 'AC_three_phase', 'AC_BPT', 'AC_BPT_DER', 'AC_DER'],
    v2xChargingParameters: {maxChargePower: 1234, maxDischargePower: 0}};
  const up = harness(await upstreamNeeds());
  await up.handler.handle(msg(octt));
  assert.deepEqual(up.log.results, ['Rejected']);
  for (const needs of [octt, {...octt, requestedEnergyTransfer: 'AC_single_phase'},
    {...octt, requestedEnergyTransfer: 'AC_single_phase', acChargingParameters: {evMaxCurrent: 16}},
    {...octt, requestedEnergyTransfer: 'DC', dcChargingParameters: {evMaxPower: 50000}}]) {
    const h = harness(Patched);
    await h.handler.handle(msg(needs));
    assert.deepEqual(h.log.results, ['Accepted']);
    assert.deepEqual(h.log.needs, [needs.requestedEnergyTransfer]);
    assert.equal(h.log.calls.length, 0);
  }
});
test('charging needs: still rejected without a transaction or charging parameters; accepted if storing fails', async () => {
  const Patched = await patchedNeeds();
  const none = harness(Patched, {transaction: null});
  await none.handler.handle(msg(trialog));
  assert.deepEqual(none.log.results, ['Rejected']);
  for (const needs of [{requestedEnergyTransfer: 'DC_BPT'}, {requestedEnergyTransfer: 'DC_BPT', acChargingParameters: null,
    dcChargingParameters: null}, {requestedEnergyTransfer: 'AC_BPT'}]) {
    const h = harness(Patched);
    await h.handler.handle(msg(needs));
    assert.deepEqual(h.log.results, ['Rejected'], JSON.stringify(needs));
  }
  const fails = harness(Patched, {storeFails: true});
  await fails.handler.handle(msg(trialog));
  assert.deepEqual(fails.log.results, ['Accepted']);
});
test('charging needs: 2.0.1 modes are unchanged, DC and AC get the upstream automatic profile', async () => {
  const Patched = await patchedNeeds();
  for (const needs of [
    {requestedEnergyTransfer: 'DC', dcChargingParameters: {evMaxPower: 50000}},
    {requestedEnergyTransfer: 'AC_three_phase', acChargingParameters: {evMaxCurrent: 16}},
  ]) {
    for (const Handler of [Patched, await upstreamNeeds()]) {
      const h = harness(Handler);
      await h.handler.handle(msg(needs));
      assert.deepEqual(h.log.results, ['Accepted']);
      assert.equal(h.log.calls.length, 1);
      assert.equal(h.log.calls[0].action, 'SetChargingProfile');
      assert.equal(h.log.profiles.length, 1);
    }
  }
  // DC needs without dcChargingParameters stay Rejected, as upstream.
  for (const needs of [{requestedEnergyTransfer: 'DC'}, {requestedEnergyTransfer: 'DC', acChargingParameters: {evMaxCurrent: 16}}]) {
    const h = harness(Patched);
    await h.handler.handle(msg(needs));
    assert.deepEqual(h.log.results, ['Rejected'], JSON.stringify(needs));
  }
});

const AET = '0002-ocpp21-allowed-energy-transfer.patch';
const ALLOWED_ENERGY_TRANSFER = ['DC', 'DC_BPT', 'AC_single_phase', 'AC_two_phase', 'AC_three_phase', 'AC_BPT'];
const AUTH_STUBS = `class AbstractHandler{constructor(logger){this._logger=logger;}}
const recordAuthorizeResult=()=>{};class OcppError extends Error{}
const AttributeEnum={},ErrorCode={},IdTokenEnum={},OCPP2_1={},OCPP_CallAction={},OCPPVersion={},OCPP2_request_types={},OCPP2_response_types={};
const AuthorizationStatusEnum={Accepted:'Accepted',Unknown:'Unknown',Invalid:'Invalid',Blocked:'Blocked',Expired:'Expired'};
const AuthorizeCertificateStatusEnum={Accepted:'Accepted'};
class CertificateAuthorityService{};const validateOcpp21IdToken=()=>({isValid:true});const OCPP2_1_Mapper={};
`;
async function send(Handler, response) {
  const sent = [];
  const h = Object.create(Handler.prototype);
  h._ocppSender = {async sendCallResultWithMessage(_m, r) { sent.push(r); return r; }};
  await h._sendAuthorizeResult({protocol: 'ocpp2.1'}, response);
  return sent[0];
}
test('allowedEnergyTransfer: upstream omits it; patched, Accepted responses carry the lab modes', async () => {
  const name = 'AuthorizeRequestOcpp21Handler';
  const Up = await load(read(`tests/fixtures/${PATCHES[AET].fixture}`), AUTH_STUBS, 'auth-up', name);
  assert.equal((await send(Up, {idTokenInfo: {status: 'Accepted'}})).allowedEnergyTransfer, undefined);

  const source = patched(AET);
  assert.ok(source.includes(`'${ALLOWED_ENERGY_TRANSFER.join("',\n          '")}'`));
  const P = await load(source, AUTH_STUBS, 'auth-patched', name);
  const ok = await send(P, {idTokenInfo: {status: 'Accepted'}, certificateStatus: 'Accepted'});
  assert.deepEqual(ok.allowedEnergyTransfer, ALLOWED_ENERGY_TRANSFER);
  assert.equal(ok.certificateStatus, 'Accepted');
  for (const status of ['Unknown', 'Invalid', 'Blocked', 'Expired']) {
    const r = await send(P, {idTokenInfo: {status}});
    assert.equal(r.allowedEnergyTransfer, undefined, status);
  }
  // A response that already sets the field keeps it.
  const own = await send(P, {idTokenInfo: {status: 'Accepted'}, allowedEnergyTransfer: ['DC']});
  assert.deepEqual(own.allowedEnergyTransfer, ['DC']);
  // The caller's response object is not changed.
  const original = {idTokenInfo: {status: 'Accepted'}};
  await send(P, original);
  assert.equal(original.allowedEnergyTransfer, undefined);
});
