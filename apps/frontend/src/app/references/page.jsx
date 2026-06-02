"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect } from "react";
import { Button, ConfirmDialog, PageHeader, Panel } from "@/components/ui";

const ACTIVE_INDEX_STATUSES = new Set(["starting", "queued", "running", "indexing"]);

function shouldWatchIndexStatus(ref, currentStatus) {
  if (ACTIVE_INDEX_STATUSES.has(currentStatus)) return true;
  if (!ref?.fasta_path) return false;
  return ref.status !== "ready" && ref.status !== "indexed";
}

export function ReferencesManager({ embedded = false } = {}) {
  const [references, setReferences] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState({});  // ref_id -> { progress, status, job_id }
  const [indexing, setIndexing] = useState({}); // ref_id -> { progress_pct, status, steps, error }
  const [showAdd, setShowAdd] = useState(false);
  const [pendingDeleteRef, setPendingDeleteRef] = useState(null);
  const emptyAddForm = { id: "", version: "custom", source: "", contig_style: "chr", fasta_path: "", fai_path: "", download_url: "", download_sha256: "" };
  const [addForm, setAddForm] = useState(emptyAddForm);

  useEffect(() => { loadRefs(); }, []);

  useEffect(() => {
    if (references.length === 0) return;
    const watchedReferences = references.filter((ref) => shouldWatchIndexStatus(ref, indexing[ref.id]?.status));
    if (watchedReferences.length === 0) return;

    let cancelled = false;
    const loadIndexStatuses = async () => {
      if (document.visibilityState === "hidden") return;
      const updates = await Promise.all(watchedReferences.map(async (ref) => {
        try {
          const res = await fetch(`${API_BASE}/references/${ref.id}/index-status`);
          if (!res.ok) return null;
          const data = await res.json();
          return { refId: ref.id, data };
        } catch {
          return null;
        }
      }));
      if (cancelled) return;
      setIndexing((prev) => {
        const next = { ...prev };
        for (const update of updates.filter(Boolean)) {
          const ref = references.find((item) => item.id === update.refId);
          const refReady = ref?.status === "ready" || ref?.status === "indexed";
          if (refReady && update.data.status === "done") delete next[update.refId];
          else if (update.data.status !== "no_job") next[update.refId] = update.data;
          else if (next[update.refId]?.status === "failed") delete next[update.refId];
        }
        return next;
      });
    };
    loadIndexStatuses();
    const interval = setInterval(loadIndexStatuses, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [references, indexing]);

  const loadRefs = async () => {
    try {
      const res = await fetch(`${API_BASE}/references`);
      const data = await res.json();
      setReferences(data.items || []);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const startDownload = async (ref) => {
    setDownloading(prev => ({ ...prev, [ref.id]: { status: "starting", progress: 0 } }));
    setIndexing(prev => {
      const next = { ...prev };
      delete next[ref.id];
      return next;
    });
    try {
      const res = await fetch(`${API_BASE}/references/${ref.id}/download`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail;
        setDownloading(prev => ({ ...prev, [ref.id]: { status: "error", error: typeof detail === "object" ? (detail.message || JSON.stringify(detail)) : (detail || "Download failed") } }));
        return;
      }
      const data = await res.json();
      setDownloading(prev => ({ ...prev, [ref.id]: { status: "downloading", job_id: data.job_id, progress: 0 } }));
      // Poll progress
      pollDownload(ref.id, data.job_id);
    } catch (e) {
      setDownloading(prev => ({ ...prev, [ref.id]: { status: "error", error: e.message } }));
    }
  };

  const pollDownload = (refId, jobId) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/data/import-url/${jobId}`);
        const data = await res.json();
        const pct = data.progress_pct != null ? Math.min(100, Math.round(data.progress_pct)) : null;
        setDownloading(prev => ({
          ...prev,
          [refId]: {
            ...prev[refId],
            progress: pct,
            status: data.status,
            downloaded: data.downloaded_bytes,
            total: data.total_bytes,
            speed_bps: data.speed_bps,
            elapsed_sec: data.elapsed_sec,
            eta_sec: data.eta_sec,
            phase: data.phase,
            checksum: data.checksum,
            error: data.error,
          },
        }));
        if (data.status === "done" || data.status === "failed") {
          clearInterval(interval);
          if (data.status === "done") loadRefs();
        }
      } catch {
        clearInterval(interval);
        setDownloading(prev => ({ ...prev, [refId]: { status: "error", error: "Poll failed" } }));
      }
    }, 2000);
  };

  const addReference = async () => {
    if (!addForm.id.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/references`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(addForm),
      });
      if (res.ok) {
        setShowAdd(false);
        setAddForm(emptyAddForm);
        loadRefs();
      }
    } catch (e) { console.error(e); }
  };

  const needsIndex = (ref) => {
    if (!ref.fasta_path) return false;
    if (indexing[ref.id]?.status === "done") return false;
    return ref.status !== "indexed" && ref.status !== "ready";
  };

  const startIndex = async (ref) => {
    setIndexing(prev => ({ ...prev, [ref.id]: { status: "starting", progress_pct: 0, steps: [] } }));
    const res = await fetch(`${API_BASE}/references/${ref.id}/index`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setIndexing(prev => ({ ...prev, [ref.id]: { status: "failed", progress_pct: 0, error: data?.detail || "Index start failed" } }));
      return;
    }
    pollIndex(ref.id);
  };

  const pollIndex = (refId) => {
    const interval = setInterval(async () => {
      const res = await fetch(`${API_BASE}/references/${refId}/index-status`);
      const data = await res.json();
      setIndexing(prev => ({ ...prev, [refId]: data }));
      if (["done", "failed", "no_job"].includes(data.status)) {
        clearInterval(interval);
        if (data.status === "done") loadRefs();
      }
    }, 2000);
  };

  const deleteReference = async (ref) => {
    setPendingDeleteRef(null);
    await fetch(`${API_BASE}/references/${ref.id}`, { method: "DELETE" });
    loadRefs();
  };

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: embedded ? "12px 0" : 40 }}>Loading references…</div>;

  return (
    <div>
      {embedded ? (
        <div style={embeddedHeaderStyle}>
          <div style={{ minWidth: 0 }}>
            <div className="page-eyebrow">Reference manager</div>
            <h2 style={{ margin: "2px 0 4px", fontSize: 20, fontWeight: 700 }}>References</h2>
            <p style={{ margin: 0, color: "var(--color-text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
              Genome reference assemblies with download, checksum, indexing, and local storage provenance.
            </p>
          </div>
          <Button onClick={() => setShowAdd(true)}>Add Reference</Button>
        </div>
      ) : (
        <PageHeader
          eyebrow="Reference manager"
          title="References"
          description="Genome reference assemblies with download, checksum, indexing, and local storage provenance."
          actions={<Button onClick={() => setShowAdd(true)}>Add Reference</Button>}
        />
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(380px, 1fr))", gap: 16 }}>
        {references.map(ref => (
          <RefCard key={ref.id} ref={ref} dl={downloading[ref.id]} idx={indexing[ref.id]} needsIndex={needsIndex(ref)} onDownload={() => startDownload(ref)} onIndex={() => startIndex(ref)} onDelete={() => setPendingDeleteRef(ref)} canDelete={!ref.builtin || ref.local_files_present} />
        ))}
      </div>

      {/* Add Reference Modal */}
      {showAdd && (
        <div className="modal-backdrop" onClick={() => setShowAdd(false)}>
          <div className="modal-panel" style={{ width: 520 }} onClick={e => e.stopPropagation()}>
            <div className="page-eyebrow">Reference manager</div>
            <h2 style={{ fontSize: 18, fontWeight: 700, margin: "0 0 20px" }}>Add Reference</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div>
                <label style={labelStyle}>Reference ID *</label>
                <input value={addForm.id} onChange={e => setAddForm({ ...addForm, id: e.target.value })} placeholder="e.g. GRCh38_custom" className="form-control" />
              </div>
              <div>
                <label style={labelStyle}>Version</label>
                <input value={addForm.version} onChange={e => setAddForm({ ...addForm, version: e.target.value })} placeholder="e.g. GRCh38" className="form-control" />
              </div>
              <div>
                <label style={labelStyle}>Source</label>
                <input value={addForm.source} onChange={e => setAddForm({ ...addForm, source: e.target.value })} placeholder="e.g. NCBI, UCSC, proprietary" className="form-control" />
              </div>
              <div>
                <label style={labelStyle}>Download URL</label>
                <input value={addForm.download_url} onChange={e => setAddForm({ ...addForm, download_url: e.target.value })} placeholder="https://example.com/reference.fa.gz" className="form-control" />
                <div style={hintStyle}>Use this for one-click download/indexing into /data/references.</div>
              </div>
              <div>
                <label style={labelStyle}>Download SHA-256 (optional)</label>
                <input value={addForm.download_sha256} onChange={e => setAddForm({ ...addForm, download_sha256: e.target.value })} placeholder="64-character SHA-256 for the downloaded file" className="form-control" />
                <div style={hintStyle}>If supplied, the API verifies the downloaded archive before unpacking or indexing.</div>
              </div>
              <div style={{ textAlign: "center", fontSize: 12, color: "var(--color-text-muted)" }}>— or use a file already on the server —</div>
              <div>
                <label style={labelStyle}>Server FASTA path</label>
                <input value={addForm.fasta_path} onChange={e => setAddForm({ ...addForm, fasta_path: e.target.value })} placeholder="/data/references/my_ref/my_ref.fa" className="form-control" />
                <div style={hintStyle}>For references uploaded manually or mounted from filesystem.</div>
              </div>
              <div>
                <label style={labelStyle}>Server FAI path (optional)</label>
                <input value={addForm.fai_path} onChange={e => setAddForm({ ...addForm, fai_path: e.target.value })} placeholder="/data/references/my_ref/my_ref.fa.fai" className="form-control" />
              </div>
              <div>
                <label style={labelStyle}>Contig style</label>
                <select value={addForm.contig_style} onChange={e => setAddForm({ ...addForm, contig_style: e.target.value })} className="form-control">
                  <option value="chr">chr (chr1, chr2, ...)</option>
                  <option value="numeric">numeric (1, 2, ...)</option>
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end", marginTop: 24 }}>
              <Button variant="secondary" onClick={() => setShowAdd(false)}>Cancel</Button>
              <Button onClick={addReference} disabled={!addForm.id.trim()}>Add Reference</Button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!pendingDeleteRef}
        title={pendingDeleteRef?.builtin ? `Clear local files for ${pendingDeleteRef.id}?` : `Delete ${pendingDeleteRef?.id || "reference"}?`}
        description={pendingDeleteRef?.builtin
          ? "The built-in reference record remains available, but downloaded FASTA/index artifacts are removed and must be rebuilt before pipeline use."
          : "This deletes the custom reference from the registry and removes its local files when managed by the API."}
        details={[
          "Existing run outputs are not deleted.",
          "Future runs depending on this reference will be blocked until the reference is ready again.",
        ]}
        confirmLabel={pendingDeleteRef?.builtin ? "Clear local files" : "Delete reference"}
        onCancel={() => setPendingDeleteRef(null)}
        onConfirm={() => deleteReference(pendingDeleteRef)}
      />
    </div>
  );
}

export default function ReferencesPage() {
  return <ReferencesManager />;
}

function RefCard({ ref, dl, idx, needsIndex, onDownload, onIndex, onDelete, canDelete }) {
  const isAvailable = ref.status === "available" || ref.status === "ready" || ref.status === "indexed";
  const isReady = ref.status === "ready" || ref.status === "indexed";
  const isDownloading = ["starting", "queued", "downloading", "verifying", "unpacking", "indexing"].includes(dl?.status);
  const canDownload = !!ref.download_url;
  const isIndexing = ["queued", "indexing", "starting"].includes(idx?.status);

  return (
    <Panel>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>{ref.id}</div>
          <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>{ref.version} · {ref.source}</div>
        </div>
        <span className={`badge ${isReady ? "badge-ok" : isDownloading ? "badge-info" : "badge-warn"}`}>
          {isDownloading ? "downloading" : ref.status}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, fontSize: 13, marginBottom: 12 }}>
        <Detail label="Profile" value={ref.builtin ? "built-in" : "custom"} />
        <Detail label="Contig style" value={ref.contig_style} />
        <Detail label="Mito contig" value={ref.mitochondrial_contig || "—"} />
      </div>
      <div style={{ marginBottom: 12 }}>
        <Detail label="FASTA" value={ref.fasta_path || "not set"} />
      </div>
      {ref.fai_path && (
        <div style={{ marginBottom: 12 }}>
          <Detail label="FAI" value={ref.fai_path} />
        </div>
      )}
      {(ref.download_source_page || ref.download_url) && (
        <div style={{ marginBottom: 12 }}>
          <Detail label="Download provenance" value={ref.download_source_page || ref.download_url} />
        </div>
      )}
      {ref.local_files_present && (
        <div style={{ marginBottom: 12 }}>
          <Detail label="Local storage" value={formatBytes(ref.local_size_bytes || 0)} />
        </div>
      )}
      {ref.download_checksum?.status !== "not_configured" && (
        <div style={{ marginBottom: 12 }}>
          <Detail label="Download checksum" value={checksumConfigLabel(ref.download_checksum)} />
        </div>
      )}

      {ref.aliases?.length > 0 && (
        <div style={{ marginBottom: 12, display: "flex", gap: 4, flexWrap: "wrap" }}>
          {ref.aliases.map(a => <span key={a} className="badge badge-accent" style={{ fontSize: 10 }}>{a}</span>)}
        </div>
      )}

      {/* Download progress */}
      {isDownloading && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            <span>{downloadStatusLabel(dl)}</span>
            <span>{dl.progress != null ? `${dl.progress}%` : "size unknown"}</span>
          </div>
          <div style={{ height: 6, background: "var(--color-bg-base)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${dl.progress != null ? dl.progress : 100}%`, height: "100%", background: dl.progress != null ? "var(--color-accent)" : "var(--color-border-default)", transition: "width 0.3s" }} />
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", marginTop: 4 }}>
            {downloadProgressDetails(dl)}
          </div>
          {dl.checksum && (
            <div style={{ fontSize: 11, color: checksumStatusColor(dl.checksum), fontFamily: "var(--font-mono)", marginTop: 4 }}>
              {checksumStatusLabel(dl.checksum)}
            </div>
          )}
        </div>
      )}

      {dl?.status === "error" && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-err)" }}>✗ {dl.error}</div>
      )}
      {dl?.status === "failed" && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-err)" }}>
          ✗ {dl.error || "Download failed"}
        </div>
      )}
      {dl?.checksum && !isDownloading && (
        <div style={{ marginBottom: 12, fontSize: 12, color: checksumStatusColor(dl.checksum), fontFamily: "var(--font-mono)" }}>
          {checksumStatusLabel(dl.checksum)}
        </div>
      )}

      {dl?.status === "done" && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-ok)" }}>✓ Downloaded and ready</div>
      )}

      {isReady && !dl && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-ok)" }}>✓ Indexed and ready</div>
      )}

      {needsIndex && (
        <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-warn, #f59e0b)" }}>
          Reference is present but not indexed. Create index before running pipeline.
        </div>
      )}

      {isIndexing && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            <span>{indexStatusLabel(idx)}</span>
            <span>{indexProgressIsEstimated(idx) ? "running" : `${idx.progress_pct || 0}%`}</span>
          </div>
          <div style={{ height: 6, background: "var(--color-bg-base)", borderRadius: 3, overflow: "hidden" }}>
            <div style={{ width: `${idx.progress_pct || 0}%`, height: "100%", background: "var(--color-accent)", transition: "width 0.3s" }} />
          </div>
        </div>
      )}
      {idx?.status === "failed" && <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-err)" }}>✗ Index failed: {idx.error}</div>}
      {idx?.status === "done" && !isReady && <div style={{ marginBottom: 12, fontSize: 12, color: "var(--color-ok)" }}>✓ Index ready</div>}

      <div style={{ display: "flex", gap: 8 }}>
      {(needsIndex || isReady) && (
        <Button onClick={onIndex} disabled={isIndexing || isReady} style={{ width: "100%" }}>
          {isReady ? "Index ready" : isIndexing ? "Indexing" : "Index now"}
        </Button>
      )}
      <Button onClick={onDownload} disabled={isDownloading || !canDownload} variant={isAvailable ? "secondary" : "primary"} style={{ width: "100%" }}>
        {!canDownload ? "No download URL — using filesystem path" : isDownloading ? downloadButtonLabel(dl) : isAvailable ? "Re-download" : "Download Reference"}
      </Button>
      {canDelete && (
        <Button onClick={onDelete} variant="danger" title={ref.builtin ? "Clear downloaded files and indexes" : "Delete custom reference"}>Delete</Button>
      )}
      </div>
    </Panel>
  );
}

