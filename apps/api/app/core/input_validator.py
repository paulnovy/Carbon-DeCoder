import gzip
import hashlib
import os
import re
import shutil
from pathlib import Path

from .models import InputValidationRequest, InputValidationResult

SUPPORTED_REFERENCE_PROFILES = {
    "GRCh38_standard",
    "GRCh38_GIAB_masked_false_duplications",
    "GRCh37_legacy",
    "T2T_CHM13v2_hs1",
    "T2T_HG002_v1_1",
    "mtDNA_rCRS",
    "mtDNA_RSRS",
}

FASTQ_EXT = (".fastq", ".fastq.gz", ".fq", ".fq.gz")


def _quick_sha256(path: Path, chunk_size: int = 1024 * 1024, max_chunks: int = 32) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        chunks = 0
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            digest.update(data)
            chunks += 1
            if chunks >= max_chunks:
                break
    return digest.hexdigest()


def _gzip_probe(path: Path) -> bool:
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
            _ = f.readline()
        return True
    except OSError:
        return False


def _fastq_header_probe(path: Path) -> bool:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="ignore") as f:
        line = f.readline()
    return line.startswith("@")


def validate_input(req: InputValidationRequest) -> InputValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    checksums: dict[str, str] = {}
    preflight: dict = {}

    if not req.sample_id.strip():
        errors.append("sample_id_missing")
    elif not re.match(r"^[A-Za-z0-9_.-]{2,64}$", req.sample_id):
        warnings.append("sample_id_contains_unusual_characters")

    r1 = Path(req.r1_path)
    r2 = Path(req.r2_path) if req.r2_path else None

    if not req.r1_path.lower().endswith(FASTQ_EXT):
        errors.append("r1_invalid_extension")

    if req.r2_path and not req.r2_path.lower().endswith(FASTQ_EXT):
        errors.append("r2_invalid_extension")

    if not r1.exists():
        errors.append("r1_missing")
    elif r1.stat().st_size == 0:
        errors.append("r1_empty")

    if r2 and not r2.exists():
        errors.append("r2_missing")
    elif r2 and r2.stat().st_size == 0:
        errors.append("r2_empty")

    if req.reference_profile not in SUPPORTED_REFERENCE_PROFILES:
        errors.append("unsupported_reference_profile")

    if not req.non_diagnostic_confirmed:
        errors.append("non_diagnostic_confirmation_required")

    if req.sample_sheet_path and not Path(req.sample_sheet_path).exists():
        errors.append("sample_sheet_missing")

    if r1.exists():
        if str(r1).endswith(".gz") and not _gzip_probe(r1):
            errors.append("r1_gzip_corrupted")
        try:
            if not _fastq_header_probe(r1):
                errors.append("r1_not_fastq_like")
        except Exception:
            errors.append("r1_probe_failed")

    if r2 and r2.exists():
        if str(r2).endswith(".gz") and not _gzip_probe(r2):
            errors.append("r2_gzip_corrupted")
        try:
            if not _fastq_header_probe(r2):
                errors.append("r2_not_fastq_like")
        except Exception:
            errors.append("r2_probe_failed")

    # Lightweight file fingerprint (not full-file hashing in API call).
    if r1.exists():
        checksums["r1_quick_sha256"] = _quick_sha256(r1)
    if r2 and r2.exists():
        checksums["r2_quick_sha256"] = _quick_sha256(r2)

    # Preflight disk estimate
    target = r1.parent if r1.exists() else Path("/")
    usage = shutil.disk_usage(target)
    free_gb = usage.free / (1024**3)
    estimated_output_gb = 120.0 if req.mode == "full-wgs" else 8.0
    preflight["free_space_gb"] = round(free_gb, 2)
    preflight["required_space_gb"] = max(req.min_free_space_gb, estimated_output_gb)
    if free_gb < preflight["required_space_gb"]:
        errors.append("insufficient_disk_space")

    if req.r2_path and r1.name and r2 and r2.name:
        if "R1" in r1.name and "R2" in r2.name:
            pass
        else:
            warnings.append("r1_r2_naming_nonstandard")

    if req.mode == "benchmark" and "GIAB" not in req.reference_profile and "GRCh38" not in req.reference_profile:
        warnings.append("benchmark_reference_may_not_match_giab_truth_sets")

    status = "OK"
    if errors:
        status = "stop"
    elif warnings:
        status = "warning"

    return InputValidationResult(
        valid=not errors,
        status=status,
        errors=errors,
        warnings=warnings,
        estimated_output_gb=estimated_output_gb,
        checksums=checksums,
        preflight=preflight,
    )
