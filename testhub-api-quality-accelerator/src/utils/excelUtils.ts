import * as XLSX from 'xlsx';
import * as fs from 'fs';
import * as path from 'path';

export type ExcelRow = Record<string, any>;

export async function readTestDataFromExcel(
    excelName: string,
    sheetName: string,
    testName: string
): Promise<ExcelRow> {

    const excelPath = path.isAbsolute(excelName)
        ? excelName
        : path.join(process.cwd(), 'test-data', 'excel', excelName);

    if (!fs.existsSync(excelPath)) {
        throw new Error(`Excel file not found: ${excelPath}`);
    }

    const workbook = XLSX.readFile(excelPath);

    const worksheet = workbook.Sheets[sheetName];

    if (!worksheet) {
        throw new Error(
            `Sheet "${sheetName}" not found in "${excelName}".`
        );
    }

    const rows: ExcelRow[] = XLSX.utils.sheet_to_json(worksheet, {
        raw: false,
        defval: ''
    });

    const row = rows.find(
        x =>
            String(x.TestName).trim().toLowerCase() ===
            String(testName).trim().toLowerCase()
    );

    if (!row) {
        throw new Error(
            `Test "${testName}" not found in sheet "${sheetName}".`
        );
    }

    return row;
}

export function readSheet(
    excelName: string,
    sheetName: string
): ExcelRow[] {

    const excelPath = path.isAbsolute(excelName)
        ? excelName
        : path.join(process.cwd(), 'test-data', 'excel', excelName);

    if (!fs.existsSync(excelPath)) {
        throw new Error(`Excel file not found: ${excelPath}`);
    }

    const workbook = XLSX.readFile(excelPath);

    const worksheet = workbook.Sheets[sheetName];

    if (!worksheet) {
        throw new Error(
            `Sheet "${sheetName}" not found in "${excelName}".`
        );
    }

    return XLSX.utils.sheet_to_json(worksheet, {
        raw: false,
        defval: ''
    });
}

export function getRowByIndex(
    excelName: string,
    sheetName: string,
    rowIndex: number
): ExcelRow {

    const rows = readSheet(excelName, sheetName);

    if (rowIndex >= rows.length) {
        throw new Error(
            `Row index ${rowIndex} does not exist in sheet "${sheetName}".`
        );
    }

    return rows[rowIndex];
}

export function getColumnValues(
    excelName: string,
    sheetName: string,
    columnName: string
): any[] {

    const rows = readSheet(excelName, sheetName);

    return rows.map(row => row[columnName]);
}

export function findRows(
    excelName: string,
    sheetName: string,
    columnName: string,
    value: any
): ExcelRow[] {

    const rows = readSheet(excelName, sheetName);

    return rows.filter(
        row =>
            String(row[columnName]).trim().toLowerCase() ===
            String(value).trim().toLowerCase()
    );
}

export function loadExcel(
    excelName: string,
    sheetName: string
): ExcelRow[] {

    return readSheet(excelName, sheetName);
}

export default {
    readTestDataFromExcel,
    readSheet,
    getRowByIndex,
    getColumnValues,
    findRows,
    loadExcel
};