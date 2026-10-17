// A narrow laboratory command policy, not general-purpose device enrolment.
// Upstream AJV validation remains mandatory after these additional constraints.
// Default command target. Option command_station_id selects one station at a
// time: a SIM-EV- simulator, or, with command_real_stations_enabled, any OCPP
// identity (a physical charger on the Plugfest listener).
export const STATION='SIM-EV-EVEREST-V2G-01';
export const STATION_PATTERN=/^SIM-EV-[A-Za-z0-9_-]{1,36}$/;
export const REAL_STATION_PATTERN=/^[A-Za-z0-9._~*+-]{1,48}$/;
export const commandStation=o=>o.command_station_id||STATION;
export const stationAllowed=(station,real=false)=>
  STATION_PATTERN.test(station)||(real===true&&REAL_STATION_PATTERN.test(station));
// PROTOCOL and ROUTES keep the original OCPP 2.1 contract that clients check.
// PROTOCOLS adds OCPP 2.0.1 and 1.6 stations (charging-only periods; no setpoints).
export const PROTOCOL='ocpp2.1';
export const PROTOCOLS=['ocpp2.1','ocpp2.0.1','ocpp1.6'];
// Lab bounds per period: 25 kW charging (import) and V2G discharge (export),
// above a 3-phase 32 A AC simulator (3 x 32 A x 240 V = 23 kW).
export const MAX_IMPORT_W=25000;
export const MAX_EXPORT_W=25000;
// Same order for every version: start, stop, profile, clear.
const ACTIONS=['evdriver/requestStartTransaction','evdriver/requestStopTransaction',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile'];
const ACTIONS_16=['evdriver/remoteStartTransaction','evdriver/remoteStopTransaction',
  'smartcharging/setChargingProfile','smartcharging/clearChargingProfile'];
export const routesFor=protocol=>(protocol==='ocpp1.6'?ACTIONS_16:ACTIONS)
  .map(a=>`/ocpp/${protocol.slice(4)}/${a}`);
export const ROUTES=routesFor(PROTOCOL);
export const COMMANDS_BY_PROTOCOL=Object.fromEntries(PROTOCOLS.map(p=>[p,routesFor(p)]));
export const ALL_ROUTES=Object.values(COMMANDS_BY_PROTOCOL).flat();
// CitrineOS role-based access for the scoped command role, derived from the
// same route list the gateway enforces so the two cannot drift apart (0.6.0
// accepted 2.0.1 and 1.6 routes at the gateway but CitrineOS refused them).
// Starts from the shipped rules (reader and Operator UI roles unchanged),
// removes the command role from every scoped route, then grants it exactly
// ALL_ROUTES when scoped commands are enabled.
export const COMMAND_ROLE='lab-controller';
export function rbacRules(base,commandsEnabled) {
  const rules=JSON.parse(JSON.stringify(base));
  const tenant=rules['1'];
  for(const route of ALL_ROUTES) {
    const roles=(tenant[route]?.POST||[]).filter(r=>r!==COMMAND_ROLE);
    if(commandsEnabled===true) roles.unshift(COMMAND_ROLE);
    if(roles.length) tenant[route]={...tenant[route],POST:roles};
    else if(tenant[route]) { delete tenant[route].POST; if(!Object.keys(tenant[route]).length) delete tenant[route]; }
  }
  return rules;
}
// The OCPP version a command route speaks, e.g. 'ocpp2.0.1'; null if not a lab route.
export function routeProtocol(pathname) {
  return PROTOCOLS.find(p=>COMMANDS_BY_PROTOCOL[p].includes(pathname))||null;
}
const action=pathname=>{
  const p=routeProtocol(pathname);
  return p?COMMANDS_BY_PROTOCOL[p].indexOf(pathname):-1;
};
const keys=(o,allowed)=>o!==null && typeof o==='object' && !Array.isArray(o)
  && Object.keys(o).every(k=>allowed.includes(k));
const int=(n,min,max)=>Number.isInteger(n)&&n>=min&&n<=max;
// OCPP identifierString characters: physical chargers use more than the simulators do.
const transaction=n=>typeof n==='string'&&/^[A-Za-z0-9*_=:+|@.-]{1,64}$/.test(n);
const timestamp=n=>typeof n==='string'
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$/.test(n)
  && Number.isFinite(Date.parse(n));

export function validateCommand(url,p,station=STATION,real=false) {
  const protocol=routeProtocol(url.pathname);
  if(!protocol||!stationAllowed(station,real)) return false;
  const a=action(url.pathname);
  if([...url.searchParams.keys()].length!==2
    ||url.searchParams.getAll('identifier').length!==1
    ||url.searchParams.getAll('tenantId').length!==1
    ||url.searchParams.get('identifier')!==station
    ||url.searchParams.get('tenantId')!=='1') return false;
  if(protocol==='ocpp1.6') return validate16(a,p);
  if(a===0) return keys(p,['remoteStartId','evseId','idToken'])
    &&int(p.remoteStartId,0,2147483647)&&p.evseId===1
    &&keys(p.idToken,['idToken','type'])&&p.idToken.idToken==='C17E0001'&&p.idToken.type==='ISO14443';
  if(a===1) return keys(p,['transactionId'])&&transaction(p.transactionId);
  // No clear-all command. The caller must select its exact test profile.
  if(a===3) return keys(p,['chargingProfileId'])
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
    const ok=validPeriod(x,s.duration,i,last,protocol);
    last=x.startPeriod;return ok;
  });
}
// OCPP 1.6 has integer transaction IDs, connectorId instead of evseId, a single
// csChargingProfiles schedule and no setpoints. Limits are whole watts here, which
// satisfies the 1.6 multipleOf 0.1 without floating-point surprises.
function validate16(a,p) {
  if(a===0) return keys(p,['connectorId','idTag'])&&p.connectorId===1&&p.idTag==='C17E0001';
  if(a===1) return keys(p,['transactionId'])&&int(p.transactionId,0,2147483647);
  if(a===3) return keys(p,['id'])&&int(p.id,1,2147483647);
  if(!keys(p,['connectorId','csChargingProfiles'])||p.connectorId!==1)return false;
  const c=p.csChargingProfiles;
  if(!keys(c,['chargingProfileId','stackLevel','chargingProfilePurpose','chargingProfileKind','transactionId','chargingSchedule'])
    ||!int(c.chargingProfileId,1,2147483647)||!int(c.stackLevel,0,10)
    ||c.chargingProfilePurpose!=='TxProfile'||!int(c.transactionId,0,2147483647)
    ||!['Absolute','Relative'].includes(c.chargingProfileKind))return false;
  const s=c.chargingSchedule;
  if(!keys(s,['startSchedule','duration','chargingRateUnit','chargingSchedulePeriod'])
    ||!int(s.duration,1,600)||s.chargingRateUnit!=='W'
    ||!Array.isArray(s.chargingSchedulePeriod)||s.chargingSchedulePeriod.length<1
    ||s.chargingSchedulePeriod.length>10)return false;
  if(c.chargingProfileKind==='Absolute'&&!timestamp(s.startSchedule))return false;
  if(c.chargingProfileKind==='Relative'&&s.startSchedule!==undefined)return false;
  let last=-1;
  return s.chargingSchedulePeriod.every((x,i)=>{
    const ok=keys(x,['startPeriod','limit','numberPhases'])
      &&int(x.startPeriod,0,s.duration-1)&&(i!==0||x.startPeriod===0)&&x.startPeriod>last
      &&int(x.limit,0,MAX_IMPORT_W)
      &&(x.numberPhases===undefined||x.numberPhases===1||x.numberPhases===3);
    last=x.startPeriod;return ok;
  });
}

