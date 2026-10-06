// import { defineConfig } from '@playwright/test';
// import dotenv from 'dotenv';

// dotenv.config();

// const env = process.env.ENV || 'dev';
// const timestamp = new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').slice(0, 19);
// const reportFolder = `reports/ortoni-report-${env}/${timestamp}`;

// // Expose to SummaryReporter so it can inject into the Ortoni HTML after the run
// process.env.ORTONI_REPORT_FOLDER = reportFolder;

// export default defineConfig({
//     testDir: './tests',
//     reporter: [
//         ['list'],
//         ['ortoni-report', {
//             folderPath: reportFolder,
//             filename: 'index.html',
//             title: `API Test Report (${env.toUpperCase()}) — ${timestamp}`,
//             open: 'never',
//             projectName: 'API Test Framework',
//             authorName: 'TestHub Automation Studio',
//             testType: 'API Regression',
//             showProject: true,
//             showTags: true,
//             saveHistory: true,
//             meta: {
//                 Environment: env.toUpperCase(),
//                 Framework: 'Playwright + Axios',
//                 Language: 'TypeScript'
//             }
//         }],
//         ['./src/reporters/summaryReporter.ts']
//     ],
//     use: {
//         baseURL: process.env.BASE_URL
//     }
// });









import { defineConfig, devices } from '@playwright/test';
import { OrtoniReportConfig } from 'ortoni-report';
import dotenv from 'dotenv';
import * as fs from 'fs';
import * as path from 'path';

const environment = process.env.ENVIRONMENT || "local";
dotenv.config();

const testFileArg =
  //process.argv.find((arg) => arg.includes("tests/api")) || "";
  process.argv.find((arg) => arg.includes("src/tests")) || "";

function getDateTime() {
  const now = new Date();
  return now
    .toISOString()
    .replace(/[:.]/g, "-")
    .replace("T", "_")
    .split(".")[0];
}

function extractAPIFromTest(filePath: string): string {
  try {
    const content = fs.readFileSync(filePath, "utf-8");
    //const testMatch = content.match(/api\s*\(\s*['"`](.*?)['"`]/);
    const testMatch = content.match(/test\s*\(\s*['"`](.*?)['"`]/);

    if (!testMatch) return "-";

    const title = testMatch[1];
    const tags = title.match(/@[\w-]+/g);

    if (tags && tags.length >= 2) {
      return tags[1].replace("@", "");
    }

    return "-";
  } catch {
    return "-";
  }
}

function resolveExecution() {
  if (!testFileArg) {
    return {
      epicJourney: "unknown",
      serviceName: "unknown",
      isFolderRun: false,
      api: "-",
    };
  }

  const normalized = testFileArg.replace(/\\/g, "/");
  const parts = normalized.split("/");

  const epicJourney = parts[parts.length - 2];
  const isFile = normalized.endsWith(".ts");

  if (isFile) {
    const serviceName = parts[parts.length - 1]
      .replace(".test.ts", "")
      .replace(".spec.ts", "");

    const api = extractAPIFromTest(testFileArg);

    return {
      epicJourney,
      serviceName,
      isFolderRun: false,
      api,
    };
  }

  const files = fs
    .readdirSync(testFileArg)
    //.filter((f) => f.endsWith(".spec.ts"))
    .filter((f) => f.endsWith(".test.ts"));

  return {
    epicJourney: parts[parts.length - 1],
    serviceName: `All Services (${files.length})`,
    isFolderRun: true,
    api: "-",
  };
}

const { epicJourney, serviceName, isFolderRun, api } = resolveExecution();

const dateTime = getDateTime();

let folderPath = "";
let filename = "";

if (isFolderRun) {
  folderPath = path.join(
    "ortoni-report",
    epicJourney,
    `${epicJourney}_${environment}`
  );

  filename = `allServices_${environment}_${dateTime}.html`;
} else {
  folderPath = path.join(
    "ortoni-report",
    epicJourney,
    serviceName,
    environment
  );

  filename = `${serviceName}_${environment}_${dateTime}.html`;
}

const reportConfig: OrtoniReportConfig = {
  open: "never",

  folderPath,
  filename,

  title: "TestHub Automation Studio",
  projectName: "Automation Framework",
  testType: "Functional",
  authorName: "TestHub Automation Studio",

  base64Image: false,
  stdIO: false,

  meta: {
    environment,
    epicJourney,
    serviceName,
    API: api,
    platform: "UI & API Platform",
    FrameWork: "Playwright Test Automation Framework",
  },
};

export default defineConfig({
  //testDir: "./tests/api",
  testDir: "./src/tests",
//    timeout: 5000000,
//    //retries: 1,
//    fullyParallel: true,
   workers: 5,

//    grep: undefined,
//    grepInvert: undefined,

//    maxFailures: 0,

  reporter: [["list"], ["ortoni-report", reportConfig]],

  use: {
    baseURL: process.env.BASE_URL
  },

//   projects: [
//     {
//       name: "chromium",
//       use: { ...devices["Desktop Chrome"] },
//     },
//   ],
});

