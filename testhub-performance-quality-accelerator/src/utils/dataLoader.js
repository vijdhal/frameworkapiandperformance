/**
 * Data loading for k6. `open()` only works in the init context (module top level)
 * and resolves paths relative to THIS file, so tests call loadScenario('load')
 * rather than passing their own paths around.
 *
 * Scenario JSON under test-data/scenarios/ is generated from the Excel workbook
 * by `npm run gen:scenarios` (scripts/excel-to-scenario.mjs) — mirroring
 * api-test-framework's DataLoader.loadExcel(), but resolved ahead of the run
 * because k6's Goja runtime can't parse .xlsx.
 */

export function loadJson(pathRelativeToUtils) {
    return JSON.parse(open(pathRelativeToUtils));
}

/**
 * Load a generated scenario by name: loadScenario('smoke') reads
 * test-data/scenarios/smoke-scenario.json. Accepts an explicit ENV override:
 *   k6 run -e SCENARIO=checkout tests/load/load-test.js
 *
 * @param {string} name  scenario/sheet name
 * @param {string} dir   directory (relative to the repo root) the compiled JSON
 *                       lives in — defaults to the shared test-data/scenarios,
 *                       but a self-contained endpoint example (its own workbook,
 *                       compiled with `--out-dir`) can point here instead, e.g.
 *                       loadScenario('createuser', 'test-data/scenarios/createuser')
 */
export function loadScenario(name, dir = 'test-data/scenarios') {
    const scenario = (__ENV.SCENARIO || name || 'load').replace(/-scenario$/, '');
    return JSON.parse(open(`../../${dir}/${scenario}-scenario.json`));
}
