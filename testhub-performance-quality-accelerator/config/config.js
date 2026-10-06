/**
 * Resolves the base URL for the current run from environments.json,
 * the same "one config file, one flag" idea as api-test-framework's config.ts + env.yaml.
 *
 * Vanilla k6 has no bundler and no native YAML parser, so this uses JSON instead of
 * YAML — open() + JSON.parse() work out of the box with a plain `k6 run`.
 *
 * Select an environment:   k6 run -e ENV=qa tests/smoke/smoke-test.js
 * Or override the URL outright, bypassing environments.json entirely:
 *                           k6 run -e BASE_URL=https://custom.example.com ...
 */

const environments = JSON.parse(open('./environments.json'));

function resolveBaseUrl() {
    const envName = __ENV.ENV || 'dev';
    const envConfig = environments[envName];

    if (!envConfig) {
        throw new Error(
            `Unknown ENV "${envName}". Defined in config/environments.json: ${Object.keys(environments).join(', ')}`
        );
    }

    // An explicit BASE_URL always wins, same override rule as api-test-framework.
    return __ENV.BASE_URL || envConfig.baseUrl;
}

export const Config = {
    envName: __ENV.ENV || 'dev',
    baseUrl: resolveBaseUrl(),
};
