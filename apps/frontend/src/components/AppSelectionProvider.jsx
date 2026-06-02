"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "wgs_app_selection_v1";

const AppSelectionContext = createContext(null);

const EMPTY_SELECTION = { selectedProjectId: "", selectedRunId: "", selectedSampleId: "" };

function readStoredSelection() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
    return {
      selectedProjectId: parsed.selectedProjectId || "",
      selectedRunId: parsed.selectedRunId || "",
      selectedSampleId: parsed.selectedSampleId || "",
    };
  } catch {
    return EMPTY_SELECTION;
  }
}

export function AppSelectionProvider({ children }) {
  const [selection, setSelection] = useState(EMPTY_SELECTION);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setSelection(readStoredSelection());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  }, [hydrated, selection]);

  const value = useMemo(() => ({
    ...selection,
    selectionReady: hydrated,
    selectProject(projectId) {
      setSelection((current) => ({
        selectedProjectId: projectId || "",
        selectedRunId: current.selectedProjectId === projectId ? current.selectedRunId : "",
        selectedSampleId: current.selectedProjectId === projectId ? current.selectedSampleId : "",
      }));
    },
    selectRun(run) {
      setSelection({
        selectedProjectId: run?.project_id || "",
        selectedRunId: run?.id || "",
        selectedSampleId: run?.sample_id || "",
      });
    },
    clearRunSelection() {
      setSelection((current) => ({ ...current, selectedRunId: "", selectedSampleId: "" }));
    },
    replaceSelection(nextSelection) {
      setSelection({
        selectedProjectId: nextSelection?.selectedProjectId || "",
        selectedRunId: nextSelection?.selectedRunId || "",
        selectedSampleId: nextSelection?.selectedSampleId || "",
      });
    },
  }), [hydrated, selection]);

  return (
    <AppSelectionContext.Provider value={value}>
      {children}
    </AppSelectionContext.Provider>
  );
}

export function useAppSelection() {
  const context = useContext(AppSelectionContext);
  if (!context) {
    throw new Error("useAppSelection must be used inside AppSelectionProvider");
  }
  return context;
}
