from __future__ import annotations

import glob
from pathlib import Path


STAGE_SCRIPT_SEARCH_DIRS = (
    "/app/pipelines/nextflow/scripts",
    "/workspace/pipelines/nextflow/scripts",
    "pipelines/nextflow/scripts",
    "/app/scripts/stages",
    "/tmp/nf-pipeline/scripts/stages",
)


def variant_calling_backend(stage_options: dict | None = None, default_backend: str = "bcftools") -> str:
    requested = (stage_options or {}).get("variant_caller") or default_backend
    return requested if requested in {"bcftools", "gatk", "deepvariant"} else "bcftools"


def stage_script_name(
    stage_name: str,
    stage_options: dict | None = None,
    default_variant_backend: str = "bcftools",
) -> str | None:
    if stage_name == "variants":
        return {
            "bcftools": "run_bcftools_variant_calling_stage.sh",
            "gatk": "run_gatk_variant_calling_stage.sh",
            "deepvariant": "run_deepvariant_stage.sh",
        }[variant_calling_backend(stage_options, default_variant_backend)]

    script_map = {
        "alignment": "run_alignment_stage.sh",
        "coverage": "run_coverage_stage.sh",
        "sv": "run_sv_calling_stage.sh",
        "cnv": "run_cnv_calling_stage.sh",
        "annotation": "run_annotation_stage.sh",
        "taxonomy": "run_taxonomy_stage.sh",
        "unknown_reads": "run_unknown_reads_stage.sh",
        "mtdna": "run_mtdna_stage.sh",
        "prs": "run_prs_stage.sh",
        "benchmark": "run_benchmark_stage.sh",
    }
    return script_map.get(stage_name)


def find_stage_script(script_name: str, search_dirs: tuple[str, ...] = STAGE_SCRIPT_SEARCH_DIRS) -> str | None:
    for search_dir in search_dirs:
        candidates = glob.glob(f"{search_dir}/**/{script_name}", recursive=True)
        if candidates:
            return candidates[0]
    return None


def sanitize_stage_script(script_path: str, output_dir: Path, stage_name: str) -> str:
    """Copy a script to the run output directory with CRLF stripped."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sanitized_script = output_dir / f".{stage_name}.stage.sh"
    raw_script = Path(script_path).read_text(encoding="utf-8", errors="ignore")
    sanitized_script.write_text(raw_script.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
    sanitized_script.chmod(0o755)
    return str(sanitized_script)


def build_stage_command(
    *,
    stage_name: str,
    script_path: str,
    sample_id: str,
    reference_fasta: str,
    r1: str,
    r2: str,
    bam: str,
    vcf: str,
    reference_id: str,
    threads: int,
    allow_fallback: str,
    stage_options: dict | None = None,
    taxonomy_route: str = "human_wgs_host_depleted",
    taxonomy_low_mapq_threshold: int = 10,
    default_variant_backend: str = "bcftools",
    deepvariant_model_default: str = "WGS",
) -> list[str] | None:
    stage_options = stage_options or {}
    if stage_name == "alignment":
        return ["bash", script_path, sample_id, reference_fasta, r1, r2, str(threads), allow_fallback]
    if stage_name == "coverage":
        return ["bash", script_path, sample_id, bam, str(threads), "1000000", "1mb", allow_fallback]
    if stage_name == "variants":
        variant_backend = variant_calling_backend(stage_options, default_variant_backend)
        if variant_backend == "deepvariant":
            model_type = str(stage_options.get("deepvariant_model") or deepvariant_model_default)
            return ["bash", script_path, sample_id, bam, reference_fasta, str(threads), allow_fallback, model_type]
        return ["bash", script_path, sample_id, bam, reference_fasta, str(threads), allow_fallback]
    if stage_name in {"sv", "cnv", "mtdna"}:
        return ["bash", script_path, sample_id, bam, reference_fasta, str(threads), allow_fallback]
    if stage_name == "annotation":
        gff = stage_options.get("annotation_gff_path") or ""
        return ["bash", script_path, sample_id, vcf, reference_fasta, gff, str(threads), allow_fallback]
    if stage_name == "taxonomy":
        taxonomy_db = stage_options.get("taxonomy_database_path") or ""
        return [
            "bash",
            script_path,
            sample_id,
            r1,
            r2,
            str(threads),
            allow_fallback,
            taxonomy_db,
            bam,
            taxonomy_route,
            str(taxonomy_low_mapq_threshold),
        ]
    if stage_name == "unknown_reads":
        taxonomy_db = stage_options.get("taxonomy_database_path") or ""
        return ["bash", script_path, sample_id, r1, r2, str(threads), allow_fallback, taxonomy_db, bam]
    if stage_name == "prs":
        return ["bash", script_path, sample_id, vcf, reference_id, allow_fallback]
    if stage_name == "benchmark":
        return ["bash", script_path, sample_id, vcf, reference_fasta, str(threads), allow_fallback]
    return None
