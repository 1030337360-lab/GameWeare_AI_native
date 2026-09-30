// Local, closed-loop benchmark against the disposable infra/benchmark stack.
// Node >= 20; no third-party load-test dependency or real AI key is required.
import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';

const endpoints = (process.env.BENCH_API_URLS ?? 'http://127.0.0.1:18080,http://127.0.0.1:18081').split(',');
const runId = randomUUID().slice(0, 8);
const durationMs = Number(process.env.BENCH_DURATION_MS ?? 5000);
const userCount = Number(process.env.BENCH_USERS ?? 100);
const stock = Number(process.env.BENCH_STOCK ?? 20);
const prepareDir = process.env.BENCH_PREPARE_DIR;
const jobCount = Number(process.env.BENCH_JOBS ?? 12);
const composeFile = 'infra/benchmark/compose.yml';
const results = { runId, startedAt: new Date().toISOString(), endpoints, kind: 'local-docker-closed-loop',
  settings: { durationMs, userCount, stock, jobCount, workerConcurrencyPerApi: 2 }, scenarios: {} };

function percentile(sorted, percent) {
  if (!sorted.length) return null;
  return Number(sorted[Math.min(sorted.length - 1, Math.ceil(percent / 100 * sorted.length) - 1)].toFixed(2));
}

function summary(latencies, statuses, elapsedMs) {
  const sorted = latencies.toSorted((a, b) => a - b);
  const total = sorted.length;
  const success = Object.entries(statuses).filter(([code]) => Number(code) >= 200 && Number(code) < 300)
    .reduce((n, [, count]) => n + count, 0);
  return { total, success, errorRate: Number(((total - success) / Math.max(total, 1)).toFixed(4)),
    elapsedSeconds: Number((elapsedMs / 1000).toFixed(2)), rps: Number((total / (elapsedMs / 1000)).toFixed(2)),
    p50Ms: percentile(sorted, 50), p95Ms: percentile(sorted, 95), p99Ms: percentile(sorted, 99),
    maxMs: sorted.length ? Number(sorted.at(-1).toFixed(2)) : null, statuses };
}

async function request(path, options = {}, endpointIndex = 0) {
  const started = performance.now();
  try {
    const response = await fetch(endpoints[endpointIndex % endpoints.length] + path, {
      ...options, signal: AbortSignal.timeout(20000),
    });
    const body = await response.text();
    let json;
    try { json = JSON.parse(body); } catch { json = null; }
    return { status: response.status, json, body, ms: performance.now() - started };
  } catch (error) {
    return { status: 0, json: null, body: String(error), ms: performance.now() - started };
  }
}

function jsonRequest(method, path, body, token, endpointIndex = 0) {
  return request(path, { method, headers: {
    'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(method === 'POST' && path === '/create/jobs' ? { 'X-Idempotency-Key': randomUUID() } : {}),
  }, body: JSON.stringify(body) }, endpointIndex);
}

function requireStatus(response, status, label) {
  if (response.status !== status) throw new Error(`${label}: HTTP ${response.status}: ${response.body.slice(0, 350)}`);
  return response.json;
}

async function mapLimited(items, limit, task) {
  let cursor = 0;
  return Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    const output = [];
    while (cursor < items.length) {
      const index = cursor++;
      output.push([index, await task(items[index], index)]);
    }
    return output;
  })).then((chunks) => chunks.flat().toSorted((a, b) => a[0] - b[0]).map(([, value]) => value));
}

async function load(name, concurrency, work, ms = durationMs) {
  const statuses = {}, latencies = [];
  const started = performance.now(), deadline = started + ms;
  await Promise.all(Array.from({ length: concurrency }, async (_, worker) => {
    let iteration = 0;
    while (performance.now() < deadline) {
      const result = await work(worker, iteration++);
      latencies.push(result.ms);
      statuses[result.status] = (statuses[result.status] ?? 0) + 1;
    }
  }));
  const report = summary(latencies, statuses, performance.now() - started);
  results.scenarios[name] = report;
  console.log(`${name}: ${report.rps} req/s, P95 ${report.p95Ms} ms, P99 ${report.p99Ms} ms, errors ${report.errorRate * 100}%`);
  return report;
}

async function waitFor(predicate, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  do {
    const value = await predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  throw new Error(`${label} timed out`);
}

for (let i = 0; i < endpoints.length; i++) {
  await waitFor(async () => (await request('/health', {}, i)).status === 200, 120000, `API ${i} health`);
}

const password = `bench-${randomUUID()}-A1`;
const users = await mapLimited(Array.from({ length: userCount }, (_, i) => i),
  prepareDir ? 20 : 10, async (i) => {
  const email = `bench-${runId}-${i}@example.invalid`;
  const registered = requireStatus(await jsonRequest('POST', '/auth/register',
    { email, password, displayName: `Benchmark ${i}` }, undefined, i), 200, `register ${i}`);
  return { email, token: registered.accessToken, id: registered.user.id };
});
console.log(`Prepared ${users.length} disposable benchmark accounts.`);

// Promote only the disposable account inside the disposable MySQL container.
const promoted = spawnSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'mysql', 'mysql',
  '-ugameweare', '-pbenchmark-password', 'gameweare', '-e',
  `UPDATE users SET role='admin' WHERE id='${users[0].id}'`], { encoding: 'utf8' });
