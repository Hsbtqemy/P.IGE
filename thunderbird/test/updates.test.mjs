import assert from 'node:assert/strict';
import test from 'node:test';
import { ADDON_ID, addVersion, compareVersions } from '../scripts/updates.mjs';

test('versions are added in order, a rebuilt one replaced', () => {
  const v = (version, hash) => ({ version, link: `https://x/pige-thunderbird-${version}.xpi`, hash, minVersion: '153.0' });
  let m = addVersion({}, v('0.3.1', 'a'.repeat(64)));
  m = addVersion(m, v('0.3.10', 'b'.repeat(64)));
  m = addVersion(m, v('0.3.2', 'c'.repeat(64)));
  m = addVersion(m, v('0.3.2', 'd'.repeat(64)));
  const updates = m.addons[ADDON_ID].updates;
  assert.deepEqual(updates.map((u) => u.version), ['0.3.1', '0.3.2', '0.3.10']);
  assert.equal(updates[1].update_hash, `sha256:${'d'.repeat(64)}`);
  assert.equal(updates[0].applications.gecko.strict_min_version, '153.0');
  assert.ok(compareVersions('1.0', '0.9.9') > 0);
});
