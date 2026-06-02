"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { API_BASE, fetchJson } from "@/lib/api";
import {
  MONOGENIC_CATALOG_VERSION,
  MONOGENIC_CONDITION_CATALOG,
  catalogCategories,
  catalogMatchesForCondition,
  filterCatalog,
} from "@/data/monogenicConditionCatalog";
import { PageHeader, Panel } from "@/components/ui";

export default function MonogenicReportPage() {
  const [samples, setSamples] = useState([]);
  const [sampleId, setSampleId] = useState("");
  const [resources, setResources] = useState(null);
  const [foundation, setFoundation] = useState(null);
  const [monogenic, setMonogenic] = useState(null);
  const [includeVus, setIncludeVus] = useState(true);
  const [minReviewRank, setMinReviewRank] = useState(1);
  const [conditionQuery, setConditionQuery] = useState("");
  const [conditionTier, setConditionTier] = useState("all");
  const [selectedCondition, setSelectedCondition] = useState(null);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogCategory, setCatalogCategory] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => { init(); }, []);
  useEffect(() => { if (sampleId) loadSample(sampleId); }, [sampleId, includeVus, minReviewRank]);

  async function init() {
    setLoading(true);
    const [res, projects] = await Promise.all([
      fetchJson(`${API_BASE}/interpretation/resources`, null),
      fetchJson(`${API_BASE}/projects`, { items: [] }),
    ]);
    setResources(res);
    const all = [];
    for (const prj of projects.items || []) {
      const data = await fetchJson(`${API_BASE}/projects/${prj.id}/samples`, { items: [] });
      for (const smp of data.items || []) all.push({ ...smp, project_name: prj.name });
    }
    setSamples(all);
    if (all.length) setSampleId(all[0].sample_id || all[0].id);
    else {
      setFoundation(null);
      setMonogenic(null);
      setLoading(false);
    }
  }

  async function loadSample(sid) {
    setLoading(true);
    setSelectedCondition(null);
    const [f, m] = await Promise.all([
      fetchJson(`${API_BASE}/samples/${sid}/interpretation/foundation`, null),
      fetchJson(`${API_BASE}/samples/${sid}/interpretation/monogenic?include_vus=${includeVus}&min_review_rank=${minReviewRank}`, null),
    ]);
    setFoundation(f);
    setMonogenic(m);
    setLoading(false);
  }

  const conditions = monogenic?.conditions || [];
  const filteredConditions = useMemo(() => filterConditions(conditions, conditionQuery, conditionTier), [conditions, conditionQuery, conditionTier]);
  const selected = selectedCondition && filteredConditions.includes(selectedCondition) ? selectedCondition : filteredConditions[0] || null;
  const summary = monogenic?.summary || {};
  const configured = monogenic?.status !== "not_configured";
  const sample = samples.find((s) => (s.sample_id || s.id) === sampleId);
  const catalogItems = useMemo(() => filterCatalog(catalogQuery, catalogCategory), [catalogQuery, catalogCategory]);
  const categories = useMemo(() => catalogCategories(), []);

  return (
    <div>
      <PageHeader
        eyebrow="Interpretation"
        title="ClinVar / Monogenic"
        description="ClinVar exact-match view for inherited and monogenic findings. Conditions with observed variants appear first; the broader catalog is a browsing and development aid, not a separate result source."
        actions={(
          <>
            <Link href="/insights" className="btn btn-ghost btn-sm">Back to Insights</Link>
            <div style={{ minWidth: 280 }}>
              <label className="field-label">Sample</label>
              <select value={sampleId} onChange={(e) => setSampleId(e.target.value)} className="form-control">
            {samples.map((s) => <option key={s.id} value={s.sample_id || s.id}>{s.sample_id || s.id} ({s.project_name})</option>)}
            {samples.length === 0 && <option value="">No samples</option>}
          </select>
            </div>
          </>
        )}
      />

      <Panel style={{ marginBottom: 16, borderLeft: "3px solid var(--color-warn)" }}>
        <b>Research-only guardrail</b>
        <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
          This report is not diagnosis and not a clinical negative screen. It shows only imported variants that exactly match the configured ClinVar TSV under the selected filters.
          The condition grouping is a presentation layer over ClinVar evidence, not an independent hereditary-condition panel.
        </p>
      </Panel>

      <Panel style={{ marginBottom: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
        <Metric label="Sample" value={sample?.sample_id || sample?.id || "—"} />
        <Metric label="Status" value={loading ? "loading" : monogenic?.status || "empty_report"} tone={configured ? "ok" : "warn"} />
        <Metric label="Conditions" value={summary.condition_count ?? monogenic?.condition_count ?? 0} />
        <Metric label="P/LP matches" value={summary.pathogenic_or_likely_pathogenic_count ?? 0} tone={(summary.pathogenic_or_likely_pathogenic_count || 0) > 0 ? "warn" : undefined} />
        <Metric label="VUS/conflicting" value={summary.uncertain_or_conflicting_count ?? 0} />
        <Metric label="Not assessable" value={summary.not_assessable_count ?? 0} tone={(summary.not_assessable_count || 0) > 0 ? "warn" : undefined} />
        <Metric label="ClinVar" value={resources?.status?.clinvar_tsv ? "configured" : "missing"} tone={resources?.status?.clinvar_tsv ? "ok" : "warn"} />
      </div>
      </Panel>

      <Panel style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <b style={{ fontSize: 13 }}>Report filters</b>
        <label style={filterLabelStyle}>
          <input type="checkbox" checked={includeVus} onChange={(e) => setIncludeVus(e.target.checked)} />
          include VUS / conflicting
        </label>
        <label style={filterLabelStyle}>
          minimum ClinVar review
          <select value={minReviewRank} onChange={(e) => setMinReviewRank(Number(e.target.value))} className="form-control" style={{ width: "auto", minHeight: 28, padding: "4px 8px", fontSize: 12 }}>
            <option value={0}>any assertion</option>
            <option value={1}>criteria provided+</option>
            <option value={2}>multiple submitters+</option>
            <option value={3}>expert panel / practice guideline</option>
          </select>
        </label>
      </div>
      </Panel>

      {conditions.length > 0 && (
        <Panel style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <b style={{ fontSize: 13 }}>Find condition</b>
          <input value={conditionQuery} onChange={(e) => setConditionQuery(e.target.value)} placeholder="Search disease, gene, variant, accession…" className="form-control" style={{ minWidth: 280, flex: "1 1 280px" }} />
          <select value={conditionTier} onChange={(e) => setConditionTier(e.target.value)} className="form-control" style={{ width: "auto", fontSize: 12 }}>
            <option value="all">all tiers</option>
            <option value="pathogenic_or_likely_pathogenic">P/LP only</option>
            <option value="uncertain_or_conflicting">VUS/conflicting only</option>
          </select>
          <span style={{ color: "var(--color-text-muted)", fontSize: 12 }}>Showing {filteredConditions.length} / {conditions.length}</span>
          </div>
        </Panel>
      )}

      <CatalogPanel
        items={catalogItems}
        total={MONOGENIC_CONDITION_CATALOG.length}
        version={MONOGENIC_CATALOG_VERSION}
        query={catalogQuery}
        category={catalogCategory}
        categories={categories}
        onQueryChange={setCatalogQuery}
        onCategoryChange={setCatalogCategory}
      />

      {!loading && monogenic?.status === "not_configured" && <ClinVarGate expectedPaths={monogenic.expected_paths || []} />}
      {!loading && monogenic?.status !== "not_configured" && conditions.length === 0 && <EmptyReport monogenic={monogenic} foundation={foundation} sample={sample} />}
      {!loading && conditions.length > 0 && (
        <Panel style={{ display: "grid", gridTemplateColumns: "minmax(300px, 0.9fr) minmax(360px, 1.1fr)", overflow: "hidden", padding: 0 }}>
          <div style={{ padding: 12, borderRight: "1px solid var(--color-border-muted)", maxHeight: 620, overflow: "auto" }}>
            {filteredConditions.length === 0 && <div style={{ padding: 14, color: "var(--color-text-muted)", fontSize: 13 }}>No matching conditions for the current search/filter.</div>}
            {filteredConditions.map((cond) => (
              <button key={`${cond.condition}:${cond.genes?.join(",")}`} onClick={() => setSelectedCondition(cond)} style={conditionButtonStyle(selected === cond)}>
                <span style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                  <b>{cond.condition}</b>
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                    <em style={{ color: "var(--color-err)", fontStyle: "normal", whiteSpace: "nowrap", fontWeight: 700 }}>wariant obecny</em>
                    <em style={{ color: tierColor(cond.highest_tier), fontStyle: "normal", whiteSpace: "nowrap" }}>{tierLabel(cond.highest_tier)}</em>
                  </span>
                </span>
                <small style={{ display: "block", marginTop: 6, color: "var(--color-text-muted)" }}>{(cond.genes || []).join(", ") || "gene unavailable"} · {cond.variant_count} variant{cond.variant_count === 1 ? "" : "s"}</small>
              </button>
            ))}
          </div>
          <ConditionDetail condition={selected} />
        </Panel>
      )}

      <Panel style={{ marginTop: 16 }}>
        <JsonBlock title="Provenance / evidence contract" data={{ build_validation: monogenic?.build_validation || foundation?.build_validation, provenance: monogenic?.provenance, non_diagnostic: monogenic?.non_diagnostic ?? true }} />
      </Panel>
    </div>
  );
}

function CatalogPanel({ items, total, version, query, category, categories, onQueryChange, onCategoryChange }) {
  return (
    <Panel
      title="ClinVar condition browsing catalog"
      description="Development catalog for browsing planned condition coverage. It is not a diagnostic panel definition; variant-level results above come only from imported variants matched to ClinVar."
      actions={<span className="badge badge-info">{version} · {items.length}/{total}</span>}
      style={{ marginBottom: 16 }}
    >
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
        <input value={query} onChange={(e) => onQueryChange(e.target.value)} placeholder="Search catalog disease, gene, inheritance…" className="form-control" style={{ minWidth: 280, flex: "1 1 280px" }} />
        <select value={category} onChange={(e) => onCategoryChange(e.target.value)} className="form-control" style={{ width: "auto" }}>
          {categories.map((cat) => <option key={cat} value={cat}>{cat === "all" ? "all categories" : cat}</option>)}
        </select>
      </div>
      <div style={{ border: "1px solid var(--color-border-muted)", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 1.6fr) minmax(160px, 0.7fr) minmax(120px, 0.35fr)", gap: 12, padding: "9px 12px", background: "var(--color-bg-base)", color: "var(--color-text-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: ".06em" }}>
          <span>Condition</span>
          <span>Genes / inheritance</span>
          <span>Flags</span>
        </div>
        <div style={{ maxHeight: 560, overflow: "auto" }}>
          {items.map((entry) => (
            <div key={entry.id} style={{ display: "grid", gridTemplateColumns: "minmax(260px, 1.6fr) minmax(160px, 0.7fr) minmax(120px, 0.35fr)", gap: 12, alignItems: "start", padding: "10px 12px", borderTop: "1px solid var(--color-border-muted)", background: "var(--color-bg-elevated)" }}>
              <div style={{ minWidth: 0 }}>
                <b style={{ display: "block", overflowWrap: "anywhere", wordBreak: "normal", lineHeight: 1.35 }}>{entry.condition}</b>
                <small style={{ display: "block", marginTop: 3, color: "var(--color-text-muted)", overflowWrap: "anywhere" }}>{entry.category}</small>
              </div>
              <div style={{ color: "var(--color-text-secondary)", fontSize: 12, lineHeight: 1.45, minWidth: 0, overflowWrap: "anywhere" }}>
                <span>{(entry.genes || []).length ? entry.genes.join(", ") : "gene by variant evidence"}</span>
                <br />
                <span style={{ color: "var(--color-text-muted)" }}>{(entry.inheritance || []).join(", ") || "inheritance varies"}</span>
              </div>
              <div style={{ display: "flex", gap: 5, flexWrap: "wrap", minWidth: 0 }}>
                {(entry.catalogFlags || []).map((flag) => <span key={flag} className="badge badge-info">{flag}</span>)}
              </div>
            </div>
          ))}
          {items.length === 0 && <div style={{ padding: 14, color: "var(--color-text-muted)", fontSize: 13 }}>No catalog entries match the current filter.</div>}
        </div>
      </div>
    </Panel>
  );
}

function ClinVarGate({ expectedPaths }) {
  return (
    <Panel style={{ borderLeft: "3px solid var(--color-warn)" }}>
      <b>ClinVar resource gate</b>
      <p style={{ margin: "6px 0", color: "var(--color-text-secondary)", fontSize: 13 }}>No monogenic interpretations are shown until a versioned ClinVar exact-match TSV is installed.</p>
      {expectedPaths.length > 0 && <ul style={{ margin: 0, paddingLeft: 18, color: "var(--color-text-muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>{expectedPaths.map((p) => <li key={p}>{p}</li>)}</ul>}
    </Panel>
  );
}

function EmptyReport({ monogenic, foundation, sample }) {
  const build = monogenic?.build_validation || foundation?.build_validation;
  const reason = !monogenic ? "No monogenic payload is loaded yet." : monogenic.status === "no_variants" ? "No imported variants are available for this sample yet." : monogenic.status === "no_reportable_findings" ? "No imported variants matched ClinVar under the current filters." : "No condition groups are available for the current evidence gates and filters.";
  return (
    <Panel style={{ borderLeft: "3px solid var(--color-info)" }}>
      <b>Empty ClinVar / monogenic view</b>
      <p style={{ margin: "6px 0 10px", color: "var(--color-text-secondary)", fontSize: 13 }}>{reason} This is a structured empty report, not a clinical negative screen.</p>
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
  if (!condition) return null;
  return (
    <div style={{ padding: 16, maxHeight: 620, overflow: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 18 }}>{condition.condition}</h3>
          <p style={{ margin: "6px 0 0", color: "var(--color-text-secondary)", fontSize: 13 }}>{(condition.genes || []).join(", ") || "Gene unavailable"} · {(condition.inheritance || []).join(", ") || "inheritance not specified"}</p>
          <CatalogMatches condition={condition.condition} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <span className="badge badge-err">wariant obecny</span>
          <span className={`badge ${condition.highest_tier === "pathogenic_or_likely_pathogenic" ? "badge-warn" : "badge-info"}`}>{tierLabel(condition.highest_tier)}</span>
        </div>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {(condition.items || []).map((item) => (
          <div key={`${item.chrom}:${item.pos}:${item.ref}:${item.alt}:${item.accession}`} style={{ padding: 12, borderRadius: 8, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-default)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <b>{item.gene || "—"} · {formatLocus(item)} {item.ref}→{item.alt}</b>
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
            <p style={{ margin: "8px 0 0", color: "var(--color-warn)", fontSize: 12 }}>{item.warning}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function CatalogMatches({ condition }) {
  const matches = catalogMatchesForCondition(condition);
  if (!matches.length) return null;
  return (
    <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
      {matches.map((entry) => <span key={entry.id} className="badge badge-info">in catalog</span>)}
    </div>
  );
}

function Metric({ label, value, tone }) {
  const color = tone === "ok" ? "var(--color-ok)" : tone === "warn" ? "var(--color-warn)" : "var(--color-text-primary)";
  return <div style={{ background: "var(--color-bg-elevated)", borderRadius: 8, padding: "10px 12px" }}><div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 4 }}>{label}</div><b style={{ color, fontSize: 13 }}>{String(value)}</b></div>;
}

function JsonBlock({ title, data }) {
  return <details><summary style={{ cursor: "pointer", color: "var(--color-accent-bright)", fontSize: 12 }}>{title}</summary><pre style={{ whiteSpace: "pre-wrap", fontSize: 11, color: "var(--color-text-muted)", background: "var(--color-bg-base)", borderRadius: 6, padding: 10, maxHeight: 220, overflow: "auto" }}>{JSON.stringify(data, null, 2)}</pre></details>;
}

function filterConditions(conditions, query, tier) {
  const q = String(query || "").trim().toLowerCase();
  return conditions.filter((condition) => {
    if (tier !== "all" && condition.highest_tier !== tier) return false;
    if (!q) return true;
    const haystack = [condition.condition, ...(condition.genes || []), ...(condition.inheritance || []), ...(condition.accessions || []), ...(condition.items || []).flatMap((item) => [item.gene, item.condition, item.clinical_significance, item.review_status, item.accession, item.genotype, item.zygosity, item.assessability, item.local_coverage_status, formatLocus(item), `${item.ref}>${item.alt}`, `${item.ref}→${item.alt}`])].filter(Boolean).join(" ").toLowerCase();
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
function formatLocus(item) { return `${String(item.chrom || "").startsWith("chr") ? item.chrom : `chr${item.chrom}`}:${item.pos}`; }
function zygosityLabel(value) {
  if (value === "heterozygous") return "heterozygous";
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
function assessabilityBadge(value) { return value === "variant_assessable" ? "badge-ok" : "badge-warn"; }
function coverageLabel(value) {
  if (value === "variant_observed_with_depth") return "local depth present";
  if (value === "low_depth") return "low local depth";
  if (value === "coverage_unknown") return "coverage unknown";
  if (value === "genotype_uncalled") return "genotype uncalled";
  return value || "coverage unknown";
}
function coverageBadge(value) { return value === "variant_observed_with_depth" ? "badge-ok" : "badge-warn"; }
function formatNumber(value) { return typeof value === "number" ? Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") : "—"; }
function tierColor(tier) { return tier === "pathogenic_or_likely_pathogenic" ? "var(--color-warn)" : tier === "uncertain_or_conflicting" || tier === "uncertain" || tier === "conflicting" ? "var(--color-info)" : "var(--color-text-secondary)"; }
function conditionButtonStyle(active) { return { width: "100%", textAlign: "left", display: "block", padding: 12, marginBottom: 8, borderRadius: 8, border: active ? "1px solid var(--color-accent)" : "1px solid var(--color-border-default)", background: active ? "var(--color-accent-bg)" : "var(--color-bg-elevated)", color: "var(--color-text-primary)", cursor: "pointer" }; }
const filterLabelStyle = { display: "inline-flex", alignItems: "center", gap: 7, color: "var(--color-text-secondary)", fontSize: 12 };