if (promoted.status !== 0) throw new Error(`Benchmark admin setup failed: ${promoted.stderr}`);
const admin = requireStatus(await jsonRequest('POST', '/auth/login',
  { email: users[0].email, password }), 200, 'admin login').accessToken;
const campaignStart = Date.now() + Number(process.env.BENCH_START_DELAY_MS ?? 90000);
const campaignEnd = campaignStart + (prepareDir ? 3600000 : 300000);
async function createCampaign(tierStock) {
  return requireStatus(await jsonRequest('POST', '/maintenance/voucher-campaigns', {
    title: `benchmark-${runId}-${tierStock}`, startsAt: new Date(campaignStart).toISOString(),
    endsAt: new Date(campaignEnd).toISOString(), stock: tierStock,
  }, admin), 200, `create campaign ${tierStock}`);
}
const campaign = await createCampaign(stock);
if (prepareDir) {
  const tierStocks = [...new Set((process.env.BENCH_TIER_STOCKS ?? String(stock))
    .split(',').map(Number))];
  if (tierStocks.some((n) => !Number.isInteger(n) || n < 1 || n > userCount))
    throw new Error('Every tier stock must be between 1 and BENCH_USERS');
  const campaigns = [{ stock, id: campaign.id }];
  for (const tierStock of tierStocks) {
    if (tierStock !== stock) campaigns.push({ stock: tierStock, id: (await createCampaign(tierStock)).id });
  }
  mkdirSync(prepareDir, { recursive: true });
  writeFileSync(`${prepareDir}/users.csv`, users.map((user, i) =>
    `${i % 2 ? 18081 : 18080},Bearer ${user.token}`).join('\n') + '\n');
  // Direct in-network JMeter runs avoid the Windows host's ephemeral TCP port limit.
  const midpoint = Math.ceil(users.length / 2);
  for (const [name, subset] of [['api-a', users.slice(0, midpoint)],
                                 ['api-b', users.slice(midpoint)]]) {
    writeFileSync(`${prepareDir}/users-${name}.csv`, subset.map((user) =>
      `8080,Bearer ${user.token}`).join('\n') + '\n');
    for (const tierStock of tierStocks) {
      const perApi = tierStock / 2;
      if (!Number.isInteger(perApi)) throw new Error('Realistic tiers need an even user count');
      writeFileSync(`${prepareDir}/realistic-${tierStock}-${name}.csv`,
        subset.slice(0, perApi).map((user, index) =>
          `8080,Bearer ${user.token},${index % 5 === 0 ? 1 : 0}`).join('\n') + '\n');
    }
  }
  writeFileSync(`${prepareDir}/unauthorized.csv`, users.map((_, i) =>
    `${i % 2 ? 18081 : 18080},Bearer invalid`).join('\n') + '\n');
  writeFileSync(`${prepareDir}/campaigns.json`, JSON.stringify({ runId, userCount,
    startsAt: new Date(campaignStart).toISOString(), endsAt: new Date(campaignEnd).toISOString(),
    campaigns }, null, 2));
  console.log(`JMeter fixtures ready in ${prepareDir}; campaign start ${new Date(campaignStart).toISOString()}`);
  process.exit(0);
}

const catalogPath = '/games/java-interview-quiz';
requireStatus(await request(catalogPath), 200, 'seed catalog detail');
for (const concurrency of [1, 16, 64]) {
  await load(`hot-game-c${concurrency}`, concurrency,
    (worker, iteration) => request(catalogPath, {}, worker + iteration));
}
for (const concurrency of [1, 16, 64]) {
  await load(`auth-session-c${concurrency}`, concurrency, (worker, iteration) =>
    request('/auth/session', { headers: { Authorization: `Bearer ${users[(worker + iteration) % users.length].token}` } }, worker + iteration));
}

if (Date.now() < campaignStart + 300) await new Promise((resolve) => setTimeout(resolve, campaignStart + 300 - Date.now()));
const claimRequests = users.map((user, i) => ({ user, i }));
for (let i = 0; i < Math.min(20, users.length); i++) claimRequests.push({ user: users[0], i: userCount + i });
const claimStarted = performance.now();
const claims = await mapLimited(claimRequests, Math.min(claimRequests.length, 128), async ({ user, i }) => ({
  userId: user.id, ...await jsonRequest('POST', `/voucher-campaigns/${campaign.id}/claim`, {}, user.token, i),
}));
const claimStatuses = {};
for (const claim of claims) claimStatuses[claim.status] = (claimStatuses[claim.status] ?? 0) + 1;
results.scenarios.seckill = summary(claims.map((claim) => claim.ms), claimStatuses, performance.now() - claimStarted);
results.scenarios.seckill.acceptedResponses = claimStatuses[202] ?? 0;
results.scenarios.seckill.expectedConflicts = claimStatuses[409] ?? 0;
results.scenarios.seckill.unexpectedResponses = claims.length
  - results.scenarios.seckill.acceptedResponses - results.scenarios.seckill.expectedConflicts;
