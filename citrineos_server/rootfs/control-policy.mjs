// A narrow laboratory command policy, not general-purpose device enrolment.
// Upstream AJV validation remains mandatory after these additional constraints.
// Default command target. Option command_station_id may select another
// simulator identity in the same SIM-EV- namespace, one station at a time.
export const STATION='SIM-EV-EVEREST-V2G-01';
export const STATION_PATTERN=/^SIM-EV-[A-Za-z0-9_-]{1,36}$/;
export const commandStation=o=>o.command_station_id||STATION;
export const PROTOCOL='ocpp2.1';
export const MAX_POWER_W=11000;
export const ROUTES=[
  '/ocpp/2.1/evdriver/requestStartTransaction',
  '/ocpp/2.1/evdriver/requestStopTransaction',
  '/ocpp/2.1/smartcharging/setChargingProfile',
  '/ocpp/2.1/smartcharging/clearChargingProfile',
];
const keys=(o,allowed)=>o!==null && typeof o==='object' && !Array.isArray(o)
  && Object.keys(o).every(k=>allowed.includes(k));
const int=(n,min,max)=>Number.isInteger(n)&&n>=min&&n<=max;
const transaction=n=>typeof n==='string'&&/^[A-Za-z0-9_-]{1,64}$/.test(n);
const timestamp=n=>typeof n==='string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(n)
  && Number.isFinite(Date.parse(n));

export function validateCommand(url,p,station=STATION) {
  if(!ROUTES.includes(url.pathname)||!STATION_PATTERN.test(station)) return false;
  if([...url.searchParams.keys()].length!==2
    ||url.searchParams.getAll('identifier').length!==1
    ||url.searchParams.getAll('tenantId').length!==1
    ||url.searchParams.get('identifier')!==station
    ||url.searchParams.get('tenantId')!=='1') return false;
  if(url.pathname===ROUTES[0]) return keys(p,['remoteStartId','evseId','idToken'])
    &&int(p.remoteStartId,0,2147483647)&&p.evseId===1
    &&keys(p.idToken,['idToken','type'])&&p.idToken.idToken==='C17E0001'&&p.idToken.type==='ISO14443';
  if(url.pathname===ROUTES[1]) return keys(p,['transactionId'])&&transaction(p.transactionId);
  // No clear-all command. The caller must select its exact test profile.
  if(url.pathname===ROUTES[3]) return keys(p,['chargingProfileId'])
    &&int(p.chargingProfileId,1,2147483647);
  if(!keys(p,['evseId','chargingProfile'])||p.evseId!==1)return false;
  const c=p.chargingProfile;
  if(!keys(c,['id','stackLevel','chargingProfilePurpose','chargingProfileKind','transactionId','chargingSchedule'])
    ||!int(c.id,1,2147483647)||!int(c.stackLevel,0,10)
    ||c.chargingProfilePurpose!=='TxProfile'||!transaction(c.transactionId)
    ||!['Absolute','Relative'].includes(c.chargingProfileKind)
    ||!Array.isArray(c.chargingSchedule)||c.chargingSchedule.length!==1)return false;
  const s=c.chargingSchedule[0];
  if(!keys(s,['id','startSchedule','duration','chargingRateUnit','chargingSchedulePeriod'])
    ||!int(s.id,0,2147483647)||!int(s.duration,1,600)||s.chargingRateUnit!=='W'
    ||!Array.isArray(s.chargingSchedulePeriod)||s.chargingSchedulePeriod.length<1
    ||s.chargingSchedulePeriod.length>10)return false;
  if(c.chargingProfileKind==='Absolute'&&!timestamp(s.startSchedule))return false;
  if(c.chargingProfileKind==='Relative'&&s.startSchedule!==undefined)return false;
  let last=-1;
  return s.chargingSchedulePeriod.every((x,i)=>{
    const ok=keys(x,['startPeriod','limit','dischargeLimit','setpoint','operationMode'])
      &&int(x.startPeriod,0,s.duration-1)&&(i!==0||x.startPeriod===0)&&x.startPeriod>last
      &&Number.isFinite(x.limit)&&x.limit>=0&&x.limit<=MAX_POWER_W
      &&Number.isFinite(x.dischargeLimit)&&x.dischargeLimit>=-MAX_POWER_W&&x.dischargeLimit<=0
      &&Number.isFinite(x.setpoint)&&x.setpoint>=x.dischargeLimit&&x.setpoint<=x.limit
      &&x.operationMode==='CentralSetpoint';
    last=x.startPeriod;return ok;
  });
}

