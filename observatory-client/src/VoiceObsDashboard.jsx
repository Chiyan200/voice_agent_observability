import { useState, useEffect, useRef, useCallback } from "react";

const API_BASE = "http://localhost:8009";

const fetcher = async (path) => {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

// ── Color utils ────────────────────────────────────────────────────────────────
const severityColor = (s) => ({
  critical: "text-red-400 bg-red-400/10 border-red-400/20",
  warning:  "text-amber-400 bg-amber-400/10 border-amber-400/20",
  info:     "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
}[s] || "text-slate-400 bg-slate-400/10 border-slate-400/20");

const categoryBadge = (cat) => ({
  tool_failure:          "bg-red-900/40 text-red-300 border-red-700/40",
  latency_spike:         "bg-amber-900/40 text-amber-300 border-amber-700/40",
  sentiment_crash:       "bg-purple-900/40 text-purple-300 border-purple-700/40",
  hallucination:         "bg-cyan-900/40 text-cyan-300 border-cyan-700/40",
  topic_drift:           "bg-blue-900/40 text-blue-300 border-blue-700/40",
  incomplete_resolution: "bg-rose-900/40 text-rose-300 border-rose-700/40",
}[cat] || "bg-slate-800 text-slate-300 border-slate-600");

// ── Tiny sparkline ─────────────────────────────────────────────────────────────
function Sparkline({ values, color = "#34d399" }) {
  if (!values?.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 80, h = 28;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    h - ((v - min) / range) * (h - 4) - 2,
  ]);
  const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0]},${p[1]}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline points={pts.map(p => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.8" />
    </svg>
  );
}

// ── Stat card ──────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color = "text-white", icon }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400 font-medium tracking-wider uppercase">{label}</span>
        {icon && <span className="text-slate-500 text-lg">{icon}</span>}
      </div>
      <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
