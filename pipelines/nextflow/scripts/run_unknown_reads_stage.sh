#!/usr/bin/env bash
set -euo pipefail

# Unknown Reads Analysis stage
# Conservative "dark matter" pipeline:
# host depletion -> known taxonomy depletion -> optional assembly -> optional contig search.
#
# Usage:
#   run_unknown_reads_stage.sh <sample_id> <r1.fastq.gz> <r2.fastq.gz> <threads> <allow_dev_fallback> [kraken2_db] [host_bam]

sample_id="${1:?sample_id required}"
r1="${2:-}"
r2="${3:-}"
threads="${4:-2}"
allow_dev_fallback="${5:-true}"
kraken_db="${6:-/data/databases/kraken2}"
host_bam="${7:-}"

outdir="${sample_id}_unknown_reads"
ingest="${sample_id}.unknown_reads.ingest.json"
mkdir -p "$outdir"

host_unmapped_r1="${outdir}/${sample_id}_host_unmapped_R1.fastq.gz"
host_unmapped_r2="${outdir}/${sample_id}_host_unmapped_R2.fastq.gz"
unknown_r1="${outdir}/${sample_id}_unknown_R1.fastq.gz"
unknown_r2="${outdir}/${sample_id}_unknown_R2.fastq.gz"
host_stats="${outdir}/${sample_id}_host_depletion.stats"
taxonomy_stats="${outdir}/${sample_id}_taxonomy_depletion.stats"
assembly_stats="${outdir}/${sample_id}_assembly.stats"
search_stats="${outdir}/${sample_id}_search.stats"
contigs_fasta="${outdir}/${sample_id}_unknown_contigs.fasta"
contig_hits="${outdir}/${sample_id}_contig_hits.tsv"
kmer_profile_json="${outdir}/${sample_id}_kmer_profile.json"

notes=()

have_tool() {
  command -v "$1" >/dev/null 2>&1
}

count_fastq_records() {
  local file="$1"
  local lines=0
  if [[ -z "$file" || ! -f "$file" ]]; then
    echo "unknown"
    return
  fi
  if [[ "$file" == *.gz ]]; then
    lines=$(gzip -cd "$file" 2>/dev/null | wc -l || true)
  else
    lines=$(wc -l < "$file" 2>/dev/null || echo 0)
  fi
  if [[ "$lines" =~ ^[0-9]+$ && "$lines" -gt 0 ]]; then
    echo $((lines / 4))
  else
    echo "unknown"
  fi
}

valid_bam() {
  local bam="$1"
  [[ -n "$bam" && -f "$bam" ]] || return 1
  have_tool samtools || return 1
  samtools quickcheck "$bam" >/dev/null 2>&1
}

legacy_bam=""
if [[ -z "$host_bam" && -n "$r1" ]]; then
  if [[ "$r1" == *.fastq.gz ]]; then
    legacy_bam="${r1%.fastq.gz}.bam"
  elif [[ "$r1" == *.fq.gz ]]; then
    legacy_bam="${r1%.fq.gz}.bam"
  fi
fi

if [[ -z "$host_bam" && -n "$legacy_bam" && -f "$legacy_bam" ]]; then
  host_bam="$legacy_bam"
fi

echo "[unknown] Step 1: host depletion for ${sample_id}" >&2
collection_mode="fastq_fallback_or_external"
host_tool="none"

if valid_bam "$host_bam"; then
  collection_mode="host_bam_unmapped_pairs"
  host_tool="samtools"
  echo "[unknown] extracting both-unmapped read pairs from ${host_bam}" >&2
  samtools fastq \
    -@ "$threads" \
    -f 12 \
    -1 "$host_unmapped_r1" \
    -2 "$host_unmapped_r2" \
    -0 /dev/null \
    -s /dev/null \
    -n \
    "$host_bam" >/dev/null 2>"${outdir}/${sample_id}_samtools_fastq.log"
  total_reads=$(samtools flagstat "$host_bam" | head -1 | awk '{print $1}' || echo "unknown")
  unmapped_reads=$(samtools view -c -f 12 "$host_bam" || echo "unknown")
  echo "tool=${host_tool} total_reads=${total_reads} unmapped_reads=${unmapped_reads}" > "$host_stats"
