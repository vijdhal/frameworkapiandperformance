import type { Reporter, TestCase, TestResult, FullResult } from '@playwright/test/reporter';
import fs from 'fs';
import path from 'path';

interface SuiteStat {
    suite: string;
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    durationMs: number;
}

export class SummaryReporter implements Reporter {
    private suites = new Map<string, SuiteStat>();
    private total = 0;
    private passed = 0;
    private failed = 0;
    private skipped = 0;
    private startMs = Date.now();
    private readonly env = process.env.ENV || 'dev';

    onTestEnd(test: TestCase, result: TestResult): void {
        this.total++;
        const suiteName = path.basename(test.location.file, '.spec.ts');

        if (!this.suites.has(suiteName)) {
            this.suites.set(suiteName, {
                suite: suiteName,
                total: 0, passed: 0, failed: 0, skipped: 0, durationMs: 0
            });
        }

        const s = this.suites.get(suiteName)!;
        s.total++;
        s.durationMs += result.duration;

        switch (result.status) {
            case 'passed':   this.passed++;  s.passed++;  break;
            case 'failed':
            case 'timedOut': this.failed++;  s.failed++;  break;
            case 'skipped':  this.skipped++; s.skipped++; break;
        }
    }

    async onEnd(result: FullResult): Promise<void> {
        const durationMs = Date.now() - this.startMs;
        const pct = (n: number) =>
            this.total === 0 ? '0.00' : ((n / this.total) * 100).toFixed(2);

        const executed = this.passed + this.failed;
        const executionPct = this.total === 0
            ? '0.00'
            : ((executed / this.total) * 100).toFixed(2);

        const suiteRows = Array.from(this.suites.values()).map(s => ({
            ...s,
            passRate: s.total === 0 ? '0.00' : ((s.passed / s.total) * 100).toFixed(2),
            failRate: s.total === 0 ? '0.00' : ((s.failed / s.total) * 100).toFixed(2),
            duration: this.formatDuration(s.durationMs)
        }));

        // ── Write JSON summary ──────────────────────────────────────────────
        const reportsDir = path.join(process.cwd(), 'reports');
        if (!fs.existsSync(reportsDir)) fs.mkdirSync(reportsDir, { recursive: true });

        const ts = new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').slice(0, 19);
        const jsonFile = path.join(reportsDir, `summary-${this.env}-${ts}.json`);
        fs.writeFileSync(jsonFile, JSON.stringify({
            environment: this.env,
            generatedAt: new Date().toISOString(),
            status: result.status,
            duration: this.formatDuration(durationMs),
            overall: {
                total: this.total, passed: this.passed, failed: this.failed,
                skipped: this.skipped,
                passRate: `${pct(this.passed)}%`,
                failRate: `${pct(this.failed)}%`,
                executionRate: `${executionPct}%`
            },
            suites: suiteRows
        }, null, 2), 'utf-8');

        // ── Inject into Ortoni HTML ────────────────────────────────────────
        const ortoniFolder = process.env.ORTONI_REPORT_FOLDER;
        if (ortoniFolder) {
            const htmlFile = path.join(process.cwd(), ortoniFolder, 'index.html');

            // Ortoni writes async; wait up to 10s for the file to appear
            let waited = 0;
            while (!fs.existsSync(htmlFile) && waited < 10000) {
                await new Promise(r => setTimeout(r, 300));
                waited += 300;
            }

            if (fs.existsSync(htmlFile)) {
                const html = fs.readFileSync(htmlFile, 'utf-8');
                const banner = this.buildBanner({
                    env: this.env,
                    status: result.status,
                    duration: this.formatDuration(durationMs),
                    total: this.total,
                    passed: this.passed,
                    failed: this.failed,
                    skipped: this.skipped,
                    passPct: pct(this.passed),
                    failPct: pct(this.failed),
                    executionPct,
                    suites: suiteRows
                });

                // Inject right before </body> so it appears at the top of the page via sticky positioning
                const patched = html.replace('</body>', `${banner}\n</body>`);
                fs.writeFileSync(htmlFile, patched, 'utf-8');
                console.log(`\nSummary injected into Ortoni report → ${htmlFile}`);
            } else {
                console.warn(`SummaryReporter: Ortoni HTML not found at ${htmlFile} after waiting 10s`);
            }
        }

        // ── Console output ─────────────────────────────────────────────────
        console.log('\n========== TEST EXECUTION SUMMARY ==========');
        console.log(`  Environment    : ${this.env.toUpperCase()}`);
        console.log(`  Status         : ${result.status.toUpperCase()}`);
        console.log(`  Duration       : ${this.formatDuration(durationMs)}`);
        console.log('---------------------------------------------');
        console.log(`  Total          : ${this.total}`);
        console.log(`  Passed         : ${this.passed}  (${pct(this.passed)}%)`);
        console.log(`  Failed         : ${this.failed}  (${pct(this.failed)}%)`);
        console.log(`  Skipped        : ${this.skipped}`);
        console.log(`  Executed       : ${executed}  (${executionPct}%)`);
        console.log('---------------------------------------------');
        console.log('  Test Suites:');
        for (const s of suiteRows) {
            const icon = s.failed > 0 ? '✗' : '✓';
            console.log(`    ${icon} ${s.suite.padEnd(32)} ${s.passed}/${s.total} passed (${s.passRate}%)  ${s.duration}`);
        }
        console.log('=============================================\n');
    }

