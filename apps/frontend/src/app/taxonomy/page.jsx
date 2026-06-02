"use client";

import { API_BASE } from "@/lib/api";
import { useEffect, useRef, useState } from "react";
import { StageActionButtons } from "@/components/RunControls";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, ConfirmDialog, PageHeader, Panel } from "@/components/ui";

const PAGE_SIZE = 100;

const ROUTES = [
  { id: "human_wgs_host_depleted", label: "Human WGS host-depleted" },
  { id: "human_wgs_sensitive_low_mapq", label: "Sensitive human WGS" },
  { id: "full_fastq_shotgun", label: "Full FASTQ shotgun" },
  { id: "custom_host_depletion", label: "Custom host depletion" },
];

const FILTERS = [
  { id: "species", label: "Species" },
  { id: "genus", label: "Genus" },
  { id: "lineage", label: "Lineage" },
  { id: "review", label: "Review" },
  { id: "bacteria", label: "Bacteria" },
  { id: "viruses", label: "Viruses" },
  { id: "fungi", label: "Fungi" },
  { id: "unclassified", label: "Unclassified" },
  { id: "all", label: "All" },
];

const CLADE_TAXIDS = {
  bacteria: "2",
  viruses: "10239",
  fungi: "4751",
};

const EMPTY_DATABASE_MESSAGE = "No taxonomy database is installed. Install or register a Kraken2 database in Settings before starting a new taxonomy run.";

function routeLabel(route) {
  return ROUTES.find((item) => item.id === route)?.label || route || "Route not selected";
}

function inputLabel(mode) {
  if (mode === "host_depleted_bam_sensitive_low_mapq") return "host-depleted BAM sensitive low-MAPQ pairs";
  if (mode === "host_depleted_custom_host") return "custom host-depleted reads";
  if (mode === "host_depleted_bam_unmapped_pairs") return "host-depleted BAM unmapped pairs";
  if (mode === "raw_fastq") return "raw FASTQ fallback";
  return mode || "unknown";
}

function runOptions(run) {
  const params = run?.parameters || {};
  return params.stage_options || params || {};
}

function dbLabel(databases, dbIdOrPath) {
  if (!dbIdOrPath) return "Not selected";
  const value = String(dbIdOrPath);
  const id = value.split("/").filter(Boolean).slice(-1)[0] || value;
  const db = databases.find((item) => item.id === value || item.id === id);
  return db ? `${db.name} (${db.id})` : id;
}

function compactPath(value) {
  if (!value || typeof value !== "string") return value;
  const parts = value.split("/").filter(Boolean);
  if (parts.length <= 3) return value;
  return `.../${parts.slice(-3).join("/")}`;
}

function taxName(hit) {
  return String(hit?.organism || hit?.name || "");
}

function taxRank(hit) {
  return String(hit?.rank || hit?.kingdom || "taxon").toLowerCase();
}

function lineageNames(hit) {
  return Array.isArray(hit?.lineage)
    ? hit.lineage.map((node) => String(node?.name || "").toLowerCase()).filter(Boolean)
    : [];
}

function lineageTaxids(hit) {
  return Array.isArray(hit?.lineage)
    ? hit.lineage.map((node) => String(node?.taxid || "")).filter(Boolean)
    : [];
}

function isSpecies(hit) {
  return taxRank(hit) === "species";
}

function isGenus(hit) {
  return taxRank(hit) === "genus";
}

function isLineage(hit) {
  const rank = taxRank(hit);
  return rank !== "species" && rank !== "genus" && rank !== "unclassified";
}

function cladeMatches(hit, value) {
  const taxid = CLADE_TAXIDS[value];
  return Boolean(taxid && lineageTaxids(hit).includes(taxid));
}

function percent(value, { zero = "0%" } = {}) {
  const pct = Number(value || 0) * 100;
  if (!Number.isFinite(pct) || pct <= 0) return zero;
  if (pct < 0.01) return "<0.01%";
  if (pct < 1) return `${pct.toFixed(2)}%`;
  if (pct < 10) return `${pct.toFixed(1)}%`;
  return `${pct.toFixed(0)}%`;
}

function support(hit) {
  const reads = Number(hit?.read_count || 0);
  const score = Math.max(Number(hit?.confidence || 0), Number(hit?.evidence_score || 0));
  if (hit?.likely_contaminant) return { label: "contaminant", badge: "badge-warn", level: 0 };
  if (!isSpecies(hit)) return { label: isGenus(hit) ? "context" : "lineage", badge: "badge-info", level: 0 };
  if (reads < 10) return { label: "trace", badge: "badge-err", level: 0 };
  if (reads < 100 || score < 0.0001) return { label: "low support", badge: "badge-warn", level: 1 };
  return { label: "review", badge: "badge-ok", level: 2 };
}

