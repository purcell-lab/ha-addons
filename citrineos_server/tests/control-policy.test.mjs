import test from 'node:test';
import assert from 'node:assert/strict';
import {ROUTES,STATION,validateCommand,targetAllows,commandStation,stationAllowed,routesFor,
  routeProtocol,COMMANDS_BY_PROTOCOL,hasPriceSchedule,validateCostUpdated,costTargetAllows,validateTariff,
  tariffTarget,tariffTargetAllows,pricePolicy,tariffStations,roleRoutes,rolesSeed,permissionName,PRICE_ROUTES,COMMAND_ROLE,ALL_ROUTES}
  from '../rootfs/control-policy.mjs';
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
// The CitrineOS v2.0.1 role rules of 0.7.7 (rbac-rules.json and the rbacRules
// generator, unchanged), kept to show that the v2.1.0 roles seed grants every
// role exactly the routes it had: {role: Set of "METHOD route"}.
const fixture=async name=>JSON.parse((await import('node:fs')).readFileSync(new URL(`./fixtures/${name}`,import.meta.url)));
async function legacyRoutes(commandsEnabled,priceEnabled=false,reportsEnabled=false) {
  const {CONFIG_UPSTREAM,STATUS_ROUTES,REPORT_ROUTES,REPORT_ROLE}=await import('../rootfs/control-policy.mjs');
  const rules=await fixture('rbac-rules.v0.7.7.json');
  const tenant=rules['1'];
  const grant=(route,role,on)=>{
    const roles=(tenant[route]?.POST||[]).filter(r=>r!==role);
    if(on) roles.unshift(role);
    if(roles.length) tenant[route]={...tenant[route],POST:roles};
    else if(tenant[route]) { delete tenant[route].POST; if(!Object.keys(tenant[route]).length) delete tenant[route]; }
  };
  for(const route of [...ALL_ROUTES,CONFIG_UPSTREAM,...Object.values(STATUS_ROUTES),...PRICE_ROUTES])
    grant(route,COMMAND_ROLE,commandsEnabled===true&&(!PRICE_ROUTES.includes(route)||priceEnabled===true));
  for(const route of Object.values(REPORT_ROUTES)) grant(route,REPORT_ROLE,reportsEnabled===true);
  const out={'lab-reader':new Set(),'lab-controller':new Set(),'lab-operator':new Set(),'lab-reporter':new Set()};
  for(const [route,methods] of Object.entries(tenant))
    for(const [method,roles] of Object.entries(methods)) for(const role of roles) out[role].add(`${method} ${route}`);
  return out;
}
const FLAGS=[false,true].flatMap(c=>[false,true].flatMap(p=>[false,true].map(r=>[c,p,r])));
const asSet=routes=>new Set(routes.map(({method,route})=>`${method} ${route}`));
test('each role gets exactly the upstream routes it had with CitrineOS v2.0.1',async()=>{
  for(const flags of FLAGS) {
    const legacy=await legacyRoutes(...flags), now=roleRoutes(...flags);
    assert.deepEqual(Object.keys(now).sort(),Object.keys(legacy).sort());
    for(const role of Object.keys(now)) assert.deepEqual(asSet(now[role]),legacy[role],`${role} ${flags}`);
  }
  const on=roleRoutes(true);
  // Every route the gateway accepts for scoped commands, on 2.1, 2.0.1 and 1.6.
  for(const route of ALL_ROUTES) assert.ok(asSet(on[COMMAND_ROLE]).has(`POST ${route}`),route);
  assert.equal(ALL_ROUTES.length,12);
  // Off: the command role keeps the tariff read only; the Operator UI role is unchanged.
  assert.deepEqual(roleRoutes(false)[COMMAND_ROLE],[{method:'GET',route:'/commands/tariff'}]);
  assert.deepEqual(roleRoutes(false)['lab-operator'],on['lab-operator']);
});
test('the roles seed names v2.1.0 permissions, and the gateway still scopes each role to its OCPP versions',async()=>{
  const {routes:upstream}=await fixture('citrineos-routes.v2.1.0.json');
  const {operatorCommand,OPERATOR_PROTOCOLS}=await import('../rootfs/control-policy.mjs');
  for(const flags of FLAGS) {
    const seed=rolesSeed(...flags), legacy=await legacyRoutes(...flags);
    assert.deepEqual(Object.keys(seed).sort(),['lab-controller','lab-operator','lab-reader','lab-reporter']);
    for(const [role,routes] of Object.entries(roleRoutes(...flags))) {
      assert.deepEqual(seed[role].resources,{});
      // Each route exists upstream and needs the permission the seed grants.
      for(const r of routes) assert.equal(upstream[`${r.method} ${r.route}`],permissionName(r),`${role} ${r.route}`);
      assert.deepEqual(seed[role].permissions,[...new Set(routes.map(permissionName))].sort());
      // What the seed grants upstream: a permission covers every OCPP version.
      const granted=Object.entries(upstream).filter(([,p])=>seed[role].permissions.includes(p)).map(([k])=>k);
      for(const route of legacy[role]) assert.ok(granted.includes(route),`${role} ${route}`);
      const extra=granted.filter(k=>!legacy[role].has(k));
      if(role!=='lab-operator') { assert.deepEqual(extra,[],`${role} ${flags}`); continue; }
      // Only the Operator UI role gains routes: the same actions on OCPP 1.6,
      // which its gateway route (operatorCommand) refuses.
      assert.ok(extra.length>0);
      for(const k of extra) {
        assert.match(k,/^POST \/ocpp\/1\.6\//);
        assert.equal(operatorCommand(new URL(`${k.slice(5)}?identifier=CP1&tenantId=1`,'http://lab')),null,k);
      }
    }
  }
  assert.deepEqual(OPERATOR_PROTOCOLS,['ocpp2.0.1','ocpp2.1']);
  assert.equal(permissionName({method:'GET',route:'/commands/tariff'}),'commands.tariff.get');
  assert.equal(permissionName({method:'POST',route:'/ocpp/2.0.1/evdriver/requestStartTransaction'}),
    'ocpp.evdriver.requestStartTransaction');
  for(const r of [{method:'GET',route:'/ocpp/2.1/evdriver/requestStartTransaction'},{method:'POST',route:'/ocpp/2.2/a/b'},
    {method:'POST',route:'/dev/token'},{method:'GET',route:'/commands/tariff/x'}])
    assert.equal(permissionName(r),null,r.route);
  // No seed role may mint tokens or administer CitrineOS.
  const all=Object.values(rolesSeed(true,true,true)).flatMap(r=>r.permissions);
  assert.equal(all.some(p=>/^(dev|permissions|ocpprouter)\.|^commands\.(?!tariff\.get$)/.test(p)),false);
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

// Dynamic pricing (price_commands_enabled).
const AUD={enabled:true,currency:'AUD'};
const absolute=(x={})=>({timeAnchor:'2026-10-18T08:00:00+10:00',priceScheduleID:1,currency:'AUD',language:'en',
  priceAlgorithm:'urn:iso:std:iso:15118:-20:PriceAlgorithm:1-Power',
  priceRuleStacks:[225,202].map(v=>({duration:1800,priceRule:[{energyFee:{value:v,exponent:-3},powerRangeStart:{value:0,exponent:0}}]})),...x});
const levels=(x={})=>({timeAnchor:'2026-10-18T08:00:00Z',priceScheduleId:2,numberOfPriceLevels:3,
  priceLevelScheduleEntries:[{duration:1800,priceLevel:2},{duration:1800,priceLevel:0}],...x});
const priced=sched=>{const p=profile();Object.assign(p.chargingProfile.chargingSchedule[0],sched);return p;};
test('B: an OCPP 2.1 profile may carry one price schedule, only when enabled',()=>{
  assert.equal(validateCommand(url(2),priced({absolutePriceSchedule:absolute()}),STATION,false,AUD),true);
  assert.equal(validateCommand(url(2),priced({priceLevelSchedule:levels()}),STATION,false,AUD),true);
  // Unchanged without a price schedule, enabled or not.
  assert.equal(validateCommand(url(2),profile(),STATION,false,AUD),true);
  // Off (default), disabled policy, or OCPP 2.0.1: refused.
  for(const options of [undefined,null,{enabled:false,currency:'AUD'}])
    assert.equal(validateCommand(url(2),priced({absolutePriceSchedule:absolute()}),STATION,false,options),false);
  const v201=new URL('http://lab'+routesFor('ocpp2.0.1')[2]+'?identifier='+STATION+'&tenantId=1');
  const ac=priced({absolutePriceSchedule:absolute()});
  ac.chargingProfile.chargingSchedule[0].chargingSchedulePeriod=[{startPeriod:0,limit:7000}];
  assert.equal(validateCommand(v201,ac,STATION,false,AUD),false,'2.0.1 has no price schedule');
  // Both kinds at once.
  assert.equal(validateCommand(url(2),priced({absolutePriceSchedule:absolute(),priceLevelSchedule:levels()}),STATION,false,AUD),false);
  // The power bounds still apply to a priced profile.
  const big=priced({absolutePriceSchedule:absolute()});big.chargingProfile.chargingSchedule[0].duration=601;
  assert.equal(validateCommand(url(2),big,STATION,false,AUD),false);
  // A different currency than price_currency.
  assert.equal(validateCommand(url(2),priced({absolutePriceSchedule:absolute()}),STATION,false,{enabled:true,currency:'EUR'}),false);
  assert.ok(hasPriceSchedule(priced({priceLevelSchedule:levels()})));
  assert.equal(hasPriceSchedule(profile()),false);
});
test('B: absolutePriceSchedule bounds',()=>{
  const ok=a=>validateCommand(url(2),priced({absolutePriceSchedule:a}),STATION,false,AUD);
  const stack=(duration,v=100)=>({duration,priceRule:[{energyFee:{value:v,exponent:-3},powerRangeStart:{value:0,exponent:0}}]});
  assert.equal(ok(absolute({priceRuleStacks:Array.from({length:288},()=>stack(300))})),true,'288 x 5 min');
  assert.equal(ok(absolute({priceRuleStacks:[stack(172800)]})),true,'48 h horizon');
  assert.equal(ok(absolute({priceScheduleDescription:'Amber import forecast',minimumCost:{value:0,exponent:0},
    maximumCost:{value:100,exponent:0}})),true);
  assert.equal(ok(absolute({priceRuleStacks:[stack(300,-32768),stack(300,32767)]})),true,'int16 range');
  for(const [name,a] of [
    ['289 stacks',absolute({priceRuleStacks:Array.from({length:289},()=>stack(300))})],
    ['no stacks',absolute({priceRuleStacks:[]})],
    ['horizon',absolute({priceRuleStacks:[stack(172800),stack(1)]})],
    ['zero duration',absolute({priceRuleStacks:[stack(0)]})],
    ['fraction duration',absolute({priceRuleStacks:[stack(1.5)]})],
    ['int16',absolute({priceRuleStacks:[stack(300,32768)]})],
    ['exponent',absolute({priceRuleStacks:[{duration:300,priceRule:[{energyFee:{value:1,exponent:-4},powerRangeStart:{value:0,exponent:0}}]}]})],
    ['power range',absolute({priceRuleStacks:[{duration:300,priceRule:[{energyFee:{value:1,exponent:0},powerRangeStart:{value:1,exponent:0}}]}]})],
    ['no rules',absolute({priceRuleStacks:[{duration:300,priceRule:[]}]})],
    ['9 rules',absolute({priceRuleStacks:[{duration:300,priceRule:Array(9).fill(stack(1).priceRule[0])}]})],
    ['parking fee',absolute({priceRuleStacks:[{duration:300,priceRule:[{...stack(1).priceRule[0],parkingFee:{value:1,exponent:0}}]}]})],
    ['currency',absolute({currency:'USD'})],
    ['language',absolute({language:'de'})],
    ['algorithm',absolute({priceAlgorithm:'urn:iso:std:iso:15118:-20:PriceAlgorithm:2-PeakPower'})],
    ['timeAnchor',absolute({timeAnchor:'tomorrow'})],
    ['id',absolute({priceScheduleID:-1})],
    ['description',absolute({priceScheduleDescription:'x'.repeat(161)})],
    ['minimumCost',absolute({minimumCost:{value:1.5,exponent:0}})],
    ['taxRules',absolute({taxRules:[]})],
    ['overstay',absolute({overstayRuleList:{}})],
    ['services',absolute({additionalSelectedServices:[]})],
    ['missing currency',(({currency,...a})=>a)(absolute())],
  ]) assert.equal(ok(a),false,name);
});
test('B: priceLevelSchedule bounds',()=>{
  const ok=l=>validateCommand(url(2),priced({priceLevelSchedule:l}),STATION,false,AUD);
  assert.equal(ok(levels({numberOfPriceLevels:10,priceLevelScheduleEntries:Array.from({length:100},(_,i)=>({duration:300,priceLevel:i%10}))})),true);
  for(const [name,l] of [
    ['101 entries',levels({priceLevelScheduleEntries:Array.from({length:101},()=>({duration:300,priceLevel:0}))})],
    ['no entries',levels({priceLevelScheduleEntries:[]})],
    ['level out of range',levels({priceLevelScheduleEntries:[{duration:300,priceLevel:3}]})],
    ['11 levels',levels({numberOfPriceLevels:11})],
    ['0 levels',levels({numberOfPriceLevels:0})],
    ['duration',levels({priceLevelScheduleEntries:[{duration:0,priceLevel:0}]})],
    ['horizon',levels({priceLevelScheduleEntries:[{duration:172800,priceLevel:0},{duration:1,priceLevel:0}]})],
    ['ID spelling',(({priceScheduleId,...l})=>({...l,priceScheduleID:2}))(levels())],
    ['extra key',levels({priceScheduleDescription:'x'})],
    ['timeAnchor',levels({timeAnchor:'2026-10-18'})],
  ]) assert.equal(ok(l),false,name);
});
const costUrl=(v='2.1',id=STATION)=>new URL(`http://lab/ocpp/${v}/transactions/costUpdated?identifier=${id}&tenantId=1`);
const cost=(x={},d={})=>({totalCost:1.25,transactionId:'test-123',customData:{vendorId:'org.openchargealliance.costmsg',
  chargingPrice:{kWhPrice:0.225},nextPeriod:{atTime:'2026-10-18T08:00:00+10:00',chargingPrice:{kWhPrice:0.202}},
  priceText:'Amber 22.5 c/kWh now, 20.2 c/kWh from 08:00',...d},...x});
test('C: CostUpdated with California Pricing customData for the command station only',()=>{
  assert.equal(validateCostUpdated(costUrl(),cost(),STATION,false,AUD),true);
  assert.equal(validateCostUpdated(costUrl('2.0.1'),cost(),STATION,false,AUD),true);
  assert.equal(validateCostUpdated(costUrl(),cost({},{chargingPrice:{kWhPrice:-5,hourPrice:0,flatFee:20},
    nextPeriod:undefined,priceText:undefined}),STATION,false,AUD),true);
  assert.equal(validateCostUpdated(costUrl(),cost({totalCost:0}),STATION,false,AUD),true);
  // Disabled, wrong station, 1.6, or extra query parameters.
  for(const options of [undefined,{enabled:false,currency:'AUD'}])
    assert.equal(validateCostUpdated(costUrl(),cost(),STATION,false,options),false);
  assert.equal(validateCostUpdated(costUrl('2.1','SIM-EV-OTHER'),cost(),STATION,false,AUD),false);
  assert.equal(validateCostUpdated(new URL('http://lab/ocpp/1.6/transactions/costUpdated?identifier='+STATION+'&tenantId=1'),cost(),STATION,false,AUD),false);
  assert.equal(validateCostUpdated(new URL(costUrl().href+'&callbackUrl=x'),cost(),STATION,false,AUD),false);
  assert.equal(validateCostUpdated(costUrl('2.1','ACME-1'),cost(),'ACME-1',false,AUD),false,'real station needs the flag');
  assert.equal(validateCostUpdated(costUrl('2.1','ACME-1'),cost(),'ACME-1',true,AUD),true);
  for(const [name,p] of [
    ['negative total',cost({totalCost:-0.01})],['total too high',cost({totalCost:10000.01})],['total string',cost({totalCost:'1'})],
    ['transaction',cost({transactionId:'a b'})],['no customData',(({customData,...p})=>p)(cost())],
    ['vendor',cost({},{vendorId:'com.example'})],['price low',cost({},{chargingPrice:{kWhPrice:-5.01}})],
    ['price high',cost({},{chargingPrice:{kWhPrice:20.01}})],['price missing',cost({},{chargingPrice:{hourPrice:1}})],
    ['hourPrice',cost({},{chargingPrice:{kWhPrice:0.2,hourPrice:21}})],['extra price key',cost({},{chargingPrice:{kWhPrice:0.2,idlePrice:1}})],
    ['next atTime',cost({},{nextPeriod:{atTime:'08:00',chargingPrice:{kWhPrice:0.2}}})],
    ['next hourPrice',cost({},{nextPeriod:{atTime:'2026-10-18T08:00:00Z',chargingPrice:{kWhPrice:0.2,hourPrice:1}}})],
    ['priceText',cost({},{priceText:'x'.repeat(256)})],['extra customData',cost({},{qrCodeText:'x'})],
    ['extra key',cost({extra:1})],['array',[]],['null',null],
  ]) assert.equal(validateCostUpdated(costUrl(),p,STATION,false,AUD),false,name);
});
test('C: the station is online on the route version and the transaction is its active one',()=>{
  assert.equal(costTargetAllows(costUrl(),cost(),state()),true);
  assert.equal(costTargetAllows(costUrl(),cost({transactionId:'other'}),state()),false);
  assert.equal(costTargetAllows(costUrl(),cost(),state(false)),false,'no active transaction');
  assert.equal(costTargetAllows(costUrl('2.0.1'),cost(),state()),false,'2.0.1 route to a 2.1 station');
  const s201=state();s201.data.ChargingStations[0].protocol='ocpp2.0.1';
  assert.equal(costTargetAllows(costUrl('2.0.1'),cost(),s201),true);
  for(const change of [{isOnline:false},{ocppConnectionName:'REAL'},{tenantId:2}]) {
    const s=state();Object.assign(s.data.ChargingStations[0],change);
    assert.equal(costTargetAllows(costUrl(),cost(),s),false,JSON.stringify(change));
  }
  const duplicate=state();duplicate.data.Transactions.push({...duplicate.data.Transactions[0]});
  assert.equal(costTargetAllows(costUrl(),cost(),duplicate),false);
  assert.equal(costTargetAllows(costUrl(),cost(),{}),false);
});
const tariffUrl=(id=STATION,extra='')=>new URL(`http://lab/ocpp/2.1/transactions/setDefaultTariff?identifier=${id}&tenantId=1${extra}`);
const tariff=(t={},e={})=>({evseId:0,tariff:{tariffId:'amber-20261018-0800',currency:'AUD',
  description:[{format:'UTF8',language:'en',content:'Amber Electric import and feed-in'}],validFrom:'2026-10-18T08:00:00+10:00',
  energy:{prices:[
    {priceKwh:0.20455,conditions:{startTimeOfDay:'08:00',endTimeOfDay:'08:30',validFromDate:'2026-10-18',validToDate:'2026-10-18'}},
    {priceKwh:-0.04545,conditions:{startTimeOfDay:'08:00',endTimeOfDay:'08:30',minPower:-1,maxPower:-1000000}}],
    taxRates:[{type:'GST',tax:10}],...e},...t}});
test('D: SetDefaultTariff to a listed station, energy prices only',()=>{
  const stations=[STATION,'EVX-AU-001'];
  assert.equal(tariffTarget(tariffUrl(),stations,AUD),STATION);
  assert.equal(tariffTarget(tariffUrl('EVX-AU-001'),stations,AUD),'EVX-AU-001','no SIM-EV- restriction');
  assert.equal(tariffTarget(tariffUrl('EVX-AU-002'),stations,AUD),null,'not provisioned');
  assert.equal(tariffTarget(tariffUrl(STATION,'&callbackUrl=x'),stations,AUD),null);
  assert.equal(tariffTarget(new URL(tariffUrl().href.replace('2.1','2.0.1')),stations,AUD),null,'2.1 only');
  assert.equal(tariffTarget(tariffUrl(),stations,{enabled:false}),null);
  assert.equal(validateTariff(tariff(),AUD),true);
  assert.equal(validateTariff({evseId:1,tariff:{tariffId:'t',currency:'AUD',energy:{prices:[{priceKwh:0.1}]}}},AUD),true,'minimal');
  assert.equal(validateTariff(tariff({},{prices:Array.from({length:96},(_,i)=>({priceKwh:i/10-5,
    conditions:{dayOfWeek:['Saturday','Sunday']}}))}),AUD),true,'96 prices');
  assert.equal(validateTariff(tariff(),undefined),false,'disabled');
  assert.equal(validateTariff(tariff(),{enabled:true,currency:'EUR'}),false,'currency');
  for(const [name,p] of [
    ['97 prices',tariff({},{prices:Array.from({length:97},()=>({priceKwh:0.1}))})],
    ['no prices',tariff({},{prices:[]})],['price low',tariff({},{prices:[{priceKwh:-5.01}]})],
    ['price high',tariff({},{prices:[{priceKwh:20.01}]})],['price NaN',tariff({},{prices:[{priceKwh:'0.1'}]})],
    ['time of day',tariff({},{prices:[{priceKwh:0.1,conditions:{startTimeOfDay:'8:00'}}]})],
    ['24:00',tariff({},{prices:[{priceKwh:0.1,conditions:{endTimeOfDay:'24:00'}}]})],
    ['date',tariff({},{prices:[{priceKwh:0.1,conditions:{validToDate:'2026-02-30'}}]})],
    ['day',tariff({},{prices:[{priceKwh:0.1,conditions:{dayOfWeek:['Funday']}}]})],
    ['day repeated',tariff({},{prices:[{priceKwh:0.1,conditions:{dayOfWeek:['Monday','Monday']}}]})],
    ['power',tariff({},{prices:[{priceKwh:0.1,conditions:{maxPower:-1000001}}]})],
    ['charging time',tariff({},{prices:[{priceKwh:0.1,conditions:{minChargingTime:60}}]})],
    ['tax type',tariff({},{taxRates:[{type:'VAT',tax:10}]})],['tax rate',tariff({},{taxRates:[{type:'GST',tax:15}]})],
    ['two taxes',tariff({},{taxRates:[{type:'GST',tax:10},{type:'GST',tax:10}]})],
    ['no energy',(p=>{delete p.tariff.energy;return p;})(tariff())],
    ['chargingTime',tariff({chargingTime:{prices:[{priceMinute:1}]}})],['idleTime',tariff({idleTime:{prices:[]}})],
    ['fixedFee',tariff({fixedFee:{prices:[]}})],['reservationTime',tariff({reservationTime:{}})],
    ['reservationFixed',tariff({reservationFixed:{}})],['maxCost',tariff({maxCost:{exclTax:1}})],
    ['tariffId long',tariff({tariffId:'x'.repeat(61)})],['tariffId empty',tariff({tariffId:''})],
    ['lab tariff id',tariff({tariffId:'HA-LAB-ZERO'})],
    ['description language',tariff({description:[{format:'UTF8',language:'de',content:'x'}]})],
    ['description format',tariff({description:[{format:'HTML',language:'en',content:'x'}]})],
    ['description long',tariff({description:[{format:'UTF8',language:'en',content:'x'.repeat(256)}]})],
    ['4 descriptions',tariff({description:Array(4).fill({format:'UTF8',language:'en',content:'x'})})],
    ['validFrom',tariff({validFrom:'2026-10-18'})],
    ['evseId',{...tariff(),evseId:-1}],['extra',{...tariff(),customData:{vendorId:'x'}}],[ 'undefined',undefined],
  ]) assert.equal(validateTariff(p,AUD),false,name);
});
test('D: the target is online on OCPP 2.1; its transactions do not matter',()=>{
  assert.equal(tariffTargetAllows(state(),STATION),true);
  assert.equal(tariffTargetAllows(state(false),STATION),true);
  for(const change of [{protocol:'ocpp2.0.1'},{isOnline:false},{ocppConnectionName:'EVX-AU-001'},{tenantId:2}]) {
    const s=state();Object.assign(s.data.ChargingStations[0],change);
    assert.equal(tariffTargetAllows(s,STATION),false,JSON.stringify(change));
  }
});
test('control policy price_commands: enabled object, disabled {"enabled":false}',()=>{
  assert.deepEqual(pricePolicy({}),{enabled:false});
  assert.deepEqual(pricePolicy({price_commands_enabled:false,price_currency:'AUD'}),{enabled:false});
  const o={price_commands_enabled:true,price_currency:'AUD',plugfest_enabled:true,
    plugfest_stations:[{id:'EVX-AU-001',password:'p'},{id:STATION,password:'q'}]};
  assert.deepEqual(pricePolicy(o),{enabled:true,currency:'AUD',
    price_schedule:{max_rule_stacks:288,max_level_entries:100,max_horizon_s:172800},
    cost_updated_by_protocol:{'ocpp2.1':'/ocpp/2.1/transactions/costUpdated','ocpp2.0.1':'/ocpp/2.0.1/transactions/costUpdated'},
    default_tariff:'/ocpp/2.1/transactions/setDefaultTariff',
    tariff_limits:{max_prices:96,min_price_kwh:-5,max_price_kwh:20},
    tariff_stations:[STATION,'EVX-AU-001']});
  // Plugfest identities count only while the listener is on.
  assert.deepEqual(tariffStations({...o,plugfest_enabled:false}),[STATION]);
  assert.deepEqual(tariffStations({command_station_id:'SIM-EV-X'}),['SIM-EV-X']);
  assert.equal(pricePolicy({price_commands_enabled:true}).currency,'AUD');
});
test('roles: the price routes go to the command role only when both flags are on',async()=>{
  assert.deepEqual(PRICE_ROUTES,['/ocpp/2.1/transactions/costUpdated','/ocpp/2.0.1/transactions/costUpdated',
    '/ocpp/2.1/transactions/setDefaultTariff']);
  const price=['ocpp.transactions.costUpdated','ocpp.transactions.setDefaultTariff'];
  const on=rolesSeed(true,true);
  for(const p of price) assert.ok(on[COMMAND_ROLE].permissions.includes(p),p);
  for(const [commands,prices] of [[true,false],[false,true],[false,false]]) {
    const seed=rolesSeed(commands,prices);
    for(const [role,{permissions}] of Object.entries(seed))
      for(const p of price) assert.ok(!permissions.includes(p),`${commands}/${prices} ${role} ${p}`);
  }
  // Price routes do not change any other grant.
  const plain=rolesSeed(true);
  assert.deepEqual(on[COMMAND_ROLE].permissions.filter(p=>!price.includes(p)),plain[COMMAND_ROLE].permissions);
  for(const role of ['lab-reader','lab-operator','lab-reporter']) assert.deepEqual(on[role],plain[role],role);
});
test('stale transactions: which station, which route, which transactions are due',async()=>{
  const {reconcileTarget,reconcileDue,startRoute,STATUS_ROUTES,RECONCILE_EVERY_MS,ALL_ROUTES:routes}=
    await import('../rootfs/control-policy.mjs');
  const rows=(protocol='ocpp2.1',isOnline=true,tx=[{stationId:2,tenantId:1,transactionId:'test-123',isActive:true}])=>({data:{
    ChargingStations:[{id:2,tenantId:1,ocppConnectionName:STATION,protocol,isOnline}],Transactions:tx}});
  assert.deepEqual(reconcileTarget(rows(),STATION),
    {protocol:'ocpp2.1',route:'/ocpp/2.1/transactions/getTransactionStatus',transactions:['test-123']});
  assert.deepEqual(reconcileTarget(rows('ocpp2.0.1'),STATION).route,STATUS_ROUTES['ocpp2.0.1']);
  assert.deepEqual(reconcileTarget(rows('ocpp2.1',true,[]),STATION).transactions,[]);
  // Another station's transactions are not asked about.
  assert.deepEqual(reconcileTarget(rows('ocpp2.1',true,[{stationId:3,tenantId:1,transactionId:'other',isActive:true}]),
    STATION).transactions,[]);
  // Offline, OCPP 1.6 (no GetTransactionStatus), another identity or a malformed row: nothing.
  for(const r of [rows('ocpp2.1',false),rows('ocpp1.6'),rows('ocpp2.1',true,[{stationId:2,tenantId:2,transactionId:'x',isActive:true}]),
    rows('ocpp2.1',true,[{stationId:2,tenantId:1,transactionId:'bad id',isActive:true}]),{data:{}},null])
    assert.equal(reconcileTarget(r,STATION),null);
  assert.equal(reconcileTarget(rows(),'SIM-EV-OTHER'),null);
  const target={transactions:['a','b','c']}, now=1e9;
  const checked=new Map([['a',now-1000],['b',now-RECONCILE_EVERY_MS]]);
  assert.deepEqual(reconcileDue(target,now,checked),['b','c']);
  assert.deepEqual(reconcileDue(target,now,checked,true),['a','b','c']);
  assert.deepEqual(reconcileDue(null,now,checked,true),[]);
  // Only the start route of each protocol triggers a check after a refusal.
  assert.deepEqual(routes.filter(startRoute),['/ocpp/2.1/evdriver/requestStartTransaction',
    '/ocpp/2.0.1/evdriver/requestStartTransaction','/ocpp/1.6/evdriver/remoteStartTransaction']);
});
test('roles: the report role gets GetBaseReport only, and nothing else changes',async()=>{
  const {REPORT_ROLE,REPORT_ROUTES}=await import('../rootfs/control-policy.mjs');
  const routes=Object.values(REPORT_ROUTES);
  assert.deepEqual(routes,['/ocpp/2.1/reporting/getBaseReport','/ocpp/2.0.1/reporting/getBaseReport']);
  for(const commands of [false,true]) {
    const on=rolesSeed(commands,false,true), off=rolesSeed(commands,false,false);
    assert.deepEqual(on[REPORT_ROLE].permissions,['ocpp.reporting.getBaseReport']);
    assert.deepEqual(off[REPORT_ROLE].permissions,[]);
    // The command role never gets GetBaseReport; the Operator UI keeps it.
    assert.ok(!on[COMMAND_ROLE].permissions.includes('ocpp.reporting.getBaseReport'));
    assert.ok(on['lab-operator'].permissions.includes('ocpp.reporting.getBaseReport'));
    for(const role of Object.keys(on)) if(role!==REPORT_ROLE) assert.deepEqual(on[role],off[role],role);
  }
});
test('device model reports: once per online transition, OCPP 2.x only, rate-limited',async()=>{
  const {reportState,reportsDue,reportDone,deviceModelReports,REPORT_ROUTES,REPORT_EVERY_MS,REPORT_PER_CYCLE,
    REPORT_ATTEMPTS}=await import('../rootfs/control-policy.mjs');
  assert.equal(deviceModelReports({}),true);
  assert.equal(deviceModelReports({device_model_reports:true}),true);
  assert.equal(deviceModelReports({device_model_reports:false}),false);
  const row=(name,protocol='ocpp2.1',isOnline=true,tenantId=1)=>({id:1,tenantId,ocppConnectionName:name,protocol,isOnline});
  const rows=(...r)=>({data:{ChargingStations:r}});
  const state=reportState();
  let now=1e9;
  const due=r=>reportsDue(r,state,now).map(t=>t.identifier);
  // Every listener's stations: simulators and Plugfest identities alike; never 1.6,
  // offline, another tenant or an identity outside the OCPP pattern.
  assert.deepEqual(reportsDue(rows(row('SIM-EV-EVEREST-V2G-03'),row('PF-EVSE-7','ocpp2.0.1'),row('PF-16','ocpp1.6'),
    row('PF-OFF','ocpp2.1',false),row('PF-T2','ocpp2.1',true,2),row('bad/id')),state,now),[
    {identifier:'SIM-EV-EVEREST-V2G-03',protocol:'ocpp2.1',route:REPORT_ROUTES['ocpp2.1']},
    {identifier:'PF-EVSE-7',protocol:'ocpp2.0.1',route:REPORT_ROUTES['ocpp2.0.1']}]);
  assert.equal(reportDone(state,'SIM-EV-EVEREST-V2G-03',{payload:{status:'Accepted'}},now),'Accepted');
  assert.equal(reportDone(state,'PF-EVSE-7',{status:504,error:'x'},now),'no reply within 8 s');
  // Still online: not asked again.
  now+=30000;
  assert.deepEqual(due(rows(row('SIM-EV-EVEREST-V2G-03'),row('PF-EVSE-7','ocpp2.0.1'))),[]);
  // Offline and back within REPORT_EVERY_MS: not asked; after it: asked once.
  assert.deepEqual(due(rows()),[]);
  now+=60000;
  assert.deepEqual(due(rows(row('SIM-EV-EVEREST-V2G-03'))),[]);
  assert.deepEqual(due(rows()),[]);
  now+=REPORT_EVERY_MS;
  assert.deepEqual(due(rows(row('SIM-EV-EVEREST-V2G-03'))),['SIM-EV-EVEREST-V2G-03']);
  assert.equal(reportDone(state,'SIM-EV-EVEREST-V2G-03',{payload:{status:'<script>'}},now),'unexpected reply');
  // A request CitrineOS could not send is retried on later checks, REPORT_ATTEMPTS at most.
  const s2=reportState();
  for(let i=1;i<=REPORT_ATTEMPTS;i++) {
    assert.deepEqual(reportsDue(rows(row('PF-1')),s2,now).map(t=>t.identifier),['PF-1']);
    assert.match(reportDone(s2,'PF-1',{status:502,error:'not sent'},now),i<REPORT_ATTEMPTS?/retry/:/giving up/);
  }
  assert.deepEqual(reportsDue(rows(row('PF-1')),s2,now),[]);
  // A pending station that goes offline is dropped.
  const s3=reportState();
  reportsDue(rows(row('PF-2')),s3,now);
  assert.deepEqual(reportsDue(rows(),s3,now),[]);
  assert.equal(s3.pending.size,0);
  // At most REPORT_PER_CYCLE per check; the rest wait for the next one.
  const s4=reportState(), many=Array.from({length:7},(_,i)=>row('PF-'+i));
  const first=reportsDue(rows(...many),s4,now);
  assert.equal(first.length,REPORT_PER_CYCLE);
  for(const t of first)reportDone(s4,t.identifier,{payload:{status:'Accepted'}},now);
  assert.deepEqual(reportsDue(rows(...many),s4,now).map(t=>t.identifier),['PF-3','PF-4','PF-5']);
  // Malformed results change nothing.
  for(const bad of [null,{data:{}},{data:{ChargingStations:'x'}},{errors:[{}]}])
    assert.deepEqual(reportsDue(bad,s4,now),[]);
  assert.equal(s4.online.size,7);
});
