import React from "react";
import { createPortal } from "react-dom";
import { Activity, AlertCircle, ArrowRight, Boxes, Check, ChevronDown, ClipboardList, Database, Gamepad2, Gift, HardDrive, LoaderCircle, RefreshCw, RotateCcw, Search, ShieldCheck, Trash2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { readApiError } from "../services/api";
import "./maintainer.css";
import "./maintainer-theme.css";

type Tab = "overview" | "jobs" | "runs" | "games" | "assets" | "reviews" | "usage" | "vouchers";
type Job = { id: string; status: string; currentStage: string | null; errorMessage: string | null; promptSummary: string; creatorEmail: string | null; createdAt: string };
type Run = { runId: string; projectTitle: string | null; agentMode: string; errorMessage: string | null; creatorEmail: string | null; steps: { stepNo: number; stage: string; status: string; outputSummary: string | null }[] };
type Game = { id: string; slug: string; title: string; visibility: string; publishStatus: string; plays: number; likes: number; updatedAt: string };
type Asset = { id: string; kind: string; bucket: string; objectKey: string; sizeBytes: number; gameId: string | null; createdAt: string };
type Review = { id: string; targetType: string; targetId: string; status: string; reason: string; createdAt: string };
type Usage = { jobId: string; jobStatus: string; engine: string; model: string; completedCalls: number; pendingCalls: number; unknownCalls: number; recordedTokens: number };
type Overview = { jobCounts: Record<string, number>; failedJobsLast24h: number; pendingReviews: number; publicGames: number; assetsTotal: number; assetsBytes: number; recentFailedJobs: Job[] };
type TraceStep = { stepNo: number; stage: string; status: string; message: string | null; createdAt: string };
type ModelCall = { id: string; model: string; state: string; promptTokens: number | null; completionTokens: number | null; startedAt: string; endedAt: string | null };
type JobTrace = { id: string; status: string; engine: string; agentMode: string; createType: string; projectId: string; gameId: string | null; gameSlug: string | null; publishStatus: string | null; creatorEmail: string; promptSummary: string; errorMessage: string | null; reservedTokens: number; actualTokens: number | null; attempts: number; createdAt: string; updatedAt: string; steps: TraceStep[]; modelCalls: ModelCall[]; workflow?: { phase: string; promptTokens: number; completionTokens: number; usedTokens: number } };

const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "总览", icon: <Activity size={18} /> },
  { id: "jobs", label: "创建任务", icon: <ClipboardList size={18} /> },
  { id: "runs", label: "失败运行", icon: <AlertCircle size={18} /> },
  { id: "games", label: "游戏管理", icon: <Gamepad2 size={18} /> },
  { id: "assets", label: "资源文件", icon: <HardDrive size={18} /> },
  { id: "reviews", label: "审核记录", icon: <ShieldCheck size={18} /> },
  { id: "usage", label: "Agent 用量", icon: <Database size={18} /> },
  { id: "vouchers", label: "生成券活动", icon: <Gift size={18} /> },
];
const shortId = (id: string) => id.length > 15 ? `${id.slice(0, 8)}…${id.slice(-5)}` : id;
const date = (value?: string | null) => { if (!value) return "—"; const d = new Date(value); return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("zh-CN", { hour12: false }); };
const bytes = (value: number) => value >= 1073741824 ? `${(value / 1073741824).toFixed(1)} GB` : value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${(value / 1024).toFixed(1)} KB`;
const maskedEmail = (value: string | null) => { if (!value) return "—"; const [name, domain] = value.split("@"); return domain ? `${name.slice(0, 2)}***@${domain}` : "***"; };
function badge(status: string) { const tone = ["failed", "rejected", "unknown"].includes(status) ? "danger" : ["completed", "published", "approved", "reviewed"].includes(status) ? "success" : ["running", "pending", "reviewing"].includes(status) ? "warning" : "neutral"; return <span className={`admin-badge ${tone}`}>{status}</span>; }

export default function MaintainerPanel() {
  const { user, apiFetch } = useAuth();
  const [tab, setTab] = React.useState<Tab>("overview");
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [runs, setRuns] = React.useState<Run[]>([]);
  const [games, setGames] = React.useState<Game[]>([]);
  const [assets, setAssets] = React.useState<Asset[]>([]);
  const [reviews, setReviews] = React.useState<Review[]>([]);
  const [usage, setUsage] = React.useState<Usage[]>([]);
  const [campaigns, setCampaigns] = React.useState<{ id: string; title: string; startsAt: string; endsAt: string; totalStock: number; remainingStock: number }[]>([]);
  const [rewardRules, setRewardRules] = React.useState<{ milestone: number; voucherCount: number; validityDays: number; enabled: boolean; effectiveAt: string | null; state: string }[]>([]);
  const [campaignTitle, setCampaignTitle] = React.useState("");
  const [campaignStart, setCampaignStart] = React.useState("");
  const [campaignEnd, setCampaignEnd] = React.useState("");
  const [campaignStock, setCampaignStock] = React.useState(100);
  const [ruleMilestone, setRuleMilestone] = React.useState(7);
  const [ruleCount, setRuleCount] = React.useState(1);
  const [ruleDays, setRuleDays] = React.useState(30);
  const [ruleEffective, setRuleEffective] = React.useState("");
  const [filter, setFilter] = React.useState("");
  const [query, setQuery] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [expandedRun, setExpandedRun] = React.useState<string | null>(null);
  const [revision, setRevision] = React.useState(0);
  const [traceId, setTraceId] = React.useState<string | null>(null);
  const [trace, setTrace] = React.useState<JobTrace | null>(null);
  const [traceLoading, setTraceLoading] = React.useState(false);
  const [traceError, setTraceError] = React.useState("");
  const [traceRevision, setTraceRevision] = React.useState(0);
  const authorized = user?.role === "admin" || user?.role === "maintainer";

  function switchTab(next: Tab) { setFilter(""); setQuery(""); setError(""); setTab(next); }
  React.useEffect(() => {
    if (!authorized) return;
    let active = true;
    const path = tab === "overview" ? "/maintenance/overview" : tab === "runs" ? "/maintenance/create-runs/failed?limit=50" : tab === "usage" ? "/maintenance/agent-usage?limit=50" : tab === "vouchers" ? "/maintenance/voucher-campaigns" :
      `/maintenance/${tab}?limit=50${filter && (tab === "jobs" || tab === "games" || tab === "reviews") ? `&status=${encodeURIComponent(filter)}` : ""}${tab === "games" && query ? `&q=${encodeURIComponent(query.trim())}` : ""}`;
    setLoading(true); setError("");
    apiFetch(path).then(async response => {
      if (!response.ok) throw new Error((await readApiError(response)).message || `请求失败 (${response.status})`);
      const data: unknown = await response.json();
      if (!active) return;
      if (tab === "overview") setOverview(data as Overview);
      if (tab === "jobs") setJobs(data as Job[]);
      if (tab === "runs") setRuns(data as Run[]);
      if (tab === "games") setGames(data as Game[]);
      if (tab === "assets") setAssets(data as Asset[]);
      if (tab === "reviews") setReviews(data as Review[]);
      if (tab === "usage") setUsage(data as Usage[]);
      if (tab === "vouchers") setCampaigns(data as typeof campaigns);
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "加载失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [authorized, apiFetch, tab, filter, query, revision]);

  React.useEffect(() => {
    if (!authorized || tab !== "vouchers") return;
    void apiFetch("/maintenance/reward-rules").then(async response => {
      if (response.ok) setRewardRules(await response.json() as typeof rewardRules);
    });
  }, [authorized, apiFetch, tab, revision]);

  React.useEffect(() => {
    if (!authorized || !traceId) return;
    let active = true;
    let timer: number | undefined;
    const loadTrace = async () => {
      setTraceLoading(true);
      try {
        const response = await apiFetch(`/maintenance/jobs/${encodeURIComponent(traceId)}/trace`);
        if (!response.ok) throw new Error((await readApiError(response)).message || `轨迹加载失败 (${response.status})`);
        const payload = (await response.json()) as JobTrace;
        if (!active) return;
        setTrace(payload); setTraceError("");
        if (["pending", "queued", "generating", "running", "planning", "reviewing"].includes(payload.status)) timer = window.setTimeout(loadTrace, 3000);
      } catch (e) { if (active) setTraceError(e instanceof Error ? e.message : "轨迹加载失败"); }
      finally { if (active) setTraceLoading(false); }
    };
    void loadTrace();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [authorized, apiFetch, traceId, traceRevision]);

  function openTrace(id: string) { setTrace(null); setTraceError(""); setTraceId(id); }

  async function action(key: string, path: string, init: RequestInit, success: string) {
    setBusy(key); setError(""); setNotice("");
    try {
      const response = await apiFetch(path, init);
      if (!response.ok) throw new Error((await readApiError(response)).message || `操作失败 (${response.status})`);
      setNotice(success); setRevision(n => n + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(null); }
  }
  function retry(job: Job) {
    if (window.confirm(`重新运行任务 ${shortId(job.id)}？这会创建一个新任务。`)) void action(job.id, `/maintenance/jobs/${encodeURIComponent(job.id)}/retry`, { method: "POST" }, "已创建重试任务");
  }
  function markReviewed(job: Job) {
    if (window.confirm(`将任务 ${shortId(job.id)} 标记为已查看？`)) void action(job.id, `/maintenance/jobs/${encodeURIComponent(job.id)}/mark-reviewed`, { method: "POST" }, "已记录查看结果");
  }
  function updateGame(game: Game, field: "visibility" | "publishStatus", value: string) {
    if (window.confirm(`将「${game.title}」的${field === "visibility" ? "可见范围" : "发布状态"}改为 ${value}？`)) void action(game.id, `/maintenance/games/${encodeURIComponent(game.id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [field]: value }) }, "游戏状态已更新");
  }
  function moderate(game: Game, status: "approved" | "rejected") {
    if (window.confirm(`${status === "approved" ? "通过" : "驳回"}「${game.title}」的审核？`)) void action(game.id, `/maintenance/games/${encodeURIComponent(game.id)}/moderate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, reason: "管理员在管理界面操作" }) }, "审核结果已记录");
  }
  function deleteAsset(asset: Asset) {
    if (window.confirm(`永久删除资源 ${shortId(asset.id)}？此操作无法撤销。正在被游戏使用的资源会被后端拒绝删除。`)) void action(asset.id, `/maintenance/assets/${encodeURIComponent(asset.id)}`, { method: "DELETE" }, "资源已删除");
  }

  if (!authorized) return <main className="admin-gate"><ShieldCheck size={42} /><h1>仅管理员可访问</h1><p>请使用具有 admin 或 maintainer 角色的账号登录。</p><Link to="/profile">返回个人中心 <ArrowRight size={16} /></Link></main>;
  return <main className="admin-shell"><div className="admin-frame">
    <aside className="admin-sidebar"><div className="admin-sidebar-brand"><span className="admin-emblem"><Boxes size={21} /></span><span><strong>GAMEWEARE</strong><small>管理工作台</small></span></div><p className="admin-sidebar-label">工作空间</p><nav aria-label="管理员导航">{tabs.map(item => <button key={item.id} type="button" className={tab === item.id ? "active" : ""} onClick={() => switchTab(item.id)}>{item.icon}<span>{item.label}</span>{tab === item.id && <ArrowRight size={15} className="admin-nav-arrow" />}</button>)}</nav><div className="admin-sidebar-foot"><ShieldCheck size={17} /> 管理员模式已启用</div></aside>
    <section className="admin-main"><div className="admin-hero"><div><span className="admin-eyebrow">OPERATIONS CENTER / 运营控制台</span><h1>{tabs.find(item => item.id === tab)?.label}</h1><p>查看平台运行情况，处理创建任务与内容审核。</p></div><button type="button" className="admin-refresh" onClick={() => setRevision(n => n + 1)} disabled={loading}><RefreshCw size={17} className={loading ? "spin" : ""} /> 刷新数据</button></div>
      <div className="admin-mobile-tabs">{tabs.map(item => <button key={item.id} type="button" className={tab === item.id ? "active" : ""} onClick={() => switchTab(item.id)}>{item.icon}{item.label}</button>)}</div>
      {error && <div className="admin-feedback error" role="alert"><AlertCircle size={18} />{error}<button onClick={() => setError("")} aria-label="关闭提示"><X size={16} /></button></div>}
      {notice && <div className="admin-feedback success" role="status"><Check size={18} />{notice}<button onClick={() => setNotice("")} aria-label="关闭提示"><X size={16} /></button></div>}
      {loading && <div className="admin-loading"><LoaderCircle size={20} className="spin" /> 正在同步数据…</div>}
      {tab === "vouchers" && <div className="admin-grid">
        <section className="admin-card"><div className="admin-card-head"><div><span className="admin-kicker">LIMITED DROP</span><h2>创建生成券秒杀</h2></div><Gift size={20} /></div>
          <form className="admin-voucher-form" onSubmit={event => { event.preventDefault(); void action("campaign", "/maintenance/voucher-campaigns", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: campaignTitle, startsAt: new Date(campaignStart).toISOString(), endsAt: new Date(campaignEnd).toISOString(), stock: campaignStock }) }, "活动已创建"); }}>
            <label>活动名称<input required maxLength={160} value={campaignTitle} onChange={event => setCampaignTitle(event.target.value)} /></label>
            <label>开始时间<input required type="datetime-local" value={campaignStart} onChange={event => setCampaignStart(event.target.value)} /></label>
            <label>结束时间<input required type="datetime-local" value={campaignEnd} onChange={event => setCampaignEnd(event.target.value)} /></label>
            <label>总库存<input required type="number" min={1} max={1000000} value={campaignStock} onChange={event => setCampaignStock(Number(event.target.value))} /></label>
            <button type="submit" disabled={busy !== null}>创建活动</button>
          </form>
          {campaigns.map(campaign => <div className="admin-recent" key={campaign.id}><strong>{campaign.title}</strong><p>{date(campaign.startsAt)} 至 {date(campaign.endsAt)} · 已发 {campaign.totalStock - campaign.remainingStock}/{campaign.totalStock}</p><button type="button" onClick={async () => { const response = await apiFetch(`/maintenance/voucher-campaigns/${campaign.id}/reconcile`); setNotice(response.ok ? JSON.stringify(await response.json()) : "对账失败"); }}>查看库存对账</button></div>)}
        </section>
        <section className="admin-card"><div className="admin-card-head"><div><span className="admin-kicker">CHECK-IN REWARDS</span><h2>未来生效的签到奖励</h2></div><Gift size={20} /></div>
          <form className="admin-voucher-form" onSubmit={event => { event.preventDefault(); void action("rule", "/maintenance/reward-rules", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ milestone: ruleMilestone, voucherCount: ruleCount, validityDays: ruleDays, enabled: true, effectiveAt: new Date(ruleEffective).toISOString() }) }, "签到规则已安排生效"); }}>
            <label>连续天数<input required type="number" min={1} max={365} value={ruleMilestone} onChange={event => setRuleMilestone(Number(event.target.value))} /></label>
            <label>奖励张数<input required type="number" min={1} max={2} value={ruleCount} onChange={event => setRuleCount(Number(event.target.value))} /></label>
            <label>有效天数<input required type="number" min={1} max={365} value={ruleDays} onChange={event => setRuleDays(Number(event.target.value))} /></label>
            <label>生效时间<input required type="datetime-local" value={ruleEffective} onChange={event => setRuleEffective(event.target.value)} /></label>
            <button type="submit" disabled={busy !== null}>安排规则</button>
          </form>
          {rewardRules.map((rule, index) => <div className="admin-recent" key={`${rule.milestone}-${index}`}><strong>连续 {rule.milestone} 天 · {rule.voucherCount} 张</strong><p>{rule.state === "scheduled" ? `将于 ${date(rule.effectiveAt)} 生效` : "当前基础规则"} · 有效 {rule.validityDays} 天 · {rule.enabled ? "启用" : "停用"}</p></div>)}
        </section>
      </div>}
      {tab === "overview" && overview && <><div className="admin-metrics"><Metric label="公开游戏" value={overview.publicGames} icon={<Gamepad2 size={20} />} tone="violet" /><Metric label="近 24 小时失败任务" value={overview.failedJobsLast24h} icon={<AlertCircle size={20} />} tone="coral" /><Metric label="待审核" value={overview.pendingReviews} icon={<ShieldCheck size={20} />} tone="gold" /><Metric label="资源占用" value={bytes(overview.assetsBytes)} sub={`${overview.assetsTotal} 个文件`} icon={<HardDrive size={20} />} tone="blue" /></div><div className="admin-grid"><section className="admin-card"><div className="admin-card-head"><div><span className="admin-kicker">TASK PIPELINE</span><h2>任务状态分布</h2></div><ClipboardList size={20} /></div><div className="admin-status-list">{Object.entries(overview.jobCounts).length ? Object.entries(overview.jobCounts).map(([status, count]) => <div key={status}><span>{badge(status)}</span><strong>{count}</strong><div className="admin-progress"><i style={{ width: `${Math.max(3, count / Math.max(1, Object.values(overview.jobCounts).reduce((a, b) => a + b, 0)) * 100)}%` }} /></div></div>) : <Empty text="暂无创建任务" />}</div></section><section className="admin-card"><div className="admin-card-head"><div><span className="admin-kicker">ATTENTION REQUIRED</span><h2>最近失败任务</h2></div><button className="admin-text-button" onClick={() => { setTab("jobs"); setFilter("failed"); }}>查看全部 <ArrowRight size={15} /></button></div>{overview.recentFailedJobs.length ? overview.recentFailedJobs.map(job => <div className="admin-recent" key={job.id}><div>{badge(job.status)}<small>{date(job.createdAt)}</small></div><button type="button" className="admin-recent-open" onClick={() => openTrace(job.id)}>{job.promptSummary || shortId(job.id)} <ArrowRight size={14} /></button><p>{job.errorMessage || "暂无错误详情"}</p></div>) : <Empty text="没有需要处理的失败任务" />}</section></div></>}
      {(tab === "jobs" || tab === "games" || tab === "reviews") && <div className="admin-toolbar"><div className="admin-filter"><span>状态筛选</span><select value={filter} onChange={e => setFilter(e.target.value)}><option value="">全部状态</option>{(tab === "jobs" ? ["queued", "running", "completed", "failed"] : tab === "games" ? ["draft", "reviewing", "published", "rejected", "archived"] : ["pending", "approved", "rejected", "reviewed"]).map(value => <option key={value} value={value}>{value}</option>)}</select><ChevronDown size={15} /></div>{tab === "games" && <label className="admin-search"><Search size={17} /><input placeholder="搜索游戏名称或 slug" value={query} onChange={e => setQuery(e.target.value)} /></label>}</div>}
      {tab === "jobs" && <section className="admin-card"><SectionHead title="创建任务" count={jobs.length} subtitle="点击任务编号直接查看完整执行轨迹、模型调用和 Token 消耗" /><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>任务 / 提示词</th><th>创建者</th><th>状态</th><th>当前阶段</th><th>创建时间</th><th>操作</th></tr></thead><tbody>{jobs.map(job => <tr key={job.id}><td><button type="button" className="admin-task-link" title={`查看 ${job.id} 的执行轨迹`} onClick={() => openTrace(job.id)}>{shortId(job.id)} <ArrowRight size={14} /></button><small title={job.promptSummary}>{job.promptSummary || "—"}</small>{job.errorMessage && <em title={job.errorMessage}>{job.errorMessage}</em>}</td><td>{maskedEmail(job.creatorEmail)}</td><td>{badge(job.status)}</td><td>{job.currentStage || "—"}</td><td>{date(job.createdAt)}</td><td><div className="admin-row-actions"><button type="button" onClick={() => openTrace(job.id)}><Activity size={15} /> 轨迹</button><button disabled={busy !== null} onClick={() => markReviewed(job)}><Check size={15} /> 已查看</button>{job.status === "failed" && <button disabled={busy !== null} onClick={() => retry(job)}><RotateCcw size={15} /> 重试</button>}</div></td></tr>)}</tbody></table></div>{!jobs.length && !loading && <Empty text="没有符合条件的任务" />}</section>}
      {tab === "runs" && <section className="admin-card"><SectionHead title="失败运行详情" count={runs.length} subtitle="展开记录，查看每一步的执行信息" />{runs.length ? runs.map(run => <div className="admin-run" key={run.runId}><button className="admin-run-heading" onClick={() => setExpandedRun(expandedRun === run.runId ? null : run.runId)} aria-expanded={expandedRun === run.runId}><span className="admin-run-icon"><AlertCircle size={19} /></span><span><strong>{run.projectTitle || shortId(run.runId)}</strong><small>{maskedEmail(run.creatorEmail)} · {run.agentMode}</small></span><span className="admin-run-error">{run.errorMessage || "运行失败"}</span><ChevronDown size={18} className={expandedRun === run.runId ? "up" : ""} /></button>{expandedRun === run.runId && <div className="admin-steps">{run.steps.length ? run.steps.map(step => <div key={step.stepNo}><span className="admin-step-index">{step.stepNo}</span><div><strong>{step.stage}</strong> {badge(step.status)}<p>{step.outputSummary || "暂无输出摘要"}</p></div></div>) : <Empty text="暂无步骤记录" />}</div>}</div>) : !loading && <Empty text="当前没有失败运行" />}</section>}
      {tab === "games" && <section className="admin-card"><SectionHead title="游戏内容" count={games.length} subtitle="发布、可见性与审核" /><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>游戏</th><th>状态</th><th>可见性</th><th>数据</th><th>更新于</th><th>管理操作</th></tr></thead><tbody>{games.map(game => <tr key={game.id}><td><strong>{game.title}</strong><small>{game.slug}</small></td><td>{badge(game.publishStatus)}</td><td><select aria-label={`${game.title} 可见性`} value={game.visibility} disabled={busy !== null} onChange={e => updateGame(game, "visibility", e.target.value)}><option value="private">private</option><option value="unlisted">unlisted</option><option value="public">public</option></select></td><td>{game.plays} 次游玩 · {game.likes} 赞</td><td>{date(game.updatedAt)}</td><td><div className="admin-row-actions"><select aria-label={`${game.title} 发布状态`} value={game.publishStatus} disabled={busy !== null} onChange={e => updateGame(game, "publishStatus", e.target.value)}>{["draft", "reviewing", "published", "rejected", "archived"].map(status => <option key={status} value={status}>{status}</option>)}</select><button disabled={busy !== null} onClick={() => moderate(game, "approved")}>通过</button><button disabled={busy !== null} onClick={() => moderate(game, "rejected")}>驳回</button></div></td></tr>)}</tbody></table></div>{!games.length && !loading && <Empty text="没有符合条件的游戏" />}</section>}
      {tab === "assets" && <section className="admin-card"><SectionHead title="对象存储资源" count={assets.length} subtitle="最近 50 个文件；使用中的文件由后端保护" /><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>资源</th><th>存储位置</th><th>大小</th><th>关联游戏</th><th>创建于</th><th>操作</th></tr></thead><tbody>{assets.map(asset => <tr key={asset.id}><td><strong title={asset.id}>{shortId(asset.id)}</strong><small>{asset.kind}</small></td><td className="admin-object-key" title={asset.objectKey}>{asset.bucket}/{asset.objectKey}</td><td>{bytes(asset.sizeBytes)}</td><td>{asset.gameId ? shortId(asset.gameId) : "—"}</td><td>{date(asset.createdAt)}</td><td><button className="admin-danger-action" disabled={busy !== null} onClick={() => deleteAsset(asset)}><Trash2 size={15} /> 删除</button></td></tr>)}</tbody></table></div>{!assets.length && !loading && <Empty text="暂无资源文件" />}</section>}
      {tab === "reviews" && <section className="admin-card"><SectionHead title="审核记录" count={reviews.length} subtitle="最近 50 条处理记录" /><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>目标</th><th>结果</th><th>原因</th><th>时间</th></tr></thead><tbody>{reviews.map(review => <tr key={review.id}><td><strong>{review.targetType}</strong><small title={review.targetId}>{shortId(review.targetId)}</small></td><td>{badge(review.status)}</td><td>{review.reason || "—"}</td><td>{date(review.createdAt)}</td></tr>)}</tbody></table></div>{!reviews.length && !loading && <Empty text="暂无审核记录" />}</section>}
      {tab === "usage" && <section className="admin-card"><SectionHead title="Agent 调用与 Token" count={usage.length} subtitle="按任务聚合，便于排查计费与失败状态" /><div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>任务</th><th>引擎 / 模型</th><th>任务状态</th><th>已完成</th><th>进行中</th><th>未知</th><th>记录 Token</th></tr></thead><tbody>{usage.map(row => <tr key={`${row.jobId}-${row.model}`}><td title={row.jobId}><button type="button" className="admin-task-link" onClick={() => openTrace(row.jobId)}>{shortId(row.jobId)} <ArrowRight size={14} /></button></td><td>{row.engine}<small>{row.model}</small></td><td>{badge(row.jobStatus)}</td><td>{row.completedCalls}</td><td>{row.pendingCalls}</td><td className={row.unknownCalls ? "admin-warning-text" : ""}>{row.unknownCalls}</td><td><strong>{row.recordedTokens.toLocaleString()}</strong></td></tr>)}</tbody></table></div>{!usage.length && !loading && <Empty text="暂无 Agent 调用记录" />}</section>}
    </section>
    {traceId && createPortal(<div className="admin-trace-overlay" onMouseDown={event => { if (event.target === event.currentTarget) setTraceId(null); }}>
      <aside className="admin-trace-panel" role="dialog" aria-modal="true" aria-label="任务执行轨迹">
        <div className="admin-trace-top"><span className="admin-kicker">EXECUTION TRACE / 执行轨迹</span><button type="button" onClick={() => setTraceId(null)} aria-label="关闭轨迹"><X size={20} /></button></div>
        <div className="admin-trace-head"><div><h2>任务执行轨迹</h2><code>{traceId}</code></div><button type="button" className="admin-refresh" onClick={() => setTraceRevision(n => n + 1)} disabled={traceLoading}><RefreshCw size={16} className={traceLoading ? "spin" : ""} /> 刷新</button></div>
        {traceLoading && !trace && <div className="admin-loading"><LoaderCircle size={18} className="spin" /> 正在读取轨迹…</div>}
        {traceError && <div className="admin-feedback error" role="alert"><AlertCircle size={17} />{traceError}</div>}
        {trace && <div className="admin-trace-content">
          <div className="admin-trace-summary"><div>{badge(trace.status)}<span>{date(trace.createdAt)}</span></div><h3>{trace.promptSummary || "未命名任务"}</h3><p>{maskedEmail(trace.creatorEmail)} · {trace.engine} / {trace.agentMode} · {trace.createType}</p>{trace.errorMessage && <p className="admin-trace-error">{trace.errorMessage}</p>}</div>
          <div className="admin-trace-metrics"><div><span>执行尝试</span><strong>{trace.attempts}</strong></div><div><span>预留 Token</span><strong>{trace.reservedTokens ?? 0}</strong></div><div><span>实际 Token</span><strong>{trace.actualTokens ?? "—"}</strong></div><div><span>模型调用</span><strong>{trace.modelCalls.length}</strong></div></div>
          {trace.gameSlug && trace.publishStatus === "published" && <Link className="admin-trace-play" to={`/play/${trace.gameSlug}`}><Gamepad2 size={17} /> 游玩这款游戏 <ArrowRight size={17} /></Link>}
          <div className="admin-trace-section"><h3><Activity size={17} /> 运行步骤 <span>{trace.steps.length}</span></h3>{trace.steps.length ? <ol className="admin-trace-timeline">{trace.steps.map(step => <li key={step.stepNo} className={`trace-${step.status}`}><div className="admin-trace-step-marker">{step.stepNo}</div><div className="admin-trace-step-body"><div><strong>{step.stage}</strong>{badge(step.status)}</div><p>{step.message || "暂无阶段说明"}</p><small>{date(step.createdAt)}</small></div></li>)}</ol> : <Empty text="任务还没有运行步骤" />}</div>
          <div className="admin-trace-section"><h3><Database size={17} /> 模型调用 <span>{trace.modelCalls.length}</span></h3>{trace.modelCalls.length ? <div className="admin-model-calls">{trace.modelCalls.map(call => <div key={call.id}><div><strong>{call.model}</strong>{badge(call.state)}</div><p>输入 {call.promptTokens ?? "—"} · 输出 {call.completionTokens ?? "—"} Token</p><small>{date(call.startedAt)}{call.endedAt ? ` → ${date(call.endedAt)}` : ""}</small></div>)}</div> : <Empty text="暂无模型调用记录" />}</div>
        </div>}
      </aside>
    </div>, document.body)}
  </div></main>;
}
function Metric({ label, value, sub, icon, tone }: { label: string; value: string | number; sub?: string; icon: React.ReactNode; tone: string }) { return <div className={`admin-metric ${tone}`}><div className="admin-metric-icon">{icon}</div><span>{label}</span><strong>{value}</strong><small>{sub || "实时数据"}</small></div>; }
function SectionHead({ title, subtitle, count }: { title: string; subtitle: string; count: number }) { return <div className="admin-section-head"><div><span className="admin-kicker">MANAGEMENT</span><h2>{title} <span>{count}</span></h2><p>{subtitle}</p></div></div>; }
function Empty({ text }: { text: string }) { return <div className="admin-empty"><Boxes size={28} /><span>{text}</span></div>; }
