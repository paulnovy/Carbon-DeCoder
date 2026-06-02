"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { Button, EmptyState, PageHeader, Panel } from "@/components/ui";


export default function BenchmarkPage() {
  const [samples, setSamples] = useState([]);
  const [giabInfo, setGiabInfo] = useState(null);
  const [selectedSample, setSelectedSample] = useState(null);
  const [stratTrust, setStratTrust] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { loadSamples(); loadGiabInfo(); }, []);
  useEffect(() => { if (selectedSample) loadSampleData(selectedSample); }, [selectedSample]);

  const loadSamples = async () => {
    try {
      const projsRes = await fetch(`${API_BASE}/projects`);
      const projsData = await projsRes.json();
      const allSamples = [];
      for (const p of projsData.items || []) {
        try {
          const sRes = await fetch(`${API_BASE}/projects/${p.id}/samples`);
          const sData = await sRes.json();
          for (const s of sData.items || sData || []) {
            allSamples.push({ ...s, project_name: p.name });
          }
        } catch {}
      }
      setSamples(allSamples);
      if (allSamples.length > 0) setSelectedSample(allSamples[0].sample_id || allSamples[0].id);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const loadGiabInfo = async () => {
    try {
      const res = await fetch(`${API_BASE}/giab/info`);
      if (res.ok) setGiabInfo(await res.json());
    } catch {}
  };

  const loadSampleData = async (sid) => {
    try {
      const res = await fetch(`${API_BASE}/samples/${sid}/stratified-trust`);
      if (res.ok) setStratTrust(await res.json());
      else setStratTrust(null);
    } catch { setStratTrust(null); }
  };

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading benchmark data…</div>;

  const benchmark = stratTrust?.benchmark;
  const stratified = stratTrust?.giab_stratified || {};
  const trustDist = stratTrust?.trust_distribution || {};

  return (
    <div>
      <PageHeader
        eyebrow="Validation"
        title="GIAB Benchmark"
        description="Precision, recall, and F1 against GIAB truth sets with stratified region metrics."
      />

      {/* Sample selector */}
      <Panel title="Benchmark context" description="Select the sample whose imported benchmark/trust metrics should be reviewed.">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Sample:</label>
          <select value={selectedSample || ""} onChange={(e) => setSelectedSample(e.target.value)} className="form-control" style={{ maxWidth: 340 }}>
            {samples.map((s) => (
              <option key={s.id} value={s.sample_id || s.id}>{s.sample_id} ({s.project_name})</option>
            ))}
            {samples.length === 0 && <option value="">No samples available</option>}
          </select>
          {benchmark && <span className="badge badge-ok">F1: {(benchmark.f1 * 100).toFixed(2)}%</span>}
        </div>
      </Panel>

      {benchmark ? (
        <>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 24 }}>
            <MetricCard label="Precision" value={(benchmark.precision * 100).toFixed(2) + "%"} />
            <MetricCard label="Recall" value={(benchmark.recall * 100).toFixed(2) + "%"} />
            <MetricCard label="F1 Score" value={(benchmark.f1 * 100).toFixed(2) + "%"} color="accent" />
            <MetricCard label="Benchmark ID" value={benchmark.benchmark_id} small />
          </div>

          {/* Regression alert */}
          {benchmark.regression_alert && (
            <Panel style={{ borderLeft: "3px solid var(--color-err)" }}>
              <div style={{ fontSize: 13, color: "var(--color-err)", fontWeight: 600 }}>⚠ {benchmark.regression_alert}</div>
            </Panel>
          )}

          {/* Stratified metrics */}
          {Object.keys(stratified).length > 0 && (
            <Panel title="GIAB Stratified Regions">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
                {Object.entries(stratified).sort((a, b) => b[1].f1 - a[1].f1).map(([region, data]) => (
                  <div key={region} style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 14px", background: "var(--color-bg-base)", borderRadius: 6,
                    borderLeft: `3px solid var(--color-${data.rating === "pass" ? "ok" : data.rating === "warn" ? "warn" : "err"})`,
                  }}>
                    <span style={{ fontSize: 13 }}>{formatRegionName(region)}</span>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600 }}>{(data.f1 * 100).toFixed(2)}%</span>
                      <span className={`badge badge-${data.rating === "pass" ? "ok" : data.rating === "warn" ? "warn" : "err"}`}>{data.rating}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {/* Variant trust distribution */}
          {Object.keys(trustDist).length > 0 && (
            <Panel title="Variant Trust Distribution">
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
                {Object.entries(trustDist).map(([label, count]) => (
                  <div key={label} style={{ textAlign: "center" }}>
                    <div style={{
                      fontSize: 24, fontWeight: 700, fontFamily: "var(--font-mono)",
                      color: `var(--color-${label === "high" ? "ok" : label === "medium" ? "warn" : label === "low" ? "err" : "text-muted"})`,
                    }}>{count}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-secondary)", textTransform: "capitalize" }}>{label}</div>
                  </div>
                ))}
              </div>
            </Panel>
          )}
        </>
      ) : (
        <EmptyState title="No benchmark data" description="Run hap.py or Truvari against GIAB truth sets and import results for this sample." />
      )}

      {/* GIAB resources */}
      {giabInfo && (
        <Panel title="GIAB Resources" description="Download truth sets directly into the pipeline input folder for benchmarking.">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
            {Object.entries(giabInfo.download_urls || {}).map(([key, url]) => (
              <GiabDownloadItem key={key} itemKey={key} url={url} />
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}

function MetricCard({ label, value, color, small }) {
  return (
    <Panel>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{
        fontSize: small ? 14 : 20, fontFamily: small ? undefined : "var(--font-mono)",
        color: color ? `var(--color-${color})` : undefined,
      }}>{value}</div>
    </Panel>
  );
}

function formatRegionName(region) {
  return region.replace(/_f1$/, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatUrlLabel(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function truncate(s) { return s.length > 60 ? s.slice(0, 57) + "..." : s; }

function GiabDownloadItem({ itemKey, url }) {
  const [status, setStatus] = useState("idle"); // idle | downloading | done | error
  const [progress, setProgress] = useState(null);

  const isLink = url.startsWith("https://github.com") || url.endsWith("/");

  const startDownload = async () => {
    setStatus("downloading");
    try {
      const res = await fetch(`${API_BASE}/data/import-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error("Failed");
      const data = await res.json();
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`${API_BASE}/data/import-url/${data.job_id}`);
          const d = await r.json();
          setProgress(d);
          if (d.status === "done") { clearInterval(poll); setStatus("done"); }
          if (d.status === "failed") { clearInterval(poll); setStatus("error"); }
        } catch { clearInterval(poll); setStatus("error"); }
      }, 2000);
    } catch (e) {
      setStatus("error");
    }
  };

  const dlPct = progress?.total_bytes ? Math.min(100, Math.round((progress.downloaded_bytes / progress.total_bytes) * 100)) : 0;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 8,
      padding: "12px 14px", background: "var(--color-bg-base)",
      border: "1px solid var(--color-border-default)", borderRadius: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 12 }}>{formatUrlLabel(itemKey)}</div>
          <div style={{ fontSize: 10, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", wordBreak: "break-all" }}>{url}</div>
        </div>
        {isLink ? (
          <a href={url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost btn-sm">Open</a>
        ) : status === "idle" ? (
          <Button onClick={startDownload} variant="primary" size="sm">Download</Button>
        ) : status === "downloading" ? (
          <span style={{ fontSize: 11, color: "var(--color-accent)", fontFamily: "var(--font-mono)" }}>{dlPct}%</span>
        ) : status === "done" ? (
          <span style={{ fontSize: 12, color: "var(--color-ok)" }}>✓ Ready</span>
        ) : (
          <span style={{ fontSize: 12, color: "var(--color-err)" }}>✗ Failed</span>
        )}
      </div>
      {status === "downloading" && progress && (
        <div style={{ height: 4, background: "var(--color-bg-elevated)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ width: `${dlPct}%`, height: "100%", background: "var(--color-accent)", transition: "width 0.3s" }} />
        </div>
      )}
    </div>
  );
}
