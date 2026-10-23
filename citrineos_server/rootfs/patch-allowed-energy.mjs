// Build-time patch to upstream CitrineOS v2.0.1: the OCPP 2.1 AuthorizeResponse
// never carries allowedEnergyTransfer.
//
// OCPP 2.1 added allowedEnergyTransfer to AuthorizeResponse: the energy transfer
// modes the EV may choose for the session. When it is omitted the station SHALL
// treat the session as charging only, so no session authorised by upstream
// CitrineOS can be bidirectional, and a CentralSetpoint TxProfile with a
// negative setpoint is rejected. OCTT (OCA, Plugfest 23 October 2026) reported
// the field missing; its CentralSetpoint TxProfiles were all Rejected.
//
// The patch adds the lab's allowed modes (DC, DC_BPT, AC_single_phase,
// AC_two_phase, AC_three_phase, AC_BPT) to every Accepted OCPP 2.1
// AuthorizeResponse that does not set the field already. Other statuses and
// OCPP 2.0.1 (which has no such field) are unchanged.
//
// The build fails unless the file is the exact upstream v2.0.1 build (or this
// patch's output), so a new upstream version cannot silently drop the patch.
// `--check` succeeds only for a patched file.
import crypto from 'node:crypto';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

export const TARGET='/usr/local/apps/citrineos/apps/ocpp-server/node_modules/@citrineos/ocpp/dist/src/handlers/requests/2/authorize-request-ocpp-21-handler.js';
export const UPSTREAM_SHA256='22d16f829dab6b89194514eac99fddb9ba0336021bf7fa7322c2392c5b276d4c';
export const PATCHED_SHA256='0f10a44a11a805bc7a05dce6c4f72aa0a87f4a85e43b14b6763c918ea486e8bd';
export const MARKER='ha-citrine patch (patch-allowed-energy.mjs)';

export const ALLOWED_ENERGY_TRANSFER=['DC','DC_BPT','AC_single_phase','AC_two_phase','AC_three_phase','AC_BPT'];
export const EDITS=[
  {
    name:'allowedEnergyTransfer on Accepted',
    anchor:`    _sendAuthorizeResult(message, response) {
        const status = response.idTokenInfo?.status ??
`,
    replacement:`    _sendAuthorizeResult(message, response) {
        // ha-citrine patch (patch-allowed-energy.mjs): OCPP 2.1 treats an omitted
        // allowedEnergyTransfer as charging only, so an Accepted session lists the
        // lab's modes, bidirectional included.
        if (response.idTokenInfo?.status === AuthorizationStatusEnum.Accepted && !response.allowedEnergyTransfer) {
            response = { ...response, allowedEnergyTransfer: ${JSON.stringify(ALLOWED_ENERGY_TRANSFER).replace(/"/g,"'")} };
        }
        const status = response.idTokenInfo?.status ??
`,
  },
];

export function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}
// Exact text edits; each anchor must occur exactly once.
export function applyEdits(text) {
  if(text.includes(MARKER))throw new Error('authorize-request-ocpp-21-handler.js is already partly patched');
  for(const {name,anchor} of EDITS) {
    const count=text.split(anchor).length-1;
    if(count!==1)throw new Error(`Anchor "${name}" found ${count} times, expected exactly once`);
  }
  return EDITS.reduce((out,{anchor,replacement})=>out.replace(anchor,()=>replacement),text);
}
// Returns the patched text; a file already patched by this version is unchanged.
export function patch(text) {
  const digest=sha256(text);
  if(digest===PATCHED_SHA256)return text;
  if(digest!==UPSTREAM_SHA256)
    throw new Error('authorize-request-ocpp-21-handler.js is not the pinned CitrineOS v2.0.1 build');
  const patched=applyEdits(text);
  if(sha256(patched)!==PATCHED_SHA256)throw new Error('Patched file does not match the expected result');
  return patched;
}
export function main(args=process.argv.slice(2)) {
  const check=args.includes('--check');
  const path=args.find(a=>a!=='--check')??TARGET;
  const text=fs.readFileSync(path,'utf8');
  if(check) {
    if(sha256(text)!==PATCHED_SHA256)throw new Error(`${path} is not patched`);
    console.log(`${path} is patched (OCPP 2.1 allowedEnergyTransfer)`);
    return;
  }
  const patched=patch(text);
  if(patched===text){console.log(`${path} is already patched`);return;}
  fs.writeFileSync(path,patched);
  const syntax=spawnSync(process.execPath,['--check',path],{encoding:'utf8'});
  if(syntax.status!==0) {
    fs.writeFileSync(path,text);
    throw new Error(`Patched file does not parse: ${syntax.stderr.trim()}`);
  }
  console.log(`patched ${path}: Accepted OCPP 2.1 AuthorizeResponses carry allowedEnergyTransfer`);
}
if(process.argv[1]===fileURLToPath(import.meta.url)) {
  try {main();}
  catch(error) {console.error(`patch-allowed-energy: ${error.message}`);process.exit(1);}
}
