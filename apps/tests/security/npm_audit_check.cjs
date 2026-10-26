// Run `npm audit --omit=dev` in frontend/ and fail on any advisory not listed (with its
// owner) in npm-audit-allow.txt.
//
//   node apps/tests/security/npm_audit_check.cjs        (from the repo root or frontend/)
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const here = __dirname;
const frontend = path.resolve(here, '..', '..', '..', 'frontend');
const allow = new Set(
  fs.readFileSync(path.join(here, 'npm-audit-allow.txt'), 'utf8')
    .split(/\r?\n/).map((l) => l.split('#')[0].trim()).filter(Boolean),
);

let raw;
try {
  raw = execSync('npm audit --omit=dev --json', { cwd: frontend, encoding: 'utf8' });
} catch (e) {
  raw = e.stdout;                 // npm audit exits non-zero when anything is found
}
let report;
try {
  report = JSON.parse(raw);
} catch (e) {
  report = { error: { summary: `unparseable npm audit output: ${String(raw).slice(0, 200)}` } };
}
if (report.error || !report.metadata || !report.vulnerabilities) {
  // The audit itself failed (registry down, timeout…) — never report that as "clean".
  console.error(`npm audit did not run: ${JSON.stringify(report.error || 'no report')}`);
  process.exit(1);
}
const fresh = [];
for (const v of Object.values(report.vulnerabilities || {})) {
  for (const via of v.via) {
    if (typeof via === 'object' && via.url && !allow.has(via.url.split('/').pop())) {
      fresh.push(`${via.url} (${v.name}, ${via.severity})`);
    }
  }
}
if (fresh.length) {
  console.error(`New npm advisories (fix, or list in npm-audit-allow.txt with an owner):\n${fresh.join('\n')}`);
  process.exit(1);
}
console.log('npm audit: no advisories beyond the known list');
