"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { Button, ConfirmDialog, PageHeader, Panel } from "@/components/ui";
import { ReferencesManager } from "@/app/references/page";

const SETTINGS_TABS = [
  { id: "overview", label: "Overview" },
  { id: "pipeline", label: "Pipeline" },
  { id: "taxonomy", label: "Taxonomy" },
  { id: "references", label: "References" },
  { id: "pgs", label: "PGS Catalog" },
  { id: "clinvar", label: "ClinVar" },
  { id: "runtime", label: "Runtime" },
  { id: "guardrails", label: "Guardrails" },
];

const settingsGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))",
  gap: 16,
};

async function fetchJson(url, options, fallback = null) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) return fallback;
    return await response.json();
  } catch {
    return fallback;
  }
}

export default function SettingsPage() {
  const [health, setHealth] = useState(null);
  const [version, setVersion] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false);
  const [pipelineSettings, setPipelineSettings] = useState(null);
  const [settingsSaving, setSettingsSaving] = useState("");
  const [taxonomyDatabases, setTaxonomyDatabases] = useState([]);
  const [installJob, setInstallJob] = useState(() => {
    try {
      if (typeof window === "undefined") return null;
      const saved = localStorage.getItem("wgs_taxonomy_install_job");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });
  const [showAddDb, setShowAddDb] = useState(false);
  const [pendingRemoveDb, setPendingRemoveDb] = useState(null);
  const [addDbForm, setAddDbForm] = useState({ name: "", description: "", path: "", url: "" });
  const [addDbLoading, setAddDbLoading] = useState(false);
  const [taxonomyDbStatus, setTaxonomyDbStatus] = useState("");
  const [pgsScores, setPgsScores] = useState(null);
  const [pgsEstimate, setPgsEstimate] = useState(null);
  const [pgsRecommended, setPgsRecommended] = useState(null);
  const [pgsJobs, setPgsJobs] = useState([]);
  const [pgsManifest, setPgsManifest] = useState(null);
  const [pgsManifestValidation, setPgsManifestValidation] = useState(null);
  const [pgsDraftManifest, setPgsDraftManifest] = useState(null);
  const [pgsBusy, setPgsBusy] = useState(false);
  const [pendingFullPgsDownload, setPendingFullPgsDownload] = useState(null);
  const [clinvarValidation, setClinvarValidation] = useState(null);
  const [clinvarResources, setClinvarResources] = useState(null);
  const [clinvarStatus, setClinvarStatus] = useState("");
  const [clinvarBusy, setClinvarBusy] = useState("");
  const [activeTab, setActiveTab] = useState("overview");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [h, v, pipe, taxDbs] = await Promise.all([
          fetch(`${API_BASE}/health`).then((r) => r.json()),
          fetch(`${API_BASE}/version`).then((r) => r.json()),
          fetch(`${API_BASE}/pipeline/settings`).then((r) => r.json()).catch(() => null),
          fetch(`${API_BASE}/data/taxonomy-databases`).then((r) => r.json()).catch(() => []),
        ]);
        setHealth(h);
        setVersion(v);
        setPipelineSettings(pipe);
        setTaxonomyDatabases(taxDbs.items || taxDbs || []);
      } catch (e) {
        console.error("Failed to load settings:", e);
      } finally {
        setLoading(false);
      }
    };
    load();
    loadCapabilities();
    loadPgsScores();
    loadPgsManifest();
    loadClinvarStatus();
  }, []);

  const loadCapabilities = async () => {
    if (capabilitiesLoading) return;
    setCapabilitiesLoading(true);
    try {
      const response = await fetch(`${API_BASE}/data/capabilities`);
      setCapabilities(response.ok ? await response.json() : null);
    } catch {
      setCapabilities(null);
    } finally {
      setCapabilitiesLoading(false);
    }
  };

  const loadPgsScores = async () => {
    const data = await fetchJson(`${API_BASE}/prs/scores`, null, { items: [] });
    setPgsScores(data);
  };

  const loadPgsJobs = async () => {
    const data = await fetchJson(`${API_BASE}/prs/catalog/download-jobs`, null, { items: [] });
    setPgsJobs(data.items || []);
  };

  const loadPgsManifest = async () => {
    const [status, validation] = await Promise.all([
      fetchJson(`${API_BASE}/prs/catalog/manifest`, null, null),
      fetchJson(`${API_BASE}/prs/catalog/manifest/validate`, null, null),
    ]);
    setPgsManifest(status);
    setPgsManifestValidation(validation || status?.validation || null);
  };

  const loadPgsCatalogMetadata = async () => {
    const [estimate, recommended] = await Promise.all([
      fetchJson(`${API_BASE}/prs/catalog/storage-estimate`, null, null),
      fetchJson(`${API_BASE}/prs/catalog/recommended`, null, null),
      loadPgsJobs(),
    ]);
    setPgsEstimate(estimate);
    setPgsRecommended(recommended);
  };

  const loadPgsDraftManifest = async () => {
    const draft = await fetchJson(`${API_BASE}/prs/catalog/draft-manifest?limit=50`, null, null);
    setPgsDraftManifest(draft);
  };

  const downloadPgsBatch = async (limit, force = false) => {
    setPgsBusy(true);
    await fetchJson(`${API_BASE}/prs/catalog/download-all`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit, retry_count: 3, force }),
    });
    await Promise.all([loadPgsJobs(), loadPgsScores()]);
    setPgsBusy(false);
  };

  const downloadFullPgsCatalog = async (force = false) => {
    if (!pendingFullPgsDownload) {
      setPendingFullPgsDownload({ force });
      return;
    }
    setPendingFullPgsDownload(null);
    return downloadPgsBatch(0, force);
  };

  const loadClinvarStatus = async () => {
    const [resources, validation] = await Promise.all([
      fetchJson(`${API_BASE}/interpretation/resources`, null, null),
      fetchJson(`${API_BASE}/interpretation/resources/clinvar/validate`, null, null),
    ]);
    setClinvarResources(resources);
    setClinvarValidation(validation);
  };

  const installClinvar = async () => {
    setClinvarBusy("install");
    setClinvarStatus("");
    const data = await fetchJson(`${API_BASE}/interpretation/resources/clinvar/install`, { method: "POST" }, null);
    setClinvarStatus(data?.status || data?.message || "ClinVar install request finished");
    await loadClinvarStatus();
    setClinvarBusy("");
  };

  const buildClinvarTsv = async () => {
    setClinvarBusy("build");
    setClinvarStatus("");
    const data = await fetchJson(`${API_BASE}/interpretation/resources/clinvar/build-tsv`, { method: "POST" }, null);
    setClinvarStatus(data?.status || data?.message || "ClinVar TSV build request finished");
    await loadClinvarStatus();
    setClinvarBusy("");
  };

  useEffect(() => {
    try {
      if (installJob && installJob.status !== "done" && installJob.status !== "error") {
        localStorage.setItem("wgs_taxonomy_install_job", JSON.stringify(installJob));
      } else {
        localStorage.removeItem("wgs_taxonomy_install_job");
      }
    } catch {}
  }, [installJob]);

  useEffect(() => {
    if (!installJob || installJob.status === "done" || installJob.status === "error") return;
    const interval = setInterval(() => {
      fetch(`${API_BASE}/data/taxonomy-databases/install/${installJob.job_id}`)
        .then(async (response) => {
          if (!response.ok) throw new Error(response.status === 404 ? "Install job disappeared after API restart" : `Install status failed (${response.status})`);
          return response.json();
        })
        .then((data) => {
          setInstallJob((previous) => ({ ...(previous || {}), ...data }));
          if (data.status === "done" || data.status === "error") {
            fetchTaxonomyDatabases();
          }
        })
        .catch((error) => {
          setInstallJob((previous) => ({ ...(previous || {}), status: "error", error: error.message }));
        });
    }, 3000);
    return () => clearInterval(interval);
  }, [installJob?.job_id, installJob?.status]);

  const fetchTaxonomyDatabases = async () => {
    const response = await fetch(`${API_BASE}/data/taxonomy-databases`);
    const data = await response.json();
    setTaxonomyDatabases(data.items || data || []);
  };

  const updateBackend = async (stage, backend) => {
    setSettingsSaving(stage);
    try {
      const res = await fetch(`${API_BASE}/pipeline/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backends: { [stage]: backend } }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Settings update failed");
      setPipelineSettings(data);
    } catch (e) {
      console.error(e);
    } finally {
      setSettingsSaving("");
    }
  };

  const updatePipelineSettings = async (label, patch) => {
    setSettingsSaving(label);
    try {
      const res = await fetch(`${API_BASE}/pipeline/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Settings update failed");
      setPipelineSettings(data);
    } catch (e) {
      console.error(e);
    } finally {
      setSettingsSaving("");
    }
  };

  const handleInstallTaxonomyDb = async (dbId) => {
    setTaxonomyDbStatus("");
    setInstallJob({ db_id: dbId, status: "starting", progress: 0 });
    try {
      const response = await fetch(`${API_BASE}/data/taxonomy-databases/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ database: dbId }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        if (detail?.code === "taxonomy_database_insufficient_storage") {
          const storage = detail.storage || {};
          throw new Error(`Not enough disk: needs ${formatBytes(storage.required_bytes)}, free ${formatBytes(storage.free_bytes)}`);
        }
        throw new Error(typeof detail === "string" ? detail : detail?.message || detail?.code || `Install failed (${response.status})`);
      }
      setInstallJob({ ...data, db_id: dbId });
    } catch (error) {
      setInstallJob({ db_id: dbId, status: "error", error: error.message });
    }
  };

  const handleAddTaxonomyDb = async () => {
    if (!addDbForm.name.trim()) return;
    setAddDbLoading(true);
    setTaxonomyDbStatus("");
    try {
      const response = await fetch(`${API_BASE}/data/taxonomy-databases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: addDbForm.name.trim(),
          description: addDbForm.description.trim() || "Custom/proprietary database",
          path: addDbForm.path.trim() || null,
          url: addDbForm.url.trim() || null,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || data.detail?.code || `Add failed (${response.status})`);
      setShowAddDb(false);
      setAddDbForm({ name: "", description: "", path: "", url: "" });
      setTaxonomyDbStatus("Database registered");
      await fetchTaxonomyDatabases();
    } catch (error) {
      setTaxonomyDbStatus(`Error: ${error.message}`);
    } finally {
      setAddDbLoading(false);
    }
  };

  const handleRemoveTaxonomyDb = async (db) => {
    setPendingRemoveDb(null);
    setTaxonomyDbStatus("");
    try {
      const response = await fetch(`${API_BASE}/data/taxonomy-databases/${db.id}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || data.detail?.code || `Remove failed (${response.status})`);
      }
      setTaxonomyDbStatus(`Removed ${db.name || db.id}`);
      await fetchTaxonomyDatabases();
    } catch (error) {
      setTaxonomyDbStatus(`Error: ${error.message}`);
    }
  };

  if (loading) {
    return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading settings…</div>;
  }

  return (
    <div>
      <PageHeader
        eyebrow="System"
        title="Settings"
        description="System configuration, runtime capabilities, pipeline safety, and connection status."
      />

      <SettingsTabs activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <div style={settingsGridStyle}>
          <ApiConnectionPanel health={health} version={version} />
          <DeploymentPanel pipelineSettings={pipelineSettings} />
        </div>
      )}

      {activeTab === "pipeline" && (
        <div style={settingsGridStyle}>
          <PipelineBackendsPanel
            capabilities={capabilities}
            pipelineSettings={pipelineSettings}
            settingsSaving={settingsSaving}
            onUpdateBackend={updateBackend}
          />
          <PipelineSafetyPanel
            pipelineSettings={pipelineSettings}
            settingsSaving={settingsSaving}
            onUpdatePipelineSettings={updatePipelineSettings}
          />
        </div>
      )}

      {activeTab === "taxonomy" && (
        <div style={settingsGridStyle}>
          <TaxonomyDatabaseManager
            databases={taxonomyDatabases}
            installJob={installJob}
            status={taxonomyDbStatus}
            onInstall={handleInstallTaxonomyDb}
            onAdd={() => setShowAddDb(true)}
            onRemove={(db) => setPendingRemoveDb(db)}
          />
        </div>
      )}

      {activeTab === "references" && <ReferencesManager embedded />}

      {activeTab === "pgs" && (
        <PgsCatalogPanel
          scores={pgsScores}
          estimate={pgsEstimate}
          recommended={pgsRecommended}
          jobs={pgsJobs}
          manifest={pgsManifest}
          manifestValidation={pgsManifestValidation}
          draftManifest={pgsDraftManifest}
          busy={pgsBusy}
          onLoadMetadata={loadPgsCatalogMetadata}
          onRefreshScores={loadPgsScores}
          onRefreshManifest={loadPgsManifest}
          onLoadDraft={loadPgsDraftManifest}
          onDownloadNext={() => downloadPgsBatch(200, false)}
          onDownloadAll={() => downloadFullPgsCatalog(false)}
          onForceRetry={() => downloadPgsBatch(200, true)}
        />
      )}

      {activeTab === "clinvar" && (
        <ClinvarSettingsPanel
          resources={clinvarResources}
          validation={clinvarValidation}
          status={clinvarStatus}
          busy={clinvarBusy}
          onRefresh={loadClinvarStatus}
          onInstall={installClinvar}
          onBuild={buildClinvarTsv}
        />
      )}

      {activeTab === "runtime" && (
        <div style={settingsGridStyle}>
          <ComputeResourcesPanel
            capabilities={capabilities}
            capabilitiesLoading={capabilitiesLoading}
            pipelineSettings={pipelineSettings}
            onLoadCapabilities={loadCapabilities}
          />
          <ToolVersions details={capabilities?.tool_details || {}} />
        </div>
      )}

      {activeTab === "guardrails" && (
        <div style={settingsGridStyle}>
          <ResearchOnlyPanel />
        </div>
      )}

      {showAddDb && (
        <div className="modal-backdrop" onClick={() => setShowAddDb(false)}>
          <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header"><h2>Add Taxonomy Database</h2></div>
            <p className="modal-description">
              Register a custom Kraken2/Bracken database by server path or download URL.
            </p>
            <div style={{ display: "grid", gap: 14, marginTop: 16 }}>
              <SettingInput label="Database name" value={addDbForm.name} onChange={(value) => setAddDbForm({ ...addDbForm, name: value })} placeholder="e.g. Standard PlusPF" />
              <SettingInput label="Description" value={addDbForm.description} onChange={(value) => setAddDbForm({ ...addDbForm, description: value })} placeholder="Short label for users" />
              <SettingInput label="Local path on server" value={addDbForm.path} onChange={(value) => setAddDbForm({ ...addDbForm, path: value })} placeholder="/data/databases/kraken2_custom" />
              <SettingInput label="Download URL" value={addDbForm.url} onChange={(value) => setAddDbForm({ ...addDbForm, url: value })} placeholder="https://example.com/kraken2_db.tar.gz" />
            </div>
            <div className="modal-actions">
              <Button variant="ghost" onClick={() => setShowAddDb(false)}>Cancel</Button>
              <Button variant="primary" disabled={!addDbForm.name.trim() || addDbLoading} onClick={handleAddTaxonomyDb}>
                {addDbLoading ? "Adding..." : "Add Database"}
              </Button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!pendingRemoveDb}
        title={`Remove ${pendingRemoveDb?.name || pendingRemoveDb?.id || "taxonomy database"}?`}
        description="This removes the local database registration/files for future taxonomy runs. Existing taxonomy results stay in run history."
        details={[
          "Current active downloads are left untouched.",
          "Runs that need this database will be blocked until it is installed again.",
        ]}
        confirmLabel="Remove database"
        onCancel={() => setPendingRemoveDb(null)}
        onConfirm={() => handleRemoveTaxonomyDb(pendingRemoveDb)}
      />

      <ConfirmDialog
        open={!!pendingFullPgsDownload}
        title="Download full PGS Catalog?"
        description="This starts a full PGS Catalog fetch and may run for a long time depending on network and storage speed."
        details={[
          `Estimated total storage: ~${pgsEstimate?.estimated_total_gb || "?"} GB.`,
          `Estimated remaining storage: ~${pgsEstimate?.estimated_remaining_gb || "?"} GB.`,
          "Existing downloaded score files are reused unless force mode is enabled.",
        ]}
        confirmLabel="Start full download"
        tone="warning"
        busy={pgsBusy}
        onCancel={() => setPendingFullPgsDownload(null)}
        onConfirm={() => downloadFullPgsCatalog(pendingFullPgsDownload.force)}
      />
    </div>
  );
}

function SettingsTabs({ activeTab, onChange }) {
  return (
    <div className="segmented-control" style={{ marginBottom: 16, width: "fit-content", maxWidth: "100%", flexWrap: "wrap" }}>
      {SETTINGS_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`segmented-button ${activeTab === tab.id ? "active" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function ApiConnectionPanel({ health, version }) {
  return (
    <Panel title="API Connection">
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <SettingsRow label="API Base URL" value={API_BASE} mono />
        <SettingsRow label="Status" value={health?.ok ? "Connected" : "Disconnected"} color={health?.ok ? "ok" : "err"} />
        <SettingsRow label="Version" value={version?.version || "—"} mono />
        <SettingsRow
          label="DB schema"
          value={version?.database_schema?.schema_version || "memory-only"}
          color={version?.database_schema?.ok === false ? "err" : "ok"}
          mono
        />
        <SettingsRow label="Timestamp" value={health?.ts ? new Date(health.ts).toLocaleString() : "—"} />
      </div>
    </Panel>
  );
}

function DeploymentPanel({ pipelineSettings }) {
  const [mode, setMode] = useState(() => {
    if (typeof window === "undefined") return "local";
    return localStorage.getItem("wgs_deployment_mode") || "local";
  });
  const [remote, setRemote] = useState(() => {
    if (typeof window === "undefined") return { host: "", auth: "ssh_key" };
    try {
      return JSON.parse(localStorage.getItem("wgs_remote_deployment") || "{}");
    } catch {
      return { host: "", auth: "ssh_key" };
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem("wgs_deployment_mode", mode);
      localStorage.setItem("wgs_remote_deployment", JSON.stringify(remote));
    } catch {}
  }, [mode, remote]);

  return (
    <Panel title="Deployment">
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="segmented-control" style={{ width: "fit-content" }}>
          {["local", "remote"].map((item) => (
            <button key={item} type="button" className={`segmented-button ${mode === item ? "active" : ""}`} onClick={() => setMode(item)}>
              {item}
            </button>
          ))}
        </div>
        <SettingsRow label="Frontend" value="Current browser host" />
        <SettingsRow label="API / Worker" value={API_BASE} mono />
        {mode === "remote" && (
          <div style={{ display: "grid", gap: 8 }}>
            <SettingInput label="Remote host / IP" value={remote.host || ""} onChange={(value) => setRemote({ ...remote, host: value })} placeholder="192.168.x.x or hostname" />
            <label style={{ display: "grid", gap: 5 }}>
              <span style={settingLabel}>Authorization</span>
              <select className="form-control" value={remote.auth || "ssh_key"} onChange={(event) => setRemote({ ...remote, auth: event.target.value })}>
                <option value="ssh_key">SSH key</option>
                <option value="token">Token</option>
                <option value="manual">Manual approval</option>
              </select>
            </label>
          </div>
        )}
        <SettingsRow
          label="Pipeline executor"
          value={pipelineSettings?.executor_policy?.effective_executor || "api_thread"}
          color={pipelineSettings?.executor_policy?.effective_executor === "worker_queue" ? "accent" : "warn"}
        />
        <SettingsRow label="Default decision" value={pipelineSettings?.executor_policy?.default_decision || "api_thread remains default until worker_queue real-run validation"} />
        <SettingsRow label="Theme" value="Obsidian Dark" />
      </div>
    </Panel>
  );
}

function ComputeResourcesPanel({ capabilities, capabilitiesLoading, pipelineSettings, onLoadCapabilities }) {
  return (
    <Panel title="Compute Resources">
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button size="sm" variant="secondary" onClick={onLoadCapabilities} disabled={capabilitiesLoading}>
            {capabilitiesLoading ? "Loading..." : capabilities ? "Refresh runtime capabilities" : "Load runtime capabilities"}
          </Button>
        </div>
        <SettingsRow label="CPU" value={capabilities?.cpu?.model_name || "—"} />
        <SettingsRow label="Threads" value={capabilities?.cpu?.threads ?? "—"} mono />
        <SettingsRow label="RAM" value={capabilities?.ram?.total_bytes ? `${(capabilities.ram.total_bytes / 1024 ** 3).toFixed(1)} GB` : "—"} mono />
        <SettingsRow label="Recommended profile" value={capabilities?.compute?.recommended_profile || "auto"} color="accent" />
        <SettingsRow label="GPU" value={capabilities?.gpu?.available ? "Detected" : "Not detected"} color={capabilities?.gpu?.available ? "ok" : "warn"} />
        <SettingsRow label="Effective plan" value={pipelineSettings?.resource_plan?.effective_profile || "—"} color="accent" />
        <SettingsRow label="Pipeline threads" value={pipelineSettings?.resource_plan?.threads ?? "—"} mono />
        <SettingsRow label="Thread source" value={pipelineSettings?.resource_plan?.threads_source || "—"} />
      </div>
    </Panel>
  );
}

function PipelineBackendsPanel({ capabilities, pipelineSettings, settingsSaving, onUpdateBackend }) {
  return (
    <Panel title="Pipeline Backends" description={!capabilities ? "Runtime capabilities are loading; backend availability will update automatically." : undefined}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {backendGroups(capabilities, pipelineSettings).map((group) => (
          <BackendChooser key={group.step} group={group} saving={settingsSaving === group.stage} onChange={(backend) => onUpdateBackend(group.stage, backend)} />
        ))}
      </div>
    </Panel>
  );
}

function PipelineSafetyPanel({ pipelineSettings, settingsSaving, onUpdatePipelineSettings }) {
  return (
    <Panel title="Pipeline Safety">
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <NumberSetting
          label="Markdup free-space floor"
          suffix="GB"
          value={pipelineSettings?.settings?.disk_pressure?.min_free_gb_before_markdup ?? 120}
          saving={settingsSaving === "disk_pressure"}
          onSave={(value) => onUpdatePipelineSettings("disk_pressure", { disk_pressure: { min_free_gb_before_markdup: value } })}
        />
        <NumberSetting
          label="Alignment peak multiplier"
          suffix="x FASTQ"
          step="0.5"
          value={pipelineSettings?.settings?.disk_pressure?.alignment_peak_multiplier ?? 5}
          saving={settingsSaving === "disk_pressure"}
          onSave={(value) => onUpdatePipelineSettings("disk_pressure", { disk_pressure: { alignment_peak_multiplier: value } })}
        />
        <TextSetting
          label="Scratch/offload root"
          value={pipelineSettings?.settings?.disk_pressure?.scratch_root || ""}
          placeholder="/data/scratch or mounted external disk"
          saving={settingsSaving === "disk_pressure"}
          onSave={(value) => onUpdatePipelineSettings("disk_pressure", { disk_pressure: { scratch_root: value } })}
        />
        <ToggleSetting
          label="Block start if estimate exceeds free space"
          value={Boolean(pipelineSettings?.settings?.disk_pressure?.block_start_when_estimate_exceeds_free)}
          saving={settingsSaving === "disk_pressure"}
          onSave={(value) => onUpdatePipelineSettings("disk_pressure", { disk_pressure: { block_start_when_estimate_exceeds_free: value } })}
        />
        <SelectSetting
          label="Default taxonomy route"
          value={pipelineSettings?.settings?.taxonomy?.default_route || "human_wgs_host_depleted"}
          options={taxonomyRouteOptions(pipelineSettings)}
          saving={settingsSaving === "taxonomy"}
          onSave={(value) => onUpdatePipelineSettings("taxonomy", { taxonomy: { default_route: value } })}
        />
        <NumberSetting
          label="Sensitive taxonomy MAPQ"
          value={pipelineSettings?.settings?.taxonomy?.low_mapq_threshold ?? 10}
          saving={settingsSaving === "taxonomy"}
          onSave={(value) => onUpdatePipelineSettings("taxonomy", { taxonomy: { low_mapq_threshold: value } })}
        />
      </div>
    </Panel>
  );
}

function ResearchOnlyPanel() {
  return (
    <Panel title="Research Only" style={{ borderLeft: "3px solid var(--color-warn)" }}>
      <div style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.6 }}>
        <p style={{ margin: "0 0 12px" }}>
          This system is designed for <strong>research-only</strong> whole genome sequencing analysis.
          It is <strong>not</strong> a medical device and must <strong>not</strong> be used for clinical diagnostics.
        </p>
        <p style={{ margin: "0 0 12px" }}>
          All results are labeled "non-diagnostic" and trust scores are technical quality indicators,
          not clinical confidence measures.
        </p>
        <p style={{ margin: 0 }}>
          Variant annotations, PRS scores, and taxonomy classifications are for research exploration only.
        </p>
      </div>
    </Panel>
  );
}

function SettingsRow({ label, value, mono, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
      <span style={{ fontSize: 13, color: "var(--color-text-secondary)", flex: "0 0 auto" }}>{label}</span>
      <span
        style={{
          fontSize: 13,
          fontFamily: mono ? "var(--font-mono)" : undefined,
          color: color ? `var(--color-${color})` : "var(--color-text-primary)",
          minWidth: 0,
          textAlign: "right",
          overflowWrap: "anywhere",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function taxonomyRouteOptions(pipelineSettings) {
  const routes = pipelineSettings?.taxonomy_routes || {};
  const entries = Object.entries(routes);
  if (entries.length === 0) {
    return [
      ["human_wgs_host_depleted", "Human WGS host-depleted"],
      ["human_wgs_sensitive_low_mapq", "Sensitive human WGS"],
      ["full_fastq_shotgun", "Full FASTQ shotgun"],
      ["custom_host_depletion", "Custom host depletion"],
    ];
  }
  return entries.map(([id, item]) => [id, item.label || id]);
}

function TaxonomyDatabaseManager({ databases, installJob, status, onInstall, onAdd, onRemove }) {
  const activeInstall = installJob && installJob.status !== "done" && installJob.status !== "error";
  return (
    <Panel
      title="Taxonomy Databases"
      description="Install and register Kraken2 databases here. The Taxonomy page only selects from installed databases."
      actions={<Button variant="primary" size="sm" onClick={onAdd}>Add Database</Button>}
    >
      <div style={{ display: "grid", gap: 10 }}>
        {databases.length === 0 && (
          <div style={{ color: "var(--color-text-muted)", fontSize: 13 }}>
            No taxonomy databases are registered.
          </div>
        )}
        {databases.map((db) => {
          const storage = db.storage_preflight || {};
          const storageBlocked = storage.ok === false;
          const installingThis = installJob?.db_id === db.id && activeInstall;
          const installError = installJob?.db_id === db.id && installJob?.status === "error";
          return (
            <div
              key={db.id}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 10,
                alignItems: "center",
                padding: 12,
                borderRadius: 8,
                background: "var(--color-bg-elevated)",
                border: "1px solid var(--color-border-muted)",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 13 }}>{db.name}</strong>
                  <span style={{ color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{db.id}</span>
                  <span className={`badge ${db.installed ? "badge-ok" : installError || storageBlocked ? "badge-err" : installingThis ? "badge-info" : "badge-warn"}`}>
                    {db.installed
                      ? "installed"
                      : installError
                        ? "error"
                        : installingThis
                          ? installProgressLabel(installJob)
                          : storageBlocked
                            ? "not enough disk"
                            : "not installed"}
                  </span>
                </div>
                <div style={{ marginTop: 5, color: "var(--color-text-secondary)", fontSize: 12, overflowWrap: "anywhere" }}>
                  {db.description || "Kraken2 database"}
                </div>
                <div style={{ marginTop: 5, color: storageBlocked ? "var(--color-err)" : "var(--color-text-muted)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                  archive {db.archive_size_gb || "?"} GB · needs {formatBytes(storage.required_bytes)} · free {formatBytes(storage.free_bytes)}
                </div>
                {installError && (
                  <div style={{ marginTop: 5, color: "var(--color-err)", fontSize: 11, overflowWrap: "anywhere" }}>
                    {installJob.error || "Install failed"}
                  </div>
                )}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
                {db.installed ? (
                  <Button variant="danger" size="sm" onClick={() => onRemove(db)}>Remove</Button>
                ) : (
                  <Button
                    variant={installError ? "warning" : "secondary"}
                    size="sm"
                    disabled={activeInstall || storageBlocked}
                    onClick={() => onInstall(db.id)}
                  >
                    {installError ? "Retry" : "Install"}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {status && (
        <div style={{ marginTop: 10, color: status.startsWith("Error") ? "var(--color-err)" : "var(--color-accent)", fontSize: 12 }}>
          {status}
        </div>
      )}
    </Panel>
  );
}

function PgsCatalogPanel({
  scores,
  estimate,
  recommended,
  jobs,
  manifest,
  manifestValidation,
  draftManifest,
  busy,
  onLoadMetadata,
  onRefreshScores,
  onRefreshManifest,
  onLoadDraft,
  onDownloadNext,
  onDownloadAll,
  onForceRetry,
}) {
  const scoreCount = scores?.items?.length || 0;
  const validation = manifestValidation || manifest?.validation || {};
  const manifestValid = Boolean(validation?.valid);
  const activeJob = (jobs || []).find((job) => ["queued", "discovering", "running"].includes(job.status)) || (jobs || [])[0];
  const draftItems = draftManifest?.items || [];
  return (
    <div style={settingsGridStyle}>
      <Panel
        title="PGS Catalog Resources"
        description={<>Downloaded score files: <b>{scoreCount}</b>. Stored under <code>/data/references/pgs</code>.</>}
        actions={
          <>
            <Button variant="primary" onClick={onDownloadNext} disabled={busy}>Download next 200</Button>
            <Button variant="secondary" onClick={onDownloadAll} disabled={busy}>Download all...</Button>
            <Button variant="secondary" onClick={onForceRetry} disabled={busy}>Force retry next 200</Button>
            <Button variant="ghost" onClick={onRefreshScores}>Refresh</Button>
            <Button variant="ghost" onClick={onLoadMetadata}>Catalog status</Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: 10 }}>
          <SettingsRow label="Score files" value={`${scoreCount} downloaded`} color={scoreCount ? "ok" : "warn"} />
          <SettingsRow label="Full catalog estimate" value={estimate ? `~${estimate.estimated_total_gb} GB total, ~${estimate.estimated_remaining_gb} GB remaining` : "load on demand"} />
          <SettingsRow label="Recommended coverage" value={recommended ? `${recommended.count} scores / ${Object.keys(recommended.categories || {}).length} categories` : "load on demand"} />
          {activeJob && <SettingsRow label="Download job" value={`${activeJob.status || "unknown"} ${activeJob.progress_pct ?? activeJob.progress ?? ""}%`} color={activeJob.status === "error" ? "err" : "accent"} />}
        </div>
      </Panel>

      <Panel
        title="Curated PRS Manifest"
        description="Approved panels must be curated, cited, overlap-gated, ancestry-caveated, and compatible with the sample reference build."
        actions={
          <>
            <Button variant="secondary" onClick={onRefreshManifest}>Refresh manifest</Button>
            <Button variant="ghost" onClick={onLoadDraft}>Load draft preview</Button>
            <a className="btn btn-ghost btn-md" href={`${API_BASE}/prs/catalog/draft-manifest.tsv?limit=500`} target="_blank" rel="noreferrer">Draft TSV</a>
          </>
        }
      >
        <div style={{ display: "grid", gap: 10 }}>
          <SettingsRow label="Manifest" value={manifestValid ? "valid" : validation?.status || manifest?.status || "missing"} color={manifestValid ? "ok" : "warn"} />
          <SettingsRow label="Curated entries" value={validation?.count ?? manifest?.count ?? 0} color={manifestValid ? "ok" : "warn"} />
          <SettingsRow label="Trait categories" value={Object.keys(validation?.categories || manifest?.categories || {}).length} color={manifestValid ? "ok" : "warn"} />
          <SettingsRow label="Genome builds" value={Object.keys(validation?.genome_builds || {}).length ? Object.entries(validation.genome_builds).map(([k, v]) => `${k}:${v}`).join(", ") : "none"} />
          <SettingsRow label="Configured path" value={validation?.path || manifest?.path || "not configured"} mono />
          <SettingsRow label="Draft candidates" value={draftManifest?.count ?? 0} color={draftItems.length ? "warn" : "ok"} />
        </div>
      </Panel>
    </div>
  );
}

function ClinvarSettingsPanel({ resources, validation, status, busy, onRefresh, onInstall, onBuild }) {
  const pipeline = resources?.modules?.clinvar_monogenic?.pipeline || {};
  const ready = Boolean(resources?.status?.clinvar_tsv || validation?.valid);
  return (
    <div style={settingsGridStyle}>
      <Panel
        title="ClinVar Resources"
        description="Manage the local ClinVar VCF and exact-match TSV used by Full ClinVar. Fast ClinVar Screening also needs build-matched target loci."
        actions={
          <>
            <Button variant="secondary" onClick={onRefresh} disabled={!!busy}>Refresh</Button>
            <Button variant="primary" onClick={onInstall} disabled={!!busy}>{busy === "install" ? "Installing..." : "Download ClinVar VCF"}</Button>
            <Button variant="secondary" onClick={onBuild} disabled={!!busy}>{busy === "build" ? "Building..." : "Build exact TSV"}</Button>
          </>
        }
      >
        <div style={{ display: "grid", gap: 10 }}>
          <SettingsRow label="Exact-match TSV" value={ready ? "available" : "missing"} color={ready ? "ok" : "warn"} />
          <SettingsRow label="Validation" value={validation?.status || (validation?.valid ? "valid" : "not validated")} color={validation?.valid ? "ok" : "warn"} />
          <SettingsRow label="Rows" value={validation?.rows ?? validation?.count ?? "—"} mono />
          <SettingsRow label="Path" value={validation?.path || pipeline?.tsv_path || "not configured"} mono />
          <SettingsRow label="VCF" value={pipeline?.vcf_path || "not configured"} mono />
          <SettingsRow label="Build note" value="BAM/reference build must match ClinVar coordinates (GRCh38 vs GRCh37 matters)." />
          {status && <SettingsRow label="Last action" value={status} color={status.toLowerCase().includes("error") ? "err" : "accent"} />}
        </div>
      </Panel>

      <Panel title="ClinVar Availability">
        <div style={{ display: "grid", gap: 10 }}>
          <SettingsRow label="Full ClinVar" value={ready ? "resource ready; variants stage still required" : "SOON / resource missing"} color={ready ? "accent" : "warn"} />
          <SettingsRow label="Fast ClinVar Screening" value="targeted BAM screen after alignment" color="accent" />
          <SettingsRow label="Clinical meaning" value="screening only; not a clinical negative result" color="warn" />
        </div>
      </Panel>
    </div>
  );
}

function installProgressLabel(job) {
  if (job.status === "downloading") return `downloading ${job.progress_pct ?? job.progress ?? 0}%`;
  if (job.status === "starting") return "starting";
  if (job.status === "extracting") return "extracting";
  return job.status || "working";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
}

function SettingInput({ label, value, onChange, placeholder }) {
  return (
    <label style={{ display: "grid", gap: 5 }}>
      <span style={settingLabel}>{label}</span>
      <input className="form-control" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function NumberSetting({ label, value, suffix, step = "1", saving, onSave }) {
  const [draft, setDraft] = useState(String(value ?? ""));
  useEffect(() => setDraft(String(value ?? "")), [value]);
  return (
    <div style={settingControlWrap}>
      <label style={settingLabel}>{label}</label>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          type="number"
          step={step}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          className="form-control"
          style={{ width: 92 }}
          disabled={saving}
        />
        {suffix && <span style={{ fontSize: 11, color: "var(--color-text-muted)", minWidth: 54 }}>{suffix}</span>}
        <Button size="sm" variant="primary" disabled={saving} onClick={() => onSave(Number(draft))}>{saving ? "..." : "Save"}</Button>
      </div>
    </div>
  );
}

function TextSetting({ label, value, placeholder, saving, onSave }) {
  const [draft, setDraft] = useState(value || "");
  useEffect(() => setDraft(value || ""), [value]);
  return (
    <div style={settingControlWrap}>
      <label style={settingLabel}>{label}</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          value={draft}
          placeholder={placeholder}
          onChange={(event) => setDraft(event.target.value)}
          className="form-control"
          style={{ flex: 1, minWidth: 0 }}
          disabled={saving}
        />
        <Button size="sm" variant="primary" disabled={saving} onClick={() => onSave(draft)}>{saving ? "..." : "Save"}</Button>
      </div>
    </div>
  );
}

function ToggleSetting({ label, value, saving, onSave }) {
  return (
    <label style={{ ...settingControlWrap, flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <span style={settingLabel}>{label}</span>
      <input type="checkbox" checked={value} disabled={saving} onChange={(event) => onSave(event.target.checked)} />
    </label>
  );
}

function SelectSetting({ label, value, options, saving, onSave }) {
  return (
    <div style={settingControlWrap}>
      <label style={settingLabel}>{label}</label>
      <select value={value} disabled={saving} onChange={(event) => onSave(event.target.value)} className="form-control">
        {options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}
      </select>
    </div>
  );
}

const PRIMARY_TOOL_ORDER = [
  "minimap2",
  "bwa-mem2",
  "bwa",
  "samtools",
  "mosdepth",
  "bcftools",
  "kraken2",
  "gatk",
  "deepvariant",
  "cnvkit.py",
  "delly",
];

function ToolVersions({ details }) {
  const entries = PRIMARY_TOOL_ORDER.map((name) => [name, details?.[name]]).filter(([, item]) => item);
  return (
    <Panel title="Runtime Tool Inventory">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {entries.map(([name, item]) => (
          <div
            key={name}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(92px, 0.8fr) minmax(82px, 1.2fr) minmax(0, 2fr)",
              gap: 8,
              alignItems: "center",
              padding: "8px 10px",
              borderRadius: 8,
              background: "var(--color-bg-elevated)",
              fontSize: 12,
            }}
          >
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-primary)" }}>{name}</span>
            <span className={`badge ${item.installed ? "badge-ok" : "badge-warn"}`}>{item.installed ? "installed" : "missing"}</span>
            <span
              title={item.path || item.version_probe || ""}
              style={{
                minWidth: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: item.version ? "var(--color-text-secondary)" : "var(--color-text-muted)",
                fontFamily: item.version ? "var(--font-mono)" : undefined,
              }}
            >
              {toolVersionLabel(item)}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function toolVersionLabel(item) {
  if (item.version) return item.version;
  if (!item.installed) return "not installed";
  if (item.version_probe === "timeout") return "version probe timed out";
  if (item.version_probe?.startsWith("error:")) return item.version_probe.replace("error:", "probe error: ");
  if (item.version_probe?.startsWith("empty:")) return `no version output (${item.version_probe.replace("empty:", "exit ")})`;
  return item.version_probe || "not probed";
}

const settingControlWrap = {
  display: "flex",
  flexDirection: "column",
  gap: 5,
  padding: 10,
  borderRadius: 8,
  background: "var(--color-bg-elevated)",
};

const settingLabel = {
  fontSize: 12,
  color: "var(--color-text-secondary)",
};

function backendGroups(capabilities, pipelineSettings) {
  const tools = capabilities?.tools || {};
  const selected = pipelineSettings?.settings?.backends || {};
  const allowed = pipelineSettings?.backend_options || {};
  const backendStatus = pipelineSettings?.backend_status || {};
  const installed = (name) => {
    if (name === "bwa-mem2") {
      return Boolean(tools["bwa-mem2"] || tools["bwa-mem2.avx512"] || tools["bwa-mem2.avx2"] || tools["bwa-mem2.sse42"] || tools["bwa-mem2.sse41"]);
    }
    return Boolean(tools[name]);
  };
  const alignmentOption = (name) => {
    const status = backendStatus?.alignment?.[name] || null;
    return {
      name,
      label: name,
      installed: name === "auto" || Boolean(status?.installed) || installed(name),
      recommended: name === "minimap2",
      requiresReferenceIndex: Boolean(status?.requires_reference_index),
      status,
    };
  };
  return [
    {
      stage: "alignment",
      step: "Alignment",
      selected: selected.alignment || "auto",
      note: "auto uses minimap2 when available; bwa and bwa-mem2 require matching reference indexes",
      options: (allowed.alignment || ["auto", "minimap2", "bwa", "bwa-mem2"]).map(alignmentOption),
    },
    {
      stage: "coverage",
      step: "Coverage / QC",
      selected: selected.coverage || "mosdepth",
      note: "coverage and callable-region summaries",
      options: [{ name: "mosdepth", label: "mosdepth", installed: installed("mosdepth"), recommended: true }],
    },
    {
      stage: "variants",
      step: "SNV / Indel",
      selected: selected.variants || "bcftools",
      note: "bcftools is light; GATK and DeepVariant stay optional for heavier hosts or remote workers",
      options: [
        { name: "bcftools", label: "bcftools", installed: installed("bcftools"), recommended: true },
        { name: "gatk", label: "GATK HaplotypeCaller", installed: installed("gatk"), recommended: false },
        { name: "deepvariant", label: "DeepVariant", installed: installed("deepvariant"), recommended: false },
      ],
    },
    {
      stage: "sv",
      step: "SV",
      selected: selected.sv || "auto",
      note: "structural-variant callers can be added without changing the pipeline contract",
      options: [
        { name: "manta", label: "Manta", installed: installed("manta") || installed("configManta.py"), recommended: true },
        { name: "delly", label: "Delly", installed: installed("delly"), recommended: false },
      ],
    },
    {
      stage: "cnv",
      step: "CNV",
      selected: selected.cnv || "auto",
      note: "CNVkit is preferred when installed; otherwise the step remains explicit",
      options: [{ name: "cnvkit", label: "CNVkit", installed: installed("cnvkit") || installed("cnvkit.py"), recommended: true }],
    },
    {
      stage: "taxonomy",
      step: "Taxonomy",
      selected: selected.taxonomy || "kraken2",
      note: "host-depleted or shotgun classification backend",
      options: (allowed.taxonomy || ["kraken2"]).map((name) => ({ name, label: name === "kraken2" ? "Kraken2" : name, installed: installed(name), recommended: name === "kraken2" })),
    },
    {
      stage: "mtdna",
      step: "mtDNA",
      selected: selected.mtdna || "gatk",
      note: "mitochondrial variant extraction/calling",
      options: (allowed.mtdna || ["gatk"]).map((name) => ({ name, label: name === "gatk" ? "GATK Mutect2" : name, installed: installed(name), recommended: name === "gatk" })),
    },
    {
      stage: "prs",
      step: "PRS",
      selected: selected.prs || "auto",
      note: "requires curated, versioned score manifests before producing results",
      options: (allowed.prs || ["auto"]).map((name) => ({ name, label: name, installed: name === "auto" || installed(name), recommended: name === "auto" })),
    },
  ];
}

function BackendChooser({ group, saving, onChange }) {
  return (
    <div style={{ padding: 12, borderRadius: 8, background: "var(--color-bg-elevated)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{group.step}</div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 2 }}>{group.note}</div>
        </div>
        <select
          value={group.selected}
          disabled={saving}
          onChange={(event) => onChange(event.target.value)}
          title="Saved in /data/config/pipeline_settings.json and used by new pipeline runs."
          className="form-control"
          style={{ width: "auto", minWidth: 124, fontSize: 12 }}
        >
          {group.options.map((option) => (
            <option key={option.name} value={option.name}>{option.label}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {group.options.map((option) => (
          <span
            key={option.name}
            className={`badge ${option.installed ? "badge-ok" : "badge-warn"}`}
            title={backendOptionTitle(option)}
          >
            {option.label}{option.recommended ? " · preferred" : ""} · {option.installed ? "installed" : "missing"}{option.requiresReferenceIndex ? " · needs index" : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function backendOptionTitle(option) {
  if (!option.installed) return "Not installed in the active API/worker image";
  if (option.requiresReferenceIndex) {
    return "Installed, but this backend requires its own reference index. Pipeline start blocks if the selected reference lacks that index.";
  }
  return "Installed in the active API/worker image";
}
