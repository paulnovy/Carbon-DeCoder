#!/usr/bin/env bash
set -euo pipefail

# Taxonomy classification stage. For human WGS, prefer host-depleted reads
# extracted from the final alignment BAM; fall back to raw FASTQ only when no
# usable BAM is available.
# Usage: run_taxonomy_stage.sh <sample_id> <r1.fastq.gz> <r2.fastq.gz> <threads> <allow_dev_fallback> [kraken2_db] [host_bam] [taxonomy_route] [low_mapq_threshold]

sample_id="$1"
r1="$2"
r2="$3"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"
kraken_db="${6:-}"
host_bam="${7:-}"
taxonomy_route="${8:-${WGS_TAXONOMY_ROUTE:-human_wgs_host_depleted}}"
low_mapq_threshold="${9:-${WGS_TAXONOMY_LOW_MAPQ_THRESHOLD:-10}}"

kraken_report="${sample_id}.kraken2.report"
bracken_tsv="${sample_id}.bracken.tsv"
bracken_log="${sample_id}.bracken.log"
ingest="${sample_id}.taxonomy.ingest.json"
kraken_output="${sample_id}.kraken2.output"

# Avoid mixing stale taxonomy artifacts from an earlier database/route with a
# fresh run. Host-depleted FASTQs are managed separately by the extraction step.
rm -f "$kraken_report" "$kraken_output" "$bracken_tsv" "$bracken_log" "$ingest"

have_kraken=false
if command -v kraken2 >/dev/null 2>&1; then
  have_kraken=true
fi

taxonomy_input_mode="raw_fastq"
taxonomy_r1="$r1"
taxonomy_r2="$r2"
host_unmapped_count=""
taxonomy_analysis_version="taxonomy-route-v1"
taxonomy_refinement="none"
taxonomy_refinement_status="not_requested"
bracken_level="${WGS_BRACKEN_LEVEL:-S}"
bracken_read_length="${WGS_BRACKEN_READ_LENGTH:-150}"

count_fastq_records() {
  local fq="$1"
  if [[ ! -s "$fq" ]]; then
    echo 0
    return
  fi
  if [[ "$fq" == *.gz ]]; then
    gzip -cd "$fq" | awk 'END {print int(NR / 4)}'
  else
    awk 'END {print int(NR / 4)}' "$fq"
  fi
}

extract_host_depleted_fastqs() {
  local mode="$1"
  local out_r1="${sample_id}.host_unmapped_R1.fastq"
  local out_r2="${sample_id}.host_unmapped_R2.fastq"
  rm -f "$out_r1" "$out_r2" "${out_r1}.gz" "${out_r2}.gz"

  if [[ "$mode" == "sensitive_low_mapq" ]]; then
    samtools view -h "$host_bam" \
      | python3 -c 'import sys
threshold = int(sys.argv[1])
for line in sys.stdin:
    if line.startswith("@"):
        sys.stdout.write(line)
        continue
    fields = line.split("\t")
    if len(fields) < 5:
        continue
    flag = int(fields[1])
    mapq = int(fields[4])
    if (flag & 4) or (flag & 8) or mapq <= threshold:
        sys.stdout.write(line)
' "$low_mapq_threshold" \
      | samtools fastq -@ "$threads" \
        -1 "$out_r1" \
        -2 "$out_r2" \
        -0 /dev/null \
        -s /dev/null \
        -n - >/dev/null
  else
    samtools fastq -@ "$threads" -f 12 \
      -1 "$out_r1" \
      -2 "$out_r2" \
      -0 /dev/null \
      -s /dev/null \
      -n "$host_bam" >/dev/null
  fi

  gzip -f "$out_r1" "$out_r2"
  taxonomy_r1="${out_r1}.gz"
  taxonomy_r2="${out_r2}.gz"
  host_unmapped_count="$(( $(count_fastq_records "$taxonomy_r1") + $(count_fastq_records "$taxonomy_r2") ))"
}

if [[ "$taxonomy_route" == "full_fastq_shotgun" ]]; then
  echo "[taxonomy] full FASTQ shotgun route selected; host depletion disabled" >&2
elif command -v samtools >/dev/null 2>&1 \
  && [[ -n "${host_bam:-}" ]] \
  && [[ -s "$host_bam" ]] \
  && samtools quickcheck "$host_bam" >/dev/null 2>&1; then
  if [[ "$taxonomy_route" == "human_wgs_sensitive_low_mapq" ]]; then
    echo "[taxonomy] extracting sensitive host-depleted reads from ${host_bam} (unmapped/mate-unmapped/MAPQ<=${low_mapq_threshold})" >&2
    extract_host_depleted_fastqs "sensitive_low_mapq"
    taxonomy_input_mode="host_depleted_bam_sensitive_low_mapq"
  else
    host_unmapped_count="$(samtools view -c -f 12 "$host_bam" 2>/dev/null || echo 0)"
    if [[ "${host_unmapped_count:-0}" -gt 0 ]]; then
      echo "[taxonomy] extracting host-depleted reads from ${host_bam} (${host_unmapped_count} both-unmapped records)" >&2
      extract_host_depleted_fastqs "both_unmapped"
    fi
    taxonomy_input_mode="host_depleted_bam_unmapped_pairs"
  fi
  if [[ "${host_unmapped_count:-0}" -le 0 ]]; then
    echo "[taxonomy] host-depleted extraction produced no paired reads; falling back to raw FASTQ" >&2
    taxonomy_input_mode="raw_fastq"
    taxonomy_r1="$r1"
    taxonomy_r2="$r2"
  else
    echo "[taxonomy] host-depleted taxonomy input ready (${host_unmapped_count} FASTQ records, route=${taxonomy_route})" >&2
  fi
