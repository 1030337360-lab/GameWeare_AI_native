import React from "react";
import { MessageCircle, Plus, Send, Sparkles, Check, ArrowRight } from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { readApiError } from "../utils/helpers";
import type { CreateJob } from "../types";
import "./creation-chat.css";

const FIELDS = { title: "游戏名称", concept: "主题与角色", genre: "游戏类型", coreLoop: "核心玩法", controls: "操作方式", rules: "规则与反馈", victory: "目标与胜负", artStyle: "视觉氛围", scope: "首版范围" } as const;
type Brief = Partial<Record<keyof typeof FIELDS, string>> & { questions: string[] };
type ChatMessage = { requestId: string; role: "user" | "assistant"; content: string; sequence: number; skillIds: string[] };
type Session = { id: string; status: string; revision: number; createType: "init" | "opt"; projectId: string | null; fundingMode: "byok" | "voucher"; voucherId: string | null; brief: Brief | null; ready: boolean; jobId: string | null; messages?: ChatMessage[] };
type Skill = { id: string; name: string; description: string };
type Props = { createType: "init" | "opt"; projectId: string; fundingMode: "byok" | "voucher"; voucherId: string; fundingReady: boolean; onCreated: (job: CreateJob) => void };

export default function CreationChat(props: Props) {
  const { apiFetch } = useAuth();
  const [sessions, setSessions] = React.useState<Session[]>([]);
  const [session, setSession] = React.useState<Session | null>(null);
  const [skills, setSkills] = React.useState<Skill[]>([]);
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const endRef = React.useRef<HTMLDivElement>(null);
  const requestRef = React.useRef<{ message: string; requestId: string; revision: number } | null>(null);
  const draftId = React.useRef(crypto.randomUUID());
  const sending = React.useRef(false);

  async function request<T>(path: string, body?: object): Promise<T> {
    const response = await apiFetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
    if (!response.ok) throw new Error((await readApiError(response)).message);
    return response.json() as Promise<T>;
  }
  async function refreshList() { setSessions(await request<Session[]>("/create/chat/sessions")); }
  React.useEffect(() => {
    let live = true;
    Promise.all([request<Session[]>("/create/chat/sessions"), request<Skill[]>("/create/chat/skills")])
      .then(([list, catalog]) => { if (live) { setSessions(list); setSkills(catalog); } })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : "无法加载历史对话"); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [apiFetch]);
  React.useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [session?.messages?.length, busy]);
  React.useEffect(() => {
    if (!session || session.status !== "replying" || busy) return;
    const timer = window.setInterval(() => {
      void request<Session>(`/create/chat/sessions/${session.id}`).then(setSession).catch(() => {});
    }, 3000);
    return () => window.clearInterval(timer);
  }, [session?.id, session?.status, busy]);

  async function open(id: string) {
    if (sending.current) return;
    setBusy(true); setError("");
    try { setSession(await request<Session>(`/create/chat/sessions/${id}`)); setText(""); requestRef.current = null; }
    catch (e) { setError(e instanceof Error ? e.message : "无法打开对话"); }
    finally { setBusy(false); }
  }
  function newChat() {
    if (busy) return;
    setSession(null); setText(""); setError(""); requestRef.current = null; draftId.current = crypto.randomUUID();
  }
  async function send() {
    if (sending.current || busy || !text.trim() || !props.fundingReady || session?.status === "confirmed") return;
    sending.current = true; setBusy(true); setError("");
    let current = session;
    try {
      if (!current) {
        current = await request<Session>("/create/chat/sessions", {
          id: draftId.current, createType: props.createType, projectId: props.createType === "opt" ? props.projectId : undefined,
          fundingMode: props.fundingMode, voucherId: props.fundingMode === "voucher" ? props.voucherId : undefined,
        });
        setSession(current);
      }
      const message = text.trim();
      if (!requestRef.current || requestRef.current.message !== message || requestRef.current.revision !== current.revision)
        requestRef.current = { message, requestId: crypto.randomUUID(), revision: current.revision };
      const next = await request<Session>(`/create/chat/sessions/${current.id}/messages`, requestRef.current);
      setSession(next); setText(""); requestRef.current = null;
      void refreshList().catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "回复失败，请重试");
      if (current) {
        try {
          const recovered = await request<Session>(`/create/chat/sessions/${current.id}`);
          setSession(recovered);
          if (recovered.messages?.some(m => m.requestId === requestRef.current?.requestId && m.role === "assistant")) {
            setText(""); setError(""); requestRef.current = null;
          }
        } catch { /* Keep the draft for retry. */ }
      }
    } finally { sending.current = false; setBusy(false); }
  }
  async function confirm() {
    if (!session || busy || sending.current || !session.ready) return;
    sending.current = true; setBusy(true); setError("");
    try {
      const job = await request<CreateJob>(`/create/chat/sessions/${session.id}/confirm`, { revision: session.revision });
      props.onCreated(job);
    } catch (e) { setError(e instanceof Error ? e.message : "确认失败，请重试"); }
    finally { sending.current = false; setBusy(false); }
  }
  const locked = busy || session?.status === "replying" || session?.status === "confirmed";
  const usedSkills = [...new Set(session?.messages?.flatMap(m => m.skillIds) ?? [])];
  return <section className="creation-chat" aria-label="游戏需求对话">
    <div className="creation-chat-top"><div><span className="create-overline">CHAT / 游戏想法访谈</span><h2><MessageCircle size={22} /> 先聊清楚，再开始创造</h2><p>一边对话，一边完善画像。确认后，ReAct 会将你的想法实现成游戏。</p></div>
      <button type="button" onClick={newChat} disabled={busy}><Plus size={16} /> 新对话</button></div>
    <div className="creation-chat-history"><label htmlFor="creation-chat-history">历史对话</label><select id="creation-chat-history" value={session?.id ?? ""} disabled={busy || loading} onChange={e => { if (e.target.value) void open(e.target.value); else newChat(); }}>
      <option value="">{loading ? "加载中…" : "新的游戏想法"}</option>
      {session && !sessions.some(s => s.id === session.id) && <option value={session.id}>当前对话</option>}
      {sessions.map(s => <option key={s.id} value={s.id}>{s.brief?.title || s.brief?.concept || "未命名游戏想法"} · {s.status === "confirmed" ? "已确认" : "讨论中"}</option>)}
    </select></div>
    {session && <p className="creation-chat-context">这段对话用于{session.createType === "opt" ? "优化已有游戏" : "创建新游戏"}，使用{session.fundingMode === "voucher" ? "官方生成券" : "你的模型配置"}。如需切换项目或费用来源，请新建对话。</p>}
    <div className="creation-chat-grid">
      <div className="creation-chat-conversation">
        <div className="creation-chat-messages" role="log" aria-live="polite" aria-label="对话消息">
          <article className="creation-chat-message assistant"><span className="creation-chat-avatar"><Sparkles size={16} /></span><div><strong>创作助手</strong><p>先告诉我：你想让玩家体验什么？可以只是一个故事、一个画面，或者“我想做个跑酷游戏”。我们一起把它变成清晰的玩法。</p></div></article>
          {session?.messages?.map(m => <article className={`creation-chat-message ${m.role}`} key={m.sequence}>
            <span className="creation-chat-avatar">{m.role === "user" ? "我" : <Sparkles size={16} />}</span><div><strong>{m.role === "user" ? "你" : "创作助手"}</strong><p>{m.content}</p>
              {m.skillIds.length > 0 && <div className="creation-chat-skill-tags">{m.skillIds.map(id => <span key={id}>参考：{skills.find(s => s.id === id)?.name ?? id}</span>)}</div>}
            </div></article>)}
          {(busy || session?.status === "replying") && <p className="creation-chat-thinking" role="status">创作助手正在整理你的想法…</p>}
          <div ref={endRef} />
        </div>
        {error && <p className="creation-chat-error" role="alert">{error}</p>}
        {session?.status === "confirmed" ? <button type="button" className="creation-chat-submit" disabled={busy} onClick={() => void confirm()}>查看已创建任务 <ArrowRight size={16} /></button> : <div className="creation-chat-composer">
          <label className="creation-chat-input-label" htmlFor="creation-chat-input">补充你的游戏想法</label>
          <textarea id="creation-chat-input" value={text} onChange={e => setText(e.target.value)} maxLength={2000} disabled={locked || !props.fundingReady}
            placeholder="用你自己的话描述，或者告诉我哪里需要调整…" rows={3}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }} />
          <div><small>Enter 发送 · Shift + Enter 换行</small><button type="button" disabled={locked || !text.trim() || !props.fundingReady} onClick={() => void send()}><Send size={16} /> {busy ? "正在回复…" : "发送"}</button></div>
        </div>}
      </div>
      <aside className="creation-chat-brief" aria-label="当前游戏画像"><span className="create-overline">逐步完善的需求</span><h3>你的游戏画像</h3>
        <dl>{Object.entries(FIELDS).map(([key, label]) => <div key={key}><dt>{label}</dt><dd className={session?.brief?.[key as keyof typeof FIELDS] ? "" : "missing"}>{session?.brief?.[key as keyof typeof FIELDS] || "还可以再聊聊"}</dd></div>)}</dl>
        {!!session?.brief?.questions.length && <div className="creation-chat-questions"><strong>还可以补充</strong><ul>{session.brief.questions.map(q => <li key={q}>{q}</li>)}</ul></div>}
        {usedSkills.length > 0 && <details><summary>本次使用的创作技能</summary>{usedSkills.map(id => <p key={id}>{skills.find(s => s.id === id)?.name ?? id}</p>)}</details>}
        <button type="button" className="creation-chat-submit" onClick={() => void confirm()} disabled={locked || !session?.ready}><Check size={17} /> 确认画像，开始生成</button>
        <small>{session?.ready ? "确认后交给 ReAct 生成。你仍可以继续对话修改画像。" : "明确主题、玩法、操作、规则和目标后即可确认。"} 官方券只在确认生成时占用；对话会调用所选模型。</small>
      </aside>
    </div>
  </section>;
}
