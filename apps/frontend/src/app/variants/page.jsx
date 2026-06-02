"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect, useMemo } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { EmptyState, PageHeader, Panel } from "@/components/ui";


export default function VariantsPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runSteps, setRunSteps] = useState([]);
  const [variants, setVariants] = useState([]);
  const [disagreement, setDisagreement] = useState(null);
  const [overlayLevel, setOverlayLevel] = useState("1mb");
  const [tab, setTab] = useState("variants");
  const [loading, setLoading] = useState(true);

  const selectedRun = runs.find((run) => run.id === selectedRunId) || null;
  const selectedSample = samples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId) || null;
  const sampleKey = selectedSample?.sample_id || selectedSample?.id || selectedSampleId;

  useEffect(() => { loadContext(); }, [selectedProjectId]);
  useEffect(() => {
    setDisagreement(null);
    if (sampleKey && selectedRunId) loadVariants(sampleKey, selectedRunId);
    else setVariants([]);
  }, [sampleKey, selectedRunId]);
  useEffect(() => {
    if (!selectedRunId) {
      setRunSteps([]);
      return;
    }
    loadRunSteps(selectedRunId);
  }, [selectedRunId]);
  useEffect(() => {
    if (sampleKey && selectedRunId && tab === "disagreement") loadDisagreement(sampleKey, selectedRunId, overlayLevel);
  }, [sampleKey, selectedRunId, overlayLevel, tab]);

  const loadContext = async () => {
    if (!selectedProjectId) {
      setProject(null);
      setSamples([]);
      setRuns([]);
      setVariants([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [projectRes, samplesRes, runsRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${selectedProjectId}`),
        fetch(`${API_BASE}/projects/${selectedProjectId}/samples`),
        fetch(`${API_BASE}/projects/${selectedProjectId}/runs`),
      ]);
      setProject(projectRes.ok ? await projectRes.json() : null);
      const samplesData = samplesRes.ok ? await samplesRes.json() : { items: [] };
      const runsData = runsRes.ok ? await runsRes.json() : { items: [] };
      setSamples(samplesData.items || samplesData || []);
      setRuns((runsData.items || runsData || []).slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")));
    } catch (error) {
      console.error(error);
      setProject(null);
      setSamples([]);
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  const loadRunSteps = async (runId = selectedRunId) => {
    if (!runId) return;
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/steps`);
      const data = res.ok ? await res.json() : { items: [] };
      setRunSteps(data.items || data || []);
    } catch {
      setRunSteps([]);
    }
  };

  const loadVariants = async (sid, runId) => {
    try {
      const res = await fetch(`${API_BASE}/samples/${sid}/variants?run_id=${encodeURIComponent(runId)}`);
      if (res.ok) { const data = await res.json(); setVariants(data.items || []); }
      else setVariants([]);
    } catch { setVariants([]); }
  };

  const loadDisagreement = async (sid, runId, level) => {
    try {
      const params = new URLSearchParams({ level, run_id: runId });
      const res = await fetch(`${API_BASE}/samples/${sid}/caller-disagreement-overlay?${params}`);
      if (res.ok) setDisagreement(await res.json());
      else setDisagreement(null);
    } catch { setDisagreement(null); }
  };

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading variants…</div>;

  return (
    <div>
      <PageHeader
        eyebrow="Sample evidence"
        title="Variants"
        description="Run-scoped variant calls for the project/run selected in Projects."
      />

      <Panel title="Variant Context">
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <ContextMetric label="Run" value={selectedRun?.id || selectedRunId || "Select in Projects"} />
          <ContextMetric label="Sample" value={selectedSample?.sample_id || selectedSampleId || "Select in Projects"} />
          <div style={{ display: "flex", background: "var(--color-bg-base)", borderRadius: 6, overflow: "hidden", border: "1px solid var(--color-border-default)" }}>
            <TabBtn active={tab === "variants"} onClick={() => setTab("variants")} label={`Variants (${variants.length})`} />
            <TabBtn active={tab === "disagreement"} onClick={() => setTab("disagreement")} label={`Caller Disagreement${disagreement?.count ? ` (${disagreement.count})` : ""}`} />
          </div>
          {selectedRun && (
            <>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                {selectedRun.id.slice(0, 12)} · {selectedRun.status}
              </span>
              <StageActionButtons
                run={selectedRun}
                stage="variants"
                steps={runSteps}
                onRefresh={() => loadRunSteps(selectedRun.id)}
                compact
              />
            </>
          )}
        </div>
      </Panel>

      {!selectedProjectId || !selectedRunId || !sampleKey ? (
        <EmptyState title="No run selected" description="Select a project and run in Projects to inspect variant calls." />
      ) : tab === "variants" ? (
        <VariantTable variants={variants} />
      ) : (
        <DisagreementView data={disagreement} level={overlayLevel} onLevelChange={setOverlayLevel} />
      )}
    </div>
  );
}

function ContextMetric({ label, value }) {
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ marginTop: 3, fontSize: 12, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}

/* ── Variants Tab ─────────────────────────────────────────────────── */

function VariantTable({ variants }) {
  const PAGE_SIZE = 100;
  const [page, setPage] = useState(0);
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState("asc");
  const [filterChrom, setFilterChrom] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterText, setFilterText] = useState("");

  // Extract unique chromosomes and types for filter dropdowns
  const chroms = useMemo(() => [...new Set(variants.map(v => v.chrom))].sort(), [variants]);
  const types = useMemo(() => [...new Set(variants.map(v => v.variant_type))].sort(), [variants]);

  // Filter
  const filtered = useMemo(() => {
    let result = variants;
    if (filterChrom) result = result.filter(v => v.chrom === filterChrom);
    if (filterType) result = result.filter(v => v.variant_type === filterType);
    if (filterText) {
      const q = filterText.toLowerCase();
      result = result.filter(v =>
        (v.chrom || "").toLowerCase().includes(q) ||
        String(v.pos).includes(q) ||
        (v.ref || "").toLowerCase().includes(q) ||
        (v.alt || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [variants, filterChrom, filterType, filterText]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortCol) return filtered;
    return [...filtered].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) va = ""; if (vb == null) vb = "";
      if (typeof va === "number" && typeof vb === "number") return sortDir === "asc" ? va - vb : vb - va;
      va = String(va); vb = String(vb);
      return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
    });
  }, [filtered, sortCol, sortDir]);

  // Paginate
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const pageData = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Reset page on filter change
  useEffect(() => { setPage(0); }, [filterChrom, filterType, filterText]);

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("asc"); }
  };

  if (variants.length === 0) {
    return <EmptyState title="No variants found" description="No SNV/indel calls are currently available for this sample." />;
  }

  const SortIcon = ({ col }) => {
    if (sortCol !== col) return <span style={{ opacity: 0.3, marginLeft: 4 }}>↕</span>;
    return <span style={{ marginLeft: 4 }}>{sortDir === "asc" ? "↑" : "↓"}</span>;
  };

  return (
    <div className="card" style={{ overflow: "hidden" }}>
      {/* Filter bar */}
      <div style={{ display: "flex", gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--color-border-muted)", flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-secondary)" }}>{filtered.length.toLocaleString()} variants</span>
        <select value={filterChrom} onChange={e => setFilterChrom(e.target.value)} style={{ ...selectStyle, minWidth: 100 }}>
          <option value="">All chroms</option>
          {chroms.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={filterType} onChange={e => setFilterType(e.target.value)} style={{ ...selectStyle, minWidth: 100 }}>
          <option value="">All types</option>
          {types.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <input
          value={filterText}
          onChange={e => setFilterText(e.target.value)}
          placeholder="Search pos, ref, alt…"
          style={{ ...inputStyle, width: 180 }}
        />
        {(filterChrom || filterType || filterText) && (
          <button onClick={() => { setFilterChrom(""); setFilterType(""); setFilterText(""); }} style={{ ...smallBtn, fontSize: 11 }}>Clear filters</button>
        )}
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ background: "var(--color-bg-elevated)" }}>
            <Th onClick={() => toggleSort("chrom")} style={{ cursor: "pointer" }}>Chrom<SortIcon col="chrom" /></Th>
            <Th onClick={() => toggleSort("pos")} style={{ cursor: "pointer" }}>Pos<SortIcon col="pos" /></Th>
            <Th>Ref</Th><Th>Alt</Th>
            <Th onClick={() => toggleSort("variant_type")} style={{ cursor: "pointer" }}>Type<SortIcon col="variant_type" /></Th>
            <Th onClick={() => toggleSort("zygosity")} style={{ cursor: "pointer" }}>Zygosity<SortIcon col="zygosity" /></Th>
            <Th onClick={() => toggleSort("genotype")} style={{ cursor: "pointer" }}>GT<SortIcon col="genotype" /></Th>
            <Th onClick={() => toggleSort("quality_score")} style={{ cursor: "pointer" }}>QUAL<SortIcon col="quality_score" /></Th>
            <Th onClick={() => toggleSort("trust_score")} style={{ cursor: "pointer" }}>Trust<SortIcon col="trust_score" /></Th>
            <Th>Label</Th><Th>Callers</Th>
          </tr>
        </thead>
        <tbody>
          {pageData.map((v) => (
            <tr key={v.id} style={{ borderBottom: "1px solid var(--color-border-muted)" }}>
              <Td mono>{v.chrom}</Td>
              <Td mono>{v.pos?.toLocaleString()}</Td>
              <Td mono>{v.ref}</Td>
              <Td mono>{v.alt}</Td>
              <Td>{v.variant_type}</Td>
              <Td>{zygosityLabel(v.zygosity)}</Td>
              <Td mono>{v.genotype || "—"}</Td>
              <Td mono>{v.quality_score ?? "—"}</Td>
              <Td><TrustBar score={v.trust_score} /></Td>
              <Td><span className={`badge ${trustBadge(v.trust_label)}`}>{v.trust_label || "—"}</span></Td>
              <Td style={{ fontSize: 11, color: "var(--color-text-muted)" }}>{v.caller_list?.join(", ") || "—"}</Td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Pagination */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 16px", borderTop: "1px solid var(--color-border-muted)", fontSize: 13 }}>
        <span style={{ color: "var(--color-text-muted)" }}>
          Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length.toLocaleString()}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setPage(0)} disabled={page === 0} style={pagBtn}>⏮</button>
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0} style={pagBtn}>←</button>
          <span style={{ padding: "4px 10px", fontSize: 12, color: "var(--color-text-secondary)" }}>{page + 1} / {totalPages}</span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} style={pagBtn}>→</button>
          <button onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1} style={pagBtn}>⏭</button>
        </div>
      </div>
    </div>
  );
}

