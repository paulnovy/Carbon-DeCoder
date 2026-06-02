"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { EmptyState, PageHeader, Panel } from "@/components/ui";


export default function CoveragePage() {
  const { selectedProjectId, selectedRunId, selectedSampleId } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runSteps, setRunSteps] = useState([]);
  const [coverage, setCoverage] = useState(null);
  const [tiles, setTiles] = useState(null);
  const [tileLevel, setTileLevel] = useState("1mb");
  const [loading, setLoading] = useState(true);

  const selectedRun = runs.find((run) => run.id === selectedRunId) || null;
  const selectedSample = samples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId) || null;
  const sampleKey = selectedSample?.sample_id || selectedSample?.id || selectedSampleId;

  useEffect(() => { loadContext(); }, [selectedProjectId]);
  useEffect(() => {
    if (sampleKey && selectedRunId) {
      loadCoverage(sampleKey, selectedRunId);
      loadTiles(sampleKey, selectedRunId, tileLevel);
    } else {
      setCoverage(null);
      setTiles(null);
    }
  }, [sampleKey, selectedRunId]);
  useEffect(() => {
    if (!selectedRunId) {
      setRunSteps([]);
      return;
    }
    loadRunSteps(selectedRunId);
  }, [selectedRunId]);
  useEffect(() => {
    if (sampleKey && selectedRunId) loadTiles(sampleKey, selectedRunId, tileLevel);
  }, [tileLevel]);

  const loadContext = async () => {
    if (!selectedProjectId) {
      setProject(null);
      setSamples([]);
      setRuns([]);
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
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const loadRunSteps = async (runId = selectedRun?.id) => {
    if (!runId) return;
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/steps`);
      const data = res.ok ? await res.json() : { items: [] };
      setRunSteps(data.items || data || []);
    } catch {
      setRunSteps([]);
    }
  };

  const loadCoverage = async (sid, runId) => {
    try {
      const res = await fetch(`${API_BASE}/samples/${sid}/coverage-summary?run_id=${encodeURIComponent(runId)}`);
      if (res.ok) setCoverage(await res.json());
    } catch {}
  };

  const loadTiles = async (sid, runId, level) => {
    try {
      const params = new URLSearchParams({ level, run_id: runId });
      const res = await fetch(`${API_BASE}/samples/${sid}/coverage-tiles?${params}`);
      if (res.ok) setTiles(await res.json());
      else setTiles(null);
    } catch { setTiles(null); }
  };

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading coverage…</div>;

  return (
    <div>
      <PageHeader
        eyebrow="Sample evidence"
        title="Coverage"
        description="Depth of coverage analysis from mosdepth with terrain visualization."
      />

      <Panel title="Coverage Context">
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <ContextMetric label="Run" value={selectedRun?.id || selectedRunId || "Select in Projects"} />
          <ContextMetric label="Sample" value={selectedSample?.sample_id || selectedSampleId || "Select in Projects"} />
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Resolution:</label>
            <select value={tileLevel} onChange={(e) => setTileLevel(e.target.value)} className="form-control" style={{ minWidth: 130 }}>
              <option value="500kb">500 kb</option>
              <option value="1mb">1 Mb</option>
              <option value="5mb">5 Mb</option>
            </select>
          </div>
          {selectedRun && (
            <>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                {selectedRun.id.slice(0, 12)} · {selectedRun.status}
              </span>
              <StageActionButtons
                run={selectedRun}
                stage="coverage"
                steps={runSteps}
                onRefresh={() => loadRunSteps(selectedRun.id)}
                compact
              />
            </>
          )}
        </div>
      </Panel>

      {!selectedProjectId || !selectedRunId || !sampleKey ? (
        <EmptyState title="No run selected" description="Select a project and run in Projects to inspect coverage." />
      ) : (
        <>
      {/* Summary stats */}
      {coverage && <CoverageStats data={coverage} tiles={tiles} />}

      {/* Terrain heatmap */}
      {tiles && tiles.tiles?.length > 0 ? (
        <TerrainHeatmap tiles={tiles} level={tileLevel} />
      ) : (
        <CoverageTileEmptyState tiles={tiles} />
      )}
        </>
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

/* ── Summary Stats ────────────────────────────────────────────────── */

function CoverageStats({ data, tiles }) {
  const d = data.mosdepth || data;
  const tileList = tiles?.tiles || [];
  const sexModel = inferSexChromosomeModel(tileList, coverageBaseline(tileList, tiles?.mean_coverage ?? tiles?.median_coverage));
  const unexpectedNoCoverage = tileList.filter((t) => !isCoverageExpectedLow(t, sexModel) && !isCoverageExplained(t) && numericCoverage(t.coverage) <= 0.05).length;
  const unexpectedLowCoverage = tileList.filter((t) => !isCoverageExpectedLow(t, sexModel) && !isCoverageExplained(t) && t.anomaly === "low" && numericCoverage(t.coverage) > 0.05).length;
  const fmt = (v, suffix = "", mult = 1) => {
    if (v == null) return "—";
    const n = Number(v);
    if (isNaN(n)) return "—";
    return (n * mult).toFixed(1) + suffix;
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 16, marginBottom: 24 }}>
      <StatCard label="Mean Coverage" value={fmt(d.mean_coverage, "x")} color="accent" />
      <StatCard label="Unexpected low coverage" value={unexpectedLowCoverage} color={unexpectedLowCoverage ? "warn" : "ok"} />
      <StatCard label="Unexpected no coverage" value={unexpectedNoCoverage} color={unexpectedNoCoverage ? "err" : "ok"} />
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ fontSize: 20, color: color ? `var(--color-${color})` : undefined, fontFamily: "var(--font-mono)" }}>{value || "—"}</div>
    </div>
  );
}

function CoverageTileEmptyState({ tiles }) {
  const summaryOnly = tiles?.status === "imported" && tiles?.mode === "summary_only";
  const otherContigs = tiles?.other_contigs || [];
  return (
    <Panel className="empty-state">
      <div style={{ color: "var(--color-text-secondary)", fontSize: 14, marginBottom: otherContigs.length ? 18 : 0 }}>
        {summaryOnly
          ? "Coverage summary is imported, but mosdepth region tiles are missing. No terrain bars are synthesized from summary-only data."
          : "No coverage tiles for this sample."}
      </div>
      {otherContigs.length > 0 && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Other Contigs</h3>
            <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>sorted by mapped reads</span>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {otherContigs.slice(0, 40).map((row) => (
              <div key={row.contig} style={{ display: "grid", gridTemplateColumns: "minmax(160px, 1fr) 120px", gap: 12, alignItems: "center", fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--color-border-muted)" }}>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.contig}>{row.contig}</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-primary)", textAlign: "right" }}>{Number(row.reads || 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

/* ── Terrain Heatmap ──────────────────────────────────────────────── */

function numericCoverage(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function normalizedContig(contig) {
  return String(contig || "").replace(/^chr/i, "").replace(/^MT$/i, "M");
}

function isPrimaryCoverageContig(contig) {
  const key = normalizedContig(contig);
  return /^(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)$/.test(key);
}

const CHROMOSOME_LENGTHS = {
  "1": 248956422, "2": 242193529, "3": 198295559, "4": 190214555, "5": 181538259,
  "6": 170805979, "7": 159345973, "8": 145138636, "9": 138394717, "10": 133797422,
  "11": 135086622, "12": 133275309, "13": 114364328, "14": 107043718, "15": 101991189,
  "16": 90338345, "17": 83257441, "18": 80373285, "19": 58617616, "20": 64444167,
  "21": 46709983, "22": 50818468, X: 156040895, Y: 57227415, M: 16569,
};

const CENTROMERES = {
  "1": [121700000, 125100000], "2": [91800000, 96000000], "3": [87800000, 94000000],
  "4": [48200000, 51800000], "5": [46100000, 51400000], "6": [58500000, 62600000],
  "7": [58100000, 62100000], "8": [43200000, 47200000], "9": [42200000, 45500000],
  "10": [38000000, 41600000], "11": [51000000, 55800000], "12": [33200000, 37800000],
  "13": [16500000, 18900000], "14": [16100000, 18200000], "15": [17500000, 20500000],
  "16": [35300000, 38400000], "17": [22700000, 27400000], "18": [15400000, 21500000],
  "19": [24200000, 28100000], "20": [25700000, 30400000], "21": [10900000, 13000000],
  "22": [13700000, 17400000], X: [58100000, 63800000], Y: [10300000, 10600000],
};

function chromosomeLength(contig) {
  return CHROMOSOME_LENGTHS[normalizedContig(contig)] || 1;
}

function overlapsCentromere(tile) {
  const range = CENTROMERES[normalizedContig(tile.contig)];
  if (!range) return false;
  const start = Number(tile.start || 0);
  const end = Number(tile.end || start);
  return start <= range[1] && end >= range[0];
}

function isCoverageExplained(tile) {
  return Boolean(tile.reference_masked || tile.coverage_track_explained);
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function coverageBaseline(tileList, payloadMean) {
  const primary = tileList
    .filter((t) => isPrimaryCoverageContig(t.contig))
    .map((t) => numericCoverage(t.coverage))
    .filter((v) => v > 0);
  const nonZero = tileList.map((t) => numericCoverage(t.coverage)).filter((v) => v > 0);
  const robustMedian = median(primary.length >= 5 ? primary : nonZero);
  const fromPayload = numericCoverage(payloadMean);
  return fromPayload || robustMedian || 30;
}

function medianCoverageFor(tileList, keys) {
  const values = tileList
    .filter((tile) => keys.includes(normalizedContig(tile.contig)))
    .map((tile) => numericCoverage(tile.coverage))
    .filter((value) => value > 0);
  return median(values);
}

function inferSexChromosomeModel(tileList, autosomeBaseline) {
  const xMedian = medianCoverageFor(tileList, ["X"]);
  const yMedian = medianCoverageFor(tileList, ["Y"]) || 0;
  const base = autosomeBaseline || coverageBaseline(tileList, null);
  if (!base) return { karyotype: "unknown", autosomeBaseline: base };
  if (xMedian && xMedian < base * 0.75 && yMedian > base * 0.15) return { karyotype: "XY", autosomeBaseline: base };
  if (xMedian && xMedian >= base * 0.75 && yMedian < base * 0.10) return { karyotype: "XX", autosomeBaseline: base };
  return { karyotype: "unknown", autosomeBaseline: base };
}

function expectedBaselineForTile(tile, sexModel, fallbackBaseline) {
  const key = normalizedContig(tile.contig);
  if (sexModel?.karyotype === "XY" && (key === "X" || key === "Y")) return (sexModel.autosomeBaseline || fallbackBaseline) * 0.5;
  if (sexModel?.karyotype === "XX" && key === "Y") return 0;
  return fallbackBaseline;
}

function isCoverageExpectedLow(tile, sexModel) {
  const key = normalizedContig(tile.contig);
  return sexModel?.karyotype === "XX" && key === "Y";
}

function mixHex(a, b, t) {
  const clamp = Math.max(0, Math.min(1, t));
  const pa = a.replace("#", "").match(/.{1,2}/g)?.map((x) => parseInt(x, 16)) || [0, 0, 0];
  const pb = b.replace("#", "").match(/.{1,2}/g)?.map((x) => parseInt(x, 16)) || [0, 0, 0];
  const out = pa.map((v, i) => Math.round(v + (pb[i] - v) * clamp).toString(16).padStart(2, "0"));
  return `#${out.join("")}`;
}

function coverageTone(depth, baseline, tile = {}, sexModel = null) {
  const cov = numericCoverage(depth);
  const expectedBaseline = expectedBaselineForTile(tile, sexModel, baseline);
  if (isCoverageExpectedLow(tile, sexModel) && cov <= 0.05) return { color: "#25313a", label: "expected Y absence for inferred XX", opacity: 0.82 };
  const explained = Boolean(tile.reference_masked || tile.coverage_track_explained);
  if (explained && cov <= 0.05) return { color: "#25313a", label: "reference track / expected low", opacity: 0.86 };
  if (cov <= 0.05) return { color: "#1e2832", label: "unexpected 0x / no coverage", opacity: 0.74 };
  const highCopy = Math.max(90, expectedBaseline * 3);
  if (cov >= highCopy) return { color: "#064e3b", label: "high-copy outlier", opacity: 0.96 };
  if (cov > expectedBaseline) return { color: "#047857", label: "above expected baseline", opacity: 0.94 };
  if (cov >= expectedBaseline * 0.90) return { color: "#16a34a", label: "near expected baseline", opacity: 0.9 };
  if (cov >= expectedBaseline * 0.65) return { color: mixHex("#22d3ee", "#22c55e", cov / Math.max(1, expectedBaseline)), label: "moderately below expected", opacity: 0.9 };
  if (cov >= expectedBaseline * 0.35) return { color: "#facc15", label: "low vs expected", opacity: 0.88 };
  return { color: "#ef4444", label: "very low vs expected", opacity: 0.9 };
}

function tileBackground(tone, tile) {
  if (!(tile.reference_masked || tile.coverage_track_explained)) return tone.color;
  return `repeating-linear-gradient(135deg, rgba(255,255,255,0.26) 0 2px, rgba(255,255,255,0) 2px 5px), ${tone.color}`;
}

function referenceTrackTitle(tile) {
  const tracks = tile.coverage_interpretation_tracks || {};
  const trackLabels = Object.values(tracks)
    .map((item) => {
      const fraction = Math.round(numericCoverage(item.fraction) * 100);
      return `${item.label || item.kind}${fraction ? ` (${fraction}% of bin)` : ""}`;
    })
    .join("; ");
  if (!tile.reference_masked && !trackLabels) return "";
  const fraction = Math.round(numericCoverage(tile.reference_mask_fraction) * 100);
  const mask = tile.reference_masked
    ? `Reference mask: ${tile.reference_mask_label || tile.reference_mask_kind || "difficult region"}${fraction ? ` (${fraction}% of bin)` : ""}`
    : "";
  const track = trackLabels ? `Reference tracks: ${trackLabels}` : "";
  return `\n${[mask, track].filter(Boolean).join("\n")}`;
}

function TerrainHeatmap({ tiles, level }) {
  const tileList = tiles.tiles || [];
  const primaryTiles = tileList.filter((t) => isPrimaryCoverageContig(t.contig));
  const otherContigs = tiles.other_contigs || [];
  const mean = tiles.mean_coverage ?? tiles.median_coverage ?? null;
  const baseline = coverageBaseline(tileList, mean);
  const sexModel = inferSexChromosomeModel(primaryTiles, baseline);

  // Group by contig
  const byContig = {};
  for (const t of primaryTiles) {
    if (!byContig[t.contig]) byContig[t.contig] = [];
    byContig[t.contig].push(t);
  }

  const contigs = Object.keys(byContig).sort((a, b) => {
    const keyA = normalizedContig(a);
    const keyB = normalizedContig(b);
    const rank = (key) => {
      if (/^\d+$/.test(key)) return Number(key);
      if (key === "X") return 23;
      if (key === "Y") return 24;
      if (key === "M") return 25;
      return 1000;
    };
    const ra = rank(keyA);
    const rb = rank(keyB);
    return ra - rb || a.localeCompare(b);
  });

  const maxChromosomeLength = Math.max(...contigs.map((ctg) => chromosomeLength(ctg)), 1);

  return (
    <div>
      {/* Heatmap grid */}
      <div className="card" style={{ padding: 20, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Coverage Terrain Map</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
            <span style={{ color: "var(--color-text-muted)" }}>0x</span>
            <div style={{ width: 160, height: 8, borderRadius: 4, background: "linear-gradient(to right, #1e2832 0%, #ef4444 18%, #facc15 38%, #22d3ee 55%, #16a34a 72%, #047857 86%, #064e3b 100%)" }} />
            <span style={{ color: "var(--color-text-muted)" }}>High copy</span>
            <span style={{ width: 18, height: 8, borderRadius: 4, background: "repeating-linear-gradient(135deg, rgba(255,255,255,0.35) 0 2px, rgba(255,255,255,0) 2px 5px), #25313a", border: "1px solid var(--color-border-muted)" }} />
            <span style={{ color: "var(--color-text-muted)" }}>reference mask</span>
          </div>
        </div>

        {contigs.map((ctg) => {
          const bins = byContig[ctg];
          const widthPct = Math.max(4, (chromosomeLength(ctg) / maxChromosomeLength) * 100);
          return (
            <div key={ctg} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ width: 80, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)", textAlign: "right", flexShrink: 0 }}>{ctg}</span>
                <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
                <div style={{ width: `${widthPct}%`, display: "flex", gap: 1, height: 16, alignItems: "center" }}>
                  {bins.map((t, i) => {
                    const tileBaseline = expectedBaselineForTile(t, sexModel, baseline);
                    const tone = coverageTone(t.coverage, baseline, t, sexModel);
                    const ratio = numericCoverage(t.coverage) / Math.max(0.1, tileBaseline);
                    const centromere = overlapsCentromere(t);
                    return (
                      <div
                        key={t.tile_id || i}
                        title={`${t.contig}:${t.start?.toLocaleString()}–${t.end?.toLocaleString()}\nCoverage: ${numericCoverage(t.coverage).toFixed(2)}x\nScale: ${tone.label}, ${ratio.toFixed(2)}× expected (${tileBaseline.toFixed(1)}x)\nAnomaly: ${t.anomaly || "none"}${referenceTrackTitle(t)}`}
                        style={{
                          flex: 1, height: centromere ? "48%" : "100%", borderRadius: centromere ? 999 : 1,
                          background: tileBackground(tone, t), opacity: tone.opacity,
                          cursor: "pointer",
                        }}
                      />
                    );
                  })}
                </div>
                </div>
                <span style={{ width: 48, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--color-text-muted)", flexShrink: 0 }}>
                  {(bins.reduce((s, t) => s + numericCoverage(t.coverage), 0) / bins.length).toFixed(1)}x
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {otherContigs.length > 0 && (
        <div className="card" style={{ padding: 20, marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Other Contigs</h3>
            <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>sorted by mapped reads</span>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            {otherContigs.slice(0, 40).map((row) => (
              <div key={row.contig} style={{ display: "grid", gridTemplateColumns: "minmax(160px, 1fr) 120px", gap: 12, alignItems: "center", fontSize: 12, padding: "6px 0", borderBottom: "1px solid var(--color-border-muted)" }}>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.contig}>{row.contig}</span>
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-primary)", textAlign: "right" }}>{Number(row.reads || 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Legend */}
      <div style={{ marginTop: 12, padding: 12, background: "var(--color-bg-base)", borderRadius: 6, borderLeft: "3px solid var(--color-accent)", fontSize: 12, color: "var(--color-text-secondary)" }}>
        <strong>Terrain map:</strong> Colors are shown only for chr1-22, X, Y, and M at {level} resolution. Autosomes use the robust autosomal baseline ({baseline.toFixed(1)}x). Sex chromosomes use separate expected coverage when the X/Y pattern looks like XX or XY; current inferred model: {sexModel.karyotype}. Other contigs are not drawn as bars; when idxstats is available they are listed only by mapped read count.
      </div>
    </div>
  );
}
