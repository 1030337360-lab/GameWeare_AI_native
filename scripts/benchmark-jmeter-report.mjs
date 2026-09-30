// Summarize JMeter's raw CSV/JTL without treating expected 403/409 as successful claims.
// Usage: node scripts/benchmark-jmeter-report.mjs <directory-containing-jtl-files>
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const directory = process.argv[2];
if (!directory) throw new Error('Provide the directory containing JMeter JTL files');

function percentile(sorted, p) {
  return sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * p / 100) - 1)] : null;
}

function summarize(samples) {
  if (!samples.length) return null;
  const latencies = samples.map((row) => Number(row[1])).sort((a, b) => a - b);
  const started = Math.min(...samples.map((row) => Number(row[0])));
  const ended = Math.max(...samples.map((row) => Number(row[0]) + Number(row[1])));
  const seconds = (ended - started) / 1000;
  const statusCounts = {};
  for (const row of samples) statusCounts[row[3]] = (statusCounts[row[3]] ?? 0) + 1;
  const responseBytes = samples.map((row) => Number(row[9])).filter(Number.isFinite);
  return {
    samples: samples.length,
    durationSeconds: Number(seconds.toFixed(2)),
    requestsPerSecond: Number((samples.length / seconds).toFixed(2)),
    p50Ms: percentile(latencies, 50), p95Ms: percentile(latencies, 95),
    p99Ms: percentile(latencies, 99), maxMs: latencies.at(-1) ?? null,
    responseBytes: responseBytes.length ? {
      min: Math.min(...responseBytes), max: Math.max(...responseBytes),
      average: Number((responseBytes.reduce((sum, bytes) => sum + bytes, 0) / responseBytes.length).toFixed(1)),
    } : null,
    statusCounts,
  };
}

const report = { generatedAt: new Date().toISOString(), kind: 'JMeter CLI raw JTL summary', scenarios: {} };
for (const file of readdirSync(directory).filter((name) => name.endsWith('.jtl')).sort()) {
  const lines = readFileSync(join(directory, file), 'utf8').trim().split(/\r?\n/).slice(1);
  const samples = lines.map((line) => line.split(',')).filter((columns) =>
    columns.length >= 4 && Number.isFinite(Number(columns[0])) && Number.isFinite(Number(columns[1])));
  const labels = [...new Set(samples.map((row) => row[2]))].sort();
  report.scenarios[file.replace(/\.jtl$/, '')] = {
    ...summarize(samples),
    labels: Object.fromEntries(labels.map((label) => [label,
      summarize(samples.filter((row) => row[2] === label))])),
  };
}
const output = join(directory, 'jmeter-summary.json');
writeFileSync(output, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
console.log(`Saved ${output}`);
