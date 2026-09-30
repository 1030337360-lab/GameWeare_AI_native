// Snapshot authenticated Prometheus histograms on both API instances and compare tiers.
// node scripts/benchmark-stage-report.mjs snapshot <out.json> <users.csv>
// node scripts/benchmark-stage-report.mjs report <before.json> <after.json> <out.json>
import { readFileSync, writeFileSync } from 'node:fs';

const [mode, first, second, third] = process.argv.slice(2);
const endpoints = ['http://127.0.0.1:18080', 'http://127.0.0.1:18081'];

function parseBuckets(body) {
  const buckets = {};
  for (const line of body.split(/\r?\n/)) {
    const match = line.match(/^gameweare_voucher_stage_seconds_bucket\{([^}]+)\}\s+([\d.eE+-]+)$/);
    if (!match) continue;
    const stage = match[1].match(/(?:^|,)stage="([^"]+)"/)?.[1];
    const bound = match[1].match(/(?:^|,)le="([^"]+)"/)?.[1];
    if (!stage || !bound) continue;
    (buckets[stage] ??= {})[bound] = Number(match[2]);
  }
  return buckets;
}

function combine(instances) {
  const total = {};
  for (const instance of instances) for (const [stage, buckets] of Object.entries(instance)) {
    const combined = total[stage] ??= {};
    for (const [bound, count] of Object.entries(buckets))
      combined[bound] = (combined[bound] ?? 0) + count;
  }
  return total;
}

function quantile(buckets, ratio) {
  const bounds = Object.keys(buckets).filter((v) => v !== '+Inf')
    .map((raw) => ({ value: Number(raw), observed: buckets[raw] }))
    .sort((a, b) => a.value - b.value);
  const count = buckets['+Inf'] ?? bounds.at(-1)?.observed ?? 0;
  if (!count) return null;
  const target = count * ratio;
  let previousBound = 0, previousCount = 0;
  for (const { value: bound, observed } of bounds) {
    if (observed >= target) {
      const share = observed === previousCount ? 0 : (target - previousCount) / (observed - previousCount);
      return Number(((previousBound + (bound - previousBound) * share) * 1000).toFixed(3));
    }
    previousBound = bound; previousCount = observed;
  }
  return null;
}

if (mode === 'snapshot') {
  if (!first || !second) throw new Error('snapshot requires output and users CSV');
  const token = readFileSync(second, 'utf8').split(/\r?\n/, 1)[0].split(',', 2)[1];
  if (!token?.startsWith('Bearer ')) throw new Error('Missing benchmark Bearer token');
  const instances = await Promise.all(endpoints.map(async (endpoint) => {
    const response = await fetch(endpoint + '/actuator/prometheus', { headers: { Authorization: token } });
    if (!response.ok) throw new Error(`${endpoint} metrics HTTP ${response.status}`);
    return parseBuckets(await response.text());
  }));
  writeFileSync(first, JSON.stringify({ at: new Date().toISOString(), endpoints, buckets: combine(instances) }, null, 2));
  console.log(`Saved stage snapshot to ${first}: ${Object.keys(combine(instances)).length} stages`);
} else if (mode === 'report') {
  if (!first || !second || !third) throw new Error('report requires before, after, output');
  const before = JSON.parse(readFileSync(first, 'utf8'));
  const after = JSON.parse(readFileSync(second, 'utf8'));
  const stages = {};
  for (const stage of Object.keys(after.buckets).sort()) {
    const delta = {};
    for (const [bound, count] of Object.entries(after.buckets[stage]))
      delta[bound] = Math.max(0, count - (before.buckets[stage]?.[bound] ?? 0));
    const count = delta['+Inf'] ?? 0;
    if (count) stages[stage] = { count, p95Ms: quantile(delta, 0.95), p99Ms: quantile(delta, 0.99) };
  }
  const result = { start: before.at, end: after.at, method: 'aggregated Prometheus histogram bucket deltas; quantiles interpolated within buckets', stages };
  writeFileSync(third, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} else {
  throw new Error('Mode must be snapshot or report');
}