function Badge({ text, cls }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-md border font-mono ${cls}`}>{text}</span>
  );
}

// ── Section header ─────────────────────────────────────────────────────────────
function SectionHeader({ title, sub, action }) {
  return (
    <div className="flex items-end justify-between mb-4">
      <div>
        <h2 className="text-sm font-semibold text-white tracking-wide uppercase">{title}</h2>
        {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

// ── Loading skeleton ───────────────────────────────────────────────────────────
function Skeleton({ h = "h-20" }) {
  return <div className={`${h} bg-slate-800/60 rounded-xl animate-pulse`} />;
}

// ── Nav ────────────────────────────────────────────────────────────────────────
const NAV = [
  { id: "dashboard", label: "Dashboard", icon: "⬡" },
  { id: "calls",     label: "Calls",     icon: "◈" },
  { id: "analysis",  label: "Analysis",  icon: "◆" },
  { id: "monitor",   label: "Monitor",   icon: "◉" },
];

// ── DASHBOARD VIEW ─────────────────────────────────────────────────────────────
function DashboardView() {
  const [data, setData] = useState(null);
  const [failures, setFailures] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetcher("/analysis/dashboard"),
      fetcher("/calls/failures"),
      fetcher("/monitor/anomalies"),
    ]).then(([d, f, a]) => {
      setData(d); setFailures(f); setAnomalies(a);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {Array(8).fill(0).map((_, i) => <Skeleton key={i} />)}
    </div>
  );
  if (!data) return <div className="text-slate-500 text-sm">Failed to load. Is the API running at {API_BASE}?</div>;

  const successRates = data.tool_stats.map(t => t.success_rate);
  const avgLatencies = data.latency_stats.map(t => t.avg_latency_ms);

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Calls" value={data.total_calls} icon="📞" />
        <StatCard label="Failed Calls" value={data.failed_calls} color="text-red-400" icon="⚠️"
          sub={`${((data.failed_calls / data.total_calls) * 100 || 0).toFixed(1)}% failure rate`} />
        <StatCard label="Avg Duration" value={`${data.avg_call_duration_sec}s`} icon="⏱" />
        <StatCard label="Anomalies" value={anomalies?.total_anomalies ?? "—"} color="text-amber-400" icon="🔍" />
      </div>

      {/* Failure taxonomy */}
      {failures && (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
          <SectionHeader title="Failure Taxonomy" sub="Auto-detected across all calls" />
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(failures.failure_counts).map(([cat, cnt]) => (
              <div key={cat} className="bg-slate-900/60 rounded-lg p-3 border border-slate-700/30">
                <div className="flex items-center justify-between mb-2">
                  <Badge text={cat.replace(/_/g, " ")} cls={categoryBadge(cat)} />
                  <span className="text-lg font-bold text-white font-mono">{cnt}</span>
                </div>
                <div className="text-xs text-slate-500">{failures.sample_call_ids[cat]?.length || 0} samples</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tool stats */}
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
        <SectionHeader title="Tool Performance" sub="Success rates across all tools" />
        <div className="space-y-2">
          {data.tool_stats.map(t => (
            <div key={t.tool_name} className="flex items-center gap-3">
              <div className="w-36 text-xs text-slate-400 truncate font-mono">{t.tool_name}</div>
              <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500 rounded-full transition-all"
                  style={{ width: `${t.success_rate}%`, background: t.success_rate > 80 ? "#34d399" : t.success_rate > 50 ? "#f59e0b" : "#f87171" }} />
              </div>
              <div className="text-xs font-mono text-white w-12 text-right">{t.success_rate}%</div>
              <div className="text-xs text-slate-500 w-20 text-right">{t.total_calls} calls</div>
            </div>
          ))}
        </div>
      </div>

      {/* Latency + Sentiment */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
          <SectionHeader title="Latency Stats" sub="Per-call avg / max / p95 (ms)" />
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1 custom-scroll">
            {data.latency_stats.slice(0, 10).map(s => (
              <div key={s.call_id} className="flex items-center gap-2 text-xs">
                <span className="text-slate-500 font-mono truncate w-28">{s.call_id.slice(-8)}</span>
                <span className="text-emerald-400 font-mono">{s.avg_latency_ms}ms avg</span>
                <span className={`font-mono ${s.max_latency_ms > 3000 ? "text-red-400" : "text-slate-400"}`}>{s.max_latency_ms}ms max</span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
          <SectionHeader title="Sentiment Trends" sub="User frustration scores" />
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1 custom-scroll">
            {data.sentiment_trends.map(s => (
              <div key={s.call_id} className="flex items-center gap-2">
                <div className="flex-1">
                  <div className="flex items-center justify-between text-xs mb-0.5">
                    <span className="text-slate-500 font-mono">{s.call_id.slice(-8)}</span>
                    <Badge text={s.user_sentiment} cls={s.user_sentiment === "negative" ? categoryBadge("sentiment_crash") : "bg-emerald-900/30 text-emerald-300 border-emerald-700/30"} />
                  </div>
                  <div className="h-1 bg-slate-700 rounded-full">
                    <div className="h-full rounded-full" style={{ width: `${s.frustration_score * 100}%`, background: s.frustration_score > 0.6 ? "#f87171" : "#34d399" }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Outliers */}
      {data.outlier_call_ids?.length > 0 && (
        <div className="bg-slate-800/40 border border-amber-700/20 rounded-xl p-5">
          <SectionHeader title="Outlier Calls" sub="High latency or multiple failure categories" />
          <div className="flex flex-wrap gap-2">
            {data.outlier_call_ids.map(id => (
              <span key={id} className="text-xs font-mono px-2 py-1 bg-amber-900/30 text-amber-300 border border-amber-700/30 rounded-lg">{id.slice(-16)}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── CALLS VIEW ─────────────────────────────────────────────────────────────────
function CallsView() {
  const [calls, setCalls] = useState(null);
  const [selected, setSelected] = useState(null);
  const [replay, setReplay] = useState(null);
  const [report, setReport] = useState(null);
  const [tab, setTab] = useState("detail");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [seeking, setSeeking] = useState(false);
  const [seekTurn, setSeekTurn] = useState(null);
  const [seekInput, setSeekInput] = useState(0);

  useEffect(() => {
    setLoading(true);
    fetcher(`/calls?page=${page}&page_size=15`)
      .then(d => { setCalls(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [page]);

  const loadCall = async (id) => {
    const [det, rep, failRep] = await Promise.all([
      fetcher(`/calls/${id}`),
      fetcher(`/calls/${id}/replay`),
      fetcher(`/analysis/${id}/report`).catch(() => null),
    ]);
    setSelected(det); setReplay(rep); setReport(failRep); setTab("detail"); setSeekTurn(null);
  };

  const doSeek = async () => {
    if (!selected) return;
    setSeeking(true);
    const data = await fetcher(`/calls/${selected.call_id}/seek?turn=${seekInput}`).catch(() => null);
    setSeekTurn(data?.turn || null);
    setSeeking(false);
  };

  const typeColor = (t) => ({ stt: "text-blue-400", llm: "text-emerald-400", tts: "text-purple-400", tool_call: "text-amber-400" }[t] || "text-slate-400");

  return (
    <div className="grid grid-cols-5 gap-4 h-full">
      {/* Left: call list */}
      <div className="col-span-2 space-y-2">
        <SectionHeader title="Call History" sub={calls ? `${calls.total} total` : ""} />
        {loading ? Array(6).fill(0).map((_, i) => <Skeleton key={i} h="h-14" />) : (
          <>
            <div className="space-y-1.5 max-h-[calc(100vh-220px)] overflow-y-auto pr-1 custom-scroll">
              {calls?.items?.map(c => (
                <button key={c.call_id} onClick={() => loadCall(c.call_id)}
                  className={`w-full text-left p-3 rounded-lg border transition-all ${selected?.call_id === c.call_id
                    ? "bg-slate-700 border-slate-500" : "bg-slate-800/40 border-slate-700/40 hover:bg-slate-800"}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-mono text-slate-300">{c.call_id.slice(-12)}</span>
                    {c.tool_failures > 0 && <Badge text={`${c.tool_failures}✗`} cls="bg-red-900/40 text-red-300 border-red-700/40" />}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <span>{c.call_type}</span>
                    <span>·</span>
                    <span>{c.call_duration}s</span>
                    <span>·</span>
                    <span>{c.total_turns} turns</span>
                    {c.has_analysis && <Badge text="analyzed" cls="bg-emerald-900/30 text-emerald-400 border-emerald-700/30" />}
                  </div>
                </button>
              ))}
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="flex-1 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-lg text-slate-300 hover:bg-slate-700 disabled:opacity-40">← Prev</button>
              <span className="text-xs text-slate-500 self-center px-2">p{page}</span>
              <button onClick={() => setPage(p => p + 1)} disabled={!calls?.items?.length || calls.items.length < 15}
                className="flex-1 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded-lg text-slate-300 hover:bg-slate-700 disabled:opacity-40">Next →</button>
            </div>
          </>
        )}
      </div>

      {/* Right: detail */}
      <div className="col-span-3">
        {!selected ? (
          <div className="h-full flex items-center justify-center text-slate-600 text-sm">Select a call to inspect</div>
        ) : (
          <div className="space-y-4">
            {/* Tab bar */}
            <div className="flex gap-1 bg-slate-800/60 p-1 rounded-lg border border-slate-700/40">
              {["detail", "replay", "report"].map(t => (
                <button key={t} onClick={() => setTab(t)}
                  className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all ${tab === t ? "bg-slate-600 text-white" : "text-slate-400 hover:text-white"}`}>
                  {t.toUpperCase()}
                </button>
              ))}
            </div>

            {tab === "detail" && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-2">
                  <StatCard label="Duration" value={`${selected.call_duration}s`} />
                  <StatCard label="Type" value={selected.call_type} />
                  <StatCard label="Turns" value={selected.observations?.length} />
                </div>
                <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4 max-h-96 overflow-y-auto custom-scroll space-y-2">
                  {selected.observations?.map((o, i) => (
                    <div key={i} className="flex gap-2 text-xs">
                      <span className="text-slate-600 font-mono w-4 shrink-0">{i}</span>
                      <span className={`font-mono w-16 shrink-0 ${typeColor(o.type)}`}>{o.type}</span>
                      <span className="text-slate-300 flex-1 break-all">{o.content || (o.tool_name ? `⚙ ${o.tool_name}` : "—")}</span>
                      {o.tool_status && <Badge text={o.tool_status} cls={o.tool_status === "failure" ? categoryBadge("tool_failure") : "bg-emerald-900/30 text-emerald-300 border-emerald-700/30"} />}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "replay" && replay && (
              <div className="space-y-3">
                <div className="flex gap-2 items-center">
                  <input type="number" min={0} max={replay.total_turns - 1} value={seekInput}
                    onChange={e => setSeekInput(Number(e.target.value))}
                    className="w-20 px-2 py-1.5 text-xs bg-slate-900 border border-slate-700 rounded-lg text-white font-mono" />
                  <button onClick={doSeek} disabled={seeking}
                    className="px-3 py-1.5 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white hover:bg-slate-600 disabled:opacity-40">
                    {seeking ? "…" : "Seek →"}
                  </button>
                  <span className="text-xs text-slate-500">{replay.total_turns} total turns</span>
                </div>

                {seekTurn && (
                  <div className="bg-slate-900 border border-cyan-700/30 rounded-xl p-4 text-xs space-y-1">
                    <div className="text-cyan-400 font-mono font-bold mb-2">Turn {seekTurn.turn_index} · {seekTurn.type} [{seekTurn.role}]</div>
                    <div className="text-slate-300">{seekTurn.content || "—"}</div>
                    {seekTurn.latency_ms !== null && <div className="text-amber-400 font-mono">latency: {seekTurn.latency_ms}ms</div>}
                    {seekTurn.tool_name && <div className="text-purple-400">⚙ {seekTurn.tool_name} → {seekTurn.tool_output}</div>}
                  </div>
                )}

                <div className="max-h-80 overflow-y-auto custom-scroll space-y-1">
                  {replay.turns?.map(t => (
                    <div key={t.turn_index} className={`flex gap-2 text-xs p-2 rounded-lg border ${t.latency_ms > 3000 ? "border-red-700/30 bg-red-900/10" : "border-transparent"}`}>
                      <span className="text-slate-600 font-mono w-4 shrink-0">{t.turn_index}</span>
                      <span className={`font-mono w-16 shrink-0 ${typeColor(t.type)}`}>{t.type}</span>
                      <span className="text-slate-300 flex-1 break-all">{t.content || (t.tool_name ? `${t.tool_name}` : "—")}</span>
                      {t.latency_ms != null && <span className={`font-mono shrink-0 ${t.latency_ms > 3000 ? "text-red-400" : "text-slate-500"}`}>{t.latency_ms}ms</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === "report" && (
              <div className="space-y-3">
                {!report ? (
                  <div className="text-slate-500 text-sm p-4">No failure report available for this call.</div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <StatCard label="Total Turns" value={report.total_turns} />
                      <StatCard label="Failure Turns" value={report.failure_turns?.length || 0} color="text-red-400" />
                    </div>
                    {report.hallucination_detected && (
                      <div className="text-xs px-3 py-2 bg-cyan-900/20 border border-cyan-700/30 rounded-lg text-cyan-300">⚡ Hallucination detected (duplicate LLM responses)</div>
                    )}
                    {report.unresolved_queries?.length > 0 && (
                      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
                        <div className="text-xs font-semibold text-slate-400 mb-2">Unresolved Queries</div>
                        {report.unresolved_queries.map((q, i) => (
                          <div key={i} className="text-xs text-amber-300 font-mono">• {q}</div>
                        ))}
                      </div>
                    )}
                    {report.failure_turns?.map(ft => (
                      <div key={ft.turn_index} className="bg-slate-900/60 border border-red-700/20 rounded-xl p-4 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-red-400 font-mono font-bold">Turn {ft.turn_index}</span>
                          <Badge text={ft.type} cls="bg-slate-800 text-slate-300 border-slate-600" />
                        </div>
                        {ft.content && <div className="text-xs text-slate-400 italic">"{ft.content}"</div>}
                        {ft.root_causes?.map((rc, i) => (
                          <div key={i} className="space-y-1">
                            <Badge text={rc.category} cls={categoryBadge(rc.category)} />
                            <div className="text-xs text-red-300 mt-1">↳ {rc.what_happened}</div>
                            <div className="text-xs text-emerald-300">✓ {rc.what_should_happen}</div>
                          </div>
                        ))}
                      </div>
                    ))}
                    {report.qa_summary && (
                      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
                        <div className="text-xs font-semibold text-slate-400 mb-1">QA Summary</div>
                        <p className="text-xs text-slate-300 leading-relaxed">{report.qa_summary}</p>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── ANALYSIS VIEW ──────────────────────────────────────────────────────────────
function AnalysisView() {
  const [callId, setCallId] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    if (!callId.trim()) return;
    setLoading(true); setError(null); setAnalysis(null);
    try {
      const d = await fetcher(`/analysis/${callId.trim()}`);
      setAnalysis(d);
    } catch (e) { setError("Not found or API error."); }
    setLoading(false);
  };

  const CircleGauge = ({ value, max = 1, color, label }) => {
    const pct = Math.min(value / max, 1);
    const r = 28, cx = 36, cy = 36;
    const circ = 2 * Math.PI * r;
    const dash = pct * circ;
    return (
      <div className="flex flex-col items-center gap-1">
        <svg width="72" height="72" viewBox="0 0 72 72">
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="#334155" strokeWidth="4" />
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="4"
            strokeDasharray={`${dash} ${circ}`} strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cy})`} />
          <text x={cx} y={cy + 5} textAnchor="middle" fill="white" fontSize="11" fontWeight="600">
            {typeof value === "number" ? value.toFixed(2) : value}
          </text>
        </svg>
        <span className="text-xs text-slate-500">{label}</span>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <div>
        <SectionHeader title="Post-Call Analysis" sub="Enter a call ID to inspect its analysis" />
        <div className="flex gap-2">
          <input value={callId} onChange={e => setCallId(e.target.value)} onKeyDown={e => e.key === "Enter" && load()}
            placeholder="call_35b3ee8c-79a3-4e50-8eaa-5e3117a29c9e"
            className="flex-1 px-3 py-2 text-xs bg-slate-900 border border-slate-700 rounded-lg text-white font-mono placeholder-slate-600 focus:outline-none focus:border-slate-500" />
          <button onClick={load} disabled={loading}
            className="px-4 py-2 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white hover:bg-slate-600 disabled:opacity-40">
            {loading ? "…" : "Fetch"}
          </button>
        </div>
        {error && <div className="mt-2 text-xs text-red-400">{error}</div>}
      </div>

      {analysis && (
        <div className="space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between p-4 bg-slate-800/40 border border-slate-700/40 rounded-xl">
            <div>
              <div className="text-xs text-slate-400 font-mono">{analysis.analyze_id}</div>
              <div className="text-xs text-slate-500 mt-0.5">{new Date(analysis.analyzed_at).toLocaleString()}</div>
            </div>
            <div className="flex gap-2">
              <Badge text={analysis.qa_evaluation.is_hallucinating ? "HALLUCINATING" : "No hallucination"} cls={analysis.qa_evaluation.is_hallucinating ? categoryBadge("hallucination") : "bg-emerald-900/30 text-emerald-300 border-emerald-700/30"} />
              <Badge text={analysis.qa_evaluation.correctly_answered ? "Answered ✓" : "Unresolved ✗"} cls={analysis.qa_evaluation.correctly_answered ? "bg-emerald-900/30 text-emerald-300 border-emerald-700/30" : categoryBadge("incomplete_resolution")} />
            </div>
          </div>

          {/* Sentiment gauges */}
          <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
            <div className="text-xs font-semibold text-slate-400 mb-4">SENTIMENT ANALYSIS</div>
            <div className="flex flex-wrap gap-6 justify-around">
              <CircleGauge value={analysis.sentiment.user.frustration_score} max={1} color="#f87171" label="Frustration" />
              <CircleGauge value={analysis.sentiment.user.confidence} max={1} color="#34d399" label="Confidence" />
              <CircleGauge value={analysis.sentiment.assistant.speech_rate_wpm} max={2000} color="#a78bfa" label="WPM (asst)" />
              <div className="flex flex-col items-center gap-1">
                <div className="w-[72px] h-[72px] flex items-center justify-center rounded-full border-4 border-slate-700">
                  <span className="text-xs font-bold text-white text-center leading-tight px-1">{analysis.sentiment.user.sentiment_label}</span>
                </div>
                <span className="text-xs text-slate-500">Sentiment</span>
              </div>
              <div className="flex flex-col items-center gap-1">
                <div className="w-[72px] h-[72px] flex items-center justify-center rounded-full border-4 border-purple-700/40">
                  <span className="text-xs font-bold text-purple-300 text-center leading-tight px-1">{analysis.sentiment.assistant.tone}</span>
                </div>
                <span className="text-xs text-slate-500">Asst tone</span>
              </div>
            </div>
          </div>

          {/* Audio metrics */}
          <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
            <div className="text-xs font-semibold text-slate-400 mb-3">AUDIO METRICS</div>
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Total duration" value={`${analysis.call_audio_metrics.total_duration_sec}s`} />
              <StatCard label="User speaking" value={`${analysis.call_audio_metrics.user_speaking_time_sec.toFixed(2)}s`} />
              <StatCard label="Asst speaking" value={`${analysis.call_audio_metrics.assistant_speaking_time_sec.toFixed(2)}s`} />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-slate-500">Silence ratio</span>
              <div className="flex-1 h-1.5 bg-slate-700 rounded-full">
                <div className="h-full bg-slate-400 rounded-full" style={{ width: `${analysis.call_audio_metrics.silence_ratio * 100}%` }} />
              </div>
              <span className="text-xs text-slate-400 font-mono">{(analysis.call_audio_metrics.silence_ratio * 100).toFixed(1)}%</span>
            </div>
          </div>

          {/* QA */}
          <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
            <div className="text-xs font-semibold text-slate-400 mb-3">QA EVALUATION</div>
            {analysis.qa_evaluation.unresolved_queries?.length > 0 && (
              <div className="mb-3">
                <div className="text-xs text-amber-400 mb-1">Unresolved queries:</div>
                {analysis.qa_evaluation.unresolved_queries.map((q, i) => (
                  <div key={i} className="text-xs text-slate-300 font-mono">• {q}</div>
                ))}
              </div>
            )}
            <p className="text-xs text-slate-300 leading-relaxed">{analysis.qa_evaluation.conversation_summary}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── MONITOR VIEW ───────────────────────────────────────────────────────────────
function MonitorView() {
  const [events, setEvents] = useState([]);
  const [callId, setCallId] = useState("");
  const [wsStatus, setWsStatus] = useState("disconnected");
  const [simulating, setSimulating] = useState(false);
  const [anomalies, setAnomalies] = useState(null);
  const wsRef = useRef(null);
  const logRef = useRef(null);

  useEffect(() => {
    return () => wsRef.current?.close();
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const connect = (id) => {
    wsRef.current?.close();
    const target = id ? `${API_BASE.replace("http", "ws")}/monitor/ws/${id}` : `${API_BASE.replace("http", "ws")}/monitor/ws`;
    console.log("Connecting to WS at", target);
    const ws = new WebSocket(target);
    wsRef.current = ws;
    ws.onopen  = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");
    ws.onerror = () => setWsStatus("error");
    ws.onmessage = e => {
      try { setEvents(prev => [...prev.slice(-199), JSON.parse(e.data)]); } catch {}
    };
  };

  const simulate = async () => {
    if (!callId.trim()) return;
    setSimulating(true);
    setEvents([]);
    connect(callId.trim());
    setTimeout(async () => {
      await fetch(`${API_BASE}/monitor/simulate/${callId.trim()}`, { method: "POST" });
      setSimulating(false);
    }, 500);
  };

  const loadAnomalies = async () => {
    const d = await fetcher("/monitor/anomalies").catch(() => null);
    setAnomalies(d);
  };

  const statusDot = { connected: "bg-emerald-400", disconnected: "bg-slate-600", error: "bg-red-400" }[wsStatus];

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
        <SectionHeader title="Live Monitor" sub="WebSocket real-time call replay" />
        <div className="flex gap-2 flex-wrap">
          <input value={callId} onChange={e => setCallId(e.target.value)}
            placeholder="call_35b3ee8c-79a3-4e50-8eaa-5e3117a29c9e"
            className="flex-1 px-3 py-2 text-xs bg-slate-900 border border-slate-700 rounded-lg text-white font-mono placeholder-slate-600 focus:outline-none focus:border-slate-500 min-w-0" />
          <button onClick={simulate} disabled={simulating || !callId.trim()}
            className="px-4 py-2 text-xs bg-emerald-700 border border-emerald-600 rounded-lg text-white hover:bg-emerald-600 disabled:opacity-40 shrink-0">
            {simulating ? "Simulating…" : "▶ Simulate"}
          </button>
          <button onClick={() => connect("")}
            className="px-3 py-2 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white hover:bg-slate-600 shrink-0">
            Global WS
          </button>
          <button onClick={() => wsRef.current?.close()}
            className="px-3 py-2 text-xs bg-slate-800 border border-slate-700 rounded-lg text-slate-400 hover:bg-slate-700 shrink-0">
            Disconnect
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className={`w-2 h-2 rounded-full ${statusDot}`} />
          <span className="text-slate-400 font-mono">{wsStatus}</span>
          {events.length > 0 && <span className="text-slate-500">· {events.length} events</span>}
        </div>
      </div>

      {/* Event log */}
      <div className="bg-slate-900 border border-slate-700/40 rounded-xl">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700/40">
          <span className="text-xs text-slate-400 font-mono">EVENT LOG</span>
          <button onClick={() => setEvents([])} className="text-xs text-slate-600 hover:text-slate-400">Clear</button>
        </div>
        <div ref={logRef} className="h-72 overflow-y-auto custom-scroll p-3 space-y-1 font-mono">
          {events.length === 0 ? (
            <div className="text-slate-600 text-xs p-2">Waiting for events… Connect via Global WS or simulate a call above.</div>
          ) : events.map((ev, i) => (
            <div key={i} className={`flex gap-2 text-xs py-0.5 border-b border-slate-800 last:border-0 ${ev.severity === "critical" ? "text-red-300" : ev.severity === "warning" ? "text-amber-300" : "text-slate-300"}`}>
              <span className="text-slate-600 w-6 shrink-0">{i}</span>
              <span className={`w-20 shrink-0 ${{ critical: "text-red-400", warning: "text-amber-400", info: "text-emerald-400" }[ev.severity]}`}>{ev.event_type}</span>
              <span className="text-slate-500 shrink-0 w-24 truncate">{ev.call_id?.slice(-8)}</span>
              <span className="flex-1 text-slate-300">{ev.message}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Historical anomalies */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <div className="flex items-center justify-between mb-3">
          <SectionHeader title="Historical Anomalies" sub="One-shot scan of all stored calls" />
          <button onClick={loadAnomalies} className="px-3 py-1.5 text-xs bg-slate-700 border border-slate-600 rounded-lg text-white hover:bg-slate-600">Scan</button>
        </div>
        {anomalies && (
          <div>
            <div className="text-xs text-slate-400 mb-3">{anomalies.total_anomalies} anomalies found</div>
            <div className="space-y-1.5 max-h-60 overflow-y-auto custom-scroll">
              {anomalies.events?.slice(0, 40).map((ev, i) => (
                <div key={i} className={`flex gap-2 text-xs p-2 rounded-lg border ${severityColor(ev.severity)}`}>
                  <span className="font-mono w-14 shrink-0">{ev.severity}</span>
                  <span className="text-slate-400 w-20 shrink-0 truncate font-mono">{ev.call_id?.slice(-8)}</span>
                  <span className="flex-1">{ev.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── APP SHELL ──────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState("dashboard");

  return (
    <div className="min-h-screen bg-slate-950 text-white" style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
      {/* Top bar */}
      <div className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-6 h-6 rounded-md bg-emerald-500 flex items-center justify-center text-xs font-bold text-slate-900">V</div>
            <span className="text-sm font-semibold text-white">VoiceObs</span>
            <span className="text-xs text-slate-500 border border-slate-700 px-2 py-0.5 rounded-md">v1.0</span>
          </div>
          <nav className="flex gap-1">
            {NAV.map(n => (
              <button key={n.id} onClick={() => setView(n.id)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-all flex items-center gap-1.5 ${view === n.id
                  ? "bg-slate-700 text-white border border-slate-600" : "text-slate-400 hover:text-white hover:bg-slate-800"}`}>
                <span className="text-sm">{n.icon}</span>
                {n.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-slate-500 font-mono">{API_BASE}</span>
          </div>
        </div>
      </div>

      {/* Main */}
      <div className="max-w-7xl mx-auto px-6 py-6">
        {view === "dashboard" && <DashboardView />}
        {view === "calls"     && <CallsView />}
        {view === "analysis"  && <AnalysisView />}
        {view === "monitor"   && <MonitorView />}
      </div>

      <style>{`
        .custom-scroll::-webkit-scrollbar { width: 4px; height: 4px; }
        .custom-scroll::-webkit-scrollbar-track { background: transparent; }
        .custom-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
        .custom-scroll::-webkit-scrollbar-thumb:hover { background: #475569; }
      `}</style>
    </div>
  );
}
