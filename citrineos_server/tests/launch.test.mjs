import test from 'node:test';
import assert from 'node:assert/strict';
import {validate,permitted,equalToken} from '../rootfs/launch.mjs';
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
