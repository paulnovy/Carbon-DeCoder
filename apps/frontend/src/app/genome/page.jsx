"use client";

import { API_BASE } from "@/lib/api";
import { useState, useEffect, useRef, useCallback } from "react";
import { useAppSelection } from "@/components/AppSelectionProvider";
import { Button, EmptyState, PageHeader, Panel } from "@/components/ui";


const DEFAULT_TRACKS = {
  alignment: true,
  variants: true,
  coverage: true,
  importedVariants: true,
};

const GENE_LOCI_GRCH38 = {
  ACTN3: "chr11:66,560,624-66,572,273",
  APOE: "chr19:44,905,754-44,909,393",
  BRCA1: "chr17:43,044,295-43,125,482",
  BRCA2: "chr13:32,315,086-32,400,268",
  CFTR: "chr7:117,480,025-117,668,665",
  COMT: "chr22:19,929,255-19,957,498",
  FTO: "chr16:53,737,875-54,195,615",
  HFE: "chr6:26,087,508-26,098,429",
  MTHFR: "chr1:11,785,723-11,806,455",
  TP53: "chr17:7,661,779-7,687,550",
};

function resolveLocus(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const gene = GENE_LOCI_GRCH38[raw.toUpperCase()];
  if (gene) return gene;

  const cleaned = raw.replace(/\s+/g, "").replace(/,/g, "");
  const match = cleaned.match(/^(?:chr)?([0-9]{1,2}|X|Y|M|MT):([0-9]+)(?:-([0-9]+))?$/i);
  if (!match) return null;

  const chrom = match[1].toUpperCase() === "MT" ? "M" : match[1].toUpperCase();
  const start = Math.max(1, Number.parseInt(match[2], 10));
  const end = match[3] ? Math.max(start, Number.parseInt(match[3], 10)) : start + 1000;
  return `chr${chrom}:${start}-${end}`;
}

