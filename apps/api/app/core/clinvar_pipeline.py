"""ClinVar VCF → exact-match TSV builder.

Converts a ClinVar VCF (from NCBI FTP) into the exact-match TSV format
consumed by ``interpretation.parse_clinvar_tsv()``.  This closes the gap
between "ClinVar VCF downloaded" and "ClinVar TSV usable for monogenic
exact-match".

Research-only; not a diagnostic tool.
"""
from __future__ import annotations

import csv
import gzip
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

CLINVAR_VCF_DIR = Path(os.getenv("WGS_CLINVAR_VCF_DIR", "/data/references/clinvar"))
DEFAULT_TSV_OUTPUT = CLINVAR_VCF_DIR / "clinvar.tsv"


def _parse_info(info_str: str) -> dict[str, str]:
    """Parse a VCF INFO field into a key→value dict."""
    result: dict[str, str] = {}
    for item in info_str.split(";"):
        if "=" in item:
            key, val = item.split("=", 1)
            result[key.strip()] = val.strip()
        else:
            result[item.strip()] = "true"
    return result


def _extract_gene(info: dict[str, str]) -> str:
    """Extract gene symbol from ClinVar INFO fields."""
    geneinfo = info.get("GENEINFO", "")
    if geneinfo:
        first = geneinfo.split("|")[0].split(":")[0].strip()
        if first:
            return first
    return info.get("GENE", "")


def _safe_index(lst: list[str], idx: int) -> str:
    return lst[idx] if 0 <= idx < len(lst) else ""


def _split_multi_allelic(
    chrom: str,
    pos: int,
    ref: str,
    alts: list[str],
    info: dict[str, str],
) -> list[dict[str, str]]:
    """Split a multi-allelic ClinVar VCF row into per-allele records."""
    clnsig = info.get("CLNSIG", "")
    clnrevstat = info.get("CLNREVSTAT", "")
    clndbn = info.get("CLNDBN", "")
    clnacc = info.get("CLNACC", "")
    gene = _extract_gene(info)

    clnalle_raw = info.get("CLNALLE", "")
    clnalle_indices = (
        [int(x) for x in clnalle_raw.split(",") if x.strip().isdigit()]
        if clnalle_raw
        else []
    )

    sig_parts = [x.strip() for x in clnsig.split(",")] if clnsig else []
    dbn_parts = [x.strip() for x in clndbn.split(",")] if clndbn else []
    acc_parts = [x.strip() for x in clnacc.split(",")] if clnacc else []
    rev_parts = [x.strip() for x in clnrevstat.split(",")] if clnrevstat else []

    records: list[dict[str, str]] = []

    for alt_idx, alt in enumerate(alts):
        ann_idx = 0
        if clnalle_indices and alt_idx in clnalle_indices:
            ann_idx = clnalle_indices.index(alt_idx)
        elif alt_idx < len(sig_parts):
            ann_idx = alt_idx

        sig = _safe_index(sig_parts, ann_idx) or clnsig
        dbn = _safe_index(dbn_parts, ann_idx) or clndbn
        acc = _safe_index(acc_parts, ann_idx) or clnacc
        rev = _safe_index(rev_parts, ann_idx) or clnrevstat

        records.append({
            "chrom": chrom,
            "pos": str(pos),
            "ref": ref,
            "alt": alt,
            "gene": gene,
            "condition": dbn.replace("_", " ").strip() or "unspecified",
            "clinical_significance": sig.replace("_", " ").strip() if sig else "unknown",
            "review_status": rev.replace("_", " ").strip() if rev else "not_provided",
            "accession": acc.split(",")[0].strip() if acc else "",
        })

    return records


def build_clinvar_tsv_from_vcf(
    vcf_path: Path | str | None = None,
    output_path: Path | str | None = None,
    *,
    max_rows: int = 0,
) -> dict[str, Any]:
    """Convert a ClinVar VCF to exact-match TSV.

    Args:
        vcf_path: Path to clinvar.vcf.gz.  Defaults to ``CLINVAR_VCF_DIR/clinvar.vcf.gz``.
        output_path: Where to write the TSV.  Defaults to ``CLINVAR_VCF_DIR/clinvar.tsv``.
        max_rows: Limit rows processed (0 = all).  Useful for testing.

    Returns:
        Provenance-wrapped result with row counts and output path.
    """
    from app.core.interpretation import InterpretationProvenance

    src = Path(vcf_path) if vcf_path else CLINVAR_VCF_DIR / "clinvar.vcf.gz"
    dst = Path(output_path) if output_path else DEFAULT_TSV_OUTPUT
    provenance = InterpretationProvenance(
        source_database="ClinVar",
        source_version=src.name if src.exists() else None,
        source_date=date.today().isoformat(),
        genome_build="GRCh38",
        rule_id="clinvar_vcf_to_tsv_builder",
    )

    if not src.exists() or not src.is_file():
        provenance.warnings.append(f"ClinVar VCF not found: {src}")
        return {
            "status": "vcf_not_found",
            "path": str(src),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    dst.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    skipped = 0
    multi_count = 0

    try:
        open_fn = gzip.open if str(src).endswith(".gz") else open
        with open_fn(src, "rt", encoding="utf-8", errors="ignore") as handle, \
             dst.open("w", encoding="utf-8", newline="") as out_fh:

            writer = csv.writer(out_fh, delimiter="\t")
            writer.writerow([
                "chrom", "pos", "ref", "alt", "gene", "condition",
                "clinical_significance", "review_status", "accession",
            ])

            for line in handle:
                if line.startswith("##"):
                    continue
                if line.startswith("#CHROM"):
                    continue

                parts = line.rstrip("\n\r").split("\t")
                if len(parts) < 8:
                    skipped += 1
                    continue

                chrom_raw = parts[0]
                pos_raw = parts[1]
                ref = parts[3]
                alt_str = parts[4]
                info_str = parts[7]

                # Normalize chromosome
                chrom = chrom_raw
                if chrom.lower().startswith("chr"):
                    chrom = chrom[3:]
                if chrom in {"23", "X"}:
                    chrom = "X"
                elif chrom in {"24", "Y"}:
                    chrom = "Y"
                elif chrom in {"M", "MT"}:
                    chrom = "M"

                try:
                    pos = int(pos_raw)
                except ValueError:
                    skipped += 1
                    continue

                alts = [a.strip() for a in alt_str.split(",") if a.strip()]
                if not alts:
                    skipped += 1
                    continue

                info = _parse_info(info_str)

                clnsig = info.get("CLNSIG", "")
                if not clnsig or clnsig.lower() in {"", "not_provided", "none"}:
                    skipped += 1
                    continue

                records = _split_multi_allelic(chrom, pos, ref, alts, info)
                if len(alts) > 1:
                    multi_count += 1

                for rec in records:
                    writer.writerow([
                        rec["chrom"], rec["pos"], rec["ref"], rec["alt"],
                        rec["gene"], rec["condition"],
                        rec["clinical_significance"], rec["review_status"],
                        rec["accession"],
                    ])
                    rows_written += 1

                if max_rows and rows_written >= max_rows:
                    break

        provenance.matched_variant_count = rows_written
        provenance.input_variant_count = rows_written + skipped
        provenance.confidence_level = "moderate" if rows_written > 0 else "insufficient"

        return {
            "status": "built",
            "rows_written": rows_written,
            "rows_skipped": skipped,
            "multi_allelic_records": multi_count,
            "output_path": str(dst),
            "output_size_bytes": dst.stat().st_size,
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }

    except Exception as exc:
        provenance.warnings.append(str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "provenance": provenance.model_dump(),
            "non_diagnostic": True,
        }
