import test from 'node:test';
import assert from 'node:assert/strict';
import {validate,permitted,equalToken,buildListeners,INTERNAL_PORTS,UPSTREAM_API_PORT,upstreamExitCode,upstreamTransactions,COST_UPDATED_INTERVAL_OFF,
  priceRequest,commandRejection} from '../rootfs/launch.mjs';
import {operatorCommand,operatorTargetAllows,OPERATOR_COMMANDS,METERING_COMMAND,meteringVariables} from '../rootfs/control-policy.mjs';
const good={mode:'isolated',database_host:'citrine-db',broker_host:'citrine-broker',hasura_host:'citrine-hasura',
  database_password:'a'.repeat(64),broker_password:'b'.repeat(64),hasura_secret:'c'.repeat(64),api_token:'d'.repeat(64)};
test('explicit mode and unique credentials required',()=>{
  assert.doesNotThrow(()=>validate(good));
  assert.doesNotThrow(()=>validate({mode:'disconnected'}));
  for(const change of [{mode:'enabled'},{api_token:''},{database_host:'http://bad'},{api_token:good.database_password}])
    assert.throws(()=>validate({...good,...change}));
});
test('gateway only admits bounded read paths',()=>{
  assert.equal(permitted('GET','/commands/tariff'),true);
  assert.equal(permitted('POST','/v1/graphql'),true);
  for(const [method,path] of [['POST','/ocpp/1.6/setChargingProfile'],['POST','/commands/tariff'],['GET','/admin'],['POST','/v1/metadata']])
    assert.equal(permitted(method,path),false);
});
test('exact authentication, not prefix matching',()=>{
  assert.equal(equalToken('Bearer abc','Bearer abc'),true);
  assert.equal(equalToken('Bearer abcX','Bearer abc'),false);
  assert.equal(equalToken(undefined,'Bearer abc'),false);
});
test('simulator admission remains opt-in with a separate password',()=>{
  assert.throws(()=>validate({...good,simulator_enabled:true}));
  assert.throws(()=>validate({...good,simulator_enabled:true,simulator_password:good.api_token}));
  assert.doesNotThrow(()=>validate({...good,simulator_enabled:true,simulator_password:'e'.repeat(40)}));
});
test('V2G admission and command privilege require two separate explicit flags',()=>{
  const v2g={...good,profile_simulator_enabled:true,profile_simulator_password:'f'.repeat(32)};
  assert.doesNotThrow(()=>validate(v2g));
  assert.throws(()=>validate({...good,profile_simulator_enabled:true}));
  assert.throws(()=>validate({...good,command_control_enabled:true,command_token:'e'.repeat(64)}));
  assert.throws(()=>validate({...v2g,command_control_enabled:true,command_token:good.api_token}));
  assert.doesNotThrow(()=>validate({...v2g,command_control_enabled:true,command_token:'e'.repeat(64)}));
});
test('open admission is a separate, explicit unauthenticated listener',()=>{
  assert.deepEqual(buildListeners(good),[]);
  const sim=buildListeners({...good,simulator_enabled:true});
  assert.equal(sim.length,1);
  assert.equal(sim[0].port,8081);
  assert.equal(sim[0].allowUnknownChargingStations,false);
  assert.equal(sim[0].ignoreAuthenticationHeaders,false);
  const open=buildListeners({...good,simulator_enabled:true,open_admission_enabled:true});
  assert.deepEqual(open.map(l=>l.port),[8081,8082]);
  assert.equal(open[0].securityProfile,1);
  assert.equal(open[0].allowUnknownChargingStations,false);
  assert.deepEqual(open[1].protocols,['ocpp2.1','ocpp2.0.1']);
  assert.equal(open[1].allowUnknownChargingStations,true);
  assert.equal(open[1].ignoreAuthenticationHeaders,true);
  assert.equal(open[1].tenantId,1);
  assert.throws(()=>validate({...good,open_admission_enabled:'yes'}));
});
test('commands may use open admission; command station stays in the SIM-EV- namespace',()=>{
  const open={...good,open_admission_enabled:true};
  assert.doesNotThrow(()=>validate({...open,command_control_enabled:true,command_token:'e'.repeat(64),
    command_station_id:'SIM-EV-EVEREST-V2G-02'}));
  for(const id of ['REAL-CHARGER','SIM-CITRINE-LAB-01','SIM-EV-','SIM-EV-a/b'])
    assert.throws(()=>validate({...open,command_station_id:id}));
});
test('Plugfest listener: opt-in Security Profile 1 on 8083 for provisioned stations only',()=>{
  const st=[{id:'EVX-AU-001',password:'Vendor-Pass-0001'},{id:'STARCHARGE.T1',password:'Vendor-Pass-0002'}];
  const pf={...good,plugfest_enabled:true,plugfest_stations:st};
  assert.doesNotThrow(()=>validate(pf));
  assert.deepEqual(buildListeners(good),[]);
  assert.deepEqual(buildListeners({...good,plugfest_stations:st}),[]);
  const ls=buildListeners(pf), [l]=ls;
  assert.equal(l.port,8083);
  assert.equal(l.id,'citrine-plugfest');
  // 8100-8105: one endpoint per station under test, admitted exactly as on 8083.
  assert.deepEqual(ls.map(x=>x.port),[8083,8100,8101,8102,8103,8104,8105]);
  assert.equal(new Set(ls.map(x=>x.id)).size,7);
  // No listener may take a loopback port the App uses itself (8088, the
  // upstream API, drew EADDRINUSE in CI).
  const all=buildListeners({...pf,open_admission_enabled:true,simulator_enabled:true}).map(x=>x.port);
  assert.ok(INTERNAL_PORTS.includes(UPSTREAM_API_PORT));
  for(const port of all)assert.ok(!INTERNAL_PORTS.includes(port),port);
  for(const x of ls)assert.deepEqual({...x,id:l.id,port:l.port},l);
  assert.equal(l.securityProfile,1);
  assert.equal(l.allowUnknownChargingStations,false);
  assert.equal(l.ignoreAuthenticationHeaders,false);
  // Upstream picks the first listed protocol the station offers.
  assert.deepEqual(l.protocols,['ocpp2.1','ocpp2.0.1','ocpp1.6']);
  assert.deepEqual(buildListeners({...pf,open_admission_enabled:true}).map(x=>x.port),[8082,8083,8100,8101,8102,8103,8104,8105]);
});
test('Plugfest open admission: 8083 without credentials, explicitly opted in',()=>{
  const st=[{id:'EVX-AU-001',password:'Vendor-Pass-0001'}];
  const open={...good,plugfest_enabled:true,plugfest_open_admission:true};
  assert.doesNotThrow(()=>validate(open));
  assert.doesNotThrow(()=>validate({...open,plugfest_stations:st}));
  const ls=buildListeners(open), [l]=ls;
  assert.equal(l.port,8083);
  assert.equal(ls.length,7);
  for(const x of ls)assert.equal(x.securityProfile,0);
  assert.equal(l.securityProfile,0);
  assert.equal(l.allowUnknownChargingStations,true);
  assert.equal(l.ignoreAuthenticationHeaders,true);
  assert.deepEqual(l.protocols,['ocpp2.1','ocpp2.0.1','ocpp1.6']);
  // Off by default, needs the listener itself, and must be a real boolean.
  assert.throws(()=>validate({...good,plugfest_enabled:true,plugfest_stations:[]}));
  assert.throws(()=>validate({...good,plugfest_open_admission:true}));
  assert.throws(()=>validate({...open,plugfest_open_admission:'yes'}));
  assert.equal(buildListeners({...good,plugfest_enabled:true,plugfest_stations:st})[0].securityProfile,1);
});
test('Plugfest stations are validated, unique and do not clash with simulator provisioning',()=>{
  const pf=s=>({...good,plugfest_enabled:true,plugfest_stations:s});
  const ok={id:'EVX-AU-001',password:'Vendor-Pass-0001'};
  for(const bad of [
    [],
    [{id:'a:b',password:ok.password}],
    [{id:'a/b',password:ok.password}],
    [{id:'x'.repeat(49),password:ok.password}],
    [{id:ok.id,password:'short'}],
    [{id:ok.id,password:'x'.repeat(41)}],
    [{id:ok.id,password:'has space in pass'}],
    [ok,{id:ok.id,password:'Vendor-Pass-0002'}],
    [ok,{id:'OTHER',password:ok.password}],
  ]) assert.throws(()=>validate(pf(bad)),undefined,JSON.stringify(bad));
  const sim={...good,simulator_enabled:true,simulator_password:'e'.repeat(40)};
  assert.throws(()=>validate({...sim,plugfest_enabled:true,plugfest_stations:[{id:ok.id,password:'e'.repeat(40)}]}));
  assert.throws(()=>validate({...good,plugfest_enabled:'yes',plugfest_stations:[ok]}));
  assert.throws(()=>validate({...good,plugfest_enabled:true,plugfest_stations:'EVX:pass'}));
  assert.doesNotThrow(()=>validate({...good,plugfest_stations:[{id:'a:b'}]}));
  // A SIM-EV- simulator may rehearse the vendor path, and may be the command
  // station, unless a simulator option already provisions that identity.
  const v2g={id:'SIM-EV-EVEREST-V2G-03',password:'f'.repeat(32)};
  assert.doesNotThrow(()=>validate({...pf([v2g]),open_admission_enabled:true,command_control_enabled:true,
    command_token:'e'.repeat(64),command_station_id:v2g.id}));
  assert.throws(()=>validate({...pf([{...v2g,id:'SIM-EV-EVEREST-V2G-01'}]),profile_simulator_enabled:true,
    profile_simulator_password:'a1'.repeat(16)}));
  assert.throws(()=>validate({...pf([{id:'SIM-CITRINE-LAB-01',password:ok.password}]),simulator_enabled:true,
    simulator_password:'e'.repeat(40)}));
  assert.doesNotThrow(()=>validate(pf([{id:'SIM-CITRINE-LAB-01',password:ok.password}])));
});

