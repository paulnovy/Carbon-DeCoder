#!/usr/bin/env bash
set -euo pipefail

sample_id="$1"
reference_fasta="$2"
r1="$3"
r2="$4"
threads="${5:-2}"
allow_dev_fallback="${6:-true}"

out_bam="${sample_id}.sorted.markdup.bam"
out_bai="${out_bam}.bai"
flagstat="${sample_id}.flagstat.txt"
idxstats="${sample_id}.idxstats.txt"
ingest="${sample_id}.alignment.ingest.json"
name_sorted_bam="${sample_id}.name_sorted.bam"
fixmate_bam="${sample_id}.fixmate.bam"
coord_sorted_bam="${sample_id}.coord_sorted.bam"
tmp_root="${sample_id}.alignment_tmp"
scratch_root="${WGS_ALIGNMENT_SCRATCH_ROOT:-}"
if [[ -n "$scratch_root" ]]; then
  mkdir -p "$scratch_root"
  tmp_dir="${scratch_root%/}/${tmp_root}.$$"
else
  tmp_dir="${tmp_root}.$$"
fi

cleanup_tmp() {
  rm -rf "$tmp_dir"
}
trap cleanup_tmp EXIT INT TERM

have_real_tools=true
if ! command -v samtools >/dev/null 2>&1; then
  have_real_tools=false
fi
if ! command -v bwa >/dev/null 2>&1 \
  && ! command -v bwa-mem2 >/dev/null 2>&1 \
  && ! command -v minimap2 >/dev/null 2>&1 \
  && ! command -v bwa-mem2.avx512 >/dev/null 2>&1 \
  && ! command -v bwa-mem2.avx2 >/dev/null 2>&1 \
  && ! command -v bwa-mem2.sse42 >/dev/null 2>&1 \
  && ! command -v bwa-mem2.sse41 >/dev/null 2>&1; then
  have_real_tools=false
fi

ref_ready=true
if [[ ! -s "$reference_fasta" ]]; then
  ref_ready=false
fi

bwa_mem2_index_ready() {
  local suffix
  for suffix in ".0123" ".amb" ".ann" ".bwt.2bit.64" ".pac"; do
    if [[ ! -s "${reference_fasta}${suffix}" ]]; then
      return 1
    fi
  done
  return 0
}

bwa_mem2_index_missing() {
  local suffix
  local missing=()
  for suffix in ".0123" ".amb" ".ann" ".bwt.2bit.64" ".pac"; do
    if [[ ! -s "${reference_fasta}${suffix}" ]]; then
      missing+=("${reference_fasta}${suffix}")
    fi
  done
  local IFS=", "
  echo "${missing[*]}"
}

classic_bwa_index_ready() {
  local suffix
  for suffix in ".amb" ".ann" ".bwt" ".pac" ".sa"; do
    if [[ ! -s "${reference_fasta}${suffix}" ]]; then
      return 1
    fi
  done
  return 0
}

classic_bwa_index_missing() {
  local suffix
  local missing=()
  for suffix in ".amb" ".ann" ".bwt" ".pac" ".sa"; do
    if [[ ! -s "${reference_fasta}${suffix}" ]]; then
      missing+=("${reference_fasta}${suffix}")
    fi
  done
  local IFS=", "
  echo "${missing[*]}"
}

