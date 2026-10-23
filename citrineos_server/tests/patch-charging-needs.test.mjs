import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {patch,applyEdits,sha256,main,UPSTREAM_SHA256,PATCHED_SHA256,MARKER,EDITS,TARGET} from '../rootfs/patch-charging-needs.mjs';

// The exact compiled file from the pinned image (both architectures share the layer).
const FIXTURE=new URL('./fixtures/notify-ev-charging-needs-request-ocpp-2-handler.v2.0.1.js',import.meta.url);
const upstream=fs.readFileSync(FIXTURE,'utf8');
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'citrine-needs-'));
test.after(()=>fs.rmSync(tmp,{recursive:true,force:true}));

test('fixture is the pinned upstream build',()=>{
  assert.equal(sha256(upstream),UPSTREAM_SHA256);
  assert.match(TARGET,/node_modules\/@citrineos\/ocpp\/dist\/src\/handlers\/requests\/2\/notify-ev-charging-needs-request-ocpp-2-handler\.js$/);
});
test('patch is exact, idempotent and parses',()=>{
  const patched=patch(upstream);
  assert.equal(sha256(patched),PATCHED_SHA256);
  assert.equal(patch(patched),patched);
  assert.equal(patched.split(MARKER).length-1,2);
  for(const {replacement} of EDITS)assert.equal(patched.split(replacement).length-1,1);
  const file=path.join(tmp,'syntax.mjs');fs.writeFileSync(file,patched);
  assert.equal(spawnSync(process.execPath,['--check',file]).status,0);
});
test('any other upstream text fails the build',()=>{
  assert.throws(()=>patch(upstream.replace('K17.FR.06','K17')),/not the pinned/);
  assert.throws(()=>applyEdits(upstream.replace(EDITS[1].anchor,'')),/found 0 times/);
  assert.throws(()=>applyEdits(upstream+EDITS[0].anchor),/found 2 times/);
  assert.throws(()=>applyEdits(applyEdits(upstream)),/already partly patched/);
});
test('build step patches once; --check passes only for a patched file',()=>{
  const file=path.join(tmp,'notify-ev-charging-needs-request-ocpp-2-handler.js');
  fs.writeFileSync(file,upstream);
  assert.throws(()=>main(['--check',file]),/not patched/);
  main([file]);
  assert.equal(sha256(fs.readFileSync(file,'utf8')),PATCHED_SHA256);
  main([file]);
  assert.doesNotThrow(()=>main(['--check',file]));
});

// Runs the compiled handler with its imports replaced by small fakes.
const STUBS=`class AbstractHandler{constructor(logger){this._logger=logger;}createHandlerReceivedMessageLog(n){return n;}}
const AsRequestHandler=()=>c=>c;
const EnergyTransferModeEnum={DC:'DC'};
const EventGroup={SmartCharging:'SmartCharging'};
const NotifyEVChargingNeedsStatusEnum={Accepted:'Accepted',Rejected:'Rejected'};
const OCPP_2_VER_LIST=[];const OCPP_CallAction={NotifyEVChargingNeeds:'NotifyEVChargingNeeds',SetChargingProfile:'SetChargingProfile'};
const OCPP2_common_types={},OCPP2_request_types={},OCPP2_response_types={};
const OCPP2_0_1_Mapper={ChargingProfileMapper:{fromChargingProfileType:p=>p}};
`;
async function load(text,name) {
  const body=text.replace(/^import [\s\S]*?;$/gm,'');
  const file=path.join(tmp,name);fs.writeFileSync(file,STUBS+body);
  return (await import(pathToFileURL(file).href)).NotifyEVChargingNeedsRequestOcpp2Handler;
}
function harness(Handler,{transaction={id:7},storeFails=false}={}) {
  const log={results:[],calls:[],needs:[],profiles:[]};
  const quiet={info(){},error(){}};
  const handler=new Handler({
    logger:quiet,
    ocppSender:{
      async sendCallResultWithMessage(_m,payload){log.results.push(payload.status);},
      async sendCall(call){log.calls.push(call);},
    },
    transactionEventRepository:{async getActiveTransactionByStationIdAndEvseId(){return transaction;}},
    chargingProfileRepository:{
      async createChargingNeeds(_t,request){if(storeFails)throw new Error('db');log.needs.push(request.chargingNeeds.requestedEnergyTransfer);return {id:1};},
      async createOrUpdateChargingProfile(_t,p){log.profiles.push(p);return p;},
    },
    smartChargingService:{async calculateChargingProfile(request){
      if(!['AC_single_phase','AC_two_phase','AC_three_phase','DC'].includes(request.chargingNeeds.requestedEnergyTransfer))
        throw new Error('Unsupported energy transfer mode');
      return {id:1,stackLevel:2};
    }},
  });
  return {handler,log};
}
const msg=needs=>({payload:{evseId:1,chargingNeeds:needs},context:{tenantId:1,ocppConnectionName:'TRIALOG-201'}});
// Trialog's NotifyEVChargingNeeds at 10:19:01 AEDT, 23 October 2026 (trimmed).
const trialog={controlMode:'DynamicControl',requestedEnergyTransfer:'DC_BPT',availableEnergyTransfer:['DC_BPT'],
  dcChargingParameters:{evMaxPower:50000,evMaxCurrent:100000,evMaxVoltage:500},
  v2xChargingParameters:{maxChargePower:50000,maxDischargePower:-50000}};

