import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {patch,applyEdits,sha256,main,UPSTREAM_SHA256,PATCHED_SHA256,MARKER,EDITS,TARGET,ALLOWED_ENERGY_TRANSFER} from '../rootfs/patch-allowed-energy.mjs';

// The exact compiled file from the pinned image (both architectures share the layer).
const FIXTURE=new URL('./fixtures/authorize-request-ocpp-21-handler.v2.0.1.js',import.meta.url);
const upstream=fs.readFileSync(FIXTURE,'utf8');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'citrine-aet-'));
test.after(()=>fs.rmSync(tmp,{recursive:true,force:true}));

test('fixture is the pinned upstream build',()=>{
  assert.equal(sha256(upstream),UPSTREAM_SHA256);
  assert.match(TARGET,/node_modules\/@citrineos\/ocpp\/dist\/src\/handlers\/requests\/2\/authorize-request-ocpp-21-handler\.js$/);
});
test('patch is exact, idempotent and parses',()=>{
  const patched=patch(upstream);
  assert.equal(sha256(patched),PATCHED_SHA256);
  assert.equal(patch(patched),patched);
  assert.equal(patched.split(MARKER).length-1,1);
  for(const {replacement} of EDITS)assert.equal(patched.split(replacement).length-1,1);
  const file=path.join(tmp,'syntax.mjs');fs.writeFileSync(file,patched);
  assert.equal(spawnSync(process.execPath,['--check',file]).status,0);
});
test('any other upstream text fails the build',()=>{
  assert.throws(()=>patch(upstream.replace('C07.FR.13','C07')),/not the pinned/);
  assert.throws(()=>applyEdits(upstream.replace(EDITS[0].anchor,'')),/found 0 times/);
  assert.throws(()=>applyEdits(upstream+EDITS[0].anchor),/found 2 times/);
  assert.throws(()=>applyEdits(applyEdits(upstream)),/already partly patched/);
});
test('build step patches once; --check passes only for a patched file',()=>{
  const file=path.join(tmp,'authorize-request-ocpp-21-handler.js');
  fs.writeFileSync(file,upstream);
  assert.throws(()=>main(['--check',file]),/not patched/);
  main([file]);
  assert.equal(sha256(fs.readFileSync(file,'utf8')),PATCHED_SHA256);
  main([file]);
  assert.doesNotThrow(()=>main(['--check',file]));
});

// Runs the compiled handler's _sendAuthorizeResult with its imports replaced by fakes.
const STUBS=`class AbstractHandler{constructor(logger){this._logger=logger;}}
const AsRequestHandler=()=>c=>c,recordAuthorizeResult=()=>{};class OcppError extends Error{}
const AttributeEnum={},ErrorCode={},IdTokenEnum={},OCPP2_1={},OCPP_CallAction={},OCPPVersion={},OCPP2_request_types={},OCPP2_response_types={};
const AuthorizationStatusEnum={Accepted:'Accepted',Unknown:'Unknown',Invalid:'Invalid',Blocked:'Blocked',Expired:'Expired'};
const AuthorizeCertificateStatusEnum={Accepted:'Accepted'};
class CertificateAuthorityService{};const validateOcpp21IdToken=()=>({isValid:true});const OCPP2_1_Mapper={};
`;
async function load(text,name) {
  const body=text.replace(/^import [\s\S]*?;$/gm,'');
  const file=path.join(tmp,name);fs.writeFileSync(file,STUBS+body);
  return (await import(pathToFileURL(file).href)).AuthorizeRequestOcpp21Handler;
}
async function send(Handler,response) {
  const sent=[];
  const h=Object.create(Handler.prototype);
  h._ocppSender={async sendCallResultWithMessage(_m,r){sent.push(r);return r;}};
  await h._sendAuthorizeResult({protocol:'ocpp2.1'},response);
  return sent[0];
}
test('upstream omits allowedEnergyTransfer; the patch adds the lab modes to Accepted only',async()=>{
  const Up=await load(upstream,'up.mjs');
  const up=await send(Up,{idTokenInfo:{status:'Accepted'}});
  assert.equal(up.allowedEnergyTransfer,undefined);

  const P=await load(patch(upstream),'patched.mjs');
  const ok=await send(P,{idTokenInfo:{status:'Accepted'},certificateStatus:'Accepted'});
  assert.deepEqual(ok.allowedEnergyTransfer,ALLOWED_ENERGY_TRANSFER);
  assert.ok(ok.allowedEnergyTransfer.includes('DC_BPT')&&ok.allowedEnergyTransfer.includes('AC_BPT'));
  assert.equal(ok.certificateStatus,'Accepted');
  for(const status of ['Unknown','Invalid','Blocked','Expired']) {
    const r=await send(P,{idTokenInfo:{status}});
    assert.equal(r.allowedEnergyTransfer,undefined,status);
  }
  const own=await send(P,{idTokenInfo:{status:'Accepted'},allowedEnergyTransfer:['DC']});
  assert.deepEqual(own.allowedEnergyTransfer,['DC']);
});
