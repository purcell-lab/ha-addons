import test from 'node:test';
import assert from 'node:assert/strict';
import {ROUTES,STATION,validateCommand,targetAllows,commandStation,stationAllowed,routesFor,
  routeProtocol,COMMANDS_BY_PROTOCOL} from '../rootfs/control-policy.mjs';
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
    {dischargeLimit:-25001},{limit:25001},{limit:-1},{limit:NaN},{setpoint:Infinity},
    {setpoint:null},{operationMode:'LocalFrequency'},{numberPhases:2},{numberPhases:'1'},
    {phaseToUse:1},{numberPhases:3,phaseToUse:1},{numberPhases:1,phaseToUse:4},{operationMode:'ChargingOnly'}]) {
    const bad=profile();Object.assign(bad.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0],change);
    assert.equal(validateCommand(url(2),bad),false,JSON.stringify(change));
  }
  const outside=profile();outside.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0].limit=2000;
  assert.equal(validateCommand(url(2),outside),false);
});
test('single-phase AC watt profile: numberPhases and charging-only periods (#39)',()=>{
  const ac=(periods)=>{const p=profile();p.chargingProfile.chargingSchedule[0].chargingSchedulePeriod=periods;return p;};
  const steps=[6000,3000,7000,0].map((limit,i)=>({startPeriod:i*60,limit,numberPhases:1}));
  assert.equal(validateCommand(url(2),ac(steps)),true);
  assert.equal(validateCommand(url(2),ac(steps.map(x=>({...x,operationMode:'ChargingOnly'})))),true);
  assert.equal(validateCommand(url(2),ac(steps.map(x=>({...x,phaseToUse:2})))),true);
  assert.equal(validateCommand(url(2),ac(steps.map(x=>({...x,numberPhases:3})))),true);
  assert.equal(validateCommand(url(2),ac([{startPeriod:0,limit:7000}])),true);
  // 3-phase 32 A AC (about 22 kW) fits the 25 kW import bound.
  assert.equal(validateCommand(url(2),ac([{startPeriod:0,limit:22080,numberPhases:3}])),true);
  assert.equal(validateCommand(url(2),ac([{startPeriod:0,limit:25000,numberPhases:3}])),true);
  // V2G discharge up to 25 kW.
  const dis=profile();Object.assign(dis.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[1],{limit:25000,dischargeLimit:-25000,setpoint:-25000});
  assert.equal(validateCommand(url(2),dis),true);
  // V2G periods may carry numberPhases too.
  const v2g=profile();v2g.chargingProfile.chargingSchedule[0].chargingSchedulePeriod.forEach(x=>x.numberPhases=3);
  assert.equal(validateCommand(url(2),v2g),true);
  for(const bad of [
    {startPeriod:0,limit:6000,numberPhases:2},
    {startPeriod:0,limit:6000,numberPhases:1,setpoint:3000},
    {startPeriod:0,limit:6000,dischargeLimit:-1000},
    {startPeriod:0,limit:25001,numberPhases:3},
    {startPeriod:0,limit:6000,operationMode:'ExternalSetpoint'},
  ]) assert.equal(validateCommand(url(2),ac([bad])),false,JSON.stringify(bad));
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
test('configured command station replaces the default target, never widens it',()=>{
  const other='SIM-EV-EVEREST-V2G-02';
  const at=i=>new URL('http://lab'+ROUTES[i]+'?identifier='+other+'&tenantId=1');
  assert.equal(validateCommand(at(0),start,other),true);
  assert.equal(validateCommand(url(0),start,other),false);
  assert.equal(validateCommand(at(0),start),false);
  for(const bad of ['REAL-CHARGER','SIM-EV-','SIM-CITRINE-LAB-01'])
    assert.equal(validateCommand(new URL('http://lab'+ROUTES[0]+'?identifier='+bad+'&tenantId=1'),start,bad),false);
  const s=state();s.data.ChargingStations[0].ocppConnectionName=other;
  assert.equal(targetAllows(at(2),profile(),s,other),true);
  assert.equal(targetAllows(at(2),profile(),s),false);
  assert.equal(commandStation({}),STATION);
  assert.equal(commandStation({command_station_id:other}),other);
});
test('physical command station: only with the real-stations flag, any OCPP identity',()=>{
  const real='ACME-WB-0042';
  const at=(i,routes=ROUTES)=>new URL('http://lab'+routes[i]+'?identifier='+real+'&tenantId=1');
  assert.equal(validateCommand(at(0),start,real),false);
  assert.equal(validateCommand(at(0),start,real,true),true);
  assert.equal(stationAllowed(real),false);
  assert.equal(stationAllowed(real,true),true);
  assert.equal(stationAllowed('SIM-EV-EVEREST-G1'),true);
  for(const bad of ['has space','a/b','a:b','',  'x'.repeat(49)]) assert.equal(stationAllowed(bad,true),false,bad);
  // The flag widens the identity only: the configured station is still the one target.
  assert.equal(validateCommand(at(0),start,'OTHER-1',true),false);
});
test('OCPP 2.0.1 routes: charging-only periods, and the route must match the station protocol',()=>{
  assert.deepEqual(Object.keys(COMMANDS_BY_PROTOCOL),['ocpp2.1','ocpp2.0.1','ocpp1.6']);
  const v201=routesFor('ocpp2.0.1');
  assert.equal(v201[2],'/ocpp/2.0.1/smartcharging/setChargingProfile');
  assert.equal(routeProtocol(v201[2]),'ocpp2.0.1');
  assert.equal(routeProtocol('/ocpp/1.6/evdriver/requestStartTransaction'),null);
  const at=i=>new URL('http://lab'+v201[i]+'?identifier='+STATION+'&tenantId=1');
  const ac=()=>{const p=profile();p.chargingProfile.chargingSchedule[0].chargingSchedulePeriod=
    [{startPeriod:0,limit:7000,numberPhases:3},{startPeriod:60,limit:0,numberPhases:3}];return p;};
  assert.equal(validateCommand(at(2),ac()),true);
  assert.equal(validateCommand(at(2),profile()),false,'2.0.1 has no CentralSetpoint');
  const only=ac();only.chargingProfile.chargingSchedule[0].chargingSchedulePeriod[0].operationMode='ChargingOnly';
  assert.equal(validateCommand(at(2),only),false,'2.0.1 has no operationMode');
  assert.equal(validateCommand(at(0),start),true);
  assert.equal(validateCommand(at(1),{transactionId:'test-123'}),true);
  assert.equal(validateCommand(at(3),{chargingProfileId:9001}),true);
  const s201=state();s201.data.ChargingStations[0].protocol='ocpp2.0.1';
  assert.equal(targetAllows(at(2),ac(),s201),true);
  assert.equal(targetAllows(url(2),profile(),s201),false,'2.1 route to a 2.0.1 station');
  assert.equal(targetAllows(at(2),ac(),state()),false,'2.0.1 route to a 2.1 station');
});
test('transaction IDs accept OCPP identifierString characters',()=>{
  for(const id of ['a1:b2.c3','TX@1|2+3=4','*abc*']) {
    assert.equal(validateCommand(url(1),{transactionId:id}),true,id);
    const s=state();s.data.Transactions[0].transactionId=id;
    assert.equal(targetAllows(url(1),{transactionId:id},s),true,id);
  }
  for(const id of ['a b','a/b','x'.repeat(65),'é']) assert.equal(validateCommand(url(1),{transactionId:id}),false,id);
});
test('OCPP 1.6 routes: 1.6 payload shapes, integer transaction IDs, charging-only',()=>{
  const v16=routesFor('ocpp1.6');
  assert.deepEqual(v16,['/ocpp/1.6/evdriver/remoteStartTransaction','/ocpp/1.6/evdriver/remoteStopTransaction',
    '/ocpp/1.6/smartcharging/setChargingProfile','/ocpp/1.6/smartcharging/clearChargingProfile']);
  assert.equal(routeProtocol(v16[0]),'ocpp1.6');
  const at=i=>new URL('http://lab'+v16[i]+'?identifier='+STATION+'&tenantId=1');
  const p16=(x={})=>({connectorId:1,csChargingProfiles:{chargingProfileId:9001,stackLevel:1,
    chargingProfilePurpose:'TxProfile',chargingProfileKind:'Absolute',transactionId:42,
    chargingSchedule:{startSchedule:'2026-10-17T00:00:00.000Z',duration:240,chargingRateUnit:'W',
      chargingSchedulePeriod:[{startPeriod:0,limit:7000,numberPhases:3},{startPeriod:60,limit:0}]},...x}});
  assert.equal(validateCommand(at(0),{connectorId:1,idTag:'C17E0001'}),true);
  assert.equal(validateCommand(at(0),start),false,'2.x start shape');
  assert.equal(validateCommand(at(0),{connectorId:2,idTag:'C17E0001'}),false);
  assert.equal(validateCommand(at(1),{transactionId:42}),true);
  assert.equal(validateCommand(at(1),{transactionId:'42'}),false,'1.6 transaction IDs are integers');
  assert.equal(validateCommand(at(3),{id:9001}),true);
  assert.equal(validateCommand(at(3),{}),false,'no clear-all');
  assert.equal(validateCommand(at(3),{chargingProfileId:9001}),false);
  assert.equal(validateCommand(at(2),p16()),true);
  assert.equal(validateCommand(at(2),profile()),false,'2.x profile shape');
  for(const bad of [{limit:7000.5},{limit:-1},{limit:25001},{setpoint:0},{phaseToUse:1},{numberPhases:2}]) {
    const p=p16();Object.assign(p.csChargingProfiles.chargingSchedule.chargingSchedulePeriod[0],bad);
    assert.equal(validateCommand(at(2),p),false,JSON.stringify(bad));
  }
  assert.equal(validateCommand(at(2),p16({transactionId:'42'})),false);
  assert.equal(validateCommand(at(2),p16({chargingProfilePurpose:'TxDefaultProfile'})),false);
  const p=p16();p.csChargingProfiles.chargingSchedule.chargingRateUnit='A';
  assert.equal(validateCommand(at(2),p),false);
  const s16=state();s16.data.ChargingStations[0].protocol='ocpp1.6';s16.data.Transactions[0].transactionId='42';
  assert.equal(targetAllows(at(2),p16(),s16),true);
  assert.equal(targetAllows(at(1),{transactionId:42},s16),true);
  assert.equal(targetAllows(at(1),{transactionId:43},s16),false);
  assert.equal(targetAllows(at(0),{connectorId:1,idTag:'C17E0001'},s16),false,'already active');
  assert.equal(targetAllows(at(3),{id:9001},state(false)),false,'1.6 route to a 2.1 station');
  const idle=state(false);idle.data.ChargingStations[0].protocol='ocpp1.6';
  assert.equal(targetAllows(at(3),{id:9001},idle),true);
});
test('RBAC rules are generated from the gateway route list',async()=>{
  const {rbacRules,ALL_ROUTES,COMMAND_ROLE,CONFIG_UPSTREAM}=await import('../rootfs/control-policy.mjs');
  const {readFileSync}=await import('node:fs');
  const base=JSON.parse(readFileSync(new URL('../rootfs/rbac-rules.json',import.meta.url)));
  const on=rbacRules(base,true)['1'];
  // Every route the gateway accepts for scoped commands, on 2.1, 2.0.1 and 1.6.
  for(const route of ALL_ROUTES) assert.ok(on[route].POST.includes(COMMAND_ROLE),route);
  assert.equal(ALL_ROUTES.length,12);
  // Nothing else gains the command role, and other roles keep their rules.
  for(const [route,methods] of Object.entries(on))
    for(const [method,roles] of Object.entries(methods))
      if(roles.includes(COMMAND_ROLE)&&!ALL_ROUTES.includes(route)&&route!==CONFIG_UPSTREAM)
        assert.deepEqual(roles,base['1'][route][method],route);
  // Read-only station configuration (OCPP 1.6 GetConfiguration) for the command role only.
  assert.deepEqual(on[CONFIG_UPSTREAM],{POST:['lab-controller']});
  assert.deepEqual(on['/ocpp/2.0.1/evdriver/requestStartTransaction'].POST,['lab-controller','lab-operator']);
  assert.deepEqual(on['/ocpp/1.6/evdriver/remoteStartTransaction'].POST,['lab-controller']);
  // Off: the command role holds no scoped route; operator rules remain.
  const off=rbacRules(base,false)['1'];
  for(const route of ALL_ROUTES) assert.ok(!(off[route]?.POST||[]).includes(COMMAND_ROLE),route);
  assert.equal(off['/ocpp/1.6/evdriver/remoteStartTransaction'],undefined);
  assert.equal(off[CONFIG_UPSTREAM],undefined);
  assert.deepEqual(off['/ocpp/2.1/smartcharging/setChargingProfile'].POST,['lab-operator']);
  // Idempotent when re-applied to its own output, and the base is not mutated.
  assert.deepEqual(rbacRules(rbacRules(base,true),true),rbacRules(base,true));
  assert.ok(!('/ocpp/1.6/evdriver/remoteStartTransaction' in base['1']));
});

test('station configuration reads only listed keys from an online 1.6 command station',async()=>{
  const {validateConfigRequest,configTargetAllows,configResult,CONFIG_KEYS}=await import('../rootfs/control-policy.mjs');
  assert.ok(validateConfigRequest({key:['ChargingScheduleAllowedChargingRateUnit']}));
  assert.ok(validateConfigRequest({key:CONFIG_KEYS}));
  for(const p of [{},{key:[]},{key:'ChargingScheduleMaxPeriods'},{key:['AuthorizationKey']},
    {key:['ChargingScheduleMaxPeriods','ChargingScheduleMaxPeriods']},
    {key:['ChargingScheduleMaxPeriods'],extra:1},null,[]])
    assert.equal(validateConfigRequest(p),false,JSON.stringify(p));
  const st=(over={})=>({data:{ChargingStations:[{id:3,tenantId:1,ocppConnectionName:'110A432M0039',protocol:'ocpp1.6',isOnline:true,...over}]}});
  assert.ok(configTargetAllows(st(),'110A432M0039'));
  assert.equal(configTargetAllows(st({protocol:'ocpp2.0.1'}),'110A432M0039'),false);
  assert.equal(configTargetAllows(st({isOnline:false}),'110A432M0039'),false);
  assert.equal(configTargetAllows(st(),'OTHER'),false);
  assert.equal(configTargetAllows({data:{ChargingStations:[]}},'110A432M0039'),false);
  // Unrequested keys the station volunteers are dropped; values are bounded.
  const r=configResult({configurationKey:[
    {key:'ChargingScheduleAllowedChargingRateUnit',readonly:true,value:'Current'},
    {key:'AuthorizationKey',readonly:false,value:'secret'},
    {key:'ChargingScheduleMaxPeriods',value:'x'.repeat(900)}],unknownKey:['MaxChargingProfilesInstalled','Other']},
    ['ChargingScheduleAllowedChargingRateUnit','ChargingScheduleMaxPeriods','MaxChargingProfilesInstalled']);
  assert.deepEqual(r.configurationKey[0],{key:'ChargingScheduleAllowedChargingRateUnit',readonly:true,value:'Current'});
  assert.equal(r.configurationKey.length,2);
  assert.equal(r.configurationKey[1].value.length,500);
  assert.deepEqual(r.unknownKey,['MaxChargingProfilesInstalled']);
  assert.ok(!JSON.stringify(r).includes('secret'));
  assert.ok(configResult({errorCode:'NotImplemented'},['ChargingScheduleMaxPeriods']).error);
});
