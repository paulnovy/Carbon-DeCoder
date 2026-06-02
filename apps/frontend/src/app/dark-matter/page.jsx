"use client";

import { useEffect, useState } from "react";
import { API_BASE, fetchJson } from "@/lib/api";

const selectStyle = {
  background: "var(--color-bg-elevated)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: 6,
  padding: "6px 10px",
  fontSize: 13,
};

export default function DarkMatterPage() {
  const [samples, setSamples] = useState([]);
  const [sampleId, setSampleId] = useState("");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { init(); }, []);
  useEffect(() => { if (sampleId) loadReport(sampleId); }, [sampleId]);

  async function init() {
    const projects = await fetchJson(`${API_BASE}/projects`, { items: [] });
    const all = [];
    for (const prj of projects.items || []) {
      const data = await fetchJson(`${API_BASE}/projects/${prj.id}/samples`, { items: [] });
      for (const sample of data.items || []) all.push({ ...sample, project_name: prj.name });
    }
    setSamples(all);
    if (all.length) setSampleId(all[0].sample_id || all[0].id);
    else setLoading(false);
  }

  async function loadReport(id) {
    setLoading(true);
    setReport(await fetchJson(`${API_BASE}/samples/${id}/dark-matter/report`, null));
    setLoading(false);
  }

  const metrics = report?.metrics || {};
  const collection = report?.unknown_read_collection || {};
  const hostDepletion = collection.host_depletion || {};
  const taxonomyDepletion = collection.taxonomy_depletion || {};
  const assembly = collection.assembly || {};
  const contigSearch = collection.contig_search || {};
  const kmerProfile = collection.kmer_profile || {};
  const kmerClusters = collection.kmer_clusters || [];
  const collectionFiles = collection.files || {};
  const statusTone = report?.status === "unclassified_reads_observed" ? "warn" : report?.status === "no_unclassified_signal" ? "ok" : undefined;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, marginBottom: 8 }}>Dark Matter</h1>
          <p style={{ margin: 0, color: "var(--color-text-secondary)", fontSize: 14, maxWidth: 900, lineHeight: 1.55 }}>
            Conservative report for reads not confidently explained by the current host alignment and taxonomy database. This page reports evidence limits, not discoveries.
          </p>
        </div>
        <div className="card" style={{ padding: 12, minWidth: 280 }}>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 6 }}>Sample</div>
          <select value={sampleId} onChange={(e) => setSampleId(e.target.value)} style={{ ...selectStyle, width: "100%" }}>
            {samples.map((s) => <option key={s.id} value={s.sample_id || s.id}>{s.sample_id || s.id} ({s.project_name})</option>)}
            {samples.length === 0 && <option value="">No samples</option>}
          </select>
        </div>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 16, borderLeft: "3px solid var(--color-warn)" }}>
        <b>Guardrail</b>
        <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
          Unclassified reads can reflect database gaps, low complexity, contamination, host-reference mismatch, alignment thresholds, or pipeline artifacts. They are not a biological claim without independent review.
        </p>
      </div>

      {loading && <div className="card" style={{ padding: 18, color: "var(--color-text-muted)" }}>Loading dark matter report...</div>}

      {!loading && report && (
        <>
          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
              <div>
                <h2 style={{ margin: "0 0 6px", fontSize: 17 }}>Evidence summary</h2>
                <p style={{ margin: 0, color: "var(--color-text-muted)", fontSize: 12 }}>Run {report.run_id || "-"} · reference {report.reference_id || "-"}</p>
              </div>
              <span className={`badge ${statusTone === "warn" ? "badge-warn" : statusTone === "ok" ? "badge-ok" : "badge-info"}`}>{report.status}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
              <Metric label="Alignment unmapped" value={formatNumber(metrics.alignment_unmapped_reads)} tone={(metrics.alignment_unmapped_reads || 0) > 0 ? "warn" : undefined} />
              <Metric label="Mapped reads" value={metrics.mapped_reads_pct == null ? "-" : `${Number(metrics.mapped_reads_pct).toFixed(2)}%`} />
              <Metric label="Taxonomy total" value={formatNumber(metrics.taxonomy_total_reads)} />
              <Metric label="Taxonomy unclassified" value={formatNumber(metrics.taxonomy_unclassified_reads)} tone={(metrics.taxonomy_unclassified_reads || 0) > 0 ? "warn" : undefined} />
              <Metric label="Unclassified fraction" value={metrics.taxonomy_unclassified_fraction == null ? "-" : `${(metrics.taxonomy_unclassified_fraction * 100).toFixed(3)}%`} />
              <Metric label="Unclassified hit rows" value={metrics.unclassified_hit_count ?? 0} />
              <Metric label="Unknown collection" value={metrics.unknown_read_collection_status || "-"} tone={metrics.unknown_read_collection_status === "not_collected" ? undefined : "warn"} />
              <Metric label="Collected unmapped" value={formatNumber(metrics.unknown_host_unmapped_reads)} tone={(metrics.unknown_host_unmapped_reads || 0) > 0 ? "warn" : undefined} />
              <Metric label="Assembled contigs" value={formatNumber(metrics.unknown_assembled_contigs)} />
              <Metric label="No-hit contigs" value={formatNumber(metrics.unknown_no_hit_contigs)} tone={(metrics.unknown_no_hit_contigs || 0) > 0 ? "warn" : undefined} />
              <Metric label="Distinct k-mers" value={formatNumber(metrics.unknown_distinct_kmers)} />
              <Metric label="K-mer clusters" value={formatNumber(metrics.unknown_kmer_cluster_count)} />
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
            <ListCard title="Evidence limits" items={report.evidence_limits || []} />
            <ListCard title="Guardrails" items={report.guardrails || []} warn />
          </div>

          <div className="card" style={{ padding: 16, marginTop: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <h2 style={{ margin: "0 0 6px", fontSize: 17 }}>Unknown-read collection</h2>
                <p style={{ margin: 0, color: "var(--color-text-muted)", fontSize: 12 }}>
                  {collection.collection_mode || "not collected"} · event {collection.event_id || "-"}
                </p>
              </div>
              <span className={`badge ${collection.status === "not_collected" ? "badge-info" : "badge-warn"}`}>{collection.status || "not_collected"}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 12 }}>
              <Metric label="Host total reads" value={formatNumber(hostDepletion.total_reads)} />
              <Metric label="Host unmapped reads" value={formatNumber(hostDepletion.unmapped_reads)} tone={(hostDepletion.unmapped_reads || 0) > 0 ? "warn" : undefined} />
              <Metric label="Taxonomy classified" value={formatNumber(taxonomyDepletion.classified)} />
              <Metric label="Taxonomy unclassified" value={formatNumber(taxonomyDepletion.unclassified)} tone={(taxonomyDepletion.unclassified || 0) > 0 ? "warn" : undefined} />
              <Metric label="Assembly tool" value={assembly.tool || "-"} />
              <Metric label="Assembly bp" value={formatNumber(assembly.total_bp)} />
              <Metric label="N50" value={formatNumber(assembly.n50)} />
              <Metric label="Search tool" value={contigSearch.tool || "-"} />
              <Metric label="K-mer status" value={kmerProfile.status || "-"} />
              <Metric label="Reads scanned" value={formatNumber(kmerProfile.reads_scanned)} />
            </div>
            {kmerClusters.length > 0 && (
              <div style={{ display: "grid", gap: 6, marginBottom: 12, fontSize: 12 }}>
                {kmerClusters.slice(0, 8).map((cluster) => (
                  <div key={cluster.cluster_id || cluster.prefix} style={{ display: "grid", gridTemplateColumns: "minmax(90px, 130px) repeat(2, minmax(80px, 1fr))", gap: 10, borderTop: "1px solid var(--color-border-muted)", paddingTop: 6 }}>
                    <b>{cluster.prefix || cluster.cluster_id}</b>
                    <span>{formatNumber(cluster.total_count)} counts</span>
                    <span>{formatNumber(cluster.distinct_kmers)} k-mers</span>
                  </div>
                ))}
              </div>
            )}
            {Object.keys(collectionFiles).length === 0 ? (
              <p style={{ margin: 0, color: "var(--color-text-muted)", fontSize: 13 }}>No collection artifacts are registered for this run.</p>
            ) : (
              <div style={{ display: "grid", gap: 6, fontSize: 12 }}>
                {Object.entries(collectionFiles).map(([key, value]) => (
                  <div key={key} style={{ display: "grid", gridTemplateColumns: "160px minmax(0, 1fr)", gap: 10, borderTop: "1px solid var(--color-border-muted)", paddingTop: 6 }}>
                    <span style={{ color: "var(--color-text-muted)" }}>{formatStageKey(key)}</span>
                    <code style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{String(value)}</code>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card" style={{ padding: 16, marginTop: 16 }}>
            <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>Top unclassified rows</h2>
            {(report.top_unclassified || []).length === 0 ? (
              <p style={{ margin: 0, color: "var(--color-text-muted)", fontSize: 13 }}>No unclassified taxonomy rows are available for the selected sample.</p>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                {report.top_unclassified.map((item, idx) => (
                  <div key={`${item.organism}-${idx}`} style={{ display: "grid", gridTemplateColumns: "minmax(180px, 1fr) 120px 120px 120px", gap: 10, borderTop: "1px solid var(--color-border-muted)", paddingTop: 8, fontSize: 12, overflowX: "auto" }}>
                    <b>{item.organism || "unclassified"}</b>
                    <span>{formatNumber(item.read_count)} reads</span>
                    <span>confidence {formatDecimal(item.confidence)}</span>
                    <span>evidence {formatDecimal(item.evidence_score)}</span>
                    {item.warning && <span style={{ gridColumn: "1 / -1", color: "var(--color-warn)" }}>{item.warning}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, tone }) {
  const color = tone === "warn" ? "var(--color-warn)" : tone === "ok" ? "var(--color-ok)" : "var(--color-text-primary)";
  return (
    <div style={{ background: "var(--color-bg-elevated)", borderRadius: 8, padding: "10px 12px" }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>{label}</div>
      <b style={{ color, fontSize: 13 }}>{String(value ?? "-")}</b>
    </div>
  );
}

function ListCard({ title, items, warn = false }) {
  return (
    <div className="card" style={{ padding: 16, borderTop: `3px solid ${warn ? "var(--color-warn)" : "var(--color-accent)"}` }}>
      <h2 style={{ margin: "0 0 10px", fontSize: 17 }}>{title}</h2>
      <ul style={{ margin: 0, paddingLeft: 18, color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.6 }}>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function formatNumber(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toLocaleString();
}

function formatDecimal(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(3);
}

function formatStageKey(value) {
  return String(value || "").replace(/_/g, " ");
}