find_bwa_mem2_binary() {
  local candidate
  for candidate in bwa-mem2.avx512 bwa-mem2.avx2 bwa-mem2.sse42 bwa-mem2.sse41 bwa-mem2; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

valid_bam() {
  local bam="$1"
  [[ -s "$bam" ]] && command -v samtools >/dev/null 2>&1 && samtools quickcheck "$bam" >/dev/null 2>&1
}

stage_bam() {
  local tmp_bam="$1"
  local final_bam="$2"
  if ! valid_bam "$tmp_bam"; then
    echo "[alignment] refusing invalid temporary BAM: ${tmp_bam}" >&2
    rm -f "$tmp_bam"
    return 1
  fi
  mv -f "$tmp_bam" "$final_bam"
}

remove_invalid_bam_if_present() {
  local bam="$1"
  if [[ -e "$bam" ]] && ! valid_bam "$bam"; then
    echo "[alignment] removing invalid stale BAM checkpoint: ${bam}" >&2
    rm -f "$bam"
  fi
}

run_real=false
if [[ "$have_real_tools" == "true" && "$ref_ready" == "true" ]]; then
  run_real=true
fi

if [[ "$run_real" == "true" ]]; then
  find . -maxdepth 1 -type d -name "${tmp_root}.*" -exec rm -rf {} +
  if [[ -n "$scratch_root" && -d "$scratch_root" ]]; then
    find "$scratch_root" -maxdepth 1 -type d -name "${tmp_root}.*" -exec rm -rf {} +
  fi
  find . -maxdepth 1 -type f \( -name "${sample_id}*.bam.tmp.*.bam" -o -name "${sample_id}*.cram.tmp.*.cram" \) -delete
  mkdir -p "$tmp_dir"
  remove_invalid_bam_if_present "$out_bam"
  remove_invalid_bam_if_present "$name_sorted_bam"
  remove_invalid_bam_if_present "$fixmate_bam"
  remove_invalid_bam_if_present "$coord_sorted_bam"

  if valid_bam "$out_bam"; then
    echo "[alignment] reusing complete BAM checkpoint: ${out_bam}" >&2
    if [[ ! -s "$out_bai" ]]; then
      samtools index -@ "$threads" "$out_bam"
    fi
    samtools flagstat -@ "$threads" "$out_bam" > "$flagstat"
    samtools idxstats "$out_bam" > "$idxstats"
    mode="real_resumed_complete"
    run_real="complete"
  fi
fi

if [[ "$run_real" == "true" ]]; then
  requested_backend="${WGS_ALIGNMENT_BACKEND:-auto}"
  ALIGNER=""
  ALIGNER_MEM_CMD=()

  if [[ "$requested_backend" == "minimap2" || "$requested_backend" == "auto" ]] && command -v minimap2 >/dev/null 2>&1; then
    # minimap2 can align short reads directly against FASTA without a large
    # prebuilt BWA-style index, which is useful on 32 GB hosts.
    ALIGNER="minimap2"
    ALIGNER_MEM_CMD=(minimap2 -ax sr -t "$threads")
  elif [[ "$requested_backend" == "bwa-mem2" || "$requested_backend" == "auto" ]]; then
    BWA_MEM2="$(find_bwa_mem2_binary || true)"
    if [[ -z "$BWA_MEM2" ]]; then
      if [[ "$requested_backend" == "bwa-mem2" ]]; then
        echo "[alignment] bwa-mem2 backend selected but bwa-mem2 binary is not installed" >&2
        run_real=false
      fi
    elif ! bwa_mem2_index_ready; then
      if [[ "$requested_backend" == "bwa-mem2" ]]; then
        echo "[alignment] bwa-mem2 index missing for ${reference_fasta}" >&2
        echo "[alignment] missing: $(bwa_mem2_index_missing)" >&2
        run_real=false
      fi
    else
      ALIGNER="$BWA_MEM2"
      ALIGNER_MEM_CMD=("$BWA_MEM2" mem -t "$threads")
    fi
  elif [[ "$requested_backend" == "bwa" || "$requested_backend" == "auto" ]]; then
    ALIGNER="bwa"
    ALIGNER_MEM_CMD=(bwa mem -t "$threads")
  else
    echo "[alignment] unsupported backend requested: ${requested_backend}" >&2
    run_real=false
  fi

  if [[ "$run_real" == "true" && -z "$ALIGNER" && "$requested_backend" == "auto" ]]; then
    if command -v bwa >/dev/null 2>&1 && classic_bwa_index_ready; then
      ALIGNER="bwa"
      ALIGNER_MEM_CMD=(bwa mem -t "$threads")
    else
      echo "[alignment] no usable auto alignment backend for ${reference_fasta}" >&2
      if ! command -v minimap2 >/dev/null 2>&1; then
        echo "[alignment] minimap2 missing" >&2
      fi
      if ! bwa_mem2_index_ready; then
        echo "[alignment] bwa-mem2 index missing: $(bwa_mem2_index_missing)" >&2
      fi
      if ! classic_bwa_index_ready; then
        echo "[alignment] classic bwa index missing: $(classic_bwa_index_missing)" >&2
      fi
      run_real=false
    fi
  fi

  if [[ "$ALIGNER" == "bwa" && ! classic_bwa_index_ready ]]; then
    echo "[alignment] classic bwa index missing for ${reference_fasta}" >&2
    echo "[alignment] missing: $(classic_bwa_index_missing)" >&2
    run_real=false
  elif [[ "$ALIGNER" == bwa-mem2* ]] && ! bwa_mem2_index_ready; then
    echo "[alignment] bwa-mem2 index missing for ${reference_fasta}" >&2
    echo "[alignment] missing: $(bwa_mem2_index_missing)" >&2
    run_real=false
  elif [[ "$ALIGNER" == bwa-mem2* ]] && ! "$ALIGNER" version >/dev/null 2>&1; then
    echo "[alignment] bwa-mem2 binary ($ALIGNER) failed version check" >&2
    run_real=false
  fi
fi

if [[ "$run_real" == "true" ]]; then
  echo "[alignment] running ${ALIGNER} + samtools for ${sample_id}" >&2

  # Set up live SAM parser for real-time metrics
  # Write to cwd which is /data/results/{run_id} when called from API
  LIVE_METRICS_FILE="$(pwd)/live_metrics.json"
  LIVE_RUN_ID="$(basename "$(pwd)")"
  LIVE_PARSER_SCRIPT=""
  for candidate in \
    "/app/app/core/live_sam_parser.py" \
    "/workspace/apps/api/app/core/live_sam_parser.py" \
    "/tmp/nf-pipeline/apps/api/app/core/live_sam_parser.py" \
    "./apps/api/app/core/live_sam_parser.py" \
    "./app/core/live_sam_parser.py"; do
    if [[ -f "$candidate" ]]; then
      LIVE_PARSER_SCRIPT="$candidate"
      break
    fi
  done

  mkdir -p "$(pwd)"

  if [[ -n "$LIVE_PARSER_SCRIPT" ]]; then
    echo "[alignment] live parser active: ${LIVE_PARSER_SCRIPT}" >&2
    LIVE_PARSER_ARGS=(--run-id "$LIVE_RUN_ID" --sample-id "${sample_id}" --backend "$ALIGNER" --metrics-file "$LIVE_METRICS_FILE")
    if [[ -n "${WGS_TOTAL_READS_ESTIMATE:-}" ]]; then
      LIVE_PARSER_ARGS+=(--total-reads "$WGS_TOTAL_READS_ESTIMATE")
      if [[ "${WGS_TOTAL_READS_ESTIMATE_EXACT:-false}" != "true" ]]; then
        LIVE_PARSER_ARGS+=(--total-reads-estimated)
      fi
      if [[ -n "${WGS_TOTAL_READS_ESTIMATE_SOURCE:-}" ]]; then
        LIVE_PARSER_ARGS+=(--total-reads-source "$WGS_TOTAL_READS_ESTIMATE_SOURCE")
      fi
    fi
    if valid_bam "$name_sorted_bam"; then
      echo "[alignment] reusing name-sorted BAM checkpoint: ${name_sorted_bam}" >&2
    elif "${ALIGNER_MEM_CMD[@]}" "$reference_fasta" "$r1" "$r2" \
      | python3 "$LIVE_PARSER_SCRIPT" "${LIVE_PARSER_ARGS[@]}" \
      | samtools sort -@ "$threads" -n -o "$tmp_dir/$name_sorted_bam" - 2>/dev/null \
      && stage_bam "$tmp_dir/$name_sorted_bam" "$name_sorted_bam"; then
      echo "[alignment] wrote name-sorted BAM checkpoint: ${name_sorted_bam}" >&2
    else
      echo "[alignment] ${ALIGNER} failed at runtime, falling back" >&2
      run_real=false
    fi
  else
    echo "[alignment] live parser not found, running without live metrics" >&2
    if valid_bam "$name_sorted_bam"; then
      echo "[alignment] reusing name-sorted BAM checkpoint: ${name_sorted_bam}" >&2
    elif "${ALIGNER_MEM_CMD[@]}" "$reference_fasta" "$r1" "$r2" \
      | samtools sort -@ "$threads" -n -o "$tmp_dir/$name_sorted_bam" - 2>/dev/null \
      && stage_bam "$tmp_dir/$name_sorted_bam" "$name_sorted_bam"; then
      echo "[alignment] wrote name-sorted BAM checkpoint: ${name_sorted_bam}" >&2
    else
      echo "[alignment] ${ALIGNER} failed at runtime, falling back" >&2
      run_real=false
    fi
  fi

  if [[ "$run_real" == "true" ]]; then
    if valid_bam "$coord_sorted_bam"; then
      echo "[alignment] reusing coordinate-sorted BAM checkpoint: ${coord_sorted_bam}" >&2
    else
      if valid_bam "$fixmate_bam"; then
        echo "[alignment] reusing fixmate BAM checkpoint: ${fixmate_bam}" >&2
      else
        samtools fixmate -@ "$threads" -m "$name_sorted_bam" "$tmp_dir/$fixmate_bam"
        stage_bam "$tmp_dir/$fixmate_bam" "$fixmate_bam"
      fi
      samtools sort -@ "$threads" -o "$tmp_dir/$coord_sorted_bam" "$fixmate_bam"
      stage_bam "$tmp_dir/$coord_sorted_bam" "$coord_sorted_bam"
    fi
    min_free_gb="${WGS_MARKDUP_MIN_FREE_GB:-0}"
    if [[ "$min_free_gb" =~ ^[0-9]+$ && "$min_free_gb" -gt 0 ]]; then
      free_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
      free_bytes=$((free_kb * 1024))
      required_bytes=$((min_free_gb * 1024 * 1024 * 1024))
      coord_bytes="$(stat -c%s "$coord_sorted_bam" 2>/dev/null || echo 0)"
      if [[ "$free_bytes" -lt "$required_bytes" ]]; then
        echo "[alignment] pausing before markdup: free disk below ${min_free_gb}GB threshold" >&2
        cat > "${sample_id}.alignment.disk_pressure.json" <<JSON
{
  "reason": "disk_pressure_before_markdup",
  "free_bytes": ${free_bytes},
  "required_free_bytes": ${required_bytes},
  "min_free_gb_before_markdup": ${min_free_gb},
  "coord_sorted_bam": "${coord_sorted_bam}",
  "coord_sorted_bam_bytes": ${coord_bytes},
  "scratch_root": "${scratch_root}"
}
JSON
        exit 75
      fi
    fi
    samtools markdup -@ "$threads" "$coord_sorted_bam" "$tmp_dir/$out_bam"
    stage_bam "$tmp_dir/$out_bam" "$out_bam"
    samtools index -@ "$threads" "$out_bam"
    samtools flagstat -@ "$threads" "$out_bam" > "$flagstat"
    samtools idxstats "$out_bam" > "$idxstats"
    rm -f "$name_sorted_bam" "$fixmate_bam" "$coord_sorted_bam"
    mode="real"
  fi
fi

if [[ "$run_real" == "complete" ]]; then
  :
elif [[ "$run_real" != "true" ]]; then
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[alignment] missing real tools or reference and fallback disabled" >&2
    echo "[alignment] bwa-mem2/samtools present=${have_real_tools}; reference_ready=${ref_ready}" >&2
    exit 127
  fi

  echo "[alignment] dev fallback for ${sample_id}; real tools/reference not available" >&2
  printf 'WGS_COCKPIT_DEV_FALLBACK_BAM\n' > "$out_bam"
  printf 'WGS_COCKPIT_DEV_FALLBACK_BAI\n' > "$out_bai"
  cat > "$flagstat" <<'EOF'
1000 + 0 in total (QC-passed reads + QC-failed reads)
970 + 0 mapped (97.00% : N/A)
940 + 0 properly paired (94.00% : N/A)
80 + 0 duplicates
EOF
  cat > "$idxstats" <<'EOF'
chr1	1000000	970	30
*	0	0	30
EOF
  mode="dev_fallback"
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "alignment",
  "payload": {
    "flagstat_txt": "${flagstat}",
    "idxstats_txt": "${idxstats}",
    "source_files": ["${out_bam}", "${out_bai}", "${flagstat}", "${idxstats}"],
    "alignment_mode": "${mode}"
  }
}
JSON
