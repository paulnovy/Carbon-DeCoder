#!/usr/bin/env bash
# ============================================================
# E2E Test Data Download — WGS Cockpit
# Downloads GRCh38 chr20 reference + simulated WGS reads
# ============================================================
# Usage: bash scripts/e2e/01_download_data.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_DIR/tests/e2e-data"
REF_DIR="$DATA_DIR/reference"
READS_DIR="$DATA_DIR/reads"
CHECKPOINT="$DATA_DIR/.download_done"

echo "============================================"
echo "  WGS Cockpit — E2E Test Data Download"
echo "============================================"
echo "Data dir: $DATA_DIR"
echo ""

# Check if already done
if [[ -f "$CHECKPOINT" ]]; then
  echo "✅ Already downloaded. Remove $CHECKPOINT to re-download."
  exit 0
fi

mkdir -p "$REF_DIR" "$READS_DIR"

# ── Step 1: Download chr20 reference ─────────────────────────
echo "[1/3] Downloading GRCh38 chr20 reference..."
REF_URL="https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz"
REF_GZ="$REF_DIR/chr20.fa.gz"
REF_FA="$REF_DIR/chr20.fa"

if [[ ! -f "$REF_GZ" ]]; then
  wget -q --show-progress -O "$REF_GZ" "$REF_URL"
  echo "  Downloaded: $(du -h "$REF_GZ" | cut -f1)"
else
  echo "  Already exists: $(du -h "$REF_GZ" | cut -f1)"
fi

# Decompress (keep both .fa and .fa.gz — bwa-mem2 needs .fa, wgsim needs .fa)
if [[ ! -f "$REF_FA" ]]; then
  echo "  Decompressing reference..."
  zcat "$REF_GZ" > "$REF_FA"
fi

# samtools faidx
if [[ ! -f "$REF_FA.fai" ]]; then
  echo "  Building samtools faidx..."
  samtools faidx "$REF_FA"
fi

# bwa-mem2 index (critical for alignment!)
if [[ ! -f "$REF_FA.bwt.2bit.64" ]]; then
  echo "  Building bwa-mem2 index (~1-2min)..."
  bwa-mem2 index "$REF_FA" 2>&1 | tail -5
  echo "  ✅ bwa-mem2 index built"
else
  echo "  bwa-mem2 index already exists"
fi

# ── Step 2: Generate simulated WGS reads ─────────────────────
echo "[2/3] Generating simulated WGS reads (1M read pairs, 150bp)..."

R1="$READS_DIR/HG002_chr20_R1.fastq.gz"
R2="$READS_DIR/HG002_chr20_R2.fastq.gz"

if [[ ! -f "$R1" || ! -f "$R2" ]]; then
  echo "  Running wgsim (1M read pairs, 150bp, 0.1% mutation rate)..."
  R1_TMP="${R1%.gz}"
  R2_TMP="${R2%.gz}"
  wgsim -N 1000000 -1 150 -2 150 -r 0.001 -R 0.0005 -X 0.0001 \
    "$REF_FA" "$R1_TMP" "$R2_TMP" 2>&1 | tail -5
  
  echo "  Compressing reads..."
  gzip -f "$R1_TMP"
  gzip -f "$R2_TMP"
  
  echo "  R1: $(du -h "$R1" | cut -f1)"
  echo "  R2: $(du -h "$R2" | cut -f1)"
else
  echo "  Already exists: R1=$(du -h "$R1" | cut -f1), R2=$(du -h "$R2" | cut -f1)"
fi

# ── Step 3: Copy to input directory ──────────────────────────
echo "[3/3] Copying reads to container input directory..."

API_INPUT_DIR="/data/input"
mkdir -p "$API_INPUT_DIR"

if [[ ! -f "$API_INPUT_DIR/HG002_chr20_R1.fastq.gz" ]]; then
  cp "$R1" "$API_INPUT_DIR/"
  cp "$R2" "$API_INPUT_DIR/"
  echo "  Copied to: $API_INPUT_DIR/"
else
  echo "  Already in API input dir"
fi

# ── Checkpoint ───────────────────────────────────────────────
echo "$(date -Iseconds)" > "$CHECKPOINT"
echo ""
echo "============================================"
echo "  ✅ Download complete!"
echo "============================================"
echo "Reference:  $REF_FA"
echo "  + faidx:  ${REF_FA}.fai"
echo "  + bwa:    ${REF_FA}.bwt.2bit.64 (+ .0123, .amb, .ann, .pac, .bwt)"
echo "Reads:      $R1"
echo "             $R2"
echo ""
echo "Next step: bash scripts/e2e/02_create_project.sh"
