import { HealMode } from '../src/utils/healMode';

const fails: string[] = [];
function check(label: string, got: unknown, want: unknown) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    console.log((ok ? '  PASS  ' : '  FAIL  ') + `${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
    if (!ok) fails.push(label);
}

console.log('\n== verify pass: skip list ==');
const d = HealMode.openDefect('users1::Empty Payload');
check('defect row found',       d !== null, true);
check('defect status',          d?.status, 500);
check('defect id shape',        /^DEF-/.test(d?.id ?? ''), true);
check('healthy row not parked', HealMode.openDefect('users1::Users1 Happy Path'), null);
check('open defect count',      HealMode.openDefects().length, 1);

console.log('\n== gating ==');
check('verifying() on dev',     HealMode.verifying(), true);
check('capturing() off in verify mode', HealMode.capturing(), false);

console.log('\n== stale skip list cannot leak into a normal run ==');
const savedMode = process.env.HEAL_MODE;
process.env.HEAL_MODE = '';
HealMode.resetCache();
check('skip list ignored outside a verify pass',
      HealMode.openDefect('users1::Empty Payload'), null);
check('open defects empty outside a verify pass',
      HealMode.openDefects().length, 0);
process.env.HEAL_MODE = savedMode;
HealMode.resetCache();
check('skip list live again inside the verify pass',
      HealMode.openDefect('users1::Empty Payload') !== null, true);

process.env.ENVIRONMENT = 'mock';
HealMode.resetCache();
check('skip list ignored on MOCK even in verify mode',
      HealMode.openDefect('users1::Empty Payload'), null);
check('verifying() blocked on MOCK', HealMode.verifying(), false);
process.env.HEAL_MODE = 'capture';
check('capturing() blocked on MOCK', HealMode.capturing(), false);
process.env.ENVIRONMENT = 'qa';
check('capturing() blocked on QA (out of scope)', HealMode.capturing(), false);
process.env.ENVIRONMENT = 'uat';
check('capturing() allowed on UAT', HealMode.capturing(), true);

console.log('\n== proxy rule mirrors heal.py ==');
for (const [url, want] of [
    ['https://mulesoft-sit.co/experience-proxy/api/v1/users', true],
    ['https://sf.example.com/salesforce-PROXY/x', true],
    ['https://host/eproxy/api', true],
    ['https://reqres.in/api/users/2', false],
] as [string, boolean][]) check(`isProxyUrl ${url}`, HealMode.isProxyUrl(url), want);

console.log('\n' + (fails.length ? `FAILED: ${fails}` : 'ALL CHECKS PASSED'));
process.exit(fails.length ? 1 : 0);
