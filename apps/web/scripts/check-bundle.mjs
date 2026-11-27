// Fails if the fixture transport or obvious secrets ended up in a production bundle.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const root = process.argv[2] ?? 'dist';
const forbidden = [
  ['fixture transport', /__glassflowFixture|ds-work-fixture|FIXTURE_NOT_DEFINED|createFixtureTransport/],
  ['API key pattern', /AIza[0-9A-Za-z_-]{30,}|sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9]{32,}/],
];
const files = [];
const walk = dir => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path);
    else if (/\.(js|css|html|map)$/.test(name)) files.push(path);
  }
};
walk(root);
let failed = false;
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const [label, pattern] of forbidden) {
    if (pattern.test(text)) {
      console.error(`FAIL ${label}: ${file}`);
      failed = true;
    }
  }
}
// The banner component itself is allowed (it renders only when transportKind === 'fixture').
console.log(failed ? 'bundle check FAILED' : `bundle check PASS: ${files.length} files, no fixture data or key patterns`);
process.exit(failed ? 1 : 0);