else
  echo "[taxonomy] no valid host BAM for depletion; falling back to raw FASTQ" >&2
fi

# Auto-detect DB path if not provided: find first dir with hash.k2d under /data/databases/kraken2/
if [[ -z "$kraken_db" ]]; then
  for candidate in /data/databases/kraken2/*/hash.k2d; do
    if [[ -f "$candidate" ]]; then
      kraken_db="$(dirname "$candidate")"
      break
    fi
  done
  # fallback: maybe hash.k2d is directly in parent dir
  if [[ -z "${kraken_db:-}" && -f /data/databases/kraken2/hash.k2d ]]; then
    kraken_db="/data/databases/kraken2"
  fi
fi

if [[ "$have_kraken" == "true" && -n "${kraken_db:-}" && -d "$kraken_db" ]]; then
  echo "[taxonomy] running Kraken2 for ${sample_id} (db=${kraken_db}, input=${taxonomy_input_mode})" >&2
  kraken_args=(
    --db "$kraken_db"
    --paired
    --threads "$threads"
    --report "$kraken_report"
    --output "$kraken_output"
  )
  if [[ "${WGS_KRAKEN_MEMORY_MAPPING:-auto}" != "false" ]]; then
    kraken_args+=(--memory-mapping)
    echo "[taxonomy] using Kraken2 memory mapping for database load" >&2
  fi
  kraken2 "${kraken_args[@]}" \
    "$taxonomy_r1" "$taxonomy_r2" 2>&1 | tail -10

  # Optional Bracken abundance re-estimation if the DB has Bracken k-mer data.
  # Bracken is a refinement layer; lack of Bracken must not turn a valid Kraken2
  # classification into a failed taxonomy stage.
  if command -v bracken >/dev/null 2>&1; then
    if bracken -d "$kraken_db" -i "$kraken_report" -o "$bracken_tsv" -r "$bracken_read_length" -l "$bracken_level" -t 10 > "$bracken_log" 2>&1; then
      taxonomy_refinement="bracken"
      taxonomy_refinement_status="applied"
      taxonomy_analysis_version="taxonomy-route-v1+bracken"
      taxonomy_mode="kraken2+bracken"
      tail -5 "$bracken_log" >&2 || true
    else
      taxonomy_refinement="bracken"
      taxonomy_refinement_status="failed"
      echo "[taxonomy] Bracken refinement failed; using Kraken2 report for import" >&2
      tail -10 "$bracken_log" >&2 || true
      cp "$kraken_report" "$bracken_tsv"
      taxonomy_mode="kraken2"
    fi
  else
    taxonomy_refinement="bracken"
    taxonomy_refinement_status="tool_missing"
    echo "[taxonomy] Bracken not installed; using Kraken2 report for import" >&2
    echo "Bracken not installed; using Kraken2 report for import" > "$bracken_log"
    cp "$kraken_report" "$bracken_tsv"
    taxonomy_mode="kraken2"
  fi
else
  if [[ "$allow_dev_fallback" != "true" ]]; then
    echo "[taxonomy] missing Kraken2 or DB and fallback disabled" >&2
    echo "[taxonomy] kraken2=${have_kraken}; db_exists=$(test -d "${kraken_db:-}" && echo true || echo false)" >&2
    exit 127
  fi

  echo "[taxonomy] dev fallback for ${sample_id}; Kraken2/DB not available; emitting empty non-diagnostic taxonomy artifact" >&2
  cat > "$kraken_report" <<'EOF'
100.00	0	0	U	0		Unclassified
EOF
  cat > "$bracken_tsv" <<'EOF'
organism	kingdom	read_count	confidence	evidence_score	tools	likely_contaminant	warning
EOF
  taxonomy_mode="dev_fallback"
  taxonomy_refinement="none"
  taxonomy_refinement_status="dev_fallback"
  echo "Dev fallback taxonomy; Bracken not run" > "$bracken_log"
fi

cat > "$ingest" <<JSON
{
  "event_type": "run.ingest.request",
  "stage": "taxonomy",
  "payload": {
    "taxonomy_report_path": "${bracken_tsv}",
    "source_files": ["${kraken_report}", "${bracken_tsv}", "${bracken_log}"],
    "taxonomy_mode": "${taxonomy_mode}",
    "taxonomy_refinement": "${taxonomy_refinement}",
    "taxonomy_refinement_status": "${taxonomy_refinement_status}",
    "kraken_report_path": "${kraken_report}",
    "bracken_report_path": "${bracken_tsv}",
    "bracken_level": "${bracken_level}",
    "bracken_read_length": "${bracken_read_length}",
    "taxonomy_route": "${taxonomy_route}",
    "taxonomy_analysis_id": "${sample_id}.${taxonomy_route}.${taxonomy_mode}",
    "taxonomy_analysis_version": "${taxonomy_analysis_version}",
    "taxonomy_input_mode": "${taxonomy_input_mode}",
    "taxonomy_input_r1": "${taxonomy_r1}",
    "taxonomy_input_r2": "${taxonomy_r2}",
    "taxonomy_database": "${kraken_db}",
    "taxonomy_database_version": "$(basename "${kraken_db:-unknown}")",
    "taxonomy_extraction_params": {
      "route": "${taxonomy_route}",
      "low_mapq_threshold": ${low_mapq_threshold}
    },
    "host_bam": "${host_bam}",
    "host_reference": "pipeline_alignment_reference",
    "host_unmapped_records": "${host_unmapped_count}"
  }
}
JSON
