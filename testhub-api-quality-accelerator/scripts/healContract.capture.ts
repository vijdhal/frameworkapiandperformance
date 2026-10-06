// Round-trip harness: drives the REAL HealMode.record() so the JSON contract
// between healMode.ts and testhubui/heal.py is exercised, not assumed.
import { HealMode } from '../src/utils/healMode';

const base = {
    suite: 'complex/users1',
    excelName: 'complex.xlsx',
    sheetName: 'users1',
    method: 'POST',
    endpoint: '/api/users/2',
    environment: 'dev',
    capturedAt: new Date().toISOString(),
    requestHeaders: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer super-secret-mulesoft-token',
        'x-api-key': 'reqres-free-v1',
        'Accept': 'application/json'
    },
    requestBody: { name: 'morpheus', job: 'leader' },
    responseBody: { id: '123', createdAt: '2026-08-19T00:00:00.000Z' },
    elapsedMs: 412
};

// 1 accept: non-proxy, 201 -> 200, expect the cell to be rewritten
HealMode.record({ ...base, rowIndex: 0, rowName: 'Users1 Happy Path',
    resolvedUrl: 'https://reqres.in/api/users/2', proxy: false,
    expectedStatus: 201, actualStatus: 200 });

// 2 defect: non-proxy 500, expect the cell UNTOUCHED + a defect pack
HealMode.record({ ...base, rowIndex: 2, rowName: 'Empty Payload',
    resolvedUrl: 'https://reqres.in/api/users/2', proxy: false,
    expectedStatus: 400, actualStatus: 500,
    responseBody: { error: 'NullPointerException in UserService.create' } });

// 3 proxy 5xx: URL contains "proxy", so ANY status is accepted and written
HealMode.record({ ...base, rowIndex: 1, rowName: 'Mandatory Only',
    resolvedUrl: 'https://mulesoft-dev.yourcompany.com/experience-proxy/api/users/2',
    proxy: HealMode.isProxyUrl('https://mulesoft-dev.yourcompany.com/experience-proxy/api/users/2'),
    expectedStatus: 201, actualStatus: 500 });

// 4 already correct: contributes to the "unchanged" count
HealMode.record({ ...base, rowIndex: 7, rowName: 'Invalid JSON',
    resolvedUrl: 'https://reqres.in/api/users/2', proxy: false,
    expectedStatus: 400, actualStatus: 400 });

// 5 binary bodies: a Buffer must be summarised, never expanded to a byte array
HealMode.record({ ...base, rowIndex: 3, rowName: 'Missing Name',
    resolvedUrl: 'https://reqres.in/api/users/2', proxy: false,
    expectedStatus: 400, actualStatus: 415,
    requestBody: Buffer.alloc(3_000_000, 7),
    responseBody: Buffer.from('binary response payload') });

console.log('capture phase: 5 rows recorded');
