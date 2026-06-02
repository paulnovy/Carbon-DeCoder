import os
from pathlib import Path

from app.core.stage_runner import (
    build_stage_command,
    find_stage_script,
    sanitize_stage_script,
    stage_script_name,
    variant_calling_backend,
)


def test_stage_script_name_routes_optional_stages():
    assert stage_script_name("unknown_reads") == "run_unknown_reads_stage.sh"
    assert stage_script_name("annotation") == "run_annotation_stage.sh"
    assert stage_script_name("taxonomy") == "run_taxonomy_stage.sh"
    assert stage_script_name("benchmark") == "run_benchmark_stage.sh"
    assert stage_script_name("variants", {"variant_caller": "deepvariant"}) == "run_deepvariant_stage.sh"
    assert (
        stage_script_name("variants", {}, default_variant_backend="gatk")
        == "run_gatk_variant_calling_stage.sh"
    )
    assert stage_script_name("not_a_stage") is None


def test_variant_calling_backend_rejects_unknown_values():
    assert variant_calling_backend({"variant_caller": "deepvariant"}) == "deepvariant"
    assert variant_calling_backend({"variant_caller": "custom"}) == "bcftools"
    assert variant_calling_backend({}, default_backend="gatk") == "gatk"


def test_find_and_sanitize_stage_script(tmp_path: Path):
    nested = tmp_path / "scripts" / "stages"
    nested.mkdir(parents=True)
    script = nested / "run_taxonomy_stage.sh"
    script.write_text("#!/usr/bin/env bash\r\nset -euo pipefail\r\necho ok\r\n", encoding="utf-8")

    found = find_stage_script("run_taxonomy_stage.sh", (str(tmp_path),))
    assert found == str(script)

    sanitized = Path(sanitize_stage_script(found, tmp_path / "run", "taxonomy"))
    assert sanitized.read_text(encoding="utf-8") == "#!/usr/bin/env bash\nset -euo pipefail\necho ok\n"
    assert os.access(sanitized, os.X_OK)


def test_build_stage_command_preserves_taxonomy_host_depletion_args():
    cmd = build_stage_command(
        stage_name="taxonomy",
        script_path="/scripts/run_taxonomy_stage.sh",
        sample_id="S1",
        reference_fasta="/ref.fa",
        r1="/reads/R1.fastq.gz",
        r2="/reads/R2.fastq.gz",
        bam="/results/S1.sorted.markdup.bam",
        vcf="/results/S1.bcftools.raw.vcf",
        reference_id="GRCh38",
        threads=8,
        allow_fallback="false",
        stage_options={"taxonomy_database_path": "/db/kraken"},
        taxonomy_route="human_wgs_host_depleted",
        taxonomy_low_mapq_threshold=12,
    )

    assert cmd == [
        "bash",
        "/scripts/run_taxonomy_stage.sh",
        "S1",
        "/reads/R1.fastq.gz",
        "/reads/R2.fastq.gz",
        "8",
        "false",
        "/db/kraken",
        "/results/S1.sorted.markdup.bam",
        "human_wgs_host_depleted",
        "12",
    ]


def test_build_stage_command_handles_unknown_reads_and_deepvariant_model():
    unknown_cmd = build_stage_command(
        stage_name="unknown_reads",
        script_path="/scripts/run_unknown_reads_stage.sh",
        sample_id="S1",
        reference_fasta="/ref.fa",
        r1="/reads/R1.fastq.gz",
        r2="/reads/R2.fastq.gz",
        bam="/results/S1.sorted.markdup.bam",
        vcf="/results/S1.bcftools.raw.vcf",
        reference_id="GRCh38",
        threads=4,
        allow_fallback="true",
        stage_options={"taxonomy_database_path": "/db/kraken"},
    )
    assert unknown_cmd[-2:] == ["/db/kraken", "/results/S1.sorted.markdup.bam"]

    variant_cmd = build_stage_command(
        stage_name="variants",
        script_path="/scripts/run_deepvariant_stage.sh",
        sample_id="S1",
        reference_fasta="/ref.fa",
        r1="/reads/R1.fastq.gz",
        r2="/reads/R2.fastq.gz",
        bam="/results/S1.sorted.markdup.bam",
        vcf="/results/S1.bcftools.raw.vcf",
        reference_id="GRCh38",
        threads=16,
        allow_fallback="false",
        stage_options={"variant_caller": "deepvariant"},
        deepvariant_model_default="PACBIO",
    )
    assert variant_cmd == [
        "bash",
        "/scripts/run_deepvariant_stage.sh",
        "S1",
        "/results/S1.sorted.markdup.bam",
        "/ref.fa",
        "16",
        "false",
        "PACBIO",
    ]


def test_build_stage_command_handles_annotation_stage():
    cmd = build_stage_command(
        stage_name="annotation",
        script_path="/scripts/run_annotation_stage.sh",
        sample_id="S1",
        reference_fasta="/ref.fa",
        r1="/reads/R1.fastq.gz",
        r2="/reads/R2.fastq.gz",
        bam="/results/S1.sorted.markdup.bam",
        vcf="/results/S1.bcftools.raw.vcf",
        reference_id="GRCh38",
        threads=6,
        allow_fallback="true",
        stage_options={"annotation_gff_path": "/refs/genes.gff3"},
    )

    assert cmd == [
        "bash",
        "/scripts/run_annotation_stage.sh",
        "S1",
        "/results/S1.bcftools.raw.vcf",
        "/ref.fa",
        "/refs/genes.gff3",
        "6",
        "true",
    ]


def test_build_stage_command_handles_benchmark_stage():
    cmd = build_stage_command(
        stage_name="benchmark",
        script_path="/scripts/run_benchmark_stage.sh",
        sample_id="S1",
        reference_fasta="/ref.fa",
        r1="/reads/R1.fastq.gz",
        r2="/reads/R2.fastq.gz",
        bam="/results/S1.sorted.markdup.bam",
        vcf="/results/S1.bcftools.raw.vcf",
        reference_id="GRCh38",
        threads=6,
        allow_fallback="false",
    )

    assert cmd == [
        "bash",
        "/scripts/run_benchmark_stage.sh",
        "S1",
        "/results/S1.bcftools.raw.vcf",
        "/ref.fa",
        "6",
        "false",
    ]