test('Operator UI scope needs its own distinct token; commands need the UI flag',()=>{
  const op={...good,operator_ui_enabled:true,operator_token:'9'.repeat(64)};
  assert.doesNotThrow(()=>validate(op));
  assert.doesNotThrow(()=>validate({...op,operator_commands_enabled:true}));
  assert.throws(()=>validate({...good,operator_ui_enabled:true}));
  assert.throws(()=>validate({...op,operator_token:good.api_token}));
  assert.throws(()=>validate({...op,operator_token:'XYZ'}));
  assert.throws(()=>validate({...good,operator_commands_enabled:true}));
  assert.throws(()=>validate({...op,operator_ui_enabled:'yes'}));
});
test('operator commands: fixed actions, both 2.x versions, one tenant-1 identity',()=>{
  const u=s=>new URL(s,'http://lab');
  assert.deepEqual(operatorCommand(u('/ocpp/2.0.1/configuration/reset?identifier=PF-EVX-01&tenantId=1')),
    {protocol:'ocpp2.0.1',action:'configuration/reset',identifier:'PF-EVX-01'});
  assert.equal(operatorCommand(u('/ocpp/2.1/evdriver/requestStartTransaction?identifier=SIM-EV-G1&tenantId=1')).protocol,'ocpp2.1');
  // SetVariables reaches the body check (metering variables only), below.
  assert.deepEqual(operatorCommand(u('/ocpp/2.0.1/monitoring/setVariables?identifier=charger1&tenantId=1')),
    {protocol:'ocpp2.0.1',action:METERING_COMMAND,identifier:'charger1'});
  for(const bad of [
    '/ocpp/2.0.1/monitoring/setVariables?identifier=A1&tenantId=2',
    '/ocpp/2.0.1/certificates/installCertificate?identifier=A1&tenantId=1',
    '/ocpp/2.0.1/configuration/updateFirmware?identifier=A1&tenantId=1',
    '/ocpp/2.0.1/configuration/setNetworkProfile?identifier=A1&tenantId=1',
    '/ocpp/2.0.1/configuration/dataTransfer?identifier=A1&tenantId=1',
    '/ocpp/2.0.1/reporting/getLog?identifier=A1&tenantId=1',
    '/ocpp/1.6/configuration/reset?identifier=A1&tenantId=1',
    '/ocpp/2.0.1/configuration/reset?identifier=A1&tenantId=2',
    '/ocpp/2.0.1/configuration/reset?identifier=A1',
    '/ocpp/2.0.1/configuration/reset?identifier=A1&identifier=B2&tenantId=1',
    '/ocpp/2.0.1/configuration/reset?identifier=A1&tenantId=1&extra=1',
    '/ocpp/2.0.1/configuration/reset?identifier=a%2Fb&tenantId=1',
    '/v1/metadata'])
    assert.equal(operatorCommand(u(bad)),null,bad);
  for(const c of OPERATOR_COMMANDS) assert.doesNotMatch(c,/setVariables|certificate|firmware|NetworkProfile|dataTransfer|getLog|customer/i);
});
test('operator SetVariables is limited to the metering variables',()=>{
  const v=(component,variable,value,extra={})=>({component:{name:component},variable:{name:variable},attributeValue:value,...extra});
  // ChargeSim (Plugfest, 23 October 2026) sends power only when asked over OCPP.
  assert.equal(meteringVariables({setVariableData:[
    v('SampledDataCtrlr','TxUpdatedMeasurands','Energy.Active.Import.Register,Power.Active.Import',{attributeType:'Actual'}),
    v('SampledDataCtrlr','TxUpdatedInterval','10')]}),true);
  assert.equal(meteringVariables({setVariableData:[v('AlignedDataCtrlr','Interval','0'),v('AlignedDataCtrlr','Measurands','SoC, Voltage')]}),true);
  for(const bad of [
    null,[],{},{setVariableData:[]},{setVariableData:Array(11).fill(v('SampledDataCtrlr','TxUpdatedInterval','10'))},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedInterval','10')],extra:1},
    {setVariableData:[v('SecurityCtrlr','BasicAuthPassword','x'.repeat(20))]},
    {setVariableData:[v('OCPPCommCtrlr','NetworkConfigurationPriority','1')]},
    {setVariableData:[v('SampledDataCtrlr','Enabled','false')]},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedInterval','-1')]},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedInterval','86401')]},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedInterval',10)]},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedMeasurands','Power.Active.Import;DROP')]},
    {setVariableData:[v('SampledDataCtrlr','TxUpdatedInterval','10',{attributeType:'Target'})]},
    {setVariableData:[{...v('SampledDataCtrlr','TxUpdatedInterval','10'),component:{name:'SampledDataCtrlr',evse:{id:1}}}]},
    {setVariableData:[{...v('SampledDataCtrlr','TxUpdatedInterval','10'),variable:{name:'TxUpdatedInterval',instance:'x'}}]},
  ]) assert.equal(meteringVariables(bad),false,JSON.stringify(bad));
});
test('operator commands need the station online on the same OCPP version',()=>{
  const cmd={protocol:'ocpp2.0.1',action:'configuration/reset',identifier:'PF-EVX-01'};
  const st=x=>({data:{ChargingStations:[{id:7,tenantId:1,ocppConnectionName:'PF-EVX-01',protocol:'ocpp2.0.1',isOnline:true,...x}]}});
  assert.equal(operatorTargetAllows(cmd,st({})),true);
  assert.equal(operatorTargetAllows(cmd,st({isOnline:false})),false);
  assert.equal(operatorTargetAllows(cmd,st({protocol:'ocpp2.1'})),false);
  assert.equal(operatorTargetAllows(cmd,st({tenantId:2})),false);
  assert.equal(operatorTargetAllows(cmd,{data:{ChargingStations:[]}}),false);
  assert.equal(operatorTargetAllows(null,st({})),false);
});
test('a deliberate stop exits 0; an unrequested upstream exit fails (#30)',()=>{
  assert.equal(upstreamExitCode(true),0);
  assert.equal(upstreamExitCode(false),1);
});
test('physical command station: explicit flag, Plugfest listener, no profile simulator',()=>{
  const pf={...good,plugfest_enabled:true,plugfest_open_admission:true,command_control_enabled:true,
    command_token:'e'.repeat(64),open_admission_enabled:true};
  const real={...pf,command_station_id:'ACME-WB-0042'};
  assert.throws(()=>validate(real),/SIM-EV-/);
  assert.doesNotThrow(()=>validate({...real,command_real_stations_enabled:true}));
  assert.throws(()=>validate({...real,command_real_stations_enabled:true,plugfest_enabled:false,
    plugfest_open_admission:false}),/plugfest_enabled/);
  assert.throws(()=>validate({...real,command_real_stations_enabled:true,profile_simulator_enabled:true,
    profile_simulator_password:'f'.repeat(32)}),/profile_simulator_enabled/);
  assert.throws(()=>validate({...real,command_real_stations_enabled:'yes'}));
  assert.throws(()=>validate({...real,command_real_stations_enabled:true,command_station_id:'a/b'}));
  // The flag alone changes nothing for a simulator command station.
  assert.doesNotThrow(()=>validate({...pf,command_real_stations_enabled:true,command_station_id:'SIM-EV-EVEREST-G1'}));
});

