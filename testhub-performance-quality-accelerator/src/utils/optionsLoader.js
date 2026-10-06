import { thresholds as baseThresholds } from '../../config/thresholds.js';

/**
 * Reads test-data/scenarios/profiles.json (compiled from the "profiles" sheet of
 * the Excel workbook by `npm run gen:scenarios`) and hands each test:
 *
 *   export const options = loadOptions('load');   // the full k6 options object
 *   const run = loadRunParams('load');            // pick / think / iterationSleep / …
 *
 * Every run parameter comes from Excel. The only runtime overrides are:
 *   -e USERS=<n>     -> options.vus       (constant-VU profiles only)
 *   -e DURATION=<d>  -> options.duration  (constant-VU profiles only)
 *   -e SCENARIO=<s>  -> which request sheet to load (handled in dataLoader)
 *
 * `dir` (both functions) defaults to the shared test-data/scenarios, but a
 * self-contained endpoint example compiled to its own folder via
 * `excel-to-scenario.mjs --out-dir` can point here instead, e.g.
 *   loadOptions('createuser-smoke', 'test-data/scenarios/createuser')
 */
const cache = {};

export function loadOptions(name, dir = 'test-data/scenarios') {
    const profiles = readProfiles(dir);
    const p = profiles[name] || {};
    const fromExcel = p.options || {};

    const options = {
        ...fromExcel,
        thresholds: { ...baseThresholds, ...(fromExcel.thresholds || {}) },
    };

    const usesStages = Array.isArray(options.stages) && options.stages.length > 0;
    const usesArrivalRate = options.rate !== undefined;

    if (__ENV.USERS || __ENV.DURATION) {
        if (usesStages || usesArrivalRate) {
            console.warn(`[options] profile "${name}" is ramp/arrival-rate based — USERS/DURATION overrides ignored.`);
        } else {
            if (__ENV.USERS) options.vus = Number(__ENV.USERS);
            if (__ENV.DURATION) options.duration = __ENV.DURATION;
        }
    }

    // A constant-VU profile with nothing set at all still needs a shape.
    if (!usesStages && !usesArrivalRate && options.iterations === undefined && options.duration === undefined) {
        options.vus = options.vus || 1;
        options.duration = '30s';
    }

    return options;
}

export function loadRunParams(name, dir = 'test-data/scenarios') {
    const profiles = readProfiles(dir);
    return (profiles[name] && profiles[name].run) || {};
}

function readProfiles(dir) {
    if (cache[dir]) return cache[dir];
    try {
        return (cache[dir] = JSON.parse(open(`../../${dir}/profiles.json`)));
    } catch (_e) {
        console.warn(`[options] ${dir}/profiles.json not found — run \`npm run gen:scenarios\` (or the matching --out-dir compile step).`);
        return (cache[dir] = {});
    }
}
