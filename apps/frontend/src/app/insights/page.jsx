"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE, fetchJson } from "@/lib/api";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const INSIGHT_TABS = [
  { id: "fast_clinvar", label: "Fast ClinVar Screening", enabled: true },
  { id: "full_clinvar", label: "Full ClinVar", enabled: false },
  { id: "pgx", label: "PGx", enabled: false },
  { id: "prs", label: "PRS", enabled: false },
  { id: "traits", label: "Traits", enabled: false },
  { id: "haplogroups", label: "Haplogroups", enabled: false },
];

export default function InsightsPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId, selectionReady } = useAppSelection();
  const [activeTab, setActiveTab] = useState("fast_clinvar");
  const [project, setProject] = useState(null);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [samples, setSamples] = useState([]);
  const [sampleId, setSampleId] = useState("");
  const [resources, setResources] = useState(null);
  const [fastScreen, setFastScreen] = useState(null);
  const [foundation, setFoundation] = useState(null);
  const [monogenic, setMonogenic] = useState(null);
  const [includeVus, setIncludeVus] = useState(true);
  const [minReviewRank, setMinReviewRank] = useState(1);
  const [conditionQuery, setConditionQuery] = useState("");
  const [conditionTier, setConditionTier] = useState("all");
  const [selectedCondition, setSelectedCondition] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (selectionReady) init();
  }, [selectionReady, selectedProjectId, selectedRunId, selectedSampleId]);

  useEffect(() => {
    if (runId) loadRunFastScreen(runId);
    else if (sampleId) loadSampleFallback(sampleId);
  }, [runId, sampleId, includeVus, minReviewRank]);

  async function init() {
    setLoading(true);
    setFoundation(null);
    setMonogenic(null);
    setFastScreen(null);
    const [res, projects] = await Promise.all([
      fetchJson(`${API_BASE}/interpretation/resources`, null),
      fetchJson(`${API_BASE}/projects`, { items: [] }),
    ]);
    setResources(res);
    const projectItems = projects.items || [];
    const selectedProject = selectedProjectId ? projectItems.find((item) => item.id === selectedProjectId) || null : null;
    const scopedProjects = selectedProjectId ? projectItems.filter((item) => item.id === selectedProjectId) : projectItems;
    setProject(selectedProject);

    const allSamples = [];
    const allRuns = [];
    for (const prj of scopedProjects) {
      const [data, runData] = await Promise.all([
        fetchJson(`${API_BASE}/projects/${prj.id}/samples`, { items: [] }),
        fetchJson(`${API_BASE}/projects/${prj.id}/runs`, { items: [] }),
      ]);
      for (const sample of data.items || []) allSamples.push({ ...sample, project_name: prj.name });
      for (const run of runData.items || runData || []) allRuns.push({ ...run, project_name: prj.name });
    }
    setSamples(allSamples);
    allRuns.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
    setRuns(allRuns);

    const preferred = allSamples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId);
    const preferredRun = allRuns.find((run) => run.id === selectedRunId)
      || allRuns.find((run) => run.sample_id === preferred?.id || run.sample_id === preferred?.sample_id)
      || allRuns[0];
    if (preferredRun) {
      setRunId(preferredRun.id);
      const runSample = allSamples.find((sample) => sample.id === preferredRun.sample_id || sample.sample_id === preferredRun.sample_id);
      setSampleId(runSample?.sample_id || runSample?.id || preferred?.sample_id || preferred?.id || "");
    } else if (allSamples.length) {
      setRunId("");
      setSampleId(preferred?.sample_id || preferred?.id || allSamples[0].sample_id || allSamples[0].id);
    } else {
      setRunId("");
      setSampleId("");
      setLoading(false);
    }
  }

  async function loadRunFastScreen(rid) {
    setLoading(true);
    setSelectedCondition(null);
    const run = runs.find((item) => item.id === rid);
    const runSample = samples.find((sample) => sample.id === run?.sample_id || sample.sample_id === run?.sample_id);
    if (runSample) setSampleId(runSample.sample_id || runSample.id);
    const [foundationData, fastScreenData] = await Promise.all([
      runSample ? fetchJson(`${API_BASE}/samples/${runSample.sample_id || runSample.id}/interpretation/foundation`, null, { timeoutMs: 10000 }) : Promise.resolve(null),
      fetchJson(`${API_BASE}/runs/${rid}/clinvar/fast-screen`, { status: "missing", run_id: rid }, { timeoutMs: 10000 }),
    ]);
    setFoundation(foundationData);
    setFastScreen(fastScreenData);
    setMonogenic(null);
    setLoading(false);
  }

  async function loadSampleFallback(sid) {
    setLoading(true);
    setSelectedCondition(null);
    const [foundationData, monogenicData] = await Promise.all([
      fetchJson(`${API_BASE}/samples/${sid}/interpretation/foundation`, null, { timeoutMs: 10000 }),
      fetchJson(
        `${API_BASE}/samples/${sid}/interpretation/monogenic?include_vus=${includeVus}&min_review_rank=${minReviewRank}`,
        { status: "unavailable", message: "ClinVar endpoint timed out or failed." },
        { timeoutMs: 60000 }
      ),
    ]);
    setFoundation(foundationData);
    setMonogenic(monogenicData);
    setLoading(false);
  }

  const selectedSample = samples.find((sample) => (sample.sample_id || sample.id) === sampleId);
  const selectedRun = runs.find((run) => run.id === runId);
  const conditions = monogenic?.conditions || [];
  const filteredConditions = useMemo(() => filterConditions(conditions, conditionQuery, conditionTier), [conditions, conditionQuery, conditionTier]);
  const selected = selectedCondition && filteredConditions.includes(selectedCondition) ? selectedCondition : filteredConditions[0] || null;
  const summary = monogenic?.summary || {};
  const clinvarReady = Boolean(resources?.status?.clinvar_tsv);

  return (
    <div>
      <PageHeader
        eyebrow="Interpretation"
        title="Insights"
        description="Tabbed interpretation workspace. Fast ClinVar Screening is the active short path; full ClinVar reporting stays disabled until the full variants stage is ready."
        actions={(
          <div style={{ minWidth: 280 }}>
            <label className="field-label">Sample</label>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>
              Run-scoped Fast ClinVar result
            </div>
            <select value={runId} onChange={(event) => setRunId(event.target.value)} className="form-control" style={{ marginBottom: 8 }}>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.id} · {run.mode} · {run.status}
                </option>
              ))}
              {runs.length === 0 && <option value="">No runs</option>}
            </select>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>
              {project?.name || selectedProjectId || "Select in Projects"}
            </div>
            <select value={sampleId} onChange={(event) => setSampleId(event.target.value)} className="form-control">
              {samples.map((sample) => (
                <option key={sample.id} value={sample.sample_id || sample.id}>
                  {sample.sample_id || sample.id} ({sample.project_name})
                </option>
              ))}
              {samples.length === 0 && <option value="">No samples</option>}
            </select>
          </div>
        )}
      />

      <InsightsTabs activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "fast_clinvar" && (
        <ClinVarTab
          loading={loading}
          sample={selectedSample}
          run={selectedRun}
          resources={resources}
          fastScreen={fastScreen}
          foundation={foundation}
          monogenic={monogenic}
          summary={summary}
          conditions={conditions}
          filteredConditions={filteredConditions}
          selectedCondition={selected}
          clinvarReady={clinvarReady}
          includeVus={includeVus}
          minReviewRank={minReviewRank}
          conditionQuery={conditionQuery}
          conditionTier={conditionTier}
          onIncludeVusChange={setIncludeVus}
          onMinReviewRankChange={setMinReviewRank}
          onConditionQueryChange={setConditionQuery}
          onConditionTierChange={setConditionTier}
          onSelectCondition={setSelectedCondition}
        />
      )}
    </div>
  );
}