function ContextMetric({ label, value }) {
  return (
    <div style={{ minWidth: 160 }}>
      <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{label}</div>
      <div style={{ marginTop: 3, fontSize: 12, color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", overflowWrap: "anywhere" }}>{value}</div>
    </div>
  );
}

export default function GenomeBrowserPage() {
  const { selectedProjectId, selectedRunId, selectedSampleId, selectionReady } = useAppSelection();
  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [selectedSample, setSelectedSample] = useState(null);
  const [runs, setRuns] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runFiles, setRunFiles] = useState([]);
  const [variants, setVariants] = useState([]);
  const [selectedTracks, setSelectedTracks] = useState(DEFAULT_TRACKS);
  const [locusInput, setLocusInput] = useState("");
  const [activeLocus, setActiveLocus] = useState("chr20:1-64,444,167");
  const [igvReady, setIgvReady] = useState(false);
  const [error, setError] = useState(null);
  const browserRef = useRef(null);
  const igvBrowserRef = useRef(null);

  // Load samples and runs
  useEffect(() => {
    const load = async () => {
      if (!selectionReady) return;
      try {
        const projsRes = await fetch(`${API_BASE}/projects`);
        const projsData = await projsRes.json();
        const projs = projsData.items || [];
        const scopedProjects = selectedProjectId
          ? projs.filter((projectItem) => projectItem.id === selectedProjectId)
          : projs;
        setProject(selectedProjectId ? projs.find((projectItem) => projectItem.id === selectedProjectId) || null : null);
        const allSamples = [];
        const allRuns = [];
        for (const p of scopedProjects) {
          const sRes = await fetch(`${API_BASE}/projects/${p.id}/samples`);
          const sData = await sRes.json();
          for (const s of sData.items || []) {
            allSamples.push({ ...s, project_name: p.name, project_id: p.id });
          }
          const rRes = await fetch(`${API_BASE}/projects/${p.id}/runs`);
          const rData = await rRes.json();
          for (const r of rData.items || []) {
            allRuns.push({ ...r, project_name: p.name });
          }
        }
        setSamples(allSamples);
        setRuns(allRuns);
        const sortedRuns = allRuns.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
        if (sortedRuns.length > 0) {
          const latest = sortedRuns.find((run) => run.id === selectedRunId) || sortedRuns[0];
          setSelectedSample(latest.sample_id);
          setSelectedRun(latest);
        } else if (allSamples.length > 0) {
          const preferredSample = allSamples.find((sample) => sample.id === selectedSampleId || sample.sample_id === selectedSampleId);
          setSelectedSample(preferredSample?.id || allSamples[0].id);
          setSelectedRun(null);
        } else {
          setSelectedSample(null);
          setSelectedRun(null);
        }
      } catch (e) {
        setProject(null);
        setSamples([]);
        setRuns([]);
        setSelectedSample(null);
        setSelectedRun(null);
        setError("Failed to load projects: " + e.message);
      }
    };
    load();
  }, [selectionReady, selectedProjectId, selectedRunId, selectedSampleId]);

  // When run changes, fetch its files
  useEffect(() => {
    if (!selectedRun) {
      setRunFiles([]);
      return;
    }
    const loadFiles = async () => {
      try {
        const res = await fetch(`${API_BASE}/runs/${selectedRun.id}/files`);
        const data = await res.json();
        setRunFiles(data.files || []);
      } catch {
        setRunFiles([]);
      }
    };
    loadFiles();
  }, [selectedRun?.id]);

  // When sample changes, load variants
  useEffect(() => {
    if (!selectedSample) {
      setVariants([]);
      return;
    }
    const loadVars = async () => {
      try {
        const params = selectedRun?.id ? `?run_id=${encodeURIComponent(selectedRun.id)}` : "";
        const res = await fetch(`${API_BASE}/samples/${selectedSample}/variants${params}`);
        const data = await res.json();
        setVariants(data.items || []);
      } catch {
        setVariants([]);
      }
    };
    loadVars();
  }, [selectedSample, selectedRun?.id]);

  // Build IGV tracks from run files
  const buildTracks = useCallback(() => {
    const tracks = [];
    const bam = runFiles.find(f => f.kind === "bam" && !f.name.includes(".mt."));
    const vcf = runFiles.find(f => f.kind === "vcf" && f.name.endsWith(".vcf")) || runFiles.find(f => f.kind === "vcf" && f.name.endsWith(".vcf.gz"));
    const cov = runFiles.find(f => f.kind === "coverage");

    if (selectedTracks.alignment && bam) {
      const bai = runFiles.find(f => f.kind === "bai" && f.name === bam.name + ".bai");
      if (bai) {
        tracks.push({
          name: "Alignments",
          type: "alignment",
          format: "bam",
          url: `${API_BASE}${bam.url}`,
          indexURL: `${API_BASE}${bai.url}`,
          displayMode: "EXPANDED",
          height: 200,
        });
      }
    }

    if (selectedTracks.variants && vcf) {
      const tbi = runFiles.find(f => f.kind === "tbi" && f.name === `${vcf.name}.tbi` && (f.size || 0) > 100);
      const track = {
        name: "Variants (bcftools)",
        type: "variant",
        format: "vcf",
        url: `${API_BASE}${vcf.url}`,
        displayMode: "EXPANDED",
        height: 100,
      };
      if (tbi) {
        track.indexURL = `${API_BASE}${tbi.url}`;
        track.indexType = "tbi";
      }
      tracks.push(track);
    }

    if (selectedTracks.coverage && cov) {
      tracks.push({
        name: "Coverage (mosdepth)",
        type: "wig",
        format: "bedgraph",
        url: `${API_BASE}${cov.url}`,
        displayMode: "COLLAPSED",
        height: 80,
        color: "#3ecf8e",
      });
    }

    // Add in-memory variant features if no VCF file available
    if (selectedTracks.importedVariants && !vcf && variants.length > 0) {
      tracks.push({
        name: "Variants (imported)",
        type: "variant",
        format: "vcf",
        features: variants.map((v) => ({
          chr: v.chrom,
          start: (v.pos || v.start || 1) - 1,
          end: v.pos || v.start || 1,
          alleles: [v.ref || ".", v.alt || "."],
          type: v.variant_type || "SNV",
        })),
        displayMode: "EXPANDED",
        height: 100,
      });
    }

    return tracks;
  }, [runFiles, variants, selectedTracks]);

  // Create/update IGV browser
  useEffect(() => {
    if (typeof window === "undefined" || !browserRef.current) return;
    const tracks = buildTracks();
    const locus = activeLocus || (tracks.length > 0 ? "chr20:1-64,444,167" : "chr20:1-20000");

    // Destroy previous browser
    if (igvBrowserRef.current) {
      try { igvBrowserRef.current.removeAllTracks(); } catch {}
    }

    import("igv/dist/igv.esm").then((igv) => {
      if (!browserRef.current) return;
      const createFn = igv.createBrowser || igv.default?.createBrowser;
      if (!createFn) {
        setError("IGV.js: createBrowser not found");
        return;
      }

      // If browser already exists, just update tracks
      if (igvBrowserRef.current) {
        for (const track of tracks) {
          try { igvBrowserRef.current.loadTrack(track); } catch {}
        }
        setIgvReady(true);
        return;
      }

      createFn(browserRef.current, {
        genome: "hg38",
        locus,
        tracks,
      }).then((browser) => {
        igvBrowserRef.current = browser;
        setIgvReady(true);
        setError(null);
      }).catch((e) => {
        setError("IGV init error: " + e.message);
      });
    }).catch((e) => {
      setError("Failed to load IGV.js: " + e.message);
    });
  }, [buildTracks, activeLocus]);

  // Jump to locus handler
  const jumpToLocus = (locus) => {
    setActiveLocus(locus);
    if (igvBrowserRef.current) {
      igvBrowserRef.current.search(locus);
    }
    setError(null);
  };

  const handleJump = () => {
    const locus = resolveLocus(locusInput);
    if (!locus) {
      setError("Enter a region like chr17:43,044,295-43,125,482 or a supported gene symbol.");
      return;
    }
    jumpToLocus(locus);
  };

  const bamFile = runFiles.find(f => f.kind === "bam" && !f.name.includes(".mt."));
  const vcfFile = runFiles.find(f => f.kind === "vcf" && f.name.endsWith(".vcf")) || runFiles.find(f => f.kind === "vcf" && f.name.endsWith(".vcf.gz"));
  const covFile = runFiles.find(f => f.kind === "coverage");
  const importedVariantsAvailable = !vcfFile && variants.length > 0;
  const trackOptions = [
    { key: "alignment", label: "BAM", available: !!bamFile, detail: bamFile?.name },
    { key: "variants", label: "VCF", available: !!vcfFile, detail: vcfFile?.name },
    { key: "coverage", label: "Coverage", available: !!covFile, detail: covFile?.name },
    { key: "importedVariants", label: "Imported variants", available: importedVariantsAvailable, detail: importedVariantsAvailable ? `${variants.length} imported` : null },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Genome view"
        title="Genome Browser"
        description="Interactive IGV.js view for run-scoped BAM, VCF, coverage, and imported variant evidence."
      />

      {/* Controls */}
      <Panel title="Browser context" description="Choose a run, jump to a gene/region, and toggle the evidence tracks loaded into IGV.">
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <ContextMetric label="Project" value={project?.name || selectedProjectId || "Select in Projects"} />
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Run:</label>
            <select
              value={selectedRun?.id || ""}
              onChange={(e) => {
                const r = runs.find(x => x.id === e.target.value);
                setSelectedRun(r || null);
                if (r) setSelectedSample(r.sample_id);
                igvBrowserRef.current = null;
                setIgvReady(false);
              }}
              className="form-control"
              style={{ minWidth: 260 }}
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>{r.project_name} — {r.id.slice(0, 12)} ({r.status})</option>
              ))}
              {runs.length === 0 && <option value="">No runs available</option>}
            </select>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Jump to:</label>
            <input
              type="text"
              value={locusInput}
              onChange={(e) => setLocusInput(e.target.value)}
              placeholder="BRCA1 or chr17:43,044,295-43,125,482"
              onKeyDown={(e) => { if (e.key === "Enter") handleJump(); }}
              className="form-control"
              style={{ minWidth: 260 }}
            />
            <Button onClick={handleJump} variant="primary">Go</Button>
          </div>

          <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
            {activeLocus}
          </div>
        </div>

        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8 }}>
          {trackOptions.map((track) => (
            <label key={track.key} style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              padding: "8px 10px",
              border: "1px solid var(--color-border-default)",
              borderRadius: 6,
              background: track.available ? "var(--color-bg-elevated)" : "var(--color-bg-base)",
              opacity: track.available ? 1 : 0.45,
              cursor: track.available ? "pointer" : "not-allowed",
            }}>
              <input
                type="checkbox"
                checked={!!selectedTracks[track.key]}
                disabled={!track.available}
                onChange={(e) => {
                  setSelectedTracks((prev) => ({ ...prev, [track.key]: e.target.checked }));
                  igvBrowserRef.current = null;
                  setIgvReady(false);
                }}
                style={{ marginTop: 2 }}
              />
              <span>
                <span style={{ display: "block", fontSize: 13, fontWeight: 600 }}>{track.label}</span>
                <span style={{ display: "block", fontSize: 11, color: "var(--color-text-muted)", overflowWrap: "anywhere" }}>
                  {track.detail || "not available for this run"}
                </span>
              </span>
            </label>
          ))}
        </div>

        {error && (
          <div style={{ marginTop: 8, padding: "6px 12px", background: "#ef444422", color: "#f87171", borderRadius: 6, fontSize: 13 }}>
            {error}
          </div>
        )}
      </Panel>

      {/* IGV browser */}
      <Panel style={{ overflow: "hidden" }}>
        <div ref={browserRef} style={{ minHeight: 500, background: "#0d1117" }} />
        {!igvReady && (
          <div style={{ padding: 60, textAlign: "center" }}>
            <div style={{ fontSize: 40, marginBottom: 16, opacity: 0.3 }}>🧬</div>
            <p style={{ color: "var(--color-text-muted)", fontSize: 14 }}>
              {runs.length === 0
                ? "No runs available for the selected project."
                : "Loading genome browser…"}
            </p>
          </div>
        )}
      </Panel>

      {/* Variant quick-view table */}
      {variants.length > 0 && (
        <Panel title={`Variants (${variants.length})`} description="Quick jump list for imported variants. The table is capped to keep the browser responsive.">
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--color-border-default)" }}>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Chrom</th>
                  <th style={{ textAlign: "right", padding: "6px 8px" }}>Position</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Ref</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Alt</th>
                  <th style={{ textAlign: "left", padding: "6px 8px" }}>Type</th>
                  <th style={{ textAlign: "center", padding: "6px 8px" }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {variants.slice(0, 50).map((v, i) => (
                  <tr key={v.id || i} style={{ borderBottom: "1px solid var(--color-border-default)10" }}>
                    <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)" }}>{v.chrom}</td>
                    <td style={{ padding: "4px 8px", textAlign: "right", fontFamily: "var(--font-mono)" }}>{(v.pos || v.start)?.toLocaleString()}</td>
                    <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)" }}>{v.ref}</td>
                    <td style={{ padding: "4px 8px", fontFamily: "var(--font-mono)" }}>{v.alt}</td>
                    <td style={{ padding: "4px 8px" }}>{v.variant_type || "SNV"}</td>
                    <td style={{ padding: "4px 8px", textAlign: "center" }}>
                      <Button
                        onClick={() => {
                          const locus = `${v.chrom}:${Math.max(1, (v.pos || v.start) - 500)}-${(v.pos || v.start) + 500}`;
                          setLocusInput(locus);
                          jumpToLocus(locus);
                        }}
                        size="sm"
                        variant="primary"
                      >
                        View
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {variants.length > 50 && (
            <p style={{ textAlign: "center", color: "var(--color-text-muted)", fontSize: 12, marginTop: 8 }}>
              Showing first 50 of {variants.length} variants
            </p>
          )}
        </Panel>
      )}
      {variants.length === 0 && (
        <EmptyState title="No imported variants" description="Load a run with imported variants or enable BAM/VCF tracks from run files." />
      )}
    </div>
  );
}
