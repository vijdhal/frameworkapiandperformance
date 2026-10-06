import fs from 'fs';
import yaml from 'js-yaml';
import xlsx from 'xlsx';

interface ExcelRow {
    name: string;
    endpoint: string;
    method: string;
    expectedStatus: number;
    service?: string;           // named service key from env.yaml services map
    requestBodyFile?: string;   // path to JSON file under test-data/request/json holding the request payload
    expectedFile?: string;
    authType?: string;
    headers?: string;
    maxResponseMs?: number;     // fail if response exceeds this threshold (ms)
    cleanupEndpoint?: string;   // endpoint to call after test (e.g. DELETE /api/users/{{ctx:id}})
    cleanupMethod?: string;     // HTTP method for cleanup (default: DELETE)
    extractField?: string;      // dotted path to extract from response body: e.g. "data.id"
    injectAs?: string;          // ContextStore key to store the extracted value under
    contractFile?: string;      // path to OpenAPI spec for contract validation
}

interface MockExcelRow {
    name: string;
    endpoint: string;
    method: string;
    requestBodyFile?: string;   // path to JSON file under test-data/request/json holding the request payload
    authType?: string;
    headers?: string;
    mockStatus: number;
    mockBody?: string;
    mockHeaders?: string;
    mockDelayMs?: number;
    flakyCallsToFail?: number;
    expectedStatus: number;
    expectedFile?: string;
    expectedHeaders?: string;
    expectedCallCount?: number;
    expectedMinDurationMs?: number;
}

const has = (v: any) => v !== undefined && v !== null && String(v).trim() !== '';

const loadRequestBody = (requestBodyFile?: string) =>
    has(requestBodyFile) ? JSON.parse(fs.readFileSync(requestBodyFile!, 'utf-8')) : undefined;

export class DataLoader {

    static loadYAML(path: string) {
        return yaml.load(fs.readFileSync(path, 'utf-8'));
    }

    static loadExcel(filePath: string, sheetName: string) {
        const workbook  = xlsx.readFile(filePath);
        const worksheet = workbook.Sheets[sheetName];
        const rows      = xlsx.utils.sheet_to_json<ExcelRow>(worksheet);

        return rows.map(row => ({
            name:             row.name,
            endpoint:         row.endpoint,
            method:           row.method,
            service:          has(row.service)          ? row.service          : undefined,
            authType:         has(row.authType)         ? row.authType         : undefined,
            headers:          has(row.headers)          ? JSON.parse(String(row.headers))     : undefined,
            requestBody:      loadRequestBody(row.requestBodyFile),
            cleanupEndpoint:  has(row.cleanupEndpoint)  ? row.cleanupEndpoint  : undefined,
            cleanupMethod:    has(row.cleanupMethod)    ? row.cleanupMethod    : 'DELETE',
            extractField:     has(row.extractField)     ? row.extractField     : undefined,
            injectAs:         has(row.injectAs)         ? row.injectAs         : undefined,
            contractFile:     has(row.contractFile)     ? row.contractFile     : undefined,
            expected: {
                status:        Number(row.expectedStatus),
                file:          has(row.expectedFile)    ? row.expectedFile     : undefined,
                maxResponseMs: has(row.maxResponseMs)   ? Number(row.maxResponseMs) : undefined
            }
        }));
    }

    static loadMockExcel(filePath: string, sheetName: string) {
        const workbook  = xlsx.readFile(filePath);
        const worksheet = workbook.Sheets[sheetName];
        const rows      = xlsx.utils.sheet_to_json<MockExcelRow>(worksheet);

        return rows.map(row => ({
            name:        row.name,
            endpoint:    row.endpoint,
            method:      row.method,
            authType:    has(row.authType)    ? row.authType    : undefined,
            headers:     has(row.headers)     ? JSON.parse(String(row.headers))     : undefined,
            requestBody: loadRequestBody(row.requestBodyFile),
            mock: {
                status:           Number(row.mockStatus ?? 200),
                body:             has(row.mockBody)    ? JSON.parse(String(row.mockBody))    : undefined,
                headers:          has(row.mockHeaders) ? JSON.parse(String(row.mockHeaders)) : undefined,
                delayMs:          has(row.mockDelayMs) ? Number(row.mockDelayMs)  : undefined,
                flakyCallsToFail: Number(row.flakyCallsToFail ?? 0)
            },
            expected: {
                status:        Number(row.expectedStatus),
                file:          has(row.expectedFile)          ? row.expectedFile          : undefined,
                headers:       has(row.expectedHeaders)       ? JSON.parse(String(row.expectedHeaders)) : undefined,
                callCount:     has(row.expectedCallCount)     ? Number(row.expectedCallCount)     : undefined,
                minDurationMs: has(row.expectedMinDurationMs) ? Number(row.expectedMinDurationMs) : undefined
            }
        }));
    }
}