function InsightsTabs({ activeTab, onChange }) {
  return (
    <div className="segmented-control" style={{ marginBottom: 16, width: "fit-content", maxWidth: "100%", flexWrap: "wrap" }}>
      {INSIGHT_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`segmented-button ${activeTab === tab.id ? "active" : ""}`}
          disabled={!tab.enabled}
          title={tab.enabled ? undefined : "SOON"}
          onClick={() => tab.enabled && onChange(tab.id)}
          style={!tab.enabled ? { opacity: 0.45, cursor: "not-allowed" } : undefined}
        >
          {tab.label}{!tab.enabled ? " · SOON" : ""}
        </button>
      ))}
    </div>
  );
}

function ClinVarTab({
  loading,
  sample,
  run,
  resources,
  fastScreen,
  foundation,
  monogenic,
  summary,
  conditions,
  filteredConditions,
  selectedCondition,
  clinvarReady,
  includeVus,
  minReviewRank,
  conditionQuery,
  conditionTier,
  onIncludeVusChange,
  onMinReviewRankChange,
  onConditionQueryChange,
  onConditionTierChange,
  onSelectCondition,
}) {
  if (loading) {
    return <EmptyState title="Loading Fast ClinVar Screening" description="Checking sample context, build validation, and local ClinVar resource status." />;
  }

  if (!sample) {
    return <EmptyState title="No run or sample in selected project" description="Select a run in Runs, or import data into this project first." />;
  }

  const hasRunFastScreen = Boolean(run?.id);
  const fastStatus = fastScreen?.status || "missing";
  const exactMatches = fastScreen?.exact_match_count ?? 0;
  const rawCalls = fastScreen?.raw_call_count ?? 0;
  const targets = fastScreen?.target_count ?? 0;

  return (
    <>
      <Panel style={{ marginBottom: 16, borderLeft: "3px solid var(--color-warn)" }}>
        <b>Research-only guardrail</b>
        <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
          Fast ClinVar Screening is a targeted BAM-based screening path for known ClinVar loci after alignment. It is not full variant calling,
          not diagnosis, not medical advice, and not a clinical negative screen.
        </p>
      </Panel>

      <Panel title="Fast ClinVar Screening" style={{ marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
          <Metric label="Sample" value={sample.sample_id || sample.id || "—"} />
          <Metric label="Run" value={run?.id || "—"} />
          <Metric label="Status" value={fastStatus} tone={fastStatus === "missing" ? "warn" : "ok"} />
          <Metric label="Profile" value={fastScreen?.profile || "high_confidence_plp"} />
          <Metric label="Reference" value={foundation?.reference_id || "—"} />
          <Metric label="Targets" value={targets || "—"} />
          <Metric label="Raw calls" value={rawCalls} />
          <Metric label="Exact ClinVar P/LP matches" value={exactMatches} tone={exactMatches > 0 ? "warn" : "ok"} />
        </div>
      </Panel>

      {hasRunFastScreen && (
        <FastScreenResult fastScreen={fastScreen} />
      )}

      {!hasRunFastScreen && (
        <Panel style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <b style={{ fontSize: 13 }}>Imported-variant fallback filters</b>
          <label style={filterLabelStyle}>
            <input type="checkbox" checked={includeVus} onChange={(event) => onIncludeVusChange(event.target.checked)} />
            include VUS / conflicting
          </label>
          <label style={filterLabelStyle}>
            minimum review
            <select value={minReviewRank} onChange={(event) => onMinReviewRankChange(Number(event.target.value))} className="form-control" style={{ width: "auto", minHeight: 28, padding: "4px 8px", fontSize: 12 }}>
              <option value={0}>any assertion</option>
              <option value={1}>criteria provided+</option>
              <option value={2}>multiple submitters+</option>
              <option value={3}>expert panel / practice guideline</option>
            </select>
          </label>
          {conditions.length > 0 && (
            <>
              <input value={conditionQuery} onChange={(event) => onConditionQueryChange(event.target.value)} placeholder="Search condition, gene, variant, accession..." className="form-control" style={{ minWidth: 280, flex: "1 1 280px" }} />
              <select value={conditionTier} onChange={(event) => onConditionTierChange(event.target.value)} className="form-control" style={{ width: "auto", fontSize: 12 }}>
                <option value="all">all tiers</option>
                <option value="pathogenic_or_likely_pathogenic">P/LP only</option>
                <option value="uncertain_or_conflicting">VUS/conflicting only</option>
              </select>
              <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>Showing {filteredConditions.length} / {conditions.length}</span>
            </>
          )}
        </div>
        </Panel>
      )}

      {!clinvarReady && <ClinVarGate resources={resources} />}
      {!hasRunFastScreen && clinvarReady && conditions.length === 0 && <EmptyClinVarReport monogenic={monogenic} foundation={foundation} sample={sample} />}
      {conditions.length > 0 && (
        <Panel style={{ display: "grid", gridTemplateColumns: "minmax(300px, 0.9fr) minmax(360px, 1.1fr)", overflow: "hidden", padding: 0 }}>
          <div style={{ padding: 12, borderRight: "1px solid var(--color-border-muted)", maxHeight: 620, overflow: "auto" }}>
            {filteredConditions.length === 0 && <div style={{ padding: 14, color: "var(--color-text-muted)", fontSize: 13 }}>No matching conditions for the current filter.</div>}
            {filteredConditions.map((condition) => (
              <button key={`${condition.condition}:${condition.genes?.join(",")}`} onClick={() => onSelectCondition(condition)} style={conditionButtonStyle(selectedCondition === condition)}>
                <span style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <b>{condition.condition}</b>
                  <em style={{ color: tierColor(condition.highest_tier), fontStyle: "normal", whiteSpace: "nowrap" }}>{tierLabel(condition.highest_tier)}</em>
                </span>
                <small style={{ display: "block", marginTop: 6, color: "var(--color-text-muted)" }}>{(condition.genes || []).join(", ") || "gene unavailable"} · {condition.variant_count} variant{condition.variant_count === 1 ? "" : "s"}</small>
              </button>
            ))}
          </div>
          <ConditionDetail condition={selectedCondition} />
        </Panel>
      )}
    </>
  );
}

function FastScreenResult({ fastScreen }) {
  if (!fastScreen || fastScreen.status === "missing") {
    return (
      <Panel style={{ marginBottom: 16, borderLeft: "3px solid var(--color-warn)" }}>
        <b>No Fast ClinVar artifact for this run yet</b>
        <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13 }}>
          The run has not produced `clinvar_fast_screen/fast_screen.highconf.report.tsv`.
        </p>
      </Panel>
    );
  }

  const matches = fastScreen.matches || [];
  const rawCalls = fastScreen.raw_calls || [];
  return (
    <Panel style={{ marginBottom: 16, borderLeft: `3px solid ${fastScreen.exact_match_count > 0 ? "var(--color-warn)" : "var(--color-ok)"}` }}>
      <b>{fastScreen.exact_match_count > 0 ? "Exact ClinVar matches found" : "No exact high-confidence P/LP matches"}</b>
      <p style={{ margin: "6px 0 10px", color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
        {fastScreen.screening_note || fastScreen.description}
      </p>
      {matches.length > 0 ? (
        <div style={{ display: "grid", gap: 8 }}>
          {matches.map((item, index) => (
            <div key={`${item.chrom}:${item.pos}:${item.ref}:${item.alt}:${index}`} style={{ padding: 10, borderRadius: 8, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-muted)" }}>
              <b>{item.gene || "—"} · {item.chrom}:{item.pos} {item.ref} &gt; {item.alt}</b>
              <div style={{ marginTop: 6, color: "var(--color-text-secondary)", fontSize: 12 }}>
                {item.clinical_significance || "ClinVar"} · {item.review_status || "review unavailable"} · GT {item.gt || "—"} · DP {item.dp || "—"}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
          <div>
            The BAM screen produced {fastScreen.raw_call_count ?? 0} raw calls at {fastScreen.target_count ?? 0} high-confidence ClinVar loci, but none matched the exact ClinVar allele list.
          </div>
          {rawCalls.length > 0 && (
            <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
              {rawCalls.slice(0, 20).map((item, index) => (
                <div key={`${item.chrom || item.CHROM}:${item.pos || item.POS}:${index}`} style={{ padding: 8, borderRadius: 8, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-muted)", overflowWrap: "anywhere" }}>
                  <b style={{ color: "var(--color-text-primary)" }}>{formatRawCall(item)}</b>
                  <div style={{ marginTop: 4, fontSize: 11 }}>
                    {formatRawCallDetails(item)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {fastScreen.artifacts?.report_tsv && (
        <div style={{ marginTop: 10, color: "var(--color-text-muted)", fontSize: 11, fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>
          {fastScreen.artifacts.report_tsv}
        </div>
      )}
    </Panel>
  );
}

function rawField(item, names) {
  for (const name of names) {
    if (item?.[name] !== undefined && item?.[name] !== "") return item[name];
  }
  return "";
}

function parseInfoField(info) {
  const parsed = {};
  if (!info || info === ".") return parsed;
  for (const part of String(info).split(";")) {
    if (!part) continue;
    const [key, ...rest] = part.split("=");
    parsed[key] = rest.length ? rest.join("=") : true;
  }
  return parsed;
}

function parseSampleFormat(item) {
  const format = rawField(item, ["format", "FORMAT"]);
  const sample = rawField(item, ["sample", "SAMPLE"]);
  const parsed = {};
  if (!format || !sample) return parsed;
  const keys = String(format).split(":");
  const values = String(sample).split(":");
  for (let index = 0; index < keys.length; index += 1) {
    if (keys[index]) parsed[keys[index]] = values[index] ?? "";
  }
  return parsed;
}

function genotypeLabel(gt) {
  if (!gt || gt === "." || gt === "./.") return "";
  const alleles = String(gt).replaceAll("|", "/").split("/");
  if (alleles.length < 2 || alleles.some((allele) => allele === ".")) return "";
  if (alleles.every((allele) => allele === "0")) return "hom ref";
  if (alleles.every((allele) => allele !== "0" && allele === alleles[0])) return "hom alt";
  return "het";
}

function formatRawCall(item) {
  const chrom = rawField(item, ["chrom", "CHROM", "#CHROM"]) || "?";
  const pos = rawField(item, ["pos", "POS"]) || "?";
  const ref = rawField(item, ["ref", "REF"]) || "?";
  const alt = rawField(item, ["alt", "ALT"]) || "?";
  return `${chrom}:${pos} ${ref} > ${alt}`;
}

function formatRawCallDetails(item) {
  const sample = parseSampleFormat(item);
  const info = parseInfoField(rawField(item, ["info", "INFO"]));
  const gt = rawField(item, ["gt", "GT", "genotype"]) || sample.GT;
  const dp = rawField(item, ["dp", "DP", "depth"]) || sample.DP || info.DP;
  const ad = rawField(item, ["ad", "AD", "allele_depth"]) || sample.AD;
  const dp4 = rawField(item, ["dp4", "DP4"]) || info.DP4;
  const mq = rawField(item, ["mq", "MQ"]) || info.MQ;
  const qual = rawField(item, ["qual", "QUAL"]);
  const parts = [
    gt ? `GT ${gt}${genotypeLabel(gt) ? ` (${genotypeLabel(gt)})` : ""}` : "GT ?",
    dp ? `DP ${dp}` : "DP ?",
  ];
  if (ad) parts.push(`AD ${ad}`);
  if (dp4) parts.push(`DP4 ${dp4}`);
  if (mq) parts.push(`MQ ${mq}`);
  if (qual) parts.push(`QUAL ${qual}`);
  return parts.join(" · ");
}

function ClinVarGate({ resources }) {
  const pipeline = resources?.modules?.clinvar_monogenic?.pipeline || {};
  const expected = resources?.resources?.find?.((item) => item.id === "clinvar_exact_match_tsv")?.warnings || [];
  return (
    <Panel style={{ borderLeft: "3px solid var(--color-warn)" }}>
        <b>ClinVar screening resource gate</b>
      <p style={{ margin: "6px 0", color: "var(--color-text-secondary)", fontSize: 13 }}>
        No ClinVar interpretations are shown until a versioned exact-match TSV is installed.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
        <Metric label="VCF" value={pipeline.vcf ? "present" : "missing"} tone={pipeline.vcf ? "ok" : "warn"} />
        <Metric label="VCF index" value={pipeline.vcf_index ? "present" : "missing"} tone={pipeline.vcf_index ? "ok" : "warn"} />
        <Metric label="Exact TSV" value={pipeline.exact_match_tsv ? "present" : "missing"} tone={pipeline.exact_match_tsv ? "ok" : "warn"} />
      </div>
      {expected.length > 0 && <p style={{ margin: "10px 0 0", color: "var(--color-text-muted)", fontSize: 12 }}>{expected.join("; ")}</p>}
    </Panel>
  );
}

function EmptyClinVarReport({ monogenic, foundation, sample }) {
  const build = monogenic?.build_validation || foundation?.build_validation;
  const reason = !monogenic
    ? "No ClinVar payload is loaded yet."
    : monogenic.message
      ? monogenic.message
    : monogenic.status === "no_variants"
      ? "No imported variants are available for this sample yet."
      : monogenic.status === "no_reportable_findings"
        ? "No imported variants matched ClinVar under the current filters."
        : "No ClinVar condition groups are available for the current evidence gates.";
  return (
    <Panel style={{ borderLeft: "3px solid var(--color-info)" }}>
      <b>Empty fast ClinVar screen</b>
      <p style={{ margin: "6px 0 10px", color: "var(--color-text-secondary)", fontSize: 13 }}>{reason}</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
        <Metric label="Sample" value={sample?.sample_id || sample?.id || "—"} />
        <Metric label="Status" value={monogenic?.status || "empty_report"} />
        <Metric label="Build" value={build?.expected_build || "—"} />
        <Metric label="Variants reviewed" value={monogenic?.provenance?.input_variant_count ?? foundation?.variant_count ?? "—"} />
      </div>
    </Panel>
  );
}

function ConditionDetail({ condition }) {
  if (!condition) return <div style={{ padding: 16, color: "var(--color-text-muted)", fontSize: 13 }}>Select a condition to inspect matched variants.</div>;
  return (
    <div style={{ padding: 16, maxHeight: 620, overflow: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 18 }}>{condition.condition}</h3>
          <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13 }}>
            {(condition.genes || []).join(", ") || "Gene unavailable"} · {(condition.inheritance || []).join(", ") || "inheritance not specified"}
          </p>
        </div>
        <span className={`badge ${condition.highest_tier === "pathogenic_or_likely_pathogenic" ? "badge-warn" : "badge-info"}`}>{tierLabel(condition.highest_tier)}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8, marginBottom: 12 }}>
        <Metric label="Variants" value={condition.variant_count} />
        <Metric label="P/LP" value={condition.pathogenic_or_likely_pathogenic_count} tone={condition.pathogenic_or_likely_pathogenic_count ? "warn" : undefined} />
        <Metric label="VUS/conflicting" value={condition.uncertain_or_conflicting_count} />
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {(condition.items || []).map((item) => (
          <div key={`${item.chrom}:${item.pos}:${item.ref}:${item.alt}:${item.accession}`} style={{ padding: 12, borderRadius: 8, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-default)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <b>{item.gene || "—"} · {formatLocus(item)} {item.ref} &gt; {item.alt}</b>
              <span style={{ color: tierColor(item.tier), fontSize: 12 }}>{item.clinical_significance}</span>
            </div>
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
              <span className="badge badge-info">{zygosityLabel(item.zygosity)} {item.genotype ? `(${item.genotype})` : ""}</span>
              <span className={`badge ${assessabilityBadge(item.assessability)}`}>{assessabilityLabel(item.assessability)}</span>
              <span className={`badge ${coverageBadge(item.local_coverage_status)}`}>{coverageLabel(item.local_coverage_status)}</span>
            </div>
            <div style={{ marginTop: 8, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, color: "var(--color-text-secondary)", fontSize: 12 }}>
              <span>Review: {item.review_status || "—"}</span>
              <span>Inheritance: {item.inheritance || "—"}</span>
              <span>Accession: {item.accession || "—"}</span>
              <span>Trust: {item.technical_trust_score ?? "—"}</span>
              <span>Depth: {item.technical_evidence?.local_depth ?? "—"}</span>
              <span>Allele balance: {formatNumber(item.technical_evidence?.allele_balance)}</span>
            </div>
            {item.warning && <p style={{ margin: "8px 0 0", color: "var(--color-warn)", fontSize: 12 }}>{item.warning}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function Metric({ label, value, tone }) {
  const color = tone === "ok" ? "var(--color-ok)" : tone === "warn" ? "var(--color-warn)" : "var(--color-text-primary)";
  return (
    <div style={{ background: "var(--color-bg-elevated)", borderRadius: 8, padding: "10px 12px", minWidth: 0 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>{label}</div>
      <b style={{ color, fontSize: 13, overflowWrap: "anywhere" }}>{String(value)}</b>
    </div>
  );
}

function filterConditions(conditions, query, tier) {
  const q = String(query || "").trim().toLowerCase();
  return conditions.filter((condition) => {
    if (tier !== "all" && condition.highest_tier !== tier) return false;
    if (!q) return true;
    const haystack = [
      condition.condition,
      ...(condition.genes || []),
      ...(condition.inheritance || []),
      ...(condition.accessions || []),
      ...(condition.items || []).flatMap((item) => [
        item.gene, item.condition, item.clinical_significance, item.review_status, item.accession,
        item.genotype, item.zygosity, item.assessability, item.local_coverage_status,
        formatLocus(item), `${item.ref}>${item.alt}`,
      ]),
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(q);
  });
}

function tierLabel(tier) {
  if (tier === "pathogenic_or_likely_pathogenic") return "P/LP";
  if (tier === "uncertain_or_conflicting") return "VUS/conflicting";
  if (tier === "uncertain") return "VUS";
  if (tier === "conflicting") return "conflicting";
  return tier || "other";
}

function tierColor(tier) {
  return tier === "pathogenic_or_likely_pathogenic"
    ? "var(--color-warn)"
    : tier === "uncertain_or_conflicting" || tier === "uncertain" || tier === "conflicting"
      ? "var(--color-info)"
      : "var(--color-text-secondary)";
}

function conditionButtonStyle(active) {
  return {
    width: "100%",
    textAlign: "left",
    display: "block",
    padding: 12,
    marginBottom: 8,
    borderRadius: 8,
    border: active ? "1px solid var(--color-accent)" : "1px solid var(--color-border-default)",
    background: active ? "var(--color-accent-bg)" : "var(--color-bg-elevated)",
    color: "var(--color-text-primary)",
    cursor: "pointer",
  };
}

function formatLocus(item) {
  const chrom = String(item.chrom || "");
  return `${chrom.startsWith("chr") ? chrom : `chr${chrom}`}:${item.pos}`;
}

function zygosityLabel(value) {
  if (value === "homozygous_alt") return "homozygous alt";
  if (value === "heterozygous_alt") return "multi-allelic het";
  if (value === "hemizygous_alt") return "hemizygous alt";
  if (value === "no_call") return "no-call";
  return value || "zygosity unknown";
}

function assessabilityLabel(value) {
  if (value === "variant_assessable") return "assessable";
  if (value === "limited") return "limited evidence";
  if (value === "not_assessable") return "not assessable";
  return value || "assessability unknown";
}

function assessabilityBadge(value) {
  return value === "variant_assessable" ? "badge-ok" : "badge-warn";
}

function coverageLabel(value) {
  if (value === "variant_observed_with_depth") return "local depth present";
  if (value === "low_depth") return "low local depth";
  if (value === "coverage_unknown") return "coverage unknown";
  if (value === "genotype_uncalled") return "genotype uncalled";
  return value || "coverage unknown";
}

function coverageBadge(value) {
  return value === "variant_observed_with_depth" ? "badge-ok" : "badge-warn";
}

function formatNumber(value) {
  return typeof value === "number" ? Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "—";
}

const filterLabelStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: 7,
  color: "var(--color-text-secondary)",
  fontSize: 12,
};