// Read the observed protocol and active transaction before any dispatch.
// No fallback from 2.1 to 2.0.1, and never start another active session.
export const TARGET_QUERY=`query ControlTarget($name: String!) {
  ChargingStations(where: {tenantId: {_eq: 1}, ocppConnectionName: {_eq: $name}}, limit: 2) {
    id tenantId ocppConnectionName protocol isOnline
  }
  Transactions(where: {tenantId: {_eq: 1}, isActive: {_eq: true}}, limit: 501) {
    stationId tenantId transactionId isActive
  }
}`;
export function targetAllows(url,p,result,station=STATION) {
  const stations=result?.data?.ChargingStations, transactions=result?.data?.Transactions;
  if(!Array.isArray(stations)||stations.length!==1||!Array.isArray(transactions)
    ||transactions.length>500)return false;
  const s=stations[0];
  if(!s||!int(s.id,1,Number.MAX_SAFE_INTEGER)||s.tenantId!==1
    ||s.ocppConnectionName!==station||s.protocol!==PROTOCOL||s.isOnline!==true)return false;
  if(transactions.some(t=>!t||t.tenantId!==1||t.isActive!==true
    ||!int(t.stationId,1,Number.MAX_SAFE_INTEGER)||!transaction(t.transactionId)))return false;
  const active=transactions.filter(t=>t.stationId===s.id);
  if(url.pathname===ROUTES[0])return active.length===0;
  // Clearing a profile during discharge can restore the default import limit.
  // Only allow cleanup once the transaction is evidenced closed.
  if(url.pathname===ROUTES[3])return active.length===0;
  const id=url.pathname===ROUTES[1]?p.transactionId:p.chargingProfile.transactionId;
  return active.length===1&&active[0].transactionId===id;
}

// Operator UI scope (operator_ui_enabled). Reads go to Hasura as the
// read-only "operator_ro" role. With operator_commands_enabled, a fixed set
// of OCPP 2.0.1/2.1 operational commands may target any tenant-1 station;
// upstream AJV still validates each payload. Commands that change station
// credentials, certificates, firmware, network profiles or variables, or
// that make the station upload files, are never allowed.
export const OPERATOR_COMMANDS=[
  'evdriver/requestStartTransaction','evdriver/requestStopTransaction',
  'evdriver/unlockConnector','evdriver/clearCache',
  'configuration/reset','configuration/changeAvailability','configuration/triggerMessage',
  'monitoring/getVariables','reporting/getBaseReport','transactions/getTransactionStatus',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile',
  'smartcharging/getChargingProfiles','smartcharging/getCompositeSchedule',
];
const OPERATOR_ROUTE=/^\/ocpp\/(2\.0\.1|2\.1)\/([a-z]+\/[A-Za-z]+)$/;
export const OPERATOR_IDENTITY=/^[A-Za-z0-9._~*+-]{1,48}$/;
export function operatorCommand(url) {
  const m=OPERATOR_ROUTE.exec(url.pathname);
  if(!m||!OPERATOR_COMMANDS.includes(m[2]))return null;
  if([...url.searchParams.keys()].length!==2||url.searchParams.getAll('identifier').length!==1
    ||url.searchParams.getAll('tenantId').length!==1||url.searchParams.get('tenantId')!=='1')return null;
  const identifier=url.searchParams.get('identifier');
  if(!OPERATOR_IDENTITY.test(identifier))return null;
  return {protocol:'ocpp'+m[1],action:m[2],identifier};
}
export const OPERATOR_TARGET_QUERY=`query OperatorTarget($name: String!) {
  ChargingStations(where: {tenantId: {_eq: 1}, ocppConnectionName: {_eq: $name}}, limit: 2) {
    id tenantId ocppConnectionName protocol isOnline
  }
}`;
// The route's OCPP version must match the station's negotiated protocol,
// and the station must be online, so a command is never sent in the wrong
// dialect or queued for a disconnected station.
export function operatorTargetAllows(cmd,result) {
  const stations=result?.data?.ChargingStations;
  if(!cmd||!Array.isArray(stations)||stations.length!==1)return false;
  const s=stations[0];
  return !!s&&s.tenantId===1&&s.ocppConnectionName===cmd.identifier
    &&s.protocol===cmd.protocol&&s.isOnline===true;
}
