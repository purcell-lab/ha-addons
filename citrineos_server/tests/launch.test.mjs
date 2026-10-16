import test from 'node:test';
import assert from 'node:assert/strict';
import {validate,permitted,equalToken,buildListeners} from '../rootfs/launch.mjs';
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
  const [l]=buildListeners(pf);
  assert.equal(l.port,8083);
  assert.equal(l.securityProfile,1);
  assert.equal(l.allowUnknownChargingStations,false);
  assert.equal(l.ignoreAuthenticationHeaders,false);
  assert.deepEqual(l.protocols,['ocpp2.1','ocpp2.0.1']);
  assert.deepEqual(buildListeners({...pf,open_admission_enabled:true}).map(x=>x.port),[8082,8083]);
});
test('Plugfest stations are validated, unique and kept out of the simulator namespace',()=>{
  const pf=s=>({...good,plugfest_enabled:true,plugfest_stations:s});
  const ok={id:'EVX-AU-001',password:'Vendor-Pass-0001'};
  for(const bad of [
    [],
    [{id:'a:b',password:ok.password}],
    [{id:'a/b',password:ok.password}],
    [{id:'x'.repeat(49),password:ok.password}],
    [{id:'SIM-CITRINE-LAB-01',password:ok.password}],
    [{id:'SIM-EV-EVEREST-V2G-01',password:ok.password}],
    [{id:'SIM-EV-OTHER',password:ok.password}],
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
});
