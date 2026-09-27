import React from "react";
import { ArrowRight, CalendarDays, Gift, Sparkles, Ticket, Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import "./rewards.css";

type Checkin = { month: string; days: number[]; currentStreak: number; longestStreak: number; totalDays: number };
type Voucher = { id: string; sourceType: string; status: string; expiresAt: string };
type Campaign = { id: string; title: string; startsAt: string; endsAt: string; totalStock: number; remainingStock: number };
type Claim = { campaignId: string; reservationId?: string; status: string; voucherId?: string };
type Leader = { userId: string; displayName: string; streak: number };

export default function Rewards() {
  const { apiFetch } = useAuth();
  const [checkin, setCheckin] = React.useState<Checkin | null>(null);
  const [vouchers, setVouchers] = React.useState<Voucher[]>([]);
  const [campaigns, setCampaigns] = React.useState<Campaign[]>([]);
  const [leaderboard, setLeaderboard] = React.useState<Leader[]>([]);
  const [claims, setClaims] = React.useState<Record<string, Claim>>({});
  const [busy, setBusy] = React.useState(false);
  const [notice, setNotice] = React.useState("");

  const load = React.useCallback(async () => {
    const results = await Promise.allSettled([
      apiFetch("/checkins/me"), apiFetch("/vouchers/me"),
      apiFetch("/voucher-campaigns"), apiFetch("/checkins/leaderboard"),
    ]);
    if (results[0].status === "fulfilled" && results[0].value.ok) setCheckin(await results[0].value.json() as Checkin);
    if (results[1].status === "fulfilled" && results[1].value.ok) setVouchers(await results[1].value.json() as Voucher[]);
    if (results[2].status === "fulfilled" && results[2].value.ok) setCampaigns(await results[2].value.json() as Campaign[]);
    if (results[3].status === "fulfilled" && results[3].value.ok) setLeaderboard(await results[3].value.json() as Leader[]);
  }, [apiFetch]);

  React.useEffect(() => { void load(); }, [load]);
  React.useEffect(() => {
    const pending = Object.entries(claims).filter(([, claim]) => claim.status === "pending");
    if (!pending.length) return;
    const timer = window.setInterval(async () => {
      for (const [campaignId] of pending) {
        try {
          const response = await apiFetch(`/voucher-campaigns/${campaignId}/claims/me`);
          if (!response.ok) continue;
          const next = await response.json() as Claim;
          setClaims((current) => ({ ...current, [campaignId]: next }));
          if (next.status === "issued") void load();
        } catch { /* Keep the provisional state until the next poll. */ }
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [claims, apiFetch, load]);

  async function signIn() {
    setBusy(true);
    try {
      const response = await apiFetch("/checkins", { method: "POST" });
      if (!response.ok) throw new Error("签到失败，请稍后重试");
      setCheckin(await response.json() as Checkin);
      setNotice("今日签到完成。连续签到达标后会自动发放生成券。");
      await load();
    } catch (error) { setNotice(error instanceof Error ? error.message : "签到失败"); }
    finally { setBusy(false); }
  }

  async function claim(campaignId: string) {
    setBusy(true);
    try {
      const response = await apiFetch(`/voucher-campaigns/${campaignId}/claim`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: string; message?: string } | null;
        throw new Error(payload?.detail || payload?.message || "活动暂时无法领取");
      }
      const result = await response.json() as Claim;
      setClaims((current) => ({ ...current, [campaignId]: result }));
      setNotice("抢到名额，生成券正在发放中。到账状态会自动更新。");
    } catch (error) { setNotice(error instanceof Error ? error.message : "抢券失败"); }
    finally { setBusy(false); }
  }

  const today = new Date().getUTCDate();
  const monthLength = new Date(new Date().getUTCFullYear(), new Date().getUTCMonth() + 1, 0).getDate();
  return <main className="rewards-page">
    <header className="rewards-hero"><div><span className="section-kicker">YOUR PLAY PASS</span><h1>每天来，玩出更多可能。</h1><p>连续签到获得官方模型生成券；限量活动也会在这里开放。券可用于创建或优化一次游戏。</p></div><span className="rewards-hero-icon"><Gift size={52} /></span></header>
    {notice && <p className="rewards-notice" role="status">{notice}</p>}
    <section className="rewards-grid">
      <article className="rewards-card"><div className="rewards-card-heading"><CalendarDays /><div><span>DAILY CHECK-IN</span><h2>连续签到</h2></div></div>
        <div className="streak-value"><strong>{checkin?.currentStreak ?? 0}</strong><span>天连续签到</span></div>
        <div className="checkin-calendar">{Array.from({ length: monthLength }, (_, index) => <span key={index}
          className={`${checkin?.days.includes(index + 1) ? "signed" : ""} ${today === index + 1 ? "today" : ""}`} title={`${index + 1} 日`}>{index + 1}</span>)}</div>
        <button className="rewards-primary" onClick={() => void signIn()} disabled={busy || Boolean(checkin?.days.includes(today))}>{checkin?.days.includes(today) ? "今日已签到" : "今日签到"}</button>
        <p className="rewards-hint">连续 7 天、30 天各得一张券；每自然月最多两张。</p>
      </article>
      <article className="rewards-card"><div className="rewards-card-heading"><Trophy /><div><span>STREAK RANKING</span><h2>签到排行榜</h2></div></div>
        <ol className="rewards-ranking">{leaderboard.length ? leaderboard.slice(0, 10).map((person, index) => <li key={person.userId}><b>{String(index + 1).padStart(2, "0")}</b><span>{person.displayName}</span><strong>{person.streak} 天</strong></li>) : <li>目前还没有榜单数据</li>}</ol>
      </article>
    </section>
    <section className="rewards-section"><div className="rewards-section-title"><span className="section-kicker">LIMITED DROP</span><h2>生成券限量活动</h2></div>
      <div className="campaign-grid">{campaigns.length ? campaigns.map((campaign) => {
        const now = Date.now(), starts = new Date(campaign.startsAt).getTime(), ends = new Date(campaign.endsAt).getTime();
        const active = now >= starts && now < ends;
        const status = claims[campaign.id]?.status;
        return <article className="campaign-card" key={campaign.id}><div className="campaign-mark"><Ticket size={25} /></div><h3>{campaign.title}</h3>
          <p>{new Date(campaign.startsAt).toLocaleString()} 开始 · 每人限领一张</p>
          <div className="campaign-foot"><span>{status === "pending" ? "抢到名额 · 发放中" : status === "issued" ? "生成券已到账" : status === "failed" ? "发放失败" : active ? "限时开放" : now < starts ? "即将开始" : "已结束"}</span>
            <button onClick={() => void claim(campaign.id)} disabled={busy || !active || status === "pending" || status === "issued"}> {status === "issued" ? "已领取" : "立即抢券"}</button></div>
        </article>;
      }) : <p className="rewards-empty">暂无限量活动，签到也可以获得生成券。</p>}</div>
    </section>
    <section className="rewards-section"><div className="rewards-section-title"><span className="section-kicker">YOUR VOUCHERS</span><h2>我的生成券</h2></div>
      <div className="voucher-list">{vouchers.length ? vouchers.map((voucher) => <div className="voucher-item" key={voucher.id}><span><Sparkles size={20} /> 官方模型生成券</span><small>{voucher.sourceType === "checkin" ? "签到奖励" : "限量活动"} · {voucher.status === "available" ? "可使用" : voucher.status === "reserved" ? "任务中" : voucher.status === "used" ? "已使用" : "已过期"}</small><time>有效期至 {new Date(voucher.expiresAt).toLocaleDateString()}</time></div>) : <p className="rewards-empty">还没有生成券。完成签到或参加限量活动即可获得。</p>}</div>
      <Link className="rewards-create-link" to="/create">带着灵感去创建游戏 <ArrowRight size={18} /></Link>
    </section>
  </main>;
}