    private buildBanner(d: {
        env: string; status: string; duration: string;
        total: number; passed: number; failed: number; skipped: number;
        passPct: string; failPct: string; executionPct: string;
        suites: Array<{ suite: string; total: number; passed: number; failed: number; skipped: number; passRate: string; duration: string }>;
    }): string {
        const statusColor = d.status === 'passed' ? '#22c55e' : '#ef4444';
        const suiteRows = d.suites.map(s => {
            const rowColor = s.failed > 0 ? '#fef2f2' : '#f0fdf4';
            const badge = s.failed > 0
                ? `<span style="color:#ef4444;font-weight:600;">✗ FAIL</span>`
                : `<span style="color:#22c55e;font-weight:600;">✓ PASS</span>`;
            return `
            <tr style="background:${rowColor};">
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;">${s.suite}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">${s.total}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;color:#22c55e;font-weight:600;">${s.passed}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;color:#ef4444;font-weight:600;">${s.failed}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">${s.skipped}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">${s.passRate}%</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">${s.duration}</td>
              <td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:center;">${badge}</td>
            </tr>`;
        }).join('');

        return `
<div id="custom-summary" style="
    position:fixed; bottom:0; left:0; right:0; z-index:9999;
    background:#1e293b; color:#f1f5f9;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px;
    box-shadow:0 -4px 16px rgba(0,0,0,0.4);
    max-height:50vh; overflow-y:auto;
">
  <!-- Toggle button -->
  <div style="
      display:flex; align-items:center; justify-content:space-between;
      padding:8px 16px; background:#0f172a; cursor:pointer; user-select:none;
  " onclick="(function(){var p=document.getElementById('summary-body');p.style.display=p.style.display==='none'?'block':'none';})()">
    <span style="font-weight:700;letter-spacing:.05em;">
      TEST EXECUTION SUMMARY &nbsp;
      <span style="color:${statusColor};">${d.status.toUpperCase()}</span>
    </span>
    <span style="font-size:11px;color:#94a3b8;">click to expand / collapse</span>
  </div>

  <!-- Body -->
  <div id="summary-body" style="display:none; padding:12px 16px;">

    <!-- Overall stats -->
    <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px;">
      ${this.statChip('Environment', d.env.toUpperCase(), '#6366f1')}
      ${this.statChip('Duration', d.duration, '#64748b')}
      ${this.statChip('Total', String(d.total), '#64748b')}
      ${this.statChip('Passed', `${d.passed} (${d.passPct}%)`, '#22c55e')}
      ${this.statChip('Failed', `${d.failed} (${d.failPct}%)`, '#ef4444')}
      ${this.statChip('Skipped', String(d.skipped), '#f59e0b')}
      ${this.statChip('Execution Rate', `${d.executionPct}%`, '#3b82f6')}
    </div>

    <!-- Progress bar -->
    <div style="height:8px;border-radius:4px;background:#334155;margin-bottom:14px;overflow:hidden;">
      <div style="height:100%;width:${d.passPct}%;background:#22c55e;border-radius:4px;transition:width .4s;"></div>
    </div>

    <!-- Suite table -->
    <table style="width:100%;border-collapse:collapse;background:#fff;color:#1e293b;border-radius:6px;overflow:hidden;font-size:12px;">
      <thead>
        <tr style="background:#1e293b;color:#f1f5f9;">
          <th style="padding:7px 12px;text-align:left;">Test Suite</th>
          <th style="padding:7px 12px;text-align:center;">Total</th>
          <th style="padding:7px 12px;text-align:center;">Passed</th>
          <th style="padding:7px 12px;text-align:center;">Failed</th>
          <th style="padding:7px 12px;text-align:center;">Skipped</th>
          <th style="padding:7px 12px;text-align:center;">Pass Rate</th>
          <th style="padding:7px 12px;text-align:center;">Duration</th>
          <th style="padding:7px 12px;text-align:center;">Status</th>
        </tr>
      </thead>
      <tbody>${suiteRows}</tbody>
    </table>
  </div>
</div>`;
    }

    private statChip(label: string, value: string, color: string): string {
        return `
        <div style="display:flex;flex-direction:column;align-items:center;background:#334155;border-radius:8px;padding:6px 14px;min-width:80px;">
          <span style="font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;">${label}</span>
          <span style="font-size:15px;font-weight:700;color:${color};">${value}</span>
        </div>`;
    }

    private formatDuration(ms: number): string {
        const s = Math.floor(ms / 1000);
        const m = Math.floor(s / 60);
        return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
    }
}

export default SummaryReporter;
