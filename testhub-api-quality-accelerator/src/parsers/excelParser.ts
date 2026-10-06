import * as XLSX from "xlsx";
import * as fs from "fs";
import * as path from "path";

export type ExcelRow = Record<string, any>;

export class ExcelParser {

    private static getWorkbook(excelName: string): XLSX.WorkBook {

        const excelPath = path.isAbsolute(excelName)
            ? excelName
            : path.join(process.cwd(), "test-data", "excel", excelName);

        if (!fs.existsSync(excelPath)) {
            throw new Error(`Excel file not found: ${excelPath}`);
        }

        return XLSX.readFile(excelPath);
    }

    static readSheet(
        excelName: string,
        sheetName: string
    ): ExcelRow[] {

        const workbook = this.getWorkbook(excelName);

        const worksheet = workbook.Sheets[sheetName];

        if (!worksheet) {
            throw new Error(
                `Sheet "${sheetName}" not found in "${excelName}".`
            );
        }

        return XLSX.utils.sheet_to_json(worksheet, {
            raw: false,
            defval: ""
        });
    }

    static readRow(
        excelName: string,
        sheetName: string,
        testName: string
    ): ExcelRow {

        const rows = this.readSheet(excelName, sheetName);

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

    static getRowByIndex(
        excelName: string,
        sheetName: string,
        rowIndex: number
    ): ExcelRow {

        const rows = this.readSheet(excelName, sheetName);

        if (rowIndex >= rows.length) {
            throw new Error(
                `Row ${rowIndex} not found in "${sheetName}".`
            );
        }

        return rows[rowIndex];
    }

    static getColumnValues(
        excelName: string,
        sheetName: string,
        columnName: string
    ): any[] {

        return this.readSheet(excelName, sheetName)
            .map(row => row[columnName]);
    }

    static findRows(
        excelName: string,
        sheetName: string,
        columnName: string,
        value: any
    ): ExcelRow[] {

        return this.readSheet(excelName, sheetName)
            .filter(
                row =>
                    String(row[columnName]).trim().toLowerCase() ===
                    String(value).trim().toLowerCase()
            );
    }

    static load(
        excelName: string,
        sheetName: string
    ): ExcelRow[] {

        return this.readSheet(excelName, sheetName);
    }
}