test('price commands: off by default, need scoped commands and an ISO currency',()=>{
  const cmd={...good,open_admission_enabled:true,command_control_enabled:true,command_token:'e'.repeat(64)};
  assert.doesNotThrow(()=>validate({...cmd,price_commands_enabled:true,price_currency:'AUD'}));
  assert.doesNotThrow(()=>validate({...good,price_commands_enabled:false,price_currency:'AUD'}));
  assert.throws(()=>validate({...good,price_commands_enabled:true}),/command_control_enabled/);
  assert.throws(()=>validate({...cmd,price_commands_enabled:'yes'}));
  for(const currency of ['aud','AU','AUDD','','A$D'])
    assert.throws(()=>validate({...cmd,price_currency:currency}),/price_currency/,currency);
});
test('CitrineOS periodic CostUpdated is pushed out of reach only with price commands',()=>{
  assert.deepEqual(upstreamTransactions({}),{});
  assert.deepEqual(upstreamTransactions({price_commands_enabled:false}),{});
  assert.deepEqual(upstreamTransactions({price_commands_enabled:true}),{TRANSACTIONS:{costUpdatedInterval:COST_UPDATED_INTERVAL_OFF}});
  // Node runs a setInterval above 2^31-1 ms every millisecond instead.
  assert.ok(COST_UPDATED_INTERVAL_OFF*1000<=2**31-1);
  assert.ok((COST_UPDATED_INTERVAL_OFF+1)*1000>2**31-1);
});
test('price route gating: flag, command credential, listed station, bounds',()=>{
  const u=s=>new URL(s,'http://lab');
  const st='SIM-EV-EVEREST-V2G-01';
  const on={price_commands_enabled:true,price_currency:'AUD',plugfest_enabled:true,
    plugfest_stations:[{id:'EVX-AU-001',password:'Vendor-Pass-0001'}]};
  const tariff={evseId:0,tariff:{tariffId:'amber-1',currency:'AUD',energy:{prices:[{priceKwh:0.2}]}}};
  const cost={totalCost:0,transactionId:'tx-1',customData:{vendorId:'org.openchargealliance.costmsg',chargingPrice:{kWhPrice:0.2}}};
  const D=id=>u(`/ocpp/2.1/transactions/setDefaultTariff?identifier=${id}&tenantId=1`);
  const C=v=>u(`/ocpp/${v}/transactions/costUpdated?identifier=${st}&tenantId=1`);
  assert.deepEqual(priceRequest({},D(st),true,tariff),{status:403,error:'Price commands are off (price_commands_enabled)'});
  assert.equal(priceRequest({},C('2.1'),true,cost).status,403);
  assert.deepEqual(priceRequest(on,D(st),false,tariff),{status:403,error:'Command credential required'});
  assert.deepEqual(priceRequest(on,D(st),true,tariff),{target:st});
  assert.deepEqual(priceRequest(on,D('EVX-AU-001'),true,tariff),{target:'EVX-AU-001'});
  assert.equal(priceRequest(on,D('EVX-AU-002'),true,tariff).status,403);
  assert.equal(priceRequest({...on,plugfest_enabled:false},D('EVX-AU-001'),true,tariff).status,403);
  assert.equal(priceRequest(on,D(st),true,{...tariff,evseId:-1}).status,400);
  assert.equal(priceRequest(on,D(st),true,undefined).status,400,'invalid JSON');
  assert.deepEqual(priceRequest(on,C('2.1'),true,cost),{target:st});
  assert.deepEqual(priceRequest(on,C('2.0.1'),true,cost),{target:st});
  assert.equal(priceRequest(on,C('2.1'),false,cost).status,403);
  assert.equal(priceRequest(on,u('/ocpp/2.1/transactions/costUpdated?identifier=EVX-AU-001&tenantId=1'),true,cost).status,400,
    'CostUpdated goes to the command station only');
  assert.equal(priceRequest(on,C('2.1'),true,{...cost,totalCost:-1}).status,400);
});
test('a refused profile with a price schedule says why',()=>{
  const u=new URL('http://lab/ocpp/2.1/smartcharging/setChargingProfile');
  const p={chargingProfile:{chargingSchedule:[{absolutePriceSchedule:{}}]}};
  assert.equal(commandRejection(u,{},null),'Command outside lab bounds');
  assert.equal(commandRejection(u,p,{enabled:false}),'Price schedules need price_commands_enabled');
  assert.equal(commandRejection(new URL('http://lab/ocpp/2.0.1/smartcharging/setChargingProfile'),p,{enabled:true}),
    'Price schedules need OCPP 2.1');
  assert.equal(commandRejection(u,p,{enabled:true}),'Command or price schedule outside lab bounds');
});
test('device model reports: on by default, a boolean option',()=>{
  assert.doesNotThrow(()=>validate(good));
  for(const v of [true,false])assert.doesNotThrow(()=>validate({...good,device_model_reports:v}));
  for(const v of ['true',1,null])assert.throws(()=>validate({...good,device_model_reports:v}));
});
