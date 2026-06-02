"use client";

import { API_BASE } from "@/lib/api";
import { useEffect, useMemo, useState } from "react";
import { Button, PageHeader, Panel } from "@/components/ui";



const TAXONOMY_ROUTE_OPTIONS = [
  {
    id: "human_wgs_host_depleted",
    label: "Human WGS host-depleted",
    note: "Default for human WGS: classify paired reads where both mates are unmapped after GRCh38 alignment.",
  },
  {
    id: "human_wgs_sensitive_low_mapq",
    label: "Sensitive human WGS",
    note: "Includes unmapped, mate-unmapped and low-MAPQ pairs. More sensitive, less specific.",
  },
  {
    id: "full_fastq_shotgun",
    label: "Full FASTQ shotgun",
    note: "Classifies all reads. Use for metagenomics, not as the default human WGS route.",
  },
  {
    id: "custom_host_depletion",
    label: "Custom host depletion",
    note: "Uses the run host BAM as the depletion source; custom host references can be wired later.",
  },
];

export function DataImportWorkflow({
  embedded = false,
  fixedProjectId = "",
  fixedProjectName = "",
  startDisabledReason = "",
  onPipelineStarted,
} = {}) {
  const [tab, setTab] = useState("browse");

  const [files, setFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState({});
  const [scanLoading, setScanLoading] = useState(false);
  const [browsePath, setBrowsePath] = useState("");
  const [browseParent, setBrowseParent] = useState(null);
  const [browseCurrentPath, setBrowseCurrentPath] = useState("");

  const [downloadUrl, setDownloadUrl] = useState("");
  const [downloadJob, setDownloadJob] = useState(null);
  const [downloadErr, setDownloadErr] = useState("");

  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState("");

  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineProject, setPipelineProject] = useState(fixedProjectId || "");
  const [pipelineRef, setPipelineRef] = useState("GRCh38_standard");
  const [projects, setProjects] = useState([]);
  const [references, setReferences] = useState([]);
  const [newProjectName, setNewProjectName] = useState("");
  const [pipelineStatus, setPipelineStatus] = useState("");
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState("core_variants");
  const [taxonomyRoute, setTaxonomyRoute] = useState("human_wgs_host_depleted");
  const [taxonomyLowMapq, setTaxonomyLowMapq] = useState(10);
  const [prepJobs, setPrepJobs] = useState({});

  const selectedCount = useMemo(() => Object.values(selectedFiles).filter(Boolean).length, [selectedFiles]);
  const selectedFileItems = useMemo(
    () => files.filter((file) => selectedFiles[file.path]),
    [files, selectedFiles]
  );
  const selectedPreparationIssues = useMemo(
    () => selectedFileItems.filter((file) => file.preflight?.required && !file.preflight?.ready),
    [selectedFileItems]
  );
  const selectedUnsupportedPipelineInputs = useMemo(
    () => selectedFileItems.filter((file) => !["fastq", "bam"].includes(file.type)),
    [selectedFileItems]
  );

  const loadScan = async (path = "") => {
    setScanLoading(true);
    try {
      const res = await fetch(`${API_BASE}/data/browse?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      setFiles(data.items || []);
      setBrowseCurrentPath(data.current_path || "");
      setBrowseParent(data.parent_path);
      setBrowsePath(path);
      return data;
    } catch (e) {
      console.error(e);
      return null;
    } finally {
      setScanLoading(false);
    }
  };

  const navigateFolder = async (path, presetPaths = []) => {
    setSelectedFiles({});
    await loadScan(path);
    if (presetPaths.length > 0) {
      setSelectedFiles(Object.fromEntries(presetPaths.map((itemPath) => [itemPath, true])));
    }
  };

  const loadProjects = async () => {
    if (fixedProjectId) return;
    try {
      const res = await fetch(`${API_BASE}/projects`);
      const data = await res.json();
      setProjects(data.items || []);
    } catch {}
  };

  const loadProfiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/pipelines/profiles`);
      const data = await res.json();
      setProfiles(data.items || []);
      // Auto-select best ready profile
      const ready = (data.items || []).filter((p) => p.ready);
      if (ready.length > 0 && !ready.find((p) => p.id === selectedProfile)) {
        setSelectedProfile(ready[0].id);
      }
    } catch {}
  };

  const loadReferences = async () => {
    try {
      const res = await fetch(`${API_BASE}/references`);
      const data = await res.json();
      const items = data.items || [];
      setReferences(items);
      const preferred = items.find((r) => r.id === "GRCh38_standard") || items.find((r) => r.status === "ready" || r.status === "indexed") || items[0];
      if (preferred && !items.some((r) => r.id === pipelineRef)) setPipelineRef(preferred.id);
    } catch {}
  };

  useEffect(() => {
    loadScan();
    loadProjects();
    loadProfiles();
    loadReferences();
  }, []);

  useEffect(() => {
    if (fixedProjectId) setPipelineProject(fixedProjectId);
  }, [fixedProjectId]);

  useEffect(() => {
    if (!downloadJob?.job_id || downloadJob.status === "done" || downloadJob.status === "failed") return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/data/import-url/${downloadJob.job_id}`);
        const data = await res.json();
        setDownloadJob(data);
        if (data.status === "done") {
          loadScan();
        }
      } catch {}
    }, 1200);
    return () => clearInterval(t);
  }, [downloadJob?.job_id, downloadJob?.status]);

  useEffect(() => {
    const active = Object.entries(prepJobs).filter(([, job]) => {
      return job?.job_id && !["done", "failed"].includes(job.status);
    });
    if (active.length === 0) return;

    const t = setInterval(async () => {
      const updates = await Promise.all(active.map(async ([path, job]) => {
        try {
          const res = await fetch(`${API_BASE}/data/prepare/${job.job_id}`);
          if (!res.ok) return null;
          return { path, data: await res.json() };
        } catch {
          return null;
        }
      }));
      const validUpdates = updates.filter(Boolean);
      if (validUpdates.length === 0) return;

      setPrepJobs((prev) => {
        const next = { ...prev };
        for (const update of validUpdates) next[update.path] = update.data;
        return next;
      });

      const completed = validUpdates.filter((update) => ["done", "failed"].includes(update.data.status));
      for (const update of completed) {
        const outputPath = update.data.output_relative_path;
        if (update.data.status === "done" && outputPath && outputPath !== update.path) {
          setSelectedFiles((prev) => ({ ...prev, [update.path]: false, [outputPath]: true }));
        }
      }
      if (completed.length > 0) loadScan(browsePath);
    }, 1200);
    return () => clearInterval(t);
  }, [prepJobs, browsePath]);

  const startDownload = async () => {
    if (!downloadUrl.trim()) return;
    setDownloadErr("");
    setDownloadJob(null);
    try {
      const res = await fetch(`${API_BASE}/data/import-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: downloadUrl.trim() }),
      });
      if (!res.ok) throw new Error("Download start failed");
      const data = await res.json();
      setDownloadJob({ ...data, downloaded_bytes: 0, total_bytes: null, speed_bps: 0 });
    } catch (e) {
      setDownloadErr("Could not start download.");
    }
  };

  const prepareFile = async (file) => {
    setPrepJobs((prev) => ({
      ...prev,
      [file.path]: {
        job_id: null,
        status: "queued",
        progress_pct: 0,
        step: "queued",
        input_relative_path: file.path,
      },
    }));
    try {
      const res = await fetch(`${API_BASE}/data/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: file.path }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        throw new Error(typeof detail === "object" ? (detail.message || detail.code || "Preparation failed") : (detail || "Preparation failed"));
      }
      setPrepJobs((prev) => ({ ...prev, [file.path]: data }));
    } catch (e) {
      setPrepJobs((prev) => ({
        ...prev,
        [file.path]: {
          ...(prev[file.path] || {}),
          status: "failed",
          progress_pct: 0,
          step: "failed",
          error: e.message,
        },
      }));
    }
  };

  const uploadOne = async (file) => {
    setUploadErr("");
    setUploadProgress(0);
    setUploading(true);

    await new Promise((resolve) => {
      const form = new FormData();
      form.append("file", file);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/data/upload`);

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          setUploadProgress(Math.round((event.loaded / event.total) * 100));
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setUploadProgress(100);
          loadScan();
        } else {
          setUploadErr("Upload failed.");
        }
        setUploading(false);
        resolve();
      };

      xhr.onerror = () => {
        setUploadErr("Upload failed.");
        setUploading(false);
        resolve();
      };

      xhr.send(form);
    });
  };

  const toggleFile = (path) => {
    setSelectedFiles((prev) => {
      const next = { ...prev, [path]: !prev[path] };
      // Human-friendly behavior: selecting one FASTQ mate selects the obvious mate too.
      const mate = findMatePath(path, files);
      if (mate) next[mate] = next[path];
      return next;
    });
  };

  const startPipeline = async () => {
    if (selectedCount === 0) return;
    if (selectedPreparationIssues.length > 0) {
      setPipelineStatus(`Error: ${selectedPreparationIssues[0].name} needs preparation before pipeline start.`);
      return;
    }
    if (selectedUnsupportedPipelineInputs.length > 0) {
      setPipelineStatus(`Error: ${selectedUnsupportedPipelineInputs[0].name} can be prepared/indexed, but pipeline start currently accepts FASTQ pairs or one BAM.`);
      return;
    }
    setPipelineRunning(true);
    setPipelineStatus("Creating project...");

    try {
      // 1. Create or select project
      let projId = fixedProjectId || pipelineProject;
      if (!projId) {
        const pName = newProjectName.trim() || `Import ${new Date().toLocaleDateString()}`;
        const pRes = await fetch(`${API_BASE}/projects`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: pName }),
        });
        if (!pRes.ok) throw new Error("Failed to create project");
        const proj = await pRes.json();
        projId = proj.id;
      }

      // 2. Detect sample name from selected files
      let selPaths = Object.keys(selectedFiles).filter(k => selectedFiles[k]);
      for (const p of [...selPaths]) {
        const mate = findMatePath(p, files);
        if (mate && !selPaths.includes(mate)) selPaths.push(mate);
      }
      const firstFile = selPaths[0]?.split("/").pop() || "sample";
      const sampleName = firstFile
        .replace(/\.f(ast)?q(\.gz)?$/i, "")
        .replace(/_R?[12]$/i, "");

      setPipelineStatus("Creating sample...");

      // 3. Create sample
      const r1 = selPaths.find(p => p.match(/_R?1\.f(ast)?q(\.gz)?$/i)) || selPaths[0];
      const r2 = selPaths.find(p => p.match(/_R?2\.f(ast)?q(\.gz)?$/i)) || null;
      if (r1 && !r2 && r1.match(/\.f(ast)?q(\.gz)?$/i)) {
        throw new Error("FASTQ pair incomplete. Select both R1 and R2 files.");
      }

      const sRes = await fetch(`${API_BASE}/projects/${projId}/samples`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sample_id: sampleName,
          reference_id: pipelineRef,
          r1_path: r1,
          r2_path: r2,
        }),
      });
      if (!sRes.ok) throw new Error("Failed to create sample");
      const sample = await sRes.json();

      setPipelineStatus("Creating run...");

      // 4. Create run
      const runRes = await fetch(`${API_BASE}/projects/${projId}/run/full`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sample_id: sample.id,
          reference_id: pipelineRef,
        }),
      });
      if (!runRes.ok) throw new Error("Failed to create run");
      const run = await runRes.json();

      setPipelineStatus("Starting pipeline...");

      // 5. Trigger pipeline execution
      const pRes2 = await fetch(`${API_BASE}/runs/${run.id}/pipeline/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile: selectedProfile,
          taxonomy_route: taxonomyRoute,
          taxonomy_low_mapq_threshold: Number(taxonomyLowMapq) || 10,
        }),
      });
      if (!pRes2.ok) {
        const errData = await pRes2.json().catch(() => ({}));
        const detail = errData.detail;
        throw new Error(typeof detail === "object" ? (detail.message || JSON.stringify(detail)) : (detail || "Failed to start pipeline"));
      }

      setPipelineStatus("Pipeline running!");

      if (onPipelineStarted) {
        onPipelineStarted({ projectId: projId, sample, run });
      } else {
        setPipelineStatus("Pipeline running! Redirecting...");
        setTimeout(() => {
          window.location.href = `/runs`;
        }, 800);
      }

    } catch (e) {
      setPipelineStatus(`Error: ${e.message}`);
      setPipelineRunning(false);
    }
  };

  const dlPct = downloadJob?.total_bytes ? Math.min(100, Math.round((downloadJob.downloaded_bytes / downloadJob.total_bytes) * 100)) : 0;

  return (
    <div>
      {!embedded && (
        <PageHeader
          eyebrow="Data intake"
          title="Data Import"
          description="Bring FASTQ, BAM, or VCF inputs into a controlled project workflow before starting pipeline work."
        />
      )}

      <div className="segmented-control">
        <TabButton active={tab === "browse"} onClick={() => setTab("browse")}>Browse Input Folder</TabButton>
        <TabButton active={tab === "download"} onClick={() => setTab("download")}>Download from URL</TabButton>
        <TabButton active={tab === "upload"} onClick={() => setTab("upload")}>Upload File</TabButton>
      </div>

      {tab === "browse" && (
        <Panel
          title="Input folder"
          description="Select only the source artifacts needed for the next run. FASTQ mates are paired automatically when the filename pattern is recognized."
          actions={<Button onClick={() => loadScan(browsePath)} disabled={scanLoading} size="sm">{scanLoading ? "Scanning..." : "Scan"}</Button>}
        >
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h3 style={{ margin: 0, fontSize: 15 }}>
                {browseCurrentPath ? `/${browseCurrentPath}` : "/"}
              </h3>
              <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>({files.length} items)</span>
            </div>
          </div>

          {/* Breadcrumb navigation */}
          {browseParent !== null && (
            <Button
              onClick={() => navigateFolder(browseParent)}
              variant="ghost"
              size="sm"
              style={{ marginBottom: 8 }}
            >
              Parent folder
            </Button>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
            {files.map((f) => (
              f.type === "directory" ? (
                <DirectoryRow
                  key={f.path}
                  folder={f}
                  onOpen={() => navigateFolder(f.path)}
                  onUsePreset={() => navigateFolder(f.path, f.preset?.recommended_paths || [])}
                />
              ) : (
                <FileRow
                  key={f.path}
                  file={f}
                  checked={!!selectedFiles[f.path]}
                  job={prepJobs[f.path]}
                  onToggle={() => toggleFile(f.path)}
                  onPrepare={() => prepareFile(f)}
                />
              )
            ))}
            {files.length === 0 && (
              <div style={{ color: "var(--color-text-muted)", fontSize: 13, padding: "18px 0", textAlign: "center" }}>
                Folder is empty. Upload or download files first, then rescan this folder.
              </div>
            )}
          </div>

          {/* Project & Reference selection */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, marginBottom: 16, padding: "14px", background: "var(--color-bg-base)", borderRadius: 8 }}>
            {fixedProjectId ? (
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Project</label>
                <div style={{ ...inputStyle, width: "100%", overflowWrap: "anywhere", background: "var(--color-bg-elevated)" }}>
                  {fixedProjectName || fixedProjectId}
                </div>
              </div>
            ) : (
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Project</label>
                <select value={pipelineProject} onChange={(e) => setPipelineProject(e.target.value)} style={{ ...selectStyle, width: "100%" }}>
                  <option value="">+ Create new</option>
                  {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
            )}
            {!fixedProjectId && !pipelineProject && (
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>New project name</label>
                <input value={newProjectName} onChange={e => setNewProjectName(e.target.value)} placeholder="Auto-generated" style={{ ...inputStyle, width: "100%" }} />
              </div>
            )}
            <div>
              <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Reference</label>
              <select value={pipelineRef} onChange={(e) => setPipelineRef(e.target.value)} style={{ ...selectStyle, width: "100%" }}>
                {references.map((ref) => (
                  <option key={ref.id} value={ref.id}>
                    {ref.id === "GRCh38_standard" ? "GRCh38" : ref.id} · {ref.status}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Pipeline Profile</label>
              <select value={selectedProfile} onChange={(e) => setSelectedProfile(e.target.value)} style={{ ...selectStyle, width: "100%" }}>
                {profiles.map((p) => (
                  <option key={p.id} value={p.id} disabled={!p.ready}>
                    {p.name} {!p.ready ? "(missing tools)" : ""}
                  </option>
                ))}
              </select>
              {profiles.find((p) => p.id === selectedProfile) && (
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                  {profiles.find((p) => p.id === selectedProfile).description}
                </div>
              )}
            </div>
            <div>
              <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Taxonomy route</label>
              <select value={taxonomyRoute} onChange={(e) => setTaxonomyRoute(e.target.value)} style={{ ...selectStyle, width: "100%" }}>
                {TAXONOMY_ROUTE_OPTIONS.map((route) => (
                  <option key={route.id} value={route.id}>{route.label}</option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                {TAXONOMY_ROUTE_OPTIONS.find((route) => route.id === taxonomyRoute)?.note}
              </div>
            </div>
            {taxonomyRoute === "human_wgs_sensitive_low_mapq" && (
              <div>
                <label style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 }}>Low MAPQ threshold</label>
                <input
                  type="number"
                  min="0"
                  max="60"
                  value={taxonomyLowMapq}
                  onChange={(e) => setTaxonomyLowMapq(e.target.value)}
                  style={{ ...inputStyle, width: "100%" }}
                />
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 }}>
                  Reads at or below this MAPQ are routed into sensitive taxonomy.
                </div>
              </div>
            )}
          </div>

          {/* Profile stage preview */}
          {profiles.find((p) => p.id === selectedProfile) && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 12 }}>
              {profiles.find((p) => p.id === selectedProfile).stages.map((s) => (
                <span key={s.name} style={{
                  padding: "3px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                  background: s.tools_ok ? "var(--color-ok)" : s.required ? "var(--color-err)" : "var(--color-warn)",
                  color: s.tools_ok ? "#fff" : s.required ? "#fff" : "#000",
                  opacity: 1,
                }}>
                  {s.name}{s.required ? "" : s.tools_ok ? "" : " (skip)"}
                </span>
              ))}
            </div>
          )}

          {selectedPreparationIssues.length > 0 && (
            <div style={{
              margin: "12px 0",
              padding: "10px 12px",
              border: "1px solid var(--color-warn, #f59e0b)",
              borderRadius: 6,
              color: "var(--color-warn, #f59e0b)",
              background: "rgba(245, 158, 11, 0.08)",
              fontSize: 12,
            }}>
              {selectedPreparationIssues.length === 1
                ? `${selectedPreparationIssues[0].name} needs preparation before pipeline start.`
                : `${selectedPreparationIssues.length} selected files need preparation before pipeline start.`}
            </div>
          )}
          {selectedUnsupportedPipelineInputs.length > 0 && (
            <div style={{
              margin: "12px 0",
              padding: "10px 12px",
              border: "1px solid var(--color-border-default)",
              borderRadius: 6,
              color: "var(--color-text-secondary)",
              background: "var(--color-bg-base)",
              fontSize: 12,
            }}>
              Pipeline start accepts FASTQ pairs or one coordinate-sorted BAM. VCF files can be prepared here, but are not a pipeline input yet.
            </div>
          )}

          <Button
            variant="primary"
            style={{ width: "100%", minHeight: 42 }}
            disabled={selectedCount === 0 || pipelineRunning || Boolean(startDisabledReason) || selectedPreparationIssues.length > 0 || selectedUnsupportedPipelineInputs.length > 0}
            onClick={startPipeline}
          >
            {pipelineRunning ? pipelineStatus : startDisabledReason || `Start Pipeline (${selectedCount} file${selectedCount !== 1 ? "s" : ""})`}
          </Button>
          {pipelineStatus && pipelineRunning && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-accent)", textAlign: "center" }}>{pipelineStatus}</div>
          )}
          {pipelineStatus && !pipelineRunning && pipelineStatus.startsWith("Error") && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--color-err)", textAlign: "center" }}>{pipelineStatus}</div>
          )}
        </Panel>
      )}

      {tab === "download" && (
        <Panel title="Download file into input folder" description="Use for source files that are safe to fetch directly on the API host. Downloads can be monitored without leaving this page.">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <input
              value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              placeholder="https://example.com/sample.fastq.gz"
              className="form-control"
              style={{ flex: 1 }}
            />
            <Button onClick={startDownload} variant="primary">Download</Button>
          </div>
          {downloadErr && <div style={{ color: "var(--color-err)", fontSize: 12 }}>{downloadErr}</div>}

          {downloadJob && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 6 }}>
                Status: <strong>{downloadJob.status}</strong>
              </div>
              <ProgressBar pct={dlPct} />
              <div style={{ marginTop: 6, fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                {formatBytes(downloadJob.downloaded_bytes || 0)} / {downloadJob.total_bytes ? formatBytes(downloadJob.total_bytes) : "unknown"} · {formatBytes(downloadJob.speed_bps || 0)}/s
              </div>
            </div>
          )}
        </Panel>
      )}

      {tab === "upload" && (
        <Panel title="Upload small file" description="For small inputs only. Large FASTQ/BAM files should be placed directly in the input folder or downloaded server-side.">
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files?.[0];
              if (f) uploadOne(f);
            }}
            style={{
              border: "1px dashed var(--color-border-default)",
              borderRadius: 10,
              padding: 28,
              textAlign: "center",
              color: "var(--color-text-secondary)",
              marginBottom: 12,
            }}
          >
            Drag and drop file here
            <div style={{ marginTop: 8 }}>
              <input
                type="file"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadOne(f);
                }}
                disabled={uploading}
              />
            </div>
          </div>
          <ProgressBar pct={uploadProgress} />
          {uploadErr && <div style={{ color: "var(--color-err)", fontSize: 12, marginTop: 8 }}>{uploadErr}</div>}
        </Panel>
      )}
    </div>
  );
}

export default function DataImportPage() {
  return <DataImportWorkflow />;
}

function TabButton({ active, children, ...props }) {
  return (
    <button
      {...props}
      className={`segmented-button ${active ? "active" : ""}`}
    >
      {children}
    </button>
  );
}

function DirectoryRow({ folder, onOpen, onUsePreset }) {
  const preset = folder.preset;
  const canUsePreset = preset?.recommended_paths?.length > 0;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) auto",
        gap: 8,
        alignItems: "stretch",
      }}
    >
      <button
        type="button"
        onClick={onOpen}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 10px",
          borderRadius: 6,
          background: "var(--color-bg-elevated)",
          border: "1px solid var(--color-border-muted)",
          cursor: "pointer",
          color: "var(--color-text-primary)",
          textAlign: "left",
          minWidth: 0,
        }}
      >
        <span style={{ fontSize: 11, fontWeight: 700, color: preset ? "var(--color-accent)" : "var(--color-text-muted)", width: 52 }}>
          {preset ? preset.vendor.toUpperCase() : "DIR"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, overflowWrap: "anywhere" }}>{folder.name}/</div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>
            {preset ? presetSummary(preset) : `${folder.child_count} item${folder.child_count !== 1 ? "s" : ""}`}
          </div>
        </div>
        <span style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", letterSpacing: "0.05em" }}>OPEN</span>
      </button>
      {canUsePreset && (
        <button
          type="button"
          onClick={onUsePreset}
          title="Open this folder and select the files recommended by its detected vendor layout"
          style={{
            ...smallBtn,
            minWidth: 116,
            fontWeight: 700,
            color: "var(--color-text-primary)",
          }}
        >
          Open + select
        </button>
      )}
    </div>
  );
}

function FileRow({ file, checked, job, onToggle, onPrepare }) {
  const preflight = file.preflight || {};
  const needsPreparation = preflight.required && !preflight.ready;
  const preparing = job?.status && !["done", "failed"].includes(job.status);
  const canPrepare = needsPreparation && preflight.can_prepare && !preparing;

  return (
    <label style={{
      display: "flex",
      alignItems: "flex-start",
      gap: 10,
      padding: "8px 10px",
      borderRadius: 6,
      background: "var(--color-bg-elevated)",
      opacity: file.supported === false ? 0.45 : 1,
    }}>
      <input type="checkbox" disabled={file.supported === false} checked={checked} onChange={onToggle} style={{ marginTop: 3 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500, overflowWrap: "anywhere" }}>{file.name}</div>
        <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
          {file.type} · {formatBytes(file.size)}{file.paired ? ` · ${file.paired}` : ""}
        </div>
        {preflight.required && (
          <div style={{
            marginTop: 4,
            fontSize: 11,
            color: preflight.ready ? "var(--color-ok)" : "var(--color-warn, #f59e0b)",
          }}>
            {preflightSummary(preflight)}
          </div>
        )}
        {job && (
          <div style={{ marginTop: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: job.status === "failed" ? "var(--color-err)" : "var(--color-text-muted)", marginBottom: 4 }}>
              <span>{job.status === "failed" ? `Failed: ${job.error || "preparation failed"}` : preparationStatus(job)}</span>
              <span>{job.progress_pct || 0}%</span>
            </div>
            <ProgressBar pct={job.progress_pct || 0} />
            {job.status === "done" && job.output_relative_path && job.output_relative_path !== file.path && (
              <div style={{ marginTop: 4, fontSize: 11, color: "var(--color-ok)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>
                Prepared output: {job.output_relative_path}
              </div>
            )}
          </div>
        )}
      </div>
      {needsPreparation && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onPrepare();
          }}
          disabled={!canPrepare}
          title={preflight.can_prepare ? prepareTitle(preflight) : "Required command-line tool is missing in the API container"}
          style={{
            ...smallBtn,
            flex: "0 0 auto",
            opacity: canPrepare ? 1 : 0.55,
            cursor: canPrepare ? "pointer" : "not-allowed",
          }}
        >
          {preparing ? `${job.progress_pct || 0}%` : prepareLabel(preflight)}
        </button>
      )}
    </label>
  );
}

function presetSummary(preset) {
  const parts = [preset.label];
  if (preset.fastq_pairs) parts.push(`${preset.fastq_pairs} FASTQ pair${preset.fastq_pairs !== 1 ? "s" : ""}`);
  if (preset.counts?.bam) parts.push(`${preset.counts.bam} BAM`);
  if (preset.counts?.vcf) parts.push(`${preset.counts.vcf} VCF`);
  if (preset.lanes?.length) parts.push(`${preset.lanes.length} lane${preset.lanes.length !== 1 ? "s" : ""}`);
  if (preset.warnings?.length) parts.push(preset.warnings.join(", "));
  return parts.join(" · ");
}

function ProgressBar({ pct }) {
  return (
    <div style={{ height: 8, background: "var(--color-bg-base)", borderRadius: 5, overflow: "hidden" }}>
      <div style={{ width: `${pct}%`, height: "100%", background: "var(--color-accent)", transition: "width 0.2s" }} />
    </div>
  );
}

function preflightSummary(preflight) {
  if (preflight.ready) {
    if (preflight.sort_order === "coordinate") return "Coordinate-sorted and indexed";
    return "Index ready";
  }
  const labels = {
    bam_index_missing: "BAM index missing",
    bam_not_coordinate_sorted: "BAM is not coordinate-sorted",
    bam_header_unreadable: "BAM header could not be read",
    bam_header_probe_timeout: "BAM header check timed out",
    bam_sort_order_missing: "BAM sort order is not declared",
    samtools_unavailable: "samtools unavailable for BAM check",
    vcf_index_missing: "VCF index missing",
    vcf_not_bgzipped: "VCF must be bgzip-compressed",
  };
  return (preflight.warnings || []).map((warning) => labels[warning] || warning).join(" · ") || "Preparation required";
}

function prepareLabel(preflight) {
  if (preflight.prepare_action === "sort_and_index") return "Sort + index";
  if (preflight.prepare_action === "compress_and_index") return "Compress + index";
  return "Index";
}

function prepareTitle(preflight) {
  if (preflight.prepare_action === "sort_and_index") return "Create a coordinate-sorted BAM copy and index it";
  if (preflight.prepare_action === "compress_and_index") return "Create bgzip-compressed VCF and tabix index";
  return "Create index for this file";
}

function preparationStatus(job) {
  if (job.status === "done") return "Done";
  if (job.status === "queued") return "Queued";
  if (job.step) return job.step[0].toUpperCase() + job.step.slice(1);
  return job.status || "Preparing";
}

function mateName(name) {
  const patterns = [
    [/_R1(\.f(?:ast)?q(?:\.gz)?)$/i, "_R2$1"],
    [/_R2(\.f(?:ast)?q(?:\.gz)?)$/i, "_R1$1"],
    [/_1(\.f(?:ast)?q(?:\.gz)?)$/i, "_2$1"],
    [/_2(\.f(?:ast)?q(?:\.gz)?)$/i, "_1$1"],
  ];
  for (const [re, repl] of patterns) {
    if (re.test(name)) return name.replace(re, repl);
  }
  return null;
}

function findMatePath(path, files) {
  const name = path.split("/").pop();
  const mate = mateName(name || "");
  if (!mate) return null;
  return files.find((f) => f.name === mate || f.path.endsWith(`/${mate}`) || f.path === mate)?.path || null;
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

const inputStyle = {
  width: "100%",
  padding: "8px 12px",
  background: "var(--color-bg-base)",
  border: "1px solid var(--color-border-default)",
  borderRadius: 6,
  color: "var(--color-text-primary)",
  fontSize: 14,
};

const primaryBtn = {
  padding: "8px 14px",
  background: "var(--color-accent)",
  color: "var(--color-text-inverse)",
  border: "none",
  borderRadius: 6,
  fontWeight: 600,
  cursor: "pointer",
};

const smallBtn = {
  padding: "4px 10px",
  background: "var(--color-bg-elevated)",
  border: "1px solid var(--color-border-default)",
  borderRadius: 5,
  color: "var(--color-text-secondary)",
  cursor: "pointer",
};

const selectStyle = {
  padding: "6px 12px", background: "var(--color-bg-base)",
  border: "1px solid var(--color-border-default)", borderRadius: 6,
  color: "var(--color-text-primary)", fontSize: 13,
};