else
  notes+=("No valid host BAM supplied; using input FASTQ pair as collection source.")
  if [[ -f "$r1" && -f "$r2" ]]; then
    host_unmapped_r1="$r1"
    host_unmapped_r2="$r2"
    total_r1=$(count_fastq_records "$r1")
    total_r2=$(count_fastq_records "$r2")
    if [[ "$total_r1" =~ ^[0-9]+$ && "$total_r2" =~ ^[0-9]+$ ]]; then
      total_reads=$((total_r1 + total_r2))
    else
      total_reads="unknown"
    fi
    echo "tool=fastq_fallback total_reads=${total_reads} unmapped_reads=unknown" > "$host_stats"
  else
    echo "tool=none total_reads=unknown unmapped_reads=unknown" > "$host_stats"
    if [[ "$allow_dev_fallback" != "true" ]]; then
      echo "[unknown] no valid BAM or FASTQ pair available" >&2
      exit 127
    fi
  fi
fi

echo "[unknown] Step 2: known taxonomy depletion" >&2
taxonomy_mode="none"
if have_tool kraken2 && [[ -d "$kraken_db" ]]; then
  kraken_output="${outdir}/${sample_id}_unknown.kraken2.output"
  kraken_report="${outdir}/${sample_id}_unknown.kraken2.report"
  kraken_args=()
  if [[ "$host_unmapped_r1" == *.gz || "$host_unmapped_r2" == *.gz ]]; then
    kraken_args+=(--gzip-compressed)
  fi
  if kraken2 \
    --db "$kraken_db" \
    --paired \
    --threads "$threads" \
    --report "$kraken_report" \
    --output "$kraken_output" \
    --unclassified-out "${outdir}/${sample_id}_unclassified#.fastq" \
    "${kraken_args[@]}" \
    "$host_unmapped_r1" "$host_unmapped_r2" >"${outdir}/${sample_id}_kraken2.log" 2>&1; then
    if [[ -f "${outdir}/${sample_id}_unclassified_1.fastq" ]]; then
      gzip -f "${outdir}/${sample_id}_unclassified_1.fastq"
      gzip -f "${outdir}/${sample_id}_unclassified_2.fastq"
      mv "${outdir}/${sample_id}_unclassified_1.fastq.gz" "$unknown_r1"
      mv "${outdir}/${sample_id}_unclassified_2.fastq.gz" "$unknown_r2"
    fi
    classified_count=$(grep -c "^C" "$kraken_output" 2>/dev/null || echo 0)
    unclassified_count=$(grep -c "^U" "$kraken_output" 2>/dev/null || echo 0)
    echo "tool=kraken2 classified=${classified_count} unclassified=${unclassified_count}" > "$taxonomy_stats"
    taxonomy_mode="kraken2"
  else
    notes+=("Kraken2 failed; carrying host-depleted reads forward without taxonomy depletion.")
    cp "$host_unmapped_r1" "$unknown_r1" 2>/dev/null || true
    cp "$host_unmapped_r2" "$unknown_r2" 2>/dev/null || true
    echo "tool=kraken2_failed classified=0 unclassified=unknown" > "$taxonomy_stats"
    taxonomy_mode="kraken2_failed"
  fi
else
  notes+=("Kraken2 or database unavailable; carrying host-depleted reads forward without taxonomy depletion.")
  cp "$host_unmapped_r1" "$unknown_r1" 2>/dev/null || true
  cp "$host_unmapped_r2" "$unknown_r2" 2>/dev/null || true
  echo "tool=none classified=0 unclassified=unknown" > "$taxonomy_stats"
fi

echo "[unknown] Step 3: optional de novo assembly" >&2
assembly_tool="none"
if [[ -s "$unknown_r1" && -s "$unknown_r2" ]] && have_tool spades.py; then
  assembly_tool="spades"
  if spades.py --meta --threads "$threads" --memory 16 -1 "$unknown_r1" -2 "$unknown_r2" -o "${outdir}/spades_output" >"${outdir}/${sample_id}_spades.log" 2>&1; then
    [[ -f "${outdir}/spades_output/contigs.fasta" ]] && cp "${outdir}/spades_output/contigs.fasta" "$contigs_fasta"
  else
    notes+=("SPAdes failed; no assembled contigs imported.")
  fi
