import test from 'node:test';
import assert from 'node:assert/strict';
import {ROUTES,STATION,validateCommand,targetAllows} from '../rootfs/control-policy.mjs';
const url=i=>new URL('http://lab'+ROUTES[i]+'?identifier='+STATION+'&tenantId=1');
const start={remoteStartId:12,evseId:1,idToken:{type:'ISO14443',idToken:'C17E0001'}};
const profile=()=>({evseId:1,chargingProfile:{id:9001,stackLevel:1,chargingProfilePurpose:'TxProfile',
  chargingProfileKind:'Relative',transactionId:'test-123',
  chargingSchedule:[{id:1,duration:240,chargingRateUnit:'W',
    chargingSchedulePeriod:[6000,-5000,3000,0].map((setpoint,i)=>({
      startPeriod:i*60,limit:11000,dischargeLimit:-11000,setpoint,operationMode:'CentralSetpoint'}))}]}});
const state=(active=true)=>({data:{
  ChargingStations:[{id:2,tenantId:1,ocppConnectionName:STATION,protocol:'ocpp2.1',isOnline:true}],
  Transactions:active?[{stationId:2,tenantId:1,transactionId:'test-123',isActive:true}]:[],
}});
test('only exact station, protocol route and tenant; no callbacks or duplicate routing',()=>{
  assert.equal(validateCommand(url(0),start),true);
  for(const query of ['identifier=REAL&tenantId=1','identifier='+STATION+'&tenantId=2',
    'identifier='+STATION+'&tenantId=1&callbackUrl=https://other',
    'identifier='+STATION+'&identifier=REAL&tenantId=1']) {
    assert.equal(validateCommand(new URL('http://lab'+ROUTES[0]+'?'+query),start),false);
  }
  const fallback=url(2);fallback.pathname=fallback.pathname.replace('2.1','2.0.1');
  assert.equal(validateCommand(fallback,profile()),false);
});
test('multi-step import/discharge/zero profile is constrained in W',()=>{
  assert.equal(validateCommand(url(2),profile()),true);
  for(const change of [{setpoint:-11001},{setpoint:11001},{dischargeLimit:1},
    {dischargeLimit:-11001},{limit:11001},{limit:-1},{limit:NaN},{setpoint:Infinity},
    {setpoint:null},{operationMode:'LocalFrequency'},{numberPhases:3}]) {
    const bad=profile();Object.assign(bad.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0],change);
    assert.equal(validateCommand(url(2),bad),false,JSON.stringify(change));
  }
  const outside=profile();outside.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0].limit=2000;
  assert.equal(validateCommand(url(2),outside),false);
});
test('duration, timestamp, purpose, sequence and transaction are not silently repaired',()=>{
  for(const mutate of [
    p=>p.chargingProfile.chargingSchedule[0].duration=601,
    p=>p.chargingProfile.transactionId='',
    p=>p.chargingProfile.chargingProfilePurpose='TxDefaultProfile',
    p=>p.chargingProfile.chargingSchedule[0].chargingRateUnit='A',
    p=>p.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[1].startPeriod=0,
    p=>p.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0].startPeriod=1,
    p=>p.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[3].startPeriod=240,
    p=>p.chargingProfile.chargingSchedule[0].startSchedule='2026-10-11T00:00:00Z',
  ]){const p=profile();mutate(p);assert.equal(validateCommand(url(2),p),false);}
  const p=profile();p.chargingProfile.chargingProfileKind='Absolute';
  assert.equal(validateCommand(url(2),p),false);
  p.chargingProfile.chargingSchedule[0].startSchedule='2026-10-11T00:00:00Z';
  assert.equal(validateCommand(url(2),p),true);
});
test('explicit stop and clear IDs; no clear-all',()=>{
  assert.equal(validateCommand(url(1),{transactionId:'test-123'}),true);
  assert.equal(validateCommand(url(1),{transactionId:'',extra:1}),false);
  assert.equal(validateCommand(url(3),{chargingProfileId:9001}),true);
  for(const p of [{},{evseId:1},{chargingProfileId:0},{chargingProfileCriteria:{evseId:1}}])
    assert.equal(validateCommand(url(3),p),false);
});
test('observed station and exact active transaction required; no start or clear during session',()=>{
  assert.equal(targetAllows(url(2),profile(),state()),true);
  assert.equal(targetAllows(url(1),{transactionId:'test-123'},state()),true);
  assert.equal(targetAllows(url(1),{transactionId:'other'},state()),false);
  assert.equal(targetAllows(url(0),start,state()),false);
  assert.equal(targetAllows(url(0),start,state(false)),true);
  assert.equal(targetAllows(url(3),{chargingProfileId:9001},state()),false);
  assert.equal(targetAllows(url(3),{chargingProfileId:9001},state(false)),true);
  for(const change of [{protocol:'ocpp2.0.1'},{isOnline:false},{ocppConnectionName:'REAL'},{tenantId:2}]) {
    const s=state();Object.assign(s.data.ChargingStations[0],change);
    assert.equal(targetAllows(url(2),profile(),s),false);
  }
  const foreign=state();foreign.data.Transactions[0].stationId=1;
  assert.equal(targetAllows(url(2),profile(),foreign),false);
  const duplicate=state();duplicate.data.Transactions.push({...duplicate.data.Transactions[0]});
  assert.equal(targetAllows(url(2),profile(),duplicate),false);
  assert.equal(targetAllows(url(2),profile(),{}),false);
});
