"""Tests for ClinVar VCF → TSV pipeline builder."""
from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

from app.core.clinvar_pipeline import build_clinvar_tsv_from_vcf, _parse_info, _extract_gene, _split_multi_allelic


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

def test_parse_info_basic():
    info = _parse_info("GENEINFO=BRCA1:672;CLNSIG=pathogenic;CLNREVSTAT=criteria_provided")
    assert info["GENEINFO"] == "BRCA1:672"
    assert info["CLNSIG"] == "pathogenic"
    assert info["CLNREVSTAT"] == "criteria_provided"


def test_parse_info_flag():
    info = _parse_info("SOMATIC;CLNSIG=pathogenic")
    assert info["SOMATIC"] == "true"


def test_extract_gene():
    info = {"GENEINFO": "BRCA1:672|BRCA2:675"}
    assert _extract_gene(info) == "BRCA1"


def test_extract_gene_fallback():
    info = {"GENE": "TP53"}
    assert _extract_gene(info) == "TP53"


def test_split_multi_allelic_single():
    info = {"CLNSIG": "pathogenic", "CLNREVSTAT": "criteria_provided", "CLNDBN": "Breast_cancer"}
    recs = _split_multi_allelic("17", 43045643, "A", ["T"], info)
    assert len(recs) == 1
    assert recs[0]["chrom"] == "17"
    assert recs[0]["alt"] == "T"
    assert recs[0]["clinical_significance"] == "pathogenic"


def test_split_multi_allelic_multi():
    info = {
        "CLNSIG": "pathogenic,benign",
        "CLNREVSTAT": "criteria_provided,criteria_provided",
        "CLNDBN": "Cancer,Benign_condition",
        "CLNALLE": "1,2",
    }
    recs = _split_multi_allelic("17", 43045643, "A", ["T", "G"], info)
    assert len(recs) == 2
    assert recs[0]["alt"] == "T"
    assert recs[1]["alt"] == "G"


# ---------------------------------------------------------------------------
# Integration: build TSV from synthetic VCF
# ---------------------------------------------------------------------------

MINIMAL_VCF = b"""\
##fileformat=VCFv4.1
##ClinVar=<ID=RCV000001>
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
17\t43045643\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672;CLNSIG=pathogenic;CLNREVSTAT=criteria_provided,_single_submitter;CLNDBN=Hereditary_breast_ovarian_cancer;CLNACC=VCV000012345
7\t117559590\t.\tC\tG\t.\t.\tGENEINFO=CFTR:1080;CLNSIG=pathogenic;CLNREVSTAT=criteria_provided,_multiple_submitters;CLNDBN=Cystic_fibrosis;CLNACC=VCV000023456
1\t55509640\t.\tG\tA\t.\t.\tGENEINFO=MTHFR:4524;CLNSIG=uncertain_significance;CLNREVSTAT=no_assertion_criteria;CLNDBN=not_specified;CLNACC=VCV000034567
"""


def _write_vcf_gz(path: Path, content: bytes = MINIMAL_VCF):
    with gzip.open(path, "wb") as fh:
        fh.write(content)


def test_build_tsv_from_synthetic_vcf():
    with tempfile.TemporaryDirectory() as tmpdir:
        vcf = Path(tmpdir) / "clinvar.vcf.gz"
        tsv = Path(tmpdir) / "out.tsv"
        _write_vcf_gz(vcf)

        result = build_clinvar_tsv_from_vcf(vcf, tsv)

        assert result["status"] == "built"
        assert result["rows_written"] == 3
        assert result["rows_skipped"] == 0
        assert tsv.exists()

        lines = tsv.read_text().strip().split("\n")
        assert len(lines) == 4  # header + 3 rows
        assert "BRCA1" in lines[1]
        assert "CFTR" in lines[2]


def test_build_tsv_skips_header_and_info_only():
    content = b"""\
##fileformat=VCFv4.1
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
22\t1000\t.\tA\tG\t.\t.\t.
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        vcf = Path(tmpdir) / "clinvar.vcf.gz"
        tsv = Path(tmpdir) / "out.tsv"
        with gzip.open(vcf, "wb") as fh:
            fh.write(content)

        result = build_clinvar_tsv_from_vcf(vcf, tsv)
        # Row has no CLNSIG → skipped
        assert result["rows_written"] == 0
        assert result["rows_skipped"] == 1


def test_build_tsv_vcf_not_found():
    result = build_clinvar_tsv_from_vcf("/nonexistent/clinvar.vcf.gz")
    assert result["status"] == "vcf_not_found"


def test_build_tsv_max_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        vcf = Path(tmpdir) / "clinvar.vcf.gz"
        tsv = Path(tmpdir) / "out.tsv"
        _write_vcf_gz(vcf)

        result = build_clinvar_tsv_from_vcf(vcf, tsv, max_rows=1)
        assert result["rows_written"] == 1
