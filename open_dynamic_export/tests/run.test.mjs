import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
    validate,
    resolveConfig,
    environment,
    prepare,
    sessionWatch,
    lineSplitter,
    SESSION_HINT,
} from '../rootfs/opt/ode-ha/run.mjs';

const GOOD = {
    config: '',
    sep2_cert_file: 'sep2-cert.pem',
    sep2_key_file: 'sep2-key.pem',
    sep2_pen: '62223',
    timezone: 'Australia/Brisbane',
    log_level: 'info',
    influxdb_host: '',
    influxdb_port: 8086,
    influxdb_org: 'open-dynamic-export',
    influxdb_bucket: 'data',
    influxdb_token: '',
};
const CONFIG = '{"setpoints":{"fixed":{"exportLimitWatts":5000}},"inverters":[],"inverterControl":{"enabled":false}}';

function tmp() {
    return fs.mkdtempSync(path.join(os.tmpdir(), 'ode-ha-'));
}

test('defaults validate', () => {
    assert.equal(validate({ ...GOOD }).log_level, 'info');
});

test('rejects unsafe values', () => {
    for (const bad of [
        { sep2_cert_file: '../secrets.yaml' },
        { sep2_key_file: '/etc/shadow' },
        { sep2_pen: 'abc' },
        { timezone: 'Australia/../../etc' },
        { log_level: 'verbose' },
        { influxdb_host: 'host name' },
        { influxdb_host: 'influx.local' },
    ]) {
        assert.throws(() => validate({ ...GOOD, ...bad }), undefined, JSON.stringify(bad));
    }
    assert.throws(() => validate(null));
    assert.throws(() => validate([]));
});

test('config option wins and is normalised', () => {
    const dir = tmp();
    fs.writeFileSync(path.join(dir, 'config.json'), '{"ignored":true}');
    const { source, json } = resolveConfig({ ...GOOD, config: CONFIG }, dir);
    assert.equal(source, 'the config option');
    assert.deepEqual(JSON.parse(json), JSON.parse(CONFIG));
});

test('falls back to config.json in the App folder', () => {
    const dir = tmp();
    fs.writeFileSync(path.join(dir, 'config.json'), CONFIG);
    assert.match(resolveConfig({ ...GOOD }, dir).source, /config\.json$/);
});

test('missing or invalid config is an error', () => {
    assert.throws(() => resolveConfig({ ...GOOD }, tmp()), /No configuration/);
    assert.throws(() => resolveConfig({ ...GOOD, config: '{bad' }, tmp()), /not valid JSON/);
    assert.throws(() => resolveConfig({ ...GOOD, config: '[1]' }, tmp()), /JSON object/);
});

test('environment maps options and only sets InfluxDB when configured', () => {
    const env = environment({ ...GOOD }, { PATH: '/bin', INFLUXDB_HOST: 'stale' });
    assert.equal(env.CONFIG_DIR, '/data/ode');
    assert.equal(env.SERVER_PORT, '3000');
    assert.equal(env.TZ, 'Australia/Brisbane');
    assert.equal(env.SEP2_PEN, '62223');
    assert.equal(env.LOGLEVEL, 'info');
    assert.equal(env.STDOUT_LOGLEVEL, 'info');
    assert.equal(env.PATH, '/bin');
    assert.ok(!('INFLUXDB_HOST' in env));
    const influx = environment({ ...GOOD, influxdb_host: 'influx', influxdb_token: 't' }, {});
    assert.equal(influx.INFLUXDB_HOST, 'influx');
    assert.equal(influx.INFLUXDB_PORT, '8086');
    assert.equal(influx.INFLUXDB_ADMIN_TOKEN, 't');
});

test('prepare writes config and copies certificates privately', () => {
    const user = tmp();
    const ode = path.join(tmp(), 'ode');
    fs.writeFileSync(path.join(user, 'sep2-cert.pem'), 'CERT');
    fs.writeFileSync(path.join(user, 'sep2-key.pem'), 'KEY');
    prepare({ ...GOOD, config: CONFIG }, user, ode);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(ode, 'config.json'), 'utf8')), JSON.parse(CONFIG));
    assert.equal(fs.readFileSync(path.join(ode, 'sep2-key.pem'), 'utf8'), 'KEY');
    assert.equal(fs.statSync(path.join(ode, 'sep2-key.pem')).mode & 0o777, 0o600);
    assert.equal(fs.statSync(path.join(ode, 'config.json')).mode & 0o777, 0o600);
});

const DER_404 = '[12:00:00.000] ERROR: Error updating DER status {"module":"DerHelper","message":"Request failed with status code 404"}';

test('session-ended hint after repeated DER 404s, at most hourly', () => {
    let t = 0;
    const watch = sessionWatch({ now: () => t });
    assert.equal(watch(DER_404), null);
    assert.equal(watch('INFO: Sending DER status {"module":"DerHelper"}'), null);
    assert.equal(watch(DER_404), null);
    assert.equal(watch(DER_404), SESSION_HINT);
    t += 60000;
    assert.equal(watch(DER_404), null);
    t += 3600000;
    assert.equal(watch(DER_404), SESSION_HINT);
});

test('other 404s and errors do not hint', () => {
    const watch = sessionWatch({ threshold: 1 });
    for (const line of [
        'ERROR: Error updating DER status {"module":"DerHelper","message":"Request failed with status code 500"}',
        'ERROR: Request failed {"module":"InfluxDB","message":"Request failed with status code 404"}',
        'INFO: Sending DER status {"module":"DerHelper"}',
    ]) {
        assert.equal(watch(line), null, line);
    }
    assert.match(SESSION_HINT, /stop the App/);
});

test('line splitter joins lines across chunks', () => {
    const split = lineSplitter();
    assert.deepEqual(split('first\nsec'), ['first']);
    assert.deepEqual(split('ond\nthird'), ['second']);
    assert.deepEqual(split('\n'), ['third']);
    assert.deepEqual(split(''), []);
});