function filterHits(hits, filter, search) {
  const needle = search.trim().toLowerCase();
  return hits.filter((hit) => {
    if (filter === "species" && !isSpecies(hit)) return false;
    if (filter === "genus" && !isGenus(hit)) return false;
    if (filter === "lineage" && !isLineage(hit)) return false;
    if (filter === "review" && support(hit).level < 2) return false;
    if (filter === "bacteria" && !cladeMatches(hit, "bacteria")) return false;
    if (filter === "viruses" && !cladeMatches(hit, "viruses")) return false;
    if (filter === "fungi" && !cladeMatches(hit, "fungi")) return false;
    if (filter === "unclassified" && !taxName(hit).toLowerCase().includes("unclassified")) return false;
    if (!needle) return true;
    const haystack = [
      hit.organism,
      hit.rank,
      hit.taxid,
      hit.top_clade,
      hit.warning,
      ...lineageNames(hit),
      ...lineageTaxids(hit),
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(needle);
  });
}

function readDenominator(hits) {
  const root = hits.find((hit) => taxRank(hit) === "root" || taxName(hit).toLowerCase() === "root");
  if (root?.read_count) return Number(root.read_count);
  return hits.reduce((max, hit) => Math.max(max, Number(hit.read_count || 0)), 0);
}

function taxonomyRunLabel(run, databases) {
  if (!run) return "No taxonomy run";
  const options = runOptions(run);
  const db = dbLabel(databases, options.taxonomy_database || options.taxonomy_database_path);
  return `${run.id} · ${run.status} · ${db}`;
}

function statusBadge(status) {
  if (status === "done") return "badge-ok";
  if (status === "running" || status === "queued") return "badge-info";
  if (status === "failed" || status === "error") return "badge-err";
  return "badge-warn";
}

function inheritedInput(value) {
  if (value === "parent_alignment_bam") return "Parent aligned BAM";
  if (value === "sample_fastq") return "Sample FASTQ";
  return value || "Run inputs";
}

function sortedRuns(runs) {
  const score = (run) => {
    if (run.mode === "taxonomy" && run.status === "done") return 0;
    if (run.mode === "taxonomy" && ["running", "queued", "paused"].includes(run.status)) return 1;
    if (run.mode !== "taxonomy" && run.status === "done") return 2;
    if (run.mode !== "taxonomy" && ["running", "queued", "paused"].includes(run.status)) return 3;
    return 4;
  };
  return [...runs].sort((a, b) => {
    const diff = score(a) - score(b);
    if (diff) return diff;
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
}

export default function TaxonomyPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId, selectionReady } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [selectedSample, setSelectedSample] = useState("");
  const [sampleRuns, setSampleRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState("");
  const [databases, setDatabases] = useState([]);
  const [selectedDb, setSelectedDb] = useState("");
  const [route, setRoute] = useState("human_wgs_host_depleted");
  const [lowMapq, setLowMapq] = useState(10);
  const [taxonomy, setTaxonomy] = useState(null);
  const [taxonomyStep, setTaxonomyStep] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [refreshError, setRefreshError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [filter, setFilter] = useState("species");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [recoverOpen, setRecoverOpen] = useState(false);
  const [recoverForm, setRecoverForm] = useState({ runId: "", parentRunId: "", reportPath: "" });
  const [pendingDeleteRun, setPendingDeleteRun] = useState(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const sampleRunsInFlight = useRef(false);
  const taxonomyInFlight = useRef(false);

  const selectedRunInfo = sampleRuns.find((run) => run.id === selectedRun);
  const parentRuns = sampleRuns.filter((run) => run.mode !== "taxonomy");
  const taxonomyRuns = sampleRuns.filter((run) => run.mode === "taxonomy");
  const installedDatabases = databases.filter((db) => db.installed);
  const selectedRunOptions = runOptions(selectedRunInfo);
  const hits = taxonomy?.items || taxonomy?.top_hits || [];
  const totalReads = Number(taxonomy?.total_reads ?? readDenominator(hits));
  const filteredCount = Number(taxonomy?.filtered_count ?? taxonomy?.count ?? hits.length);
  const totalCount = Number(taxonomy?.total_count ?? filteredCount);
  const selectedTaxonomyRun = taxonomyRuns.find((run) => run.id === selectedRun);
  const selectedParentRun = selectedRunInfo?.mode === "taxonomy"
    ? parentRuns.find((run) => run.id === selectedRunOptions.parent_run_id) || parentRuns[0]
    : selectedRunInfo;
  const totalPages = Math.max(1, Math.ceil(filteredCount / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedHits = hits;

  useEffect(() => {
    if (!selectionReady) return;
    loadInitial();
  }, [selectionReady, selectedProjectId, selectedSampleId]);

  useEffect(() => {
    setPage(1);
  }, [selectedSample, selectedRun, filter, search]);

  useEffect(() => {
    if (selectedSample) loadSampleRuns(selectedSample);
    else {
      setSampleRuns([]);
      setSelectedRun("");
      setTaxonomy(null);
    }
  }, [selectedSample, selectedRunId]);

  useEffect(() => {
    if (selectedSample && selectedRun) loadTaxonomy(selectedSample, selectedRun);
  }, [selectedSample, selectedRun, filter, search, page]);

  useEffect(() => {
    if (selectedDb || installedDatabases.length === 0) return;
    const preferred = installedDatabases.find((db) => db.id === "standard") || installedDatabases[0];
    if (preferred) setSelectedDb(preferred.id);
  }, [installedDatabases, selectedDb]);

  useEffect(() => {
    const runActive = ["running", "queued", "paused", "interrupted"].includes(selectedRunInfo?.status);
    const stepActive = ["running", "queued"].includes(taxonomyStep?.status);
    const waiting = taxonomy?.provenance?.event_type === "taxonomy.results_cleared";
    if (!selectedSample || !selectedRun || (!runActive && !stepActive && !waiting)) return;
    const interval = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      loadSampleRuns(selectedSample);
      loadTaxonomy(selectedSample, selectedRun, { silent: true });
    }, stepActive || waiting ? 10000 : 30000);
    return () => clearInterval(interval);
  }, [selectedSample, selectedRun, selectedRunInfo?.status, taxonomyStep?.status, taxonomy?.provenance?.event_type]);

  async function loadInitial() {
    if (!selectionReady) return;
    setLoading(true);
    try {
      const [projectsRes, dbRes] = await Promise.all([
        fetch(`${API_BASE}/projects`),
        fetch(`${API_BASE}/data/taxonomy-databases`),
      ]);
      const [projects, dbs] = await Promise.all([projectsRes.json(), dbRes.json()]);
      setDatabases(dbs.items || dbs || []);

      const loadedSamples = [];
      const projectItems = projects.items || [];
      const scopedProjects = selectedProjectId
        ? projectItems.filter((item) => item.id === selectedProjectId)
        : projectItems;
      setProject(selectedProjectId ? projectItems.find((item) => item.id === selectedProjectId) || null : null);
      for (const projectItem of scopedProjects) {
        const sampleRes = await fetch(`${API_BASE}/projects/${projectItem.id}/samples`).catch(() => null);
        if (!sampleRes?.ok) continue;
        const sampleData = await sampleRes.json();
        for (const sample of sampleData.items || sampleData || []) {
          loadedSamples.push({ ...sample, project_name: projectItem.name, project_id: projectItem.id });
        }
      }
      setSamples(loadedSamples);
      const preferredSample = loadedSamples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId);
      const nextSample = preferredSample?.id || loadedSamples[0]?.id || "";
      setSelectedSample(nextSample);
      if (!nextSample) {
        setSampleRuns([]);
        setSelectedRun("");
        setTaxonomy(null);
        setTaxonomyStep(null);
      }
    } catch (error) {
      setProject(null);
      setSamples([]);
      setSelectedSample("");
      setStatus(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function loadSampleRuns(sampleId) {
    if (sampleRunsInFlight.current) return;
    sampleRunsInFlight.current = true;
    try {
      const res = await fetch(`${API_BASE}/samples/${sampleId}/runs`);
      if (!res.ok) throw new Error(`runs ${res.status}`);
      const data = await res.json();
      const runs = sortedRuns(data.items || data || []);
      setSampleRuns(runs);
      setSelectedRun((current) => {
        if (current && runs.some((run) => run.id === current)) return current;
        const preferredRun = runs.find((run) => run.id === selectedRunId);
        return preferredRun?.id || runs[0]?.id || "";
      });
    } catch {
      setSampleRuns([]);
      setSelectedRun("");
    } finally {
      sampleRunsInFlight.current = false;
    }
  }

  function taxonomyQuery({ runId = "", includePaging = true, includeView = true } = {}) {
    const params = new URLSearchParams();
    if (runId) params.set("run_id", runId);
    if (includePaging) {
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String((Math.max(1, page) - 1) * PAGE_SIZE));
    }
    if (includeView) {
      params.set("filter", filter);
      if (search.trim()) params.set("search", search.trim());
    }
    const query = params.toString();
    return query ? `?${query}` : "";
  }

  async function fetchTaxonomy(sampleId, runId = "") {
    const scopedRes = await fetch(`${API_BASE}/samples/${sampleId}/taxonomy${taxonomyQuery({ runId })}`);
    if (!scopedRes.ok) return null;
    const scoped = await scopedRes.json();
    if (!runId || Number(scoped.count || 0) > 0 || (scoped.items || []).length > 0) return scoped;

    const sampleRes = await fetch(`${API_BASE}/samples/${sampleId}/taxonomy${taxonomyQuery({ includePaging: false, includeView: false })}`);
    if (!sampleRes.ok) return scoped;
    const sampleWide = await sampleRes.json();
    const recoveredItems = filterHits((sampleWide.items || []).filter((item) => item.run_id === runId), filter, search);
    if (recoveredItems.length === 0) return scoped;
    const offset = (Math.max(1, page) - 1) * PAGE_SIZE;
    const pageItems = recoveredItems.slice(offset, offset + PAGE_SIZE);
    return {
      ...sampleWide,
      run_id: runId,
      count: recoveredItems.length,
      total_count: recoveredItems.length,
      filtered_count: recoveredItems.length,
      limit: PAGE_SIZE,
      offset,
      has_more: offset + pageItems.length < recoveredItems.length,
      page_count: pageItems.length,
      total_reads: readDenominator(recoveredItems),
      items: pageItems,
      provenance: {
        ...(sampleWide.provenance || {}),
        warning: sampleWide.provenance?.warning || "run_scoped_taxonomy_recovered_from_sample_cache",
      },
    };
  }

  async function loadTaxonomy(sampleId, runId = "", { silent = false } = {}) {
    if (taxonomyInFlight.current) return;
    taxonomyInFlight.current = true;
    try {
      const [taxonomyData, stepData] = await Promise.all([
        fetchTaxonomy(sampleId, runId),
        runId ? fetch(`${API_BASE}/runs/${runId}/steps`).then((r) => r.ok ? r.json() : { items: [] }) : { items: [] },
      ]);
      setTaxonomy(taxonomyData);
      setTaxonomyStep((stepData.items || stepData || []).find((step) => step.step_name === "taxonomy") || null);
      setLastRefresh(new Date());
      setRefreshError("");
    } catch {
      if (!silent) setTaxonomy(null);
      setRefreshError("refresh failed");
    } finally {
      taxonomyInFlight.current = false;
    }
  }

  async function startSubrun() {
    const parentRunId = selectedRunInfo?.mode === "taxonomy" ? selectedParentRun?.id : selectedRun;
    if (!parentRunId || !selectedDb) return;
    setBusy(true);
    setStatus("Starting taxonomy subrun...");
    try {
      const res = await fetch(`${API_BASE}/runs/${parentRunId}/taxonomy/subruns`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taxonomy_database: selectedDb,
          taxonomy_route: route,
          taxonomy_low_mapq_threshold: Number(lowMapq) || 10,
          allow_dev_fallback: false,
          stop_on_failure: false,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || data.detail?.code || `HTTP ${res.status}`);
      setStatus(`Started taxonomy subrun ${data.subrun_id}`);
      await loadSampleRuns(selectedSample);
      setSelectedRun(data.subrun_id);
    } catch (error) {
      setStatus(`Error: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function recoverTaxonomy() {
    if (!selectedSample) return;
    const reportPath = (recoverForm.reportPath || taxonomy?.provenance?.taxonomy_report_path || taxonomy?.provenance?.kraken_report_path || selectedRunOptions.taxonomy_report_path || "").trim();
    if (!reportPath) {
      setStatus("Error: Kraken report path is required");
      return;
    }
    setBusy(true);
    setStatus("Importing taxonomy report...");
    try {
      const res = await fetch(`${API_BASE}/samples/${selectedSample}/taxonomy/recover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: (recoverForm.runId || (selectedRunInfo?.mode === "taxonomy" ? selectedRun : "")).trim() || null,
          parent_run_id: (recoverForm.parentRunId || selectedRunOptions.parent_run_id || "").trim() || null,
          taxonomy_report_path: reportPath,
          replace_existing_for_run: true,
          taxonomy_mode: "kraken2",
          taxonomy_input_mode: selectedRunOptions.taxonomy_input_mode || "host_depleted_bam_unmapped_pairs",
          taxonomy_database: selectedDb || selectedRunOptions.taxonomy_database || selectedRunOptions.taxonomy_database_path || null,
          taxonomy_route: route || selectedRunOptions.taxonomy_route || null,
          kraken_report_path: reportPath,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || data.detail?.code || `HTTP ${res.status}`);
      const runId = data.recovered_run_id || data.run_id;
      setRecoverOpen(false);
      setStatus(`Imported ${Number(data.count || 0).toLocaleString()} taxonomy rows into ${runId}`);
      await loadSampleRuns(selectedSample);
      setSelectedRun(runId);
    } catch (error) {
      setStatus(`Error: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteTaxonomyRun(run) {
    if (!run?.id) return;
    setPendingDeleteRun(null);
    setDeleteConfirm("");
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || data.detail?.code || `HTTP ${res.status}`);
      setStatus(`Deleted taxonomy subrun ${run.id}`);
      await loadSampleRuns(selectedSample);
    } catch (error) {
      setStatus(`Error: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading taxonomy...</div>;
  }

  return (
    <div>
      <PageHeader
        eyebrow="Taxonomy"
        title="Taxonomy"
        description="Inspect run-scoped microbial classification results for the project selected in Projects."
        actions={<Button variant="secondary" onClick={() => window.location.assign("/settings")}>Database Settings</Button>}
      />

      <Panel title="Taxonomy Setup" description="Database management lives in Settings. This page only chooses an installed database and a result to view.">
        {installedDatabases.length === 0 ? (
          <Notice tone="warn">{EMPTY_DATABASE_MESSAGE}</Notice>
        ) : (
          <div style={workspaceGrid}>
            <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
            <SelectField label="Sample" value={selectedSample} onChange={setSelectedSample}>
              {samples.map((sample) => (
                <option key={sample.id} value={sample.id}>{sample.sample_id} ({sample.project_name})</option>
              ))}
              {samples.length === 0 && <option value="">No samples in selected project</option>}
            </SelectField>
            <SelectField label="Taxonomy database" value={selectedDb} onChange={setSelectedDb}>
              {installedDatabases.map((db) => <option key={db.id} value={db.id}>{db.name}</option>)}
            </SelectField>
            <SelectField label="Result" value={selectedTaxonomyRun?.id || ""} onChange={setSelectedRun}>
              {taxonomyRuns.length === 0 && <option value="">No taxonomy results yet</option>}
              {taxonomyRuns.map((run) => (
                <option key={run.id} value={run.id}>{taxonomyRunLabel(run, databases)}</option>
              ))}
            </SelectField>
          </div>
        )}

        {installedDatabases.length > 0 && taxonomyRuns.length === 0 && (
          <Notice>No taxonomy result is imported for this sample yet. Start a subrun from Advanced actions when a completed parent WGS run is available.</Notice>
        )}

        <div style={actionBar}>
          <Button variant="ghost" onClick={() => setAdvancedOpen((value) => !value)}>
            {advancedOpen ? "Hide Advanced" : "Advanced Actions"}
          </Button>
          {status && <span style={{ color: status.startsWith("Error") ? "var(--color-err)" : "var(--color-accent)", fontSize: 12 }}>{status}</span>}
        </div>

        {advancedOpen && (
          <div style={advancedPanelStyle}>
            <div style={newRunGrid}>
              <SelectField label="Parent WGS run for new taxonomy" value={selectedParentRun?.id || ""} onChange={setSelectedRun}>
                <option value="">Select parent run...</option>
                {parentRuns.map((run) => (
                  <option key={run.id} value={run.id}>{run.id} · {run.status}</option>
                ))}
              </SelectField>
              <SelectField label="Route" value={route} onChange={setRoute}>
                {ROUTES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
              </SelectField>
              {route === "human_wgs_sensitive_low_mapq" && (
                <Field label="Low MAPQ">
                  <input className="form-control" type="number" min="0" max="60" value={lowMapq} onChange={(event) => setLowMapq(event.target.value)} />
                </Field>
              )}
            </div>

            <div style={actionBar}>
              <Button
                variant="primary"
                onClick={startSubrun}
                disabled={busy || !(selectedRunInfo?.mode === "taxonomy" ? selectedParentRun?.id : selectedRun) || !selectedDb || installedDatabases.length === 0}
                title="Start a separate taxonomy run from the selected WGS parent."
              >
                Start Taxonomy Subrun
              </Button>
              <Button variant="ghost" onClick={() => setRecoverOpen((value) => !value)}>
                Recovery Tools
              </Button>
              {selectedRunInfo && (
                <StageActionButtons
                  run={selectedRunInfo}
                  stage="taxonomy"
                  steps={taxonomyStep ? [taxonomyStep] : []}
                  onRefresh={() => {
                    loadSampleRuns(selectedSample);
                    loadTaxonomy(selectedSample, selectedRun);
                  }}
                  compact
                />
              )}
            </div>

            <RunChooser
              parentRuns={parentRuns}
              taxonomyRuns={taxonomyRuns}
              databases={databases}
              selectedRun={selectedRun}
              selectedParentRun={selectedParentRun}
              onSelect={setSelectedRun}
              onDelete={(run) => {
                setDeleteConfirm("");
                setPendingDeleteRun(run);
              }}
            />

            {recoverOpen && (
              <RecoveryForm
                form={recoverForm}
                setForm={setRecoverForm}
                selectedRun={selectedRunInfo}
                defaultReport={taxonomy?.provenance?.taxonomy_report_path || taxonomy?.provenance?.kraken_report_path || selectedRunOptions.taxonomy_report_path || ""}
                busy={busy}
                onRecover={recoverTaxonomy}
              />
            )}
          </div>
        )}
      </Panel>

      <div style={resultsStack}>
        <ResultHeader
          run={selectedRunInfo}
          taxonomy={taxonomy}
          step={taxonomyStep}
          databases={databases}
          lastRefresh={lastRefresh}
          refreshError={refreshError}
          totalReads={totalReads}
          hitsCount={filteredCount}
        />

        {!taxonomy ? (
          <EmptyTaxonomy run={selectedRunInfo} step={taxonomyStep} hasSubruns={taxonomyRuns.length > 0} databasesInstalled={installedDatabases.length > 0} />
        ) : (
          <>
            <TaxonomyResults
              hits={pagedHits}
              filteredCount={filteredCount}
              totalCount={totalCount}
              totalReads={totalReads}
              filter={filter}
              setFilter={setFilter}
              search={search}
              setSearch={setSearch}
              page={currentPage}
              totalPages={totalPages}
              setPage={setPage}
            />
            <Provenance provenance={taxonomy?.provenance} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={!!pendingDeleteRun}
        title={`Delete ${pendingDeleteRun?.id || "taxonomy subrun"}?`}
        description="This removes the selected taxonomy subrun, its run-scoped taxonomy rows, events, logs, and result directory."
        details={[
          "This action cannot be undone from the UI.",
          "Type the exact run id below to confirm deletion.",
          "The parent WGS run and extracted Kraken databases are preserved.",
        ]}
        confirmLabel="Delete subrun"
        confirmDisabled={deleteConfirm !== pendingDeleteRun?.id || busy}
        onCancel={() => {
          setPendingDeleteRun(null);
          setDeleteConfirm("");
        }}
        onConfirm={() => deleteTaxonomyRun(pendingDeleteRun)}
      >
        <div style={{ display: "grid", gap: 6, marginTop: 12 }}>
          <label style={fieldLabel}>Confirm run id</label>
          <input className="form-control" value={deleteConfirm} onChange={(event) => setDeleteConfirm(event.target.value)} placeholder={pendingDeleteRun?.id || "run_..."} autoFocus />
        </div>
      </ConfirmDialog>
    </div>
  );
}

function SelectField({ label, value, onChange, children }) {
  return (
    <Field label={label}>
      <select className="form-control" value={value || ""} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </Field>
  );
}

function Field({ label, children }) {
  return (
    <label style={{ display: "grid", gap: 5, minWidth: 0 }}>
      <span style={fieldLabel}>{label}</span>
      {children}
    </label>
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

function Notice({ tone = "info", children }) {
  const color = tone === "warn" ? "var(--color-warn)" : "var(--color-info)";
  return (
    <div style={{ marginTop: 12, padding: "10px 12px", border: `1px solid ${color}`, borderRadius: 8, color, background: "var(--color-bg-elevated)", fontSize: 12 }}>
      {children}
    </div>
  );
}

function RecoveryForm({ form, setForm, selectedRun, defaultReport, busy, onRecover }) {
  return (
    <div style={{ marginTop: 14, padding: 12, border: "1px solid var(--color-border-muted)", borderRadius: 8, background: "var(--color-bg-elevated)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))", gap: 10, alignItems: "end" }}>
        <Field label="Kraken report path">
          <input className="form-control" value={form.reportPath} onChange={(event) => setForm((draft) => ({ ...draft, reportPath: event.target.value }))} placeholder={defaultReport || "/data/input/Backup/.../*.kraken2.report"} />
        </Field>
        <Field label="Target run id">
          <input className="form-control" value={form.runId} onChange={(event) => setForm((draft) => ({ ...draft, runId: event.target.value }))} placeholder={selectedRun?.mode === "taxonomy" ? selectedRun.id : "run_..."} />
        </Field>
        <Field label="Parent run id">
          <input className="form-control" value={form.parentRunId} onChange={(event) => setForm((draft) => ({ ...draft, parentRunId: event.target.value }))} placeholder={runOptions(selectedRun).parent_run_id || "optional"} />
        </Field>
        <Button variant="secondary" disabled={busy} onClick={onRecover}>Import Report</Button>
      </div>
    </div>
  );
}

function RunChooser({ parentRuns, taxonomyRuns, databases, selectedRun, selectedParentRun, onSelect, onDelete }) {
  return (
    <div style={runChooserStyle}>
      <RunGroup title="Taxonomy results" empty="No taxonomy results for this sample yet.">
        {taxonomyRuns.map((run) => (
          <RunRow key={run.id} run={run} databases={databases} selected={selectedRun === run.id} onSelect={onSelect} onDelete={onDelete} />
        ))}
      </RunGroup>
      <RunGroup title="WGS parent runs" empty="No parent runs available.">
        {parentRuns.map((run) => (
          <RunRow key={run.id} run={run} databases={databases} selected={selectedRun === run.id || selectedParentRun?.id === run.id} compact onSelect={onSelect} />
        ))}
      </RunGroup>
    </div>
  );
}

function RunGroup({ title, empty, children }) {
  const rows = Array.isArray(children) ? children.filter(Boolean) : children;
  return (
    <div style={{ display: "grid", gap: 8, minWidth: 0 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{title}</div>
      <div style={runGroupRowsStyle}>
        {rows && rows.length ? rows : <div style={{ color: "var(--color-text-muted)", fontSize: 12 }}>{empty}</div>}
      </div>
    </div>
  );
}

function RunRow({ run, databases, selected, compact = false, onSelect, onDelete }) {
  const options = runOptions(run);
  const canDelete = run.mode === "taxonomy" && !["running", "queued", "paused", "cancelling"].includes(run.status);
  return (
    <div style={{ ...runRowStyle, minWidth: compact ? 220 : 280, borderColor: selected ? "var(--color-accent)" : "var(--color-border-muted)" }}>
      <button type="button" onClick={() => onSelect(run.id)} style={runButtonStyle}>
        <span className={`badge ${statusBadge(run.status)}`}>{run.status}</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflowWrap: "anywhere" }}>{run.id}</span>
        {!compact && (
          <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>
            {run.mode === "taxonomy"
              ? `${dbLabel(databases, options.taxonomy_database || options.taxonomy_database_path)} · ${routeLabel(options.taxonomy_route)}`
              : run.mode}
          </span>
        )}
        {!compact && options.parent_run_id && <span style={{ color: "var(--color-text-muted)", fontSize: 11 }}>parent {options.parent_run_id}</span>}
      </button>
      {onDelete && (
        <Button size="sm" variant="danger" disabled={!canDelete || !selected} onClick={() => onDelete(run)}>
          Delete
        </Button>
      )}
    </div>
  );
}

function ResultHeader({ run, taxonomy, step, databases, lastRefresh, refreshError, totalReads, hitsCount }) {
  const options = runOptions(run);
  const provenance = taxonomy?.provenance || {};
  const database = provenance.taxonomy_database || options.taxonomy_database || options.taxonomy_database_path;
  return (
    <Panel title="Selected Result" description="The table below belongs to the selected taxonomy run. Database installation is intentionally outside this page.">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
        <Metric label="Run" value={run ? `${run.id} · ${run.mode}` : "None"} />
        <Metric label="Status" value={run?.status || "No run"} tone={run?.status === "done" ? "ok" : run?.status === "failed" ? "err" : "info"} />
        <Metric label="Database" value={dbLabel(databases, database)} />
        <Metric label="Route" value={routeLabel(provenance.taxonomy_route || options.taxonomy_route)} />
        <Metric label="Input" value={inputLabel(provenance.taxonomy_input_mode || options.taxonomy_input_mode || options.inherited_input)} />
        <Metric label="Taxa / reads" value={`${hitsCount.toLocaleString()} / ${totalReads.toLocaleString()}`} />
      </div>
      <div style={{ marginTop: 10, fontSize: 12, color: refreshError ? "var(--color-warn)" : "var(--color-text-muted)" }}>
        Refresh {lastRefresh ? lastRefresh.toLocaleTimeString() : "waiting"}{step?.status ? ` · taxonomy step ${step.status}` : ""}{refreshError ? ` · ${refreshError}` : ""}
      </div>
    </Panel>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div style={{ padding: 10, borderRadius: 8, background: "var(--color-bg-elevated)", minWidth: 0 }}>
      <div style={metricLabel}>{label}</div>
      <div style={{ fontSize: 12, color: tone ? `var(--color-${tone})` : "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>
        {value || "None"}
      </div>
    </div>
  );
}

function EmptyTaxonomy({ run, step, hasSubruns, databasesInstalled }) {
  const failed = step?.status === "failed";
  return (
    <Panel>
      <div style={{ padding: "42px 24px", textAlign: "center", color: failed ? "var(--color-err)" : "var(--color-text-muted)" }}>
        <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>
          {failed ? "Taxonomy failed before import" : databasesInstalled ? "No taxonomy rows for the selected run" : "No taxonomy database installed"}
        </div>
        <div style={{ fontSize: 12 }}>
          {!databasesInstalled
            ? EMPTY_DATABASE_MESSAGE
            : run?.mode !== "taxonomy" && hasSubruns
            ? "Select a taxonomy result above to view imported rows."
            : run
              ? `${run.id} is ${run.status}.`
              : "Select a sample and run."}
        </div>
        {failed && <div style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 11 }}>{step.error || step.last_log || "No error detail returned."}</div>}
      </div>
    </Panel>
  );
}

function TaxonomyResults({ hits, filteredCount, totalCount, totalReads, filter, setFilter, search, setSearch, page, totalPages, setPage }) {
  const firstRow = filteredCount ? (page - 1) * PAGE_SIZE + 1 : 0;
  const lastRow = filteredCount ? Math.min((page - 1) * PAGE_SIZE + hits.length, filteredCount) : 0;
  return (
    <Panel title="Taxa" description="Filtered taxonomy rows. Clade and rank come from preserved Kraken lineage when available.">
      <div style={tableToolbarStyle}>
        <select className="form-control" value={filter} onChange={(event) => setFilter(event.target.value)} style={{ width: 170 }}>
          {FILTERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <input className="form-control" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search taxon, clade, taxid..." style={{ width: "min(100%, 320px)" }} />
        <span style={{ color: "var(--color-text-muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {firstRow.toLocaleString()}-{lastRow.toLocaleString()} of {filteredCount.toLocaleString()} filtered · {totalCount.toLocaleString()} total
        </span>
        <Pager page={page} totalPages={totalPages} setPage={setPage} />
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "var(--color-bg-elevated)" }}>
              <Th>Taxon</Th>
              <Th>Clade</Th>
              <Th>Rank</Th>
              <Th>Taxid</Th>
              <Th>Reads</Th>
              <Th>Abundance</Th>
              <Th>Confidence</Th>
              <Th>Evidence</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {hits.map((hit, index) => {
              const abundance = totalReads > 0 ? (hit.read_count || 0) / totalReads : 0;
              const s = support(hit);
              return (
                <tr key={hit.id || `${hit.organism}-${index}`} style={{ borderBottom: "1px solid var(--color-border-muted)" }}>
                  <Td wide>
                    <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{hit.organism}</div>
                    <div style={{ color: "var(--color-text-muted)", fontSize: 11, marginTop: 2, overflowWrap: "anywhere" }}>{lineagePreview(hit)}</div>
                  </Td>
                  <Td mono compact>{hit.top_clade || "unknown"}</Td>
                  <Td mono>{taxRank(hit)}</Td>
                  <Td mono compact>{hit.taxid || "-"}</Td>
                  <Td mono>{Number(hit.read_count || 0).toLocaleString()}</Td>
                  <Td><Abundance value={abundance} /></Td>
                  <Td compact><span className={`badge ${Number(hit.confidence || 0) >= 0.4 ? "badge-ok" : Number(hit.confidence || 0) > 0 ? "badge-warn" : "badge-err"}`}>{percent(hit.confidence)}</span></Td>
                  <Td mono compact>{percent(hit.evidence_score)}</Td>
                  <Td><span className={`badge ${s.badge}`}>{s.label}</span></Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filteredCount === 0 && (
        <div style={{ padding: 24, color: "var(--color-text-muted)", textAlign: "center", fontSize: 13 }}>No rows match this filter.</div>
      )}
      {filteredCount > 0 && (
        <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, color: "var(--color-text-muted)", fontSize: 12 }}>
          <span style={{ fontFamily: "var(--font-mono)" }}>100 rows per page · {firstRow.toLocaleString()}-{lastRow.toLocaleString()}</span>
          <Pager page={page} totalPages={totalPages} setPage={setPage} />
        </div>
      )}
    </Panel>
  );
}

function Pager({ page, totalPages, setPage }) {
  if (totalPages <= 1) return null;
  return (
    <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8 }}>
      <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage(1)}>First</Button>
      <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
      <span style={{ color: "var(--color-text-muted)", fontSize: 12, fontFamily: "var(--font-mono)" }}>{page} / {totalPages}</span>
      <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>Next</Button>
      <Button size="sm" variant="ghost" disabled={page >= totalPages} onClick={() => setPage(totalPages)}>Last</Button>
    </span>
  );
}

function lineagePreview(hit) {
  const lineage = Array.isArray(hit.lineage) ? hit.lineage.map((node) => node.name).filter(Boolean) : [];
  if (lineage.length === 0) return "";
  return lineage.slice(0, -1).slice(-4).join(" / ");
}

function Abundance({ value }) {
  const pct = value * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 116 }}>
      <div style={{ width: 58, height: 6, background: "var(--color-bg-base)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(100, pct)}%`, background: "var(--color-accent)" }} />
      </div>
      <span style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--color-text-secondary)" }}>{pct.toFixed(pct >= 1 ? 1 : 3)}%</span>
    </div>
  );
}

function Provenance({ provenance }) {
  if (!provenance) return null;
  const rows = [
    ["Event", provenance.event_type],
    ["Created", provenance.created_at ? new Date(provenance.created_at).toLocaleString() : null],
    ["Input", inputLabel(provenance.taxonomy_input_mode)],
    ["Database", compactPath(provenance.taxonomy_database || provenance.taxonomy_database_version)],
    ["Kraken report", compactPath(provenance.kraken_report_path || provenance.taxonomy_report_path)],
    ["Host BAM", compactPath(provenance.host_bam)],
    ["Host unmapped", provenance.host_unmapped_records],
    ["Recovered", provenance.recovered_from_backup ? "yes" : null],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return (
    <Panel title="Provenance">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: 10 }}>
        {rows.map(([label, value]) => <Metric key={label} label={label} value={String(value)} />)}
      </div>
    </Panel>
  );
}

function Th({ children }) {
  return (
    <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 650, fontSize: 11, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid var(--color-border-default)" }}>
      {children}
    </th>
  );
}

function Td({ children, mono, compact, wide }) {
  return (
    <td style={{ padding: "9px 12px", verticalAlign: "top", fontFamily: mono ? "var(--font-mono)" : undefined, fontSize: mono ? 12 : undefined, minWidth: wide ? 280 : compact ? 92 : undefined }}>
      {children}
    </td>
  );
}

const workspaceGrid = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
  gap: 12,
};

const newRunGrid = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
  gap: 12,
  marginTop: 14,
};

const actionBar = {
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: 8,
  marginTop: 14,
};

const advancedPanelStyle = {
  marginTop: 14,
  padding: 12,
  border: "1px solid var(--color-border-muted)",
  borderRadius: 8,
  background: "var(--color-bg-elevated)",
};

const resultsStack = {
  display: "grid",
  gap: 16,
  marginTop: 16,
  minWidth: 0,
};

const runChooserStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
  gap: 14,
  marginTop: 14,
  paddingTop: 14,
  borderTop: "1px solid var(--color-border-muted)",
};

const runGroupRowsStyle = {
  display: "flex",
  gap: 8,
  overflowX: "auto",
  paddingBottom: 3,
};

const tableToolbarStyle = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
  alignItems: "center",
  marginBottom: 12,
};

const fieldLabel = {
  fontSize: 12,
  color: "var(--color-text-secondary)",
};

const metricLabel = {
  marginBottom: 4,
  color: "var(--color-text-muted)",
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
};

const runRowStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) auto",
  gap: 8,
  alignItems: "center",
  border: "1px solid var(--color-border-muted)",
  borderRadius: 8,
  padding: 10,
  background: "var(--color-bg-elevated)",
};

const runButtonStyle = {
  display: "grid",
  gap: 5,
  minWidth: 0,
  border: 0,
  padding: 0,
  background: "transparent",
  color: "var(--color-text-primary)",
  textAlign: "left",
  cursor: "pointer",
};