function Detail({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{label}</div>
      <div title={String(value)} style={{ fontFamily: "var(--font-mono)", fontSize: 12, overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}

function indexProgressIsEstimated(job) {
  return String(job?.phase || "").endsWith("_index");
}

function indexStatusLabel(job) {
  const backend = job?.backend ? ` with ${job.backend}` : "";
  if (String(job?.phase || "").endsWith("_index")) return `Indexing${backend}; tool progress unavailable`;
  if (job?.phase === "faidx") return "Building FASTA index";
  if (job?.phase === "dict") return "Building sequence dictionary";
  return "Indexing";
}

function checksumConfigLabel(checksum) {
  if (!checksum || checksum.status === "not_configured") return "not configured";
  const expected = checksum.expected ? `${checksum.expected.slice(0, 12)}...` : "configured";
  return `${checksum.algorithm || "sha256"} ${expected}`;
}

function checksumStatusLabel(checksum) {
  if (!checksum || checksum.status === "not_configured") return "checksum not configured";
  if (checksum.status === "pending") return "checksum pending";
  if (checksum.status === "verified") return `${checksum.algorithm || "sha256"} verified`;
  if (checksum.status === "failed") return `${checksum.algorithm || "sha256"} mismatch: ${String(checksum.actual || "").slice(0, 12)}...`;
  return `checksum ${checksum.status}`;
}

function checksumStatusColor(checksum) {
  if (checksum?.status === "verified") return "var(--color-ok)";
  if (checksum?.status === "failed") return "var(--color-err)";
  return "var(--color-text-muted)";
}

function downloadStatusLabel(job) {
  if (job?.phase === "checksum") return "Verifying checksum";
  if (job?.phase === "decompressing") return "Unpacking FASTA";
  if (job?.phase === "faidx") return "Building FASTA index";
  if (job?.phase === "done") return "Download complete";
  if (job?.status === "queued" || job?.status === "starting") return "Starting";
  return "Downloading";
}

function downloadButtonLabel(job) {
  const label = downloadStatusLabel(job);
  return job?.progress != null ? `${label} ${job.progress}%` : label;
}

function downloadProgressDetails(job) {
  const downloaded = formatBytes(job?.downloaded || 0);
  const speed = job?.speed_bps ? ` · ${formatRate(job.speed_bps)}` : "";
  const eta = job?.eta_sec != null ? ` · ETA ${formatDuration(job.eta_sec)}` : "";
  if (job?.total) return `${downloaded} / ${formatBytes(job.total)}${speed}${eta}`;
  return `${downloaded} downloaded${speed}`;
}

function formatRate(bytesPerSec) {
  return `${formatBytes(bytesPerSec)}/s`;
}

function formatDuration(seconds) {
  const sec = Math.max(0, Math.round(seconds || 0));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const hrs = Math.floor(min / 60);
  return `${hrs}h ${min % 60}m`;
}

function formatBytes(v) {
  if (v < 1024) return `${v} B`;
  if (v < 1024 ** 2) return `${(v / 1024).toFixed(1)} KB`;
  if (v < 1024 ** 3) return `${(v / 1024 ** 2).toFixed(1)} MB`;
  return `${(v / 1024 ** 3).toFixed(2)} GB`;
}

const labelStyle = { fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 };
const hintStyle = { fontSize: 11, color: "var(--color-text-muted)", marginTop: 4 };
const embeddedHeaderStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 16,
  marginBottom: 16,
  flexWrap: "wrap",
};