elif [[ -s "$unknown_r1" && -s "$unknown_r2" ]] && have_tool megahit; then
  assembly_tool="megahit"
  if megahit -1 "$unknown_r1" -2 "$unknown_r2" --num-cpu-threads "$threads" -o "${outdir}/megahit_output" >"${outdir}/${sample_id}_megahit.log" 2>&1; then
    [[ -f "${outdir}/megahit_output/final.contigs.fa" ]] && cp "${outdir}/megahit_output/final.contigs.fa" "$contigs_fasta"
  else
    notes+=("MEGAHIT failed; no assembled contigs imported.")
  fi
else
  notes+=("No assembler available or no unknown read pair present; assembly skipped.")
fi

if [[ -f "$contigs_fasta" ]]; then
  num_contigs=$(grep -c "^>" "$contigs_fasta" 2>/dev/null || echo 0)
  total_bp=$(grep -v "^>" "$contigs_fasta" | tr -d '\n' | wc -c)
  n50=$(python3 - "$contigs_fasta" <<'PY' 2>/dev/null || echo 0
import sys
path = sys.argv[1]
lens = []
seq = []
with open(path, encoding="utf-8", errors="ignore") as handle:
    for line in handle:
        if line.startswith(">"):
            if seq:
                lens.append(sum(len(x.strip()) for x in seq))
            seq = []
        else:
            seq.append(line)
if seq:
    lens.append(sum(len(x.strip()) for x in seq))
lens.sort(reverse=True)
total = sum(lens)
acc = 0
for length in lens:
    acc += length
    if acc >= total / 2:
        print(length)
        break
if not lens:
    print(0)
PY
)
  echo "tool=${assembly_tool} contigs=${num_contigs} total_bp=${total_bp} n50=${n50}" > "$assembly_stats"
else
  echo "tool=${assembly_tool} contigs=0 total_bp=0 n50=0" > "$assembly_stats"
fi

echo "[unknown] Step 4: optional contig search" >&2
search_tool="none"
blast_db="${WGS_BLAST_DB:-}"
if [[ -f "$contigs_fasta" && -n "$blast_db" && "$(grep -c '^>' "$contigs_fasta" || echo 0)" -gt 0 ]] && have_tool blastn; then
  search_tool="blastn"
  if blastn \
    -query "$contigs_fasta" \
    -db "$blast_db" \
    -outfmt "6 qseqid sseqid pident length evalue bitscore stitle" \
    -max_target_seqs 5 \
    -evalue 1e-10 \
    -num_threads "$threads" \
    -out "$contig_hits" >"${outdir}/${sample_id}_blastn.log" 2>&1; then
    total_contigs=$(grep -c "^>" "$contigs_fasta" 2>/dev/null || echo 0)
    hit_contigs=$(cut -f1 "$contig_hits" 2>/dev/null | sort -u | wc -l || echo 0)
    no_hit=$((total_contigs - hit_contigs))
    echo "tool=blastn total_contigs=${total_contigs} with_hits=${hit_contigs} no_hits=${no_hit}" > "$search_stats"
  else
    notes+=("BLAST failed; contig search skipped.")
    echo "tool=blastn_failed total_contigs=0 with_hits=0 no_hits=0" > "$search_stats"
  fi
else
  notes+=("No BLAST database configured; contig search skipped.")
  echo "tool=${search_tool} total_contigs=0 with_hits=0 no_hits=0" > "$search_stats"
fi