if (results.scenarios.seckill.unexpectedResponses !== 0)
  throw new Error(`Unexpected seckill responses: ${JSON.stringify(claimStatuses)}`);
const reservations = new Set(claims.filter((claim) => claim.status === 202).map((claim) => claim.json?.reservationId));
const reconciliation = await waitFor(async () => {
  const response = await request(`/maintenance/voucher-campaigns/${campaign.id}/reconcile`, {
    headers: { Authorization: `Bearer ${admin}` },
  });
  if (response.status !== 200) return null;
  return response.json.issuedCount === stock ? response.json : null;
}, 60000, 'voucher issuance');
if (!reconciliation.mysqlBalanced || reconciliation.remainingStock !== 0 || reservations.size !== stock)
  throw new Error(`Seckill invariant failed: ${JSON.stringify({ reconciliation, reservations: reservations.size })}`);
const claimAudit = spawnSync('docker', ['compose', '-f', composeFile, 'exec', '-T', 'mysql', 'mysql',
  '-N', '-B', '-ugameweare', '-pbenchmark-password', 'gameweare', '-e',
  `SELECT COUNT(*), COUNT(DISTINCT user_id) FROM voucher_claims WHERE campaign_id='${campaign.id}'`], { encoding: 'utf8' });
if (claimAudit.status !== 0) throw new Error(`Voucher MySQL audit failed: ${claimAudit.stderr}`);
const [claimCount, distinctUsers] = claimAudit.stdout.trim().split(/\s+/).map(Number);
if (claimCount !== stock || distinctUsers !== stock)
  throw new Error(`Voucher one-per-user audit failed: ${claimAudit.stdout.trim()}`);
results.scenarios.seckill.uniqueReservations = reservations.size;
results.scenarios.seckill.mysqlDistinctUsers = distinctUsers;
results.scenarios.seckill.reconciliation = reconciliation;
console.log(`seckill: ${results.scenarios.seckill.rps} req/s, P95 ${results.scenarios.seckill.p95Ms} ms, `
  + `${reconciliation.issuedCount}/${stock} issued, MySQL balanced`);

requireStatus(await jsonRequest('PUT', '/create/ai-config', {
  baseUrl: 'http://mock-llm:8080', model: 'mock-model', apiKey: 'sk-benchmark', provider: 'openai',
}, users[1].token), 200, 'mock AI config');
const jobStarted = performance.now();
const jobs = await mapLimited(Array.from({ length: jobCount }, (_, i) => i), jobCount, (i) =>
  jsonRequest('POST', '/create/jobs', { prompt: `Benchmark game ${runId}-${i}`, agentMode: 'chat',
    createType: 'init', fundingMode: 'byok' }, users[1].token, i));
const jobStatuses = {};
for (const job of jobs) jobStatuses[job.status] = (jobStatuses[job.status] ?? 0) + 1;
results.scenarios.jobAcceptance = summary(jobs.map((job) => job.ms), jobStatuses, performance.now() - jobStarted);
if (jobs.some((job) => job.status !== 202)) throw new Error(`Job submit failures: ${JSON.stringify(jobStatuses)}`);
const jobIds = jobs.map((job) => job.json.id);
const finalJobs = await waitFor(async () => {
  const states = await mapLimited(jobIds, 8, async (id, i) =>
    requireStatus(await request(`/create/jobs/${id}`, {
      headers: { Authorization: `Bearer ${users[1].token}` },
    }, i), 200, `job ${id}`));
  return states.every((job) => ['completed', 'failed', 'canceled'].includes(job.status)) ? states : null;
}, 120000, 'mock game jobs');
results.scenarios.jobAcceptance.terminal = finalJobs.reduce((counts, job) => {
  counts[job.status] = (counts[job.status] ?? 0) + 1;
  return counts;
}, {});
console.log(`jobs: ${results.scenarios.jobAcceptance.rps} accepted/s, `
  + `P95 ${results.scenarios.jobAcceptance.p95Ms} ms, terminal ${JSON.stringify(results.scenarios.jobAcceptance.terminal)}`);

results.finishedAt = new Date().toISOString();
if (process.env.BENCH_OUTPUT) writeFileSync(process.env.BENCH_OUTPUT, JSON.stringify(results, null, 2));
console.log(JSON.stringify(results));