// A period is either a V2G CentralSetpoint period (setpoint and discharge
// limit required, OCPP 2.1 only), or an AC charging-only period (operationMode
// absent or ChargingOnly, no setpoint or discharge). OCPP 2.0.1 has no
// operationMode, setpoint or dischargeLimit at all. libocpp assumes 3 phases when
// numberPhases is absent, so a single-phase AC station would get a third of a
// watt limit (#39): numberPhases may be 1 or 3, and phaseToUse (1-3) only
// with numberPhases 1.
function validPeriod(x,duration,i,last,protocol=PROTOCOL) {
  if(!keys(x,['startPeriod','limit','dischargeLimit','setpoint','operationMode','numberPhases','phaseToUse'])
    ||!int(x.startPeriod,0,duration-1)||(i===0&&x.startPeriod!==0)||x.startPeriod<=last
    ||!Number.isFinite(x.limit)||x.limit<0||x.limit>MAX_IMPORT_W)return false;
  if(x.numberPhases!==undefined&&x.numberPhases!==1&&x.numberPhases!==3)return false;
  if(x.phaseToUse!==undefined&&(x.numberPhases!==1||!int(x.phaseToUse,1,3)))return false;
  if(protocol==='ocpp2.0.1')
    return x.operationMode===undefined&&x.setpoint===undefined&&x.dischargeLimit===undefined;
  if(x.operationMode==='CentralSetpoint')
    return Number.isFinite(x.dischargeLimit)&&x.dischargeLimit>=-MAX_EXPORT_W&&x.dischargeLimit<=0
      &&Number.isFinite(x.setpoint)&&x.setpoint>=x.dischargeLimit&&x.setpoint<=x.limit;
  return (x.operationMode===undefined||x.operationMode==='ChargingOnly')
    &&x.setpoint===undefined&&x.dischargeLimit===undefined;
}

// Read the observed protocol and active transaction before any dispatch.
// The route's OCPP version must be the station's negotiated protocol (no
// fallback between versions), and never start another active session.
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
    ||s.ocppConnectionName!==station||s.protocol!==routeProtocol(url.pathname)||s.isOnline!==true)return false;
  if(transactions.some(t=>!t||t.tenantId!==1||t.isActive!==true
    ||!int(t.stationId,1,Number.MAX_SAFE_INTEGER)||!transaction(t.transactionId)))return false;
  const active=transactions.filter(t=>t.stationId===s.id);
  const a=action(url.pathname);
  if(a===0)return active.length===0;
  // Clearing a profile during discharge can restore the default import limit.
  // Only allow cleanup once the transaction is evidenced closed.
  if(a===3)return active.length===0;
  const id=a===1?p.transactionId:(p.chargingProfile||p.csChargingProfiles).transactionId;
  // CitrineOS stores 1.6 integer transaction IDs as strings.
  return active.length===1&&active[0].transactionId===String(id);
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