echo "[unknown] Step 5: k-mer profiling" >&2
kmer_size="${WGS_UNKNOWN_KMER_SIZE:-31}"
kmer_max_reads="${WGS_UNKNOWN_KMER_MAX_READS:-200000}"
kmer_top_n="${WGS_UNKNOWN_KMER_TOP_N:-30}"
if python3 - "$unknown_r1" "$unknown_r2" "$kmer_profile_json" "$kmer_size" "$kmer_max_reads" "$kmer_top_n" <<'PY' >/dev/null 2>"${outdir}/${sample_id}_kmer_profile.log"; then
import collections
import gzip
import json
import sys
from pathlib import Path


r1, r2, out_path = sys.argv[1], sys.argv[2], Path(sys.argv[3])
k = int(sys.argv[4])
max_reads = int(sys.argv[5])
top_n = int(sys.argv[6])


def read_lines(path):
    if not path or not Path(path).exists():
        return
    if path.endswith(".gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    yield line
            return
        except Exception:
            pass
    with open(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            yield line


def iter_fastq_sequences(path):
    line_no = 0
    for line in read_lines(path) or []:
        line_no += 1
        if line_no % 4 == 2:
            yield line.strip().upper()


def revcomp(seq):
    table = str.maketrans("ACGT", "TGCA")
    return seq.translate(table)[::-1]


counts = collections.Counter()
reads_scanned = 0
for path in (r1, r2):
    for seq in iter_fastq_sequences(path):
        reads_scanned += 1
        if reads_scanned > max_reads:
            break
        if len(seq) < k:
            continue
        for idx in range(0, len(seq) - k + 1):
            kmer = seq[idx:idx + k]
            if any(base not in "ACGT" for base in kmer):
                continue
            canonical = min(kmer, revcomp(kmer))
            counts[canonical] += 1
    if reads_scanned > max_reads:
        break

cluster_counts = collections.defaultdict(lambda: {"total_count": 0, "distinct_kmers": 0})
for kmer, count in counts.items():
    prefix = kmer[: min(8, len(kmer))]
    cluster_counts[prefix]["total_count"] += count
    cluster_counts[prefix]["distinct_kmers"] += 1

clusters = [
    {
        "cluster_id": f"prefix:{prefix}",
        "prefix": prefix,
        "total_count": values["total_count"],
        "distinct_kmers": values["distinct_kmers"],
        "method": "canonical_kmer_prefix",
    }
    for prefix, values in sorted(cluster_counts.items(), key=lambda item: item[1]["total_count"], reverse=True)[:top_n]
]

payload = {
    "tool": "internal_kmer_counter",
    "status": "profiled" if counts else ("no_reads" if reads_scanned == 0 else "no_kmers"),
    "kmer_size": k,
    "reads_scanned": min(reads_scanned, max_reads),
    "read_limit": max_reads,
    "distinct_kmers": len(counts),
    "top_kmers": [
        {"kmer": kmer, "count": count}
        for kmer, count in counts.most_common(top_n)
    ],
    "clusters": clusters,
    "non_diagnostic": True,
}
out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "[unknown] k-mer profile written to ${kmer_profile_json}" >&2
else
  notes+=("Internal k-mer profiling failed; no k-mer profile imported.")
  cat > "$kmer_profile_json" <<EOF
{"tool":"internal_kmer_counter","status":"failed","kmer_size":${kmer_size},"reads_scanned":0,"distinct_kmers":0,"top_kmers":[],"clusters":[],"non_diagnostic":true}
EOF
fi

echo "[unknown] Step 6: generating ingest contract" >&2

export SAMPLE_ID="$sample_id"
export INGEST="$ingest"
export COLLECTION_MODE="$collection_mode"
export HOST_BAM="$host_bam"
export KRAKEN_DB="$kraken_db"
export HOST_STATS="$host_stats"
export TAXONOMY_STATS="$taxonomy_stats"
export ASSEMBLY_STATS="$assembly_stats"
export SEARCH_STATS="$search_stats"
export HOST_UNMAPPED_R1="$host_unmapped_r1"
export HOST_UNMAPPED_R2="$host_unmapped_r2"
export UNKNOWN_R1="$unknown_r1"
export UNKNOWN_R2="$unknown_r2"
export CONTIGS_FASTA="$contigs_fasta"
export CONTIG_HITS="$contig_hits"
export KMER_PROFILE_JSON="$kmer_profile_json"
export NOTES_JSON="$(printf '%s\n' "${notes[@]}" | python3 -c 'import json,sys; print(json.dumps([x.strip() for x in sys.stdin if x.strip()]))')"

python3 <<'PY'
import json
import os
from pathlib import Path


def read_stats(path):
    values = {}
    try:
        for token in Path(path).read_text(encoding="utf-8", errors="ignore").split():
            if "=" in token:
                key, value = token.split("=", 1)
                values[key] = value
    except Exception:
        pass
    return values


def as_int(value):
    if value in (None, "", ".", "unknown"):
        return "unknown"
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return "unknown"


def present(path):
    return bool(path) and Path(path).exists()


host = read_stats(os.environ["HOST_STATS"])
taxonomy = read_stats(os.environ["TAXONOMY_STATS"])
assembly = read_stats(os.environ["ASSEMBLY_STATS"])
search = read_stats(os.environ["SEARCH_STATS"])
files = {
    "host_unmapped_r1": os.environ["HOST_UNMAPPED_R1"],
    "host_unmapped_r2": os.environ["HOST_UNMAPPED_R2"],
    "unknown_r1": os.environ["UNKNOWN_R1"],
    "unknown_r2": os.environ["UNKNOWN_R2"],
    "host_stats": os.environ["HOST_STATS"],
    "taxonomy_stats": os.environ["TAXONOMY_STATS"],
    "assembly_stats": os.environ["ASSEMBLY_STATS"],
    "search_stats": os.environ["SEARCH_STATS"],
}
if present(os.environ["CONTIGS_FASTA"]):
    files["contigs_fasta"] = os.environ["CONTIGS_FASTA"]
if present(os.environ["CONTIG_HITS"]):
    files["contig_hits"] = os.environ["CONTIG_HITS"]
if present(os.environ["KMER_PROFILE_JSON"]):
    files["kmer_profile_json"] = os.environ["KMER_PROFILE_JSON"]

notes = json.loads(os.environ.get("NOTES_JSON") or "[]")
try:
    kmer_payload = json.loads(Path(os.environ["KMER_PROFILE_JSON"]).read_text(encoding="utf-8"))
except Exception:
    kmer_payload = {"tool": "internal_kmer_counter", "status": "not_run", "distinct_kmers": 0, "top_kmers": [], "clusters": []}
payload = {
    "status": "imported",
    "collection_mode": os.environ["COLLECTION_MODE"],
    "host_bam": os.environ.get("HOST_BAM") or None,
    "taxonomy_database": os.environ.get("KRAKEN_DB") or None,
    "host_depletion": {
        "tool": host.get("tool", "none"),
        "total_reads": as_int(host.get("total_reads") or host.get("total")),
        "unmapped_reads": as_int(host.get("unmapped_reads") or host.get("unmapped")),
    },
    "taxonomy_depletion": {
        "tool": taxonomy.get("tool", "none"),
        "classified": as_int(taxonomy.get("classified")),
        "unclassified": as_int(taxonomy.get("unclassified")),
    },
    "assembly": {
        "tool": assembly.get("tool", "none"),
        "contigs": as_int(assembly.get("contigs")),
        "total_bp": as_int(assembly.get("total_bp")),
        "n50": as_int(assembly.get("n50")),
    },
    "contig_search": {
        "tool": search.get("tool", "none"),
        "total_contigs": as_int(search.get("total_contigs")),
        "with_hits": as_int(search.get("with_hits")),
        "no_hits": as_int(search.get("no_hits")),
    },
    "kmer_profile": {
        key: value
        for key, value in kmer_payload.items()
        if key != "clusters"
    },
    "kmer_clusters": kmer_payload.get("clusters", []),
    "files": files,
    "source_files": list(files.values()),
    "notes": notes,
    "non_diagnostic": True,
}
contract = {
    "event_type": "run.ingest.request",
    "stage": "unknown_reads",
    "sample_id": os.environ["SAMPLE_ID"],
    "payload": payload,
}
Path(os.environ["INGEST"]).write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "[unknown] done. Ingest contract: ${ingest}" >&2
