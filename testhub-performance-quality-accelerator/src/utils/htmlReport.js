// Pinned to a specific commit (tag 3.0.4), not `main` — this file is fetched and
// executed by every k6 run, inside a process that holds API_KEY/CLIENT_SECRET
// etc. via __ENV. Tracking `main` would let any future upstream commit (or a
// compromised maintainer account) run arbitrary code in that same process.
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/25058f7861695cb4fe6e0ecf6415ea489c489005/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';

/**
 * Builds a k6 summary handler that writes a self-contained HTML report
 * (in addition to the usual console summary).
 *
 * @param {object} data - the summary data k6 passes into handleSummary()
 * @param {string} reportName - file name (without extension) for the HTML report
 */
export function buildSummary(data, reportName) {
    return {
        [`reports/${reportName}.html`]: htmlReport(data),
        stdout: textSummary(data, { indent: ' ', enableColors: true }),
    };
}
