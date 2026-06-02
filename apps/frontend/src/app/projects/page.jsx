"use client";

import { API_BASE } from "@/lib/api";
import { useEffect, useMemo, useState } from "react";
import { DataImportWorkflow } from "@/app/data-import/page";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, PageHeader, Panel } from "@/components/ui";

const ACTIVE_RUN_STATUSES = new Set(["queued", "running", "paused", "cancelling"]);

export default function ProjectsPage() {
  const {
    selectedProjectId,
    selectedRunId,
    selectProject,
    selectRun,
    clearRunSelection,
  } = useAppSelection();
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);
  const [runs, setRuns] = useState([]);
  const [globalRuns, setGlobalRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [editingProject, setEditingProject] = useState(null);
  const [renameName, setRenameName] = useState("");
  const [renameDescription, setRenameDescription] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const selectedProject = projects.find((project) => project.id === selectedProjectId);
  const selectedRun = runs.find((run) => run.id === selectedRunId);
  const activeRuns = useMemo(() => runs.filter((run) => ACTIVE_RUN_STATUSES.has(run.status)), [runs]);
  const globalActiveRuns = useMemo(() => globalRuns.filter((run) => ACTIVE_RUN_STATUSES.has(run.status)), [globalRuns]);

  useEffect(() => {
    loadProjects();
    loadGlobalRuns();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      loadInventory(selectedProjectId);
    } else {
      setSamples([]);
      setRuns([]);
    }
  }, [selectedProjectId]);

  async function loadProjects() {
    try {
      const res = await fetch(`${API_BASE}/projects`);
      const data = await res.json();
      const nextProjects = (data.items || []).slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setProjects(nextProjects);
      if (!selectedProjectId && nextProjects.length > 0) {
        selectProject(nextProjects[0].id);
      } else if (selectedProjectId && !nextProjects.find((project) => project.id === selectedProjectId)) {
        selectProject(nextProjects[0]?.id || "");
      }
    } catch (error) {
      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  async function loadInventory(projectId) {
    try {
      const [sampleRes, runRes] = await Promise.all([
        fetch(`${API_BASE}/projects/${projectId}/samples`).then((res) => res.json()),
        fetch(`${API_BASE}/projects/${projectId}/runs`).then((res) => res.json()),
      ]);
      const nextSamples = sampleRes.items || sampleRes || [];
      const nextRuns = (runRes.items || runRes || []).slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
      setSamples(nextSamples);
      setRuns(nextRuns);
      if (selectedRunId && !nextRuns.find((run) => run.id === selectedRunId)) {
        clearRunSelection();
      }
    } catch (error) {
      console.error(error);
      setSamples([]);
      setRuns([]);
    }
  }

  async function loadGlobalRuns() {
    try {
      const res = await fetch(`${API_BASE}/runs?limit=50`);
      const data = await res.json();
      setGlobalRuns(data.items || data || []);
    } catch (error) {
      console.error(error);
      setGlobalRuns([]);
    }
  }

  async function createProject() {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
      if (res.ok) {
        const project = await res.json();
        setNewName("");
        setNewDesc("");
        await loadProjects();
        selectProject(project.id);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setCreating(false);
    }
  }

  function beginRename(project) {
    setEditingProject(project.id);
    setRenameName(project.name || "");
    setRenameDescription(project.description || "");
  }

  async function saveRename() {
    if (!editingProject || !renameName.trim()) return;
    setRenaming(true);
    try {
      const res = await fetch(`${API_BASE}/projects/${editingProject}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: renameName.trim(),
          description: renameDescription.trim() || null,
        }),
      });
      if (res.ok) {
        const updated = await res.json();
        setProjects((current) => current.map((project) => project.id === updated.id ? updated : project));
        setEditingProject(null);
      }
    } catch (error) {
      console.error(error);
    } finally {
      setRenaming(false);
    }
  }

  async function deleteProject(projectId) {
    try {
      await fetch(`${API_BASE}/projects/${projectId}`, { method: "DELETE" });
      selectProject("");
      await loadProjects();
    } catch (error) {
      console.error(error);
    }
  }

  async function deleteRun(runId) {
    try {
      await fetch(`${API_BASE}/runs/${runId}`, { method: "DELETE" });
      if (selectedProjectId) loadInventory(selectedProjectId);
    } catch (error) {
      console.error(error);
    }
  }

  if (loading) return <div style={{ color: "var(--color-text-secondary)", padding: 40 }}>Loading projects...</div>;

  return (
    <div>
      <PageHeader
        eyebrow="Workspace"
        title="Projects"
        description="Project and run selection controls the rest of the workspace."
      />

      <Panel title="New Project">
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 240px" }}>
            <label style={labelStyle}>Name</label>
            <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Project name" className="form-control" />
          </div>
          <div style={{ flex: "2 1 320px" }}>
            <label style={labelStyle}>Description</label>
            <input value={newDesc} onChange={(event) => setNewDesc(event.target.value)} placeholder="Optional description" className="form-control" />
          </div>
          <Button onClick={createProject} disabled={creating || !newName.trim()} variant="primary">
            {creating ? "Creating..." : "Create"}
          </Button>
        </div>
      </Panel>

      <div className="split-layout">
        <Panel className="list-panel">
          <h3 className="list-panel-title">
            {projects.length} project{projects.length !== 1 ? "s" : ""}
          </h3>
          {projects.length === 0 ? (
            <div style={{ padding: 16, textAlign: "center", color: "var(--color-text-muted)", fontSize: 13 }}>No projects yet</div>
          ) : projects.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              selected={selectedProjectId === project.id}
              editing={editingProject === project.id}
              renameName={renameName}
              renameDescription={renameDescription}
              renaming={renaming}
              onSelect={() => selectProject(project.id)}
              onRename={() => beginRename(project)}
              onCancelRename={() => setEditingProject(null)}
              onSaveRename={saveRename}
              onRenameName={setRenameName}
              onRenameDescription={setRenameDescription}
              onDelete={() => setDeleteTarget({ type: "project", id: project.id, name: project.name })}
            />
          ))}
        </Panel>

        <ProjectInventory
          project={selectedProject}
          samples={samples}
          runs={runs}
          selectedRunId={selectedRunId}
          selectedRun={selectedRun}
          activeRuns={activeRuns}
          globalActiveRuns={globalActiveRuns}
          onRefresh={() => {
            if (selectedProjectId) loadInventory(selectedProjectId);
            loadGlobalRuns();
          }}
          onSelectRun={selectRun}
          onClearRun={clearRunSelection}
          onDeleteRun={(run) => setDeleteTarget({ type: "run", id: run.id, name: run.id.slice(0, 16) })}
          onPipelineStarted={({ run }) => {
            if (selectedProjectId) loadInventory(selectedProjectId);
            loadGlobalRuns();
            if (run) selectRun(run);
          }}
        />
      </div>

      {deleteTarget && (
        <DeleteConfirmModal
          target={deleteTarget}
          onConfirm={() => {
            if (deleteTarget.type === "project") deleteProject(deleteTarget.id);
            else if (deleteTarget.type === "run") deleteRun(deleteTarget.id);
            setDeleteTarget(null);
          }}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

function ProjectRow({
  project,
  selected,
  editing,
  renameName,
  renameDescription,
  renaming,
  onSelect,
  onRename,
  onCancelRename,
  onSaveRename,
  onRenameName,
  onRenameDescription,
  onDelete,
}) {
  if (editing) {
    return (
      <div style={{ ...projectRowStyle, background: "var(--color-accent-bg)", alignItems: "stretch", flexDirection: "column" }}>
        <input className="form-control" value={renameName} onChange={(event) => onRenameName(event.target.value)} />
        <input className="form-control" value={renameDescription} onChange={(event) => onRenameDescription(event.target.value)} placeholder="Optional description" />
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button size="sm" variant="ghost" onClick={onCancelRename}>Cancel</Button>
          <Button size="sm" variant="primary" disabled={renaming || !renameName.trim()} onClick={onSaveRename}>
            {renaming ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        ...projectRowStyle,
        background: selected ? "var(--color-accent-bg)" : "transparent",
        borderColor: selected ? "var(--color-accent)" : "transparent",
      }}
      onClick={onSelect}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: selected ? 800 : 700, fontSize: selected ? 18 : 16, color: selected ? "var(--color-text-primary)" : "var(--color-text-secondary)", overflowWrap: "anywhere" }}>
          {project.name}
        </div>
        <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", marginTop: 3 }}>{project.id}</div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Button size="sm" variant="ghost" onClick={(event) => { event.stopPropagation(); onRename(); }}>Rename</Button>
        <button onClick={(event) => { event.stopPropagation(); onDelete(); }} style={deleteBtn} title="Delete project">Delete</button>
      </div>
    </div>
  );
}

function ProjectInventory({
  project,
  samples,
  runs,
  selectedRunId,
  selectedRun,
  activeRuns,
  globalActiveRuns,
  onRefresh,
  onSelectRun,
  onClearRun,
  onDeleteRun,
  onPipelineStarted,
}) {
  if (!project) {
    return <Panel className="empty-state"><h2>Select a project</h2></Panel>;
  }

  return (
    <div>
      <Panel>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: 28, overflowWrap: "anywhere" }}>{project.name}</h2>
            <div style={{ fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", marginTop: 6 }}>{project.id}</div>
            {project.description && <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 8 }}>{project.description}</div>}
          </div>
          <Button size="sm" onClick={onRefresh}>Refresh</Button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10, marginTop: 14 }}>
          <Metric label="Samples" value={samples.length.toLocaleString()} />
          <Metric label="Runs" value={runs.length.toLocaleString()} />
          <Metric label="Active" value={activeRuns.length.toLocaleString()} tone={activeRuns.length ? "warn" : undefined} />
          <Metric label="Selected run" value={selectedRun?.id || "None"} />
        </div>
      </Panel>

      {globalActiveRuns.length > 0 && (
        <Panel>
          <div style={{ color: "var(--color-text-secondary)", fontSize: 13 }}>
            Active backend run detected. You can inspect other projects while it runs; start controls remain disabled until active work clears.
          </div>
        </Panel>
      )}

      <div style={{ margin: "16px 0" }}>
        <div className="page-eyebrow" style={{ marginBottom: 6 }}>Project setup</div>
        <h2 style={{ margin: "0 0 12px", fontSize: 20, fontWeight: 700 }}>Data Import</h2>
        <DataImportWorkflow
          embedded
          fixedProjectId={project.id}
          fixedProjectName={project.name}
          startDisabledReason={globalActiveRuns.length > 0 ? "A backend run is active; wait before starting another run" : ""}
          onPipelineStarted={onPipelineStarted}
        />
      </div>

      <Panel title={`Samples (${samples.length})`}>
        {samples.length === 0 ? (
          <div style={{ color: "var(--color-text-muted)", fontSize: 13, padding: 12 }}>No samples yet.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {samples.map((sample) => (
              <div key={sample.id} style={inventoryRowStyle}>
                <div>
                  <span style={{ fontWeight: 600 }}>{sample.sample_id}</span>
                  <span style={{ marginLeft: 8, fontSize: 12, color: "var(--color-text-muted)" }}>ref: {sample.reference_id}</span>
                </div>
                <span style={monoMuted}>{sample.id}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title={`Runs (${runs.length})`}
        actions={selectedRunId ? <Button size="sm" variant="ghost" onClick={onClearRun}>Clear selection</Button> : null}
      >
        {runs.length === 0 ? (
          <div style={{ color: "var(--color-text-muted)", fontSize: 13, padding: 12 }}>No runs yet.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {runs.map((run) => {
              const selected = run.id === selectedRunId;
              const active = ACTIVE_RUN_STATUSES.has(run.status);
              return (
                <div
                  key={run.id}
                  style={{
                    ...inventoryRowStyle,
                    border: `1px solid ${selected ? "var(--color-accent)" : "transparent"}`,
                    background: selected ? "var(--color-accent-bg)" : "var(--color-bg-elevated)",
                  }}
                >
                  <button type="button" onClick={() => onSelectRun(run)} style={runSelectButtonStyle}>
                    <span className={`badge ${statusBadge(run.status)}`}>{run.status}</span>
                    <span style={{ fontWeight: 600 }}>{run.mode}</span>
                    {active && <span className="badge badge-warn">active</span>}
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>ref: {run.reference_id}</span>
                    <span style={monoMuted}>{run.id}</span>
                  </button>
                  <button onClick={() => onDeleteRun(run)} style={deleteBtn} title="Delete run">Delete</button>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div style={{ padding: 10, borderRadius: 8, background: "var(--color-bg-elevated)", minWidth: 0 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ marginTop: 4, fontSize: 13, color: tone ? `var(--color-${tone})` : "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}

function DeleteConfirmModal({ target, onConfirm, onCancel }) {
  const [input, setInput] = useState("");
  const requiresTyping = target.type !== "project";
  const canDelete = !requiresTyping || input === "DELETE";

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header"><h2>Delete {target.type}</h2></div>
        <p className="modal-description">
          You are about to delete <strong>{target.type}</strong>:<br />
          <code style={{ fontSize: 13, fontFamily: "var(--font-mono)" }}>{target.name}</code>
        </p>
        {requiresTyping ? (
          <>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", margin: "0 0 12px" }}>
              This action cannot be undone. Type <strong>DELETE</strong> to confirm:
            </p>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && canDelete) onConfirm(); }}
              placeholder="Type DELETE"
              autoFocus
              className="form-control"
              style={{ marginBottom: 20, fontFamily: "var(--font-mono)", fontWeight: 600 }}
            />
          </>
        ) : (
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", margin: "0 0 20px" }}>
            This removes the project and its samples/runs. Confirm once below.
          </p>
        )}
        <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
          <Button onClick={onCancel} variant="ghost">Cancel</Button>
          <Button onClick={onConfirm} disabled={!canDelete} variant="danger">Delete {target.type}</Button>
        </div>
      </div>
    </div>
  );
}

function statusBadge(status) {
  switch (status) {
    case "done": return "badge-ok";
    case "running": return "badge-info";
    case "queued": return "badge-warn";
    case "failed": return "badge-err";
    default: return "badge-info";
  }
}

const labelStyle = { fontSize: 12, color: "var(--color-text-secondary)", display: "block", marginBottom: 4 };
const monoMuted = { fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" };
const projectRowStyle = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "12px",
  borderRadius: 8,
  border: "1px solid transparent",
  marginBottom: 4,
  cursor: "pointer",
};
const inventoryRowStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  padding: "10px 12px",
  borderRadius: 6,
  background: "var(--color-bg-elevated)",
};
const runSelectButtonStyle = {
  flex: 1,
  display: "flex",
  alignItems: "center",
  flexWrap: "wrap",
  gap: 8,
  minWidth: 0,
  background: "none",
  border: 0,
  padding: 0,
  color: "inherit",
  textAlign: "left",
  cursor: "pointer",
};
const deleteBtn = {
  background: "none",
  border: "1px solid var(--color-border-muted)",
  color: "var(--color-text-muted)",
  cursor: "pointer",
  fontSize: 11,
  padding: "4px 8px",
  borderRadius: 4,
};
