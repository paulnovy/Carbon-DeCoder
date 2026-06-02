"""Tests for interpretation module additions.

Covers:
- PharmCAT install check
- HaploGrep install check
- bcftools csq annotation (mock)
- VCF normalization (mock)
- Curated PGS manifest loading
- Curated traits manifest loading
- ClinVar VCF install check
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PIPELINE_SCRIPTS = PROJECT_ROOT / "pipelines" / "nextflow" / "scripts"


# ---------------------------------------------------------------------------
# Curated manifest loading tests
# ---------------------------------------------------------------------------


class TestCuratedPGSManifest:
    """Task 6: Validate the curated PGS manifest fixture."""

    def test_manifest_file_exists(self):
        path = FIXTURES / "pgs_curated_manifest.json"
        assert path.exists(), f"PGS manifest fixture not found: {path}"

    def test_manifest_loads_as_valid_json(self):
        path = FIXTURES / "pgs_curated_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_manifest_has_15_entries(self):
        path = FIXTURES / "pgs_curated_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["items"]) == 15, f"Expected 15 curated PGS scores, got {len(data['items'])}"

    def test_manifest_required_fields(self):
        path = FIXTURES / "pgs_curated_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"pgs_id", "name", "trait_reported", "trait_category", "variants_number", "ftp_url", "confidence"}
        for item in data["items"]:
            missing = required - set(item.keys())
            assert not missing, f"PGS {item.get('pgs_id', '?')} missing fields: {missing}"

    def test_manifest_covers_required_traits(self):
        """Ensure the curated set covers key trait categories."""
        path = FIXTURES / "pgs_curated_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        traits = {item["trait_reported"].lower() for item in data["items"]}
        required_traits = [
            "coronary artery disease",
            "type 2 diabetes",
            "breast cancer",
            "prostate cancer",
            "atrial fibrillation",
            "alzheimer",
            "obesity",  # matches "Obesity / Body mass index"
            "ldl cholesterol",
            "depressive",
            "lung cancer",
            "colorectal cancer",
            "osteoporosis",
            "rheumatoid arthritis",
            "schizophrenia",
            "asthma",
        ]
        for req in required_traits:
            assert any(req in t for t in traits), f"Missing trait coverage: {req}"

    def test_manifest_confidence_levels_valid(self):
        path = FIXTURES / "pgs_curated_manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        valid_levels = {"high", "moderate", "low", "insufficient"}
        for item in data["items"]:
            assert item["confidence"] in valid_levels, f"Invalid confidence '{item['confidence']}' for {item['pgs_id']}"


class TestCuratedTraitsManifest:
    """Task 7: Validate the curated traits manifest fixture."""

    def test_manifest_file_exists(self):
        path = FIXTURES / "curated_traits.json"
        assert path.exists(), f"Traits manifest fixture not found: {path}"

    def test_manifest_loads_as_valid_json(self):
        path = FIXTURES / "curated_traits.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_manifest_required_fields(self):
        path = FIXTURES / "curated_traits.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        required = {"trait_id", "trait_name", "chrom", "pos", "ref", "alt", "gene", "effect", "confidence"}
        for item in data["items"]:
            missing = required - set(item.keys())
            assert not missing, f"Trait {item.get('trait_id', '?')} missing fields: {missing}"

    def test_manifest_covers_required_variants(self):
        """Ensure key trait variants are present."""
        path = FIXTURES / "curated_traits.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        trait_ids = {item["trait_id"] for item in data["items"]}
        required_ids = [
            "lactose_tolerance",       # LCT/MCM6 rs4988235
            "mthfr_folate_metabolism", # MTHFR rs1801133
            "apoe_alzheimer_risk",     # APOE rs429358
            "actn3_athletic_performance",  # ACTN3 rs1815739
            "ald2_alcohol_flush",      # ALDH2 rs671
            "hfe_c282y_hemochromatosis",  # HFE C282Y
            "fto_obesity_risk",        # FTO rs9939609
            "bdnf_brain_derived",      # BDNF rs6265
            "comt_val158met",          # COMT rs4680
        ]
        for req in required_ids:
            assert req in trait_ids, f"Missing required trait: {req}"

    def test_manifest_genome_build(self):
        path = FIXTURES / "curated_traits.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data["items"]:
            assert item.get("genome_build") == "GRCh37", f"Unexpected build for {item['trait_id']}"


# ---------------------------------------------------------------------------
# PharmCAT install test
# ---------------------------------------------------------------------------


class TestPharmCATInstall:
    """Task 3: PharmCAT install checks."""

    def test_install_pharmcat_function_exists(self):
        from app.core.interpretation import install_pharmcat
        assert callable(install_pharmcat)

    def test_install_pharmcat_already_installed(self, tmp_path):
        from app.core.interpretation import PHARMCAT_INSTALL_DIR, install_pharmcat

        jar_dir = tmp_path / "pharmcat"
        jar_dir.mkdir(parents=True, exist_ok=True)
        jar = jar_dir / "pharmcat.jar"
        jar.write_bytes(b"fake-jar-content")

        with patch("app.core.interpretation.PHARMCAT_INSTALL_DIR", jar_dir), \
             patch("app.core.interpretation._pharmcat_jar_path", return_value=jar):
            result = install_pharmcat(force=False)

        assert result["status"] == "already_installed"
        assert "provenance" in result
        assert result["non_diagnostic"] is True

    def test_install_pharmcat_endpoint_exists(self):
        """Verify the endpoint function is importable."""
        from app.routers.foundation import interpretation_pharmcat_install
        assert callable(interpretation_pharmcat_install)


# ---------------------------------------------------------------------------
# HaploGrep install test
# ---------------------------------------------------------------------------


class TestHaploGrepInstall:
    """Task 4: HaploGrep install checks."""

    def test_install_haplogrep_function_exists(self):
        from app.core.interpretation import install_haplogrep
        assert callable(install_haplogrep)

    def test_install_haplogrep_already_installed(self, tmp_path):
        from app.core.interpretation import install_haplogrep

        jar_dir = tmp_path / "haplogrep"
        jar_dir.mkdir(parents=True, exist_ok=True)
        jar = jar_dir / "haplogrep.jar"
        jar.write_bytes(b"fake-jar-content")

        with patch("app.core.interpretation.HAPLOGREP_INSTALL_DIR", jar_dir), \
             patch("app.core.interpretation._haplogrep_jar_path", return_value=jar):
            result = install_haplogrep(force=False)

        assert result["status"] == "already_installed"
        assert "provenance" in result
        assert result["non_diagnostic"] is True

    def test_install_haplogrep_endpoint_exists(self):
        from app.routers.foundation import interpretation_haplogrep_install
        assert callable(interpretation_haplogrep_install)

    def test_parse_haplogrep_output_with_header(self, tmp_path):
        from app.core.interpretation import parse_haplogrep_output

        out = tmp_path / "haplogroups.txt"
        out.write_text(
            "SampleID\tHaplogroup\tQuality\tNo. of Ns\tCovered Positions\tRange\tInput Mutations\n"
            "S1\tH1a1\t0.947\t0\t16569\t1-16569\tA73G C150T\n",
            encoding="utf-8",
        )

        parsed = parse_haplogrep_output(out)

        assert parsed == [
            {
                "sample_id": "S1",
                "haplogroup": "H1a1",
                "quality_score": 0.947,
                "n_count": "0",
                "covered_positions": "16569",
                "range": "1-16569",
                "input_mutations": "A73G C150T",
            }
        ]

    def test_run_haplogrep_uses_cli_and_parses_output(self, tmp_path):
        from app.core.interpretation import run_haplogrep

        vcf = tmp_path / "S1.mtdna.vcf"
        vcf.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            out_file = Path(cmd[cmd.index("--out") + 1])
            out_file.write_text("SampleID\tHaplogroup\tQuality\nS1\tJ1c\t0.88\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        with patch("app.core.interpretation._haplogrep_executable", return_value="/usr/bin/haplogrep3"), \
             patch("app.core.interpretation.subprocess.run", side_effect=fake_run):
            result = run_haplogrep(vcf, tmp_path / "haplogrep")

        assert result["status"] == "completed"
        assert result["input_vcf_path"] == str(vcf)
        assert result["haplogroups"][0]["haplogroup"] == "J1c"
        assert result["command_source"] == "/usr/bin/haplogrep3"


# ---------------------------------------------------------------------------
# ClinVar VCF install test
# ---------------------------------------------------------------------------


class TestClinVarInstall:
    """Task 5: ClinVar VCF download checks."""

    def test_install_clinvar_vcf_function_exists(self):
        from app.core.interpretation import install_clinvar_vcf
        assert callable(install_clinvar_vcf)

    def test_install_clinvar_vcf_already_installed(self, tmp_path):
        from app.core.interpretation import install_clinvar_vcf

        vcf_dir = tmp_path / "clinvar"
        vcf_dir.mkdir(parents=True, exist_ok=True)
        vcf = vcf_dir / "clinvar.vcf.gz"
        tbi = vcf_dir / "clinvar.vcf.gz.tbi"
        vcf.write_bytes(b"fake-vcf-gz")
        tbi.write_bytes(b"fake-tbi")

        with patch("app.core.interpretation.CLINVAR_VCF_DIR", vcf_dir):
            result = install_clinvar_vcf(force=False)

        assert result["status"] == "already_installed"
        assert "provenance" in result
        assert result["non_diagnostic"] is True

    def test_install_clinvar_endpoint_exists(self):
        from app.routers.foundation import interpretation_clinvar_install
        assert callable(interpretation_clinvar_install)


# ---------------------------------------------------------------------------
# bcftools csq annotation (mock)
# ---------------------------------------------------------------------------


class TestBcftoolsCsqAnnotation:
    """Task 2: Annotation stage script tests (mock)."""

    def test_annotation_script_exists(self):
        script = PIPELINE_SCRIPTS / "run_annotation_stage.sh"
        assert script.exists(), f"Annotation script not found: {script}"

    def test_annotation_script_is_executable(self):
        script = PIPELINE_SCRIPTS / "run_annotation_stage.sh"
        assert os.access(script, os.X_OK), f"Script not executable: {script}"

    def test_annotation_script_contains_bcftools_csq(self):
        script = PIPELINE_SCRIPTS / "run_annotation_stage.sh"
        content = script.read_text(encoding="utf-8")
        assert "bcftools csq" in content

    def test_annotation_script_emits_ingest_json(self):
        script = PIPELINE_SCRIPTS / "run_annotation_stage.sh"
        content = script.read_text(encoding="utf-8")
        assert "annotation.ingest.json" in content


# ---------------------------------------------------------------------------
# VCF normalization (mock)
# ---------------------------------------------------------------------------


class TestVCFNormalization:
    """Task 1 & 8: VCF normalization tests (mock)."""

    def test_normalize_script_exists(self):
        script = PIPELINE_SCRIPTS / "run_vcf_normalize_stage.sh"
        assert script.exists(), f"Normalize script not found: {script}"

    def test_normalize_script_is_executable(self):
        script = PIPELINE_SCRIPTS / "run_vcf_normalize_stage.sh"
        assert os.access(script, os.X_OK), f"Script not executable: {script}"

    def test_normalize_script_contains_bcftools_norm(self):
        script = PIPELINE_SCRIPTS / "run_vcf_normalize_stage.sh"
        content = script.read_text(encoding="utf-8")
        assert "bcftools norm" in content
        assert "-m -any" in content

    def test_normalize_script_emits_ingest_json(self):
        script = PIPELINE_SCRIPTS / "run_vcf_normalize_stage.sh"
        content = script.read_text(encoding="utf-8")
        assert "normalize.ingest.json" in content

    def test_normalize_endpoint_exists(self):
        from app.routers.foundation import interpretation_normalize
        assert callable(interpretation_normalize)