test('upstream rejects DC_BPT; the patch accepts it, stores the needs and sends no profile',async()=>{
  const Up=await load(upstream,'up.mjs');
  const up=harness(Up);
  await up.handler.handle(msg(trialog));
  assert.deepEqual(up.log.results,['Rejected']);

  const Patched=await load(patch(upstream),'patched.mjs');
  const p=harness(Patched);
  await p.handler.handle(msg(trialog));
  assert.deepEqual(p.log.results,['Accepted']);
  assert.deepEqual(p.log.needs,['DC_BPT']);
  assert.equal(p.log.calls.length,0);
  assert.equal(p.log.profiles.length,0);
  for(const mode of ['DC_ACDP','DC_ACDP_BPT']) {
    const h=harness(Patched);
    await h.handler.handle(msg({...trialog,requestedEnergyTransfer:mode}));
    assert.deepEqual(h.log.results,['Accepted']);
  }
});
test('OCPP 2.1 V2X needs with only v2xChargingParameters (OCTT AC_BPT, AC) are accepted without a profile',async()=>{
  const Up=await load(upstream,'up-v2x.mjs');
  const Patched=await load(patch(upstream),'patched-v2x.mjs');
  // OCTT's NotifyEVChargingNeeds at 12:26:15 AEDT, 23 October 2026.
  const octt={controlMode:'ScheduledControl',requestedEnergyTransfer:'AC_BPT',
    availableEnergyTransfer:['AC_single_phase','AC_two_phase','AC_three_phase','AC_BPT','AC_BPT_DER','AC_DER'],
    v2xChargingParameters:{maxChargePower:1234,maxDischargePower:0}};
  const up=harness(Up);
  await up.handler.handle(msg(octt));
  assert.deepEqual(up.log.results,['Rejected']);
  for(const needs of [octt,{...octt,requestedEnergyTransfer:'AC_single_phase'},
    {...octt,requestedEnergyTransfer:'AC_single_phase',acChargingParameters:{evMaxCurrent:16}}]) {
    const h=harness(Patched);
    await h.handler.handle(msg(needs));
    assert.deepEqual(h.log.results,['Accepted']);
    assert.deepEqual(h.log.needs,[needs.requestedEnergyTransfer]);
    assert.equal(h.log.calls.length,0);
  }
});
test('the patch still rejects without a transaction or charging parameters, and accepts if storing fails',async()=>{
  const Patched=await load(patch(upstream),'patched2.mjs');
  const none=harness(Patched,{transaction:null});
  await none.handler.handle(msg(trialog));
  assert.deepEqual(none.log.results,['Rejected']);
  const noParams=harness(Patched);
  await noParams.handler.handle(msg({requestedEnergyTransfer:'DC_BPT'}));
  assert.deepEqual(noParams.log.results,['Rejected']);
  const fails=harness(Patched,{storeFails:true});
  await fails.handler.handle(msg(trialog));
  assert.deepEqual(fails.log.results,['Accepted']);
});
test('2.0.1 modes are unchanged: DC and AC get the upstream automatic profile',async()=>{
  const Patched=await load(patch(upstream),'patched3.mjs');
  for(const needs of [
    {requestedEnergyTransfer:'DC',dcChargingParameters:{evMaxPower:50000}},
    {requestedEnergyTransfer:'AC_three_phase',acChargingParameters:{evMaxCurrent:16}},
  ]) {
    const h=harness(Patched);
    await h.handler.handle(msg(needs));
    assert.deepEqual(h.log.results,['Accepted']);
    assert.equal(h.log.calls.length,1);
    assert.equal(h.log.calls[0].action,'SetChargingProfile');
  }
  // DC needs without dcChargingParameters stay Rejected, as upstream.
  const h=harness(Patched);
  await h.handler.handle(msg({requestedEnergyTransfer:'DC'}));
  assert.deepEqual(h.log.results,['Rejected']);
});
