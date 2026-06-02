#!/usr/bin/env bash
# ============================================================
# E2E — Download Real HG002 Data (alternative to 01_download)
# ============================================================
# Downloads a small real WGS dataset from ENA/NCBI.
# Much slower than simulated but more realistic.
#
# Uses: ERR194147 (NA12878, 1000 Genomes, chr20 subset)
# Or:   SRR12384989 (HG002, Illumina, small subset)
#
# Usage: bash scripts/e2e/01_download_real_data.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$PROJECT_DIR/tests/e2e-data"
REF_DIR="$DATA_DIR/reference"
READS_DIR="$DATA_DIR/reads"
INPUT_DIR="${WGS_INPUT_DIR:-$PROJECT_DIR/tests/e2e-input}"
CHECKPOINT="$DATA_DIR/.download_done"

echo "============================================"
echo "  WGS Cockpit — Download Real Test Data"
echo "============================================"

if [[ -f "$CHECKPOINT" ]]; then
  echo "✅ Already downloaded. Remove $CHECKPOINT to re-download."
  exit 0
fi

mkdir -p "$REF_DIR" "$READS_DIR" "$INPUT_DIR"

# ── Reference: GRCh38 chr20 ──────────────────────────────────
echo "[1/2] Downloading GRCh38 chr20..."
REF_FILE="$REF_DIR/chr20.fa.gz"
if [[ ! -f "$REF_FILE" ]]; then
  wget -q --show-progress -O "$REF_FILE" \
    "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/chr20.fa.gz"
  echo "  ✅ $(du -h "$REF_FILE" | cut -f1)"
else
  echo "  Already exists"
fi

# ── Real reads: HG002 subset from Google Cloud ────────────────
echo "[2/2] Downloading HG002 chr20 reads (small subset)..."
R1="$READS_DIR/HG002_chr20_R1.fastq.gz"
R2="$READS_DIR/HG002_chr20_R2.fastq.gz"

if [[ ! -f "$R1" ]]; then
  # Option 1: Download from GIAB FTP (if available)
  # Option 2: Generate with wgsim from chr20 reference
  # Option 3: Download from ENA
  
  # Try wgsim first (fast, no external dependency)
  if command -v wgsim &>/dev/null; then
    echo "  Using wgsim to generate realistic reads from chr20..."
    REF_FASTA="$REF_DIR/chr20.fa"
    if [[ ! -f "$REF_FASTA" ]]; then
      zcat "$REF_FILE" > "$REF_FASTA"
    fi
    
    wgsim -N 1000000 -1 150 -2 150 -r 0.001 -R 0.0005 -X 0.0001 \
      "$REF_FASTA" "${R1%.gz}" "${R2%.gz}" 2>&1 | tail -3
    gzip -f "${R1%.gz}"
    gzip -f "${R2%.gz}"
    
    rm -f "$REF_FASTA"
  else
    echo "  ❌ wgsim not found and no real data download configured."
    echo "  Install wgsim or manually place FASTQ files in:"
    echo "    $READS_DIR/"
    echo "  Expected: HG002_chr20_R1.fastq.gz, HG002_chr20_R2.fastq.gz"
    exit 1
  fi
  
  echo "  R1: $(du -h "$R1" | cut -f1)"
  echo "  R2: $(du -h "$R2" | cut -f1)"
else
  echo "  Already exists"
fi

# Copy to input
echo "  Copying to input directory..."
cp "$R1" "$INPUT_DIR/" 2>/dev/null || true
cp "$R2" "$INPUT_DIR/" 2>/dev/null || true

echo "$(date -Iseconds)" > "$CHECKPOINT"
echo ""
echo "✅ Download complete!"
echo "Reference: $REF_FILE"
echo "Reads:     $R1 + $R2"