/* ── Caller Disagreement Tab ──────────────────────────────────────── */

function DisagreementView({ data, level, onLevelChange }) {
  if (!data || !data.hotspots || data.hotspots.length === 0) {
    return (
      <EmptyState
        title="No caller disagreement hotspots"
        description="Variants where multiple callers disagree get flagged here."
      />
    );
  }

  const maxCount = Math.max(...data.hotspots.map((h) => h.variant_count), 1);

  return (
    <div>
      {/* Level selector + summary */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Resolution:</label>
          <select value={level} onChange={(e) => onLevelChange(e.target.value)} style={selectStyle}>
            <option value="500kb">500 kb</option>
            <option value="1mb">1 Mb</option>
            <option value="5mb">5 Mb</option>
          </select>
        </div>
        <div style={{ display: "flex", gap: 16, fontSize: 13 }}>
          <span><strong>{data.count}</strong> hotspot{data.count !== 1 ? "s" : ""}</span>
          <span style={{ color: "var(--color-text-muted)" }}>Sample: {data.sample_id}</span>
        </div>
      </div>

      {/* Hotspot visualization — bar chart */}
      <div className="card" style={{ padding: 20, marginBottom: 24 }}>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: 0, marginBottom: 16 }}>Disagreement Hotspot Map</h3>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 120 }}>
          {data.hotspots.map((h, i) => {
            const pct = (h.variant_count / maxCount) * 100;
            const trustColor = h.avg_trust_score >= 70 ? "var(--color-ok)" : h.avg_trust_score >= 40 ? "var(--color-warn)" : "var(--color-err)";
            return (
              <div key={h.hotspot_id} title={`${h.chrom}:${h.start?.toLocaleString()}–${h.end?.toLocaleString()}\n${h.variant_count} variants\nTrust: ${h.avg_trust_score}\nAgreement: ${h.avg_caller_agreement_score}`} style={{
                flex: 1, minWidth: 4, maxWidth: 24, height: `${Math.max(4, pct)}%`,
                background: trustColor, borderRadius: "2px 2px 0 0", cursor: "pointer",
                transition: "opacity 0.15s", opacity: 0.85,
              }} onMouseOver={(e) => e.target.style.opacity = "1"} onMouseOut={(e) => e.target.style.opacity = "0.85"} />
            );
          })}
        </div>
        <div style={{ marginTop: 8, display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
          <span>{data.hotspots[0]?.chrom}:{data.hotspots[0]?.start?.toLocaleString()}</span>
          <span>{data.hotspots[data.hotspots.length - 1]?.chrom}:{data.hotspots[data.hotspots.length - 1]?.end?.toLocaleString()}</span>
        </div>
      </div>

      {/* Hotspot detail table */}
      <div className="card" style={{ overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--color-bg-elevated)" }}>
              <Th>Region</Th><Th>Start</Th><Th>End</Th><Th>Variants</Th>
              <Th>Avg Trust</Th><Th>Avg Agreement</Th>
            </tr>
          </thead>
          <tbody>
            {data.hotspots.map((h) => (
              <tr key={h.hotspot_id} style={{ borderBottom: "1px solid var(--color-border-muted)" }}>
                <Td mono>{h.chrom}</Td>
                <Td mono>{h.start?.toLocaleString()}</Td>
                <Td mono>{h.end?.toLocaleString()}</Td>
                <Td mono style={{ fontWeight: 600, color: "var(--color-err)" }}>{h.variant_count}</Td>
                <Td><TrustBar score={h.avg_trust_score} /></Td>
                <Td mono>{h.avg_caller_agreement_score?.toFixed(3)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Methodology note */}
      <div style={{ marginTop: 16, padding: 12, background: "var(--color-bg-base)", borderRadius: 6, borderLeft: "3px solid var(--color-accent)", fontSize: 12, color: "var(--color-text-secondary)" }}>
        <strong>Methodology:</strong> Genomic regions are binned at {level} resolution. Hotspots contain variants where caller agreement score &lt; 1.0, indicating disagreement between callers (e.g. HaplotypeCaller vs DeepVariant vs bcftools). Higher variant counts in a bin suggest complex regions requiring manual review.
      </div>
    </div>
  );
}

/* ── Shared components ────────────────────────────────────────────── */

function TabBtn({ active, onClick, label }) {
  return (
    <button onClick={onClick} style={{
      padding: "6px 16px", background: active ? "var(--color-accent-bg)" : "transparent",
      border: "none", color: active ? "var(--color-accent)" : "var(--color-text-secondary)",
      fontSize: 13, fontWeight: active ? 600 : 400, cursor: "pointer",
    }}>{label}</button>
  );
}

function Th({ children, onClick, style: extraStyle }) {
  return <th onClick={onClick} style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid var(--color-border-default)", userSelect: "none", ...extraStyle }}>{children}</th>;
}

function Td({ children, mono, style: extraStyle }) {
  return <td style={{ padding: "8px 12px", fontFamily: mono ? "var(--font-mono)" : undefined, fontSize: mono ? 12 : undefined, ...extraStyle }}>{children}</td>;
}

function TrustBar({ score }) {
  if (score == null) return <span style={{ color: "var(--color-text-muted)" }}>—</span>;
  const pct = Math.min(100, Math.max(0, score));
  const color = pct >= 70 ? "var(--color-ok)" : pct >= 40 ? "var(--color-warn)" : "var(--color-err)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 40, height: 4, background: "var(--color-bg-base)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color }}>{score}</span>
    </div>
  );
}

function trustBadge(label) {
  switch (label) {
    case "high": return "badge-ok";
    case "medium": return "badge-warn";
    case "low": return "badge-err";
    default: return "badge-info";
  }
}

function zygosityLabel(value) {
  switch (value) {
    case "heterozygous": return "heterozygous";
    case "homozygous_alt": return "homozygous alt";
    case "heterozygous_alt": return "heterozygous alt";
    case "hemizygous_alt": return "hemizygous alt";
    case "homozygous_ref": return "homozygous ref";
    case "hemizygous_ref": return "hemizygous ref";
    case "no_call": return "no call";
    default: return "—";
  }
}

const selectStyle = {
  padding: "6px 12px", background: "var(--color-bg-base)",
  border: "1px solid var(--color-border-default)", borderRadius: 6,
  color: "var(--color-text-primary)", fontSize: 13, minWidth: 200,
};

const inputStyle = {
  padding: "6px 12px", background: "var(--color-bg-base)",
  border: "1px solid var(--color-border-default)", borderRadius: 6,
  color: "var(--color-text-primary)", fontSize: 13,
};

const smallBtn = {
  padding: "4px 10px", background: "var(--color-bg-elevated)",
  border: "1px solid var(--color-border-default)", borderRadius: 5,
  color: "var(--color-text-secondary)", cursor: "pointer",
};

const pagBtn = {
  padding: "4px 10px", background: "var(--color-bg-elevated)",
  border: "1px solid var(--color-border-default)", borderRadius: 4,
  color: "var(--color-text-primary)", cursor: "pointer", fontSize: 12,
};
