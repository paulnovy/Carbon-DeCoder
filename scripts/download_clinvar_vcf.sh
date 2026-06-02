#!/usr/bin/env bash
# Download latest ClinVar VCF for GRCh38 from NCBI FTP.
# Usage: scripts/download_clinvar_vcf.sh [output_dir]
#
# Research-only; not a diagnostic tool.

set -euo pipefail

OUT_DIR="${1:-/data/references/clinvar}"
BASE_URL="https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38"

mkdir -p "$OUT_DIR"

echo "Fetching ClinVar VCF directory listing..."
LATEST=$(curl -s "$BASE_URL/" | grep -oP 'clinvar_\d{4}-\d{2}\.vcf\.gz' | sort -V | tail -1)

if [ -z "$LATEST" ]; then
    echo "ERROR: Could not determine latest ClinVar VCF filename"
    exit 1
fi

echo "Latest ClinVar VCF: $LATEST"
echo "Downloading to $OUT_DIR..."

curl -# -o "$OUT_DIR/$LATEST" "$BASE_URL/$LATEST"
curl -# -o "$OUT_DIR/$LATEST.tbi" "$BASE_URL/$LATEST.tbi" || echo "Warning: tabix index not available"

echo ""
echo "Download complete: $OUT_DIR/$LATEST"
echo "Run the build endpoint to convert to TSV:"
echo "  curl -X POST http://localhost:8000/interpretation/resources/clinvar/build-tsv"
