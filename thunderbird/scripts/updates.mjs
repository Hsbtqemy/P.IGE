// Adds a version to the self-hosted update manifest of the extension (updates.json), which
// Thunderbird reads from the manifest's update_url. Run by .github/workflows/thunderbird.yml:
//   node scripts/updates.mjs <updates.json (existing or missing)> <version> <xpi url> <sha256> <min TB>
// Not packaged in the .xpi.
import { existsSync, readFileSync, writeFileSync } from 'node:fs';

export const ADDON_ID = 'pige@hsbtqemy.github';

/** The manifest with ``version`` added (or replaced), versions in order. */
export function addVersion(manifest, { version, link, hash, minVersion }) {
  const out = structuredClone(manifest || {});
  out.addons ??= {};
  const addon = (out.addons[ADDON_ID] ??= { updates: [] });
  const entry = {
    version,
    update_link: link,
    update_hash: `sha256:${hash}`,
    applications: { gecko: { strict_min_version: minVersion } }
  };
  addon.updates = [...addon.updates.filter((u) => u.version !== version), entry].sort((a, b) =>
    compareVersions(a.version, b.version)
  );
  return out;
}

export function compareVersions(a, b) {
  const pa = String(a).split('.').map(Number);
  const pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [file, version, link, hash, minVersion] = process.argv.slice(2);
  if (!file || !version || !link || !/^[0-9a-f]{64}$/.test(hash || '') || !minVersion) {
    console.error('usage: updates.mjs <updates.json> <version> <xpi url> <sha256> <min TB version>');
    process.exit(2);
  }
  const current = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  writeFileSync(file, `${JSON.stringify(addVersion(current, { version, link, hash, minVersion }), null, 2)}\n`);
}
