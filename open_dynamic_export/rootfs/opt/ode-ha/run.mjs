// Home Assistant launcher for Open Dynamic Export.
//
// Turns the App options into ODE's environment and config directory, then
// runs the upstream server unchanged (node dist/app.js) and forwards signals.
//   - config.json comes from the `config` option when it is set, otherwise
//     from /config/config.json (this App's folder under /addon_configs).
//   - CSIP-AUS certificate and key files, when present in /config, are
//     copied into the private config directory ODE reads.
//   - ODE's output is passed through unchanged; when it shows the CSIP-AUS
//     server answering 404 for the DER (for example after a test session
//     has ended), one explanatory line is added, at most once an hour.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const OPTIONS = '/data/options.json';
export const USER_DIR = '/config';
export const ODE_DIR = '/data/ode';
export const APP_DIR = '/app';

const SAFE_FILE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SAFE_TZ = /^[A-Za-z0-9_+-]+(\/[A-Za-z0-9_+-]+){0,2}$/;
const SAFE_HOST = /^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$/;
const LEVELS = ['trace', 'debug', 'info', 'warn', 'error'];

export function validate(options) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
        throw new Error('options must be an object');
    }
    for (const key of ['sep2_cert_file', 'sep2_key_file']) {
        if (!SAFE_FILE.test(options[key] ?? '')) {
            throw new Error(`${key} must be a plain file name in /config`);
        }
    }
    if (!/^[0-9]{1,10}$/.test(String(options.sep2_pen ?? ''))) {
        throw new Error('sep2_pen must be a number');
    }
    if (!SAFE_TZ.test(options.timezone ?? '')) {
        throw new Error('timezone must be an IANA name such as Australia/Brisbane');
    }
    if (!LEVELS.includes(options.log_level)) {
        throw new Error(`log_level must be one of ${LEVELS.join(', ')}`);
    }
    const influx = options.influxdb_host ?? '';
    if (influx && !SAFE_HOST.test(influx)) {
        throw new Error('influxdb_host must be a host name or address');
    }
    if (influx && !options.influxdb_token) {
        throw new Error('influxdb_token is required when influxdb_host is set');
    }
    return options;
}

// Returns the config.json text to use, as pretty JSON.
export function resolveConfig(options, userDir = USER_DIR) {
    let source;
    let text;
    if ((options.config ?? '').trim()) {
        source = 'the config option';
        text = options.config;
    } else {
        source = path.join(userDir, 'config.json');
        if (!fs.existsSync(source)) {
            throw new Error(
                'No configuration: set the config option, or put config.json in ' +
                    'this App\'s folder under /addon_configs (see the documentation).',
            );
        }
        text = fs.readFileSync(source, 'utf8');
    }
    let parsed;
    try {
        parsed = JSON.parse(text);
    } catch (error) {
        throw new Error(`config from ${source} is not valid JSON: ${error.message}`);
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error(`config from ${source} must be a JSON object`);
    }
    return { source, json: JSON.stringify(parsed, null, 4) + '\n' };
}

export function environment(options, base = process.env) {
    const env = {
        ...base,
        NODE_ENV: 'production',
        TZ: options.timezone,
        SERVER_PORT: '3000',
        CONFIG_DIR: ODE_DIR,
        SEP2_CERT_FILE: options.sep2_cert_file,
        SEP2_KEY_FILE: options.sep2_key_file,
        SEP2_PEN: String(options.sep2_pen),
        LOGLEVEL: options.log_level,
        STDOUT_LOGLEVEL: options.log_level,
    };
    for (const key of Object.keys(env)) {
        if (key.startsWith('INFLUXDB_')) delete env[key];
    }
    if (options.influxdb_host) {
        Object.assign(env, {
            INFLUXDB_HOST: options.influxdb_host,
            INFLUXDB_PORT: String(options.influxdb_port),
            INFLUXDB_ORG: options.influxdb_org,
            INFLUXDB_BUCKET: options.influxdb_bucket,
            INFLUXDB_ADMIN_TOKEN: options.influxdb_token,
        });
    }
    return env;
}

export function prepare(options, userDir = USER_DIR, odeDir = ODE_DIR) {
    const { source, json } = resolveConfig(options, userDir);
    fs.mkdirSync(odeDir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(path.join(odeDir, 'config.json'), json, { mode: 0o600 });
    console.log(`Open Dynamic Export: configuration from ${source}.`);
    const cert = path.join(userDir, options.sep2_cert_file);
    const key = path.join(userDir, options.sep2_key_file);
    if (fs.existsSync(cert) && fs.existsSync(key)) {
        fs.copyFileSync(cert, path.join(odeDir, options.sep2_cert_file));
        fs.copyFileSync(key, path.join(odeDir, options.sep2_key_file));
        fs.chmodSync(path.join(odeDir, options.sep2_key_file), 0o600);
        console.log('Open Dynamic Export: CSIP-AUS certificate and key found.');
    } else {
        console.log(
            'Open Dynamic Export: no CSIP-AUS certificate and key in /config; ' +
                'CSIP-AUS setpoints will not connect until they are provided.',
        );
    }
}

// A CSIP-AUS server that no longer knows the EndDevice/DER (a test session
// that has ended) answers 404 to every DER update.
const DER_404 = /DerHelper.*status code 404/;
export const SESSION_HINT =
    'Open Dynamic Export (App): EndDevice/DER not found on the CSIP-AUS ' +
    'server (HTTP 404). The test session has probably ended; stop the App ' +
    'or remove csipAus from its configuration.';

// Watches ODE's log lines; returns the hint line to print, or null. Hints
// after `threshold` 404 lines, then again at most every `interval` ms.
export function sessionWatch({ threshold = 3, interval = 3600000, now = Date.now } = {}) {
    let count = 0;
    let last = null;
    return function line(text) {
        if (!DER_404.test(text)) return null;
        count += 1;
        if (count < threshold) return null;
        if (last !== null && now() - last < interval) return null;
        last = now();
        return SESSION_HINT;
    };
}

// Splits one stream's raw output into complete lines.
export function lineSplitter() {
    let partial = '';
    return function split(chunk) {
        const lines = (partial + chunk).split('\n');
        partial = lines.pop().slice(-65536);
        return lines;
    };
}

function main() {
    let options;
    try {
        options = validate(JSON.parse(fs.readFileSync(OPTIONS, 'utf8')));
        prepare(options);
    } catch (error) {
        console.error(`Open Dynamic Export not started: ${error.message}`);
        process.exit(1);
    }
    const child = spawn('node', ['dist/app.js'], {
        cwd: APP_DIR,
        env: environment(options),
        stdio: ['inherit', 'pipe', 'pipe'],
    });
    const watch = sessionWatch();
    for (const [from, to] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) {
        const split = lineSplitter();
        from.on('data', (chunk) => {
            to.write(chunk);
            for (const text of split(chunk.toString('utf8'))) {
                const hint = watch(text);
                if (hint) console.log(hint);
            }
        });
    }
    for (const signal of ['SIGTERM', 'SIGINT']) {
        process.on(signal, () => child.kill(signal));
    }
    // 'close' waits for the piped output to drain.
    child.on('close', (code, signal) => process.exit(signal ? 0 : (code ?? 1)));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
