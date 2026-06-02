from __future__ import annotations

import os
import re
import copy
import json
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter()

MAX_UPLOAD_BYTES = 10_737_418_240
INPUT_MIN_FREE_GB_ENV = "WGS_INPUT_MIN_FREE_GB"
DOWNLOAD_JOBS: dict[str, dict[str, Any]] = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
TAXONOMY_DB_DIR = Path(os.getenv("WGS_KRAKEN_DB_DIR", "/data/databases/kraken2"))
TAXONOMY_INSTALL_JOBS: dict[str, dict[str, Any]] = {}
TAXONOMY_INSTALL_JOBS_LOCK = threading.Lock()
CUSTOM_REFS_DIR = Path("/data/references/custom")
REFERENCE_INDEX_JOBS: dict[str, dict[str, Any]] = {}
DATA_PREP_JOBS: dict[str, dict[str, Any]] = {}
DATA_PREP_JOBS_LOCK = threading.Lock()
CAPABILITIES_CACHE_TTL_SECONDS = int(os.getenv("WGS_CAPABILITIES_CACHE_TTL_SECONDS", "300"))
CAPABILITIES_CACHE: dict[str, Any] = {"expires_at": 0.0, "data": None}
CAPABILITIES_CACHE_LOCK = threading.Lock()

TAXONOMY_DATABASES = [
    {
        "id": "viral",
        "name": "RefSeq Viral",
        "description": "RefSeq viral genomes — quick contamination screen",
        "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_viral_20260226.tar.gz",
        "archive_size_gb": 0.5,
        "index_size_gb": 0.6,
    },
    {
        "id": "standard-8",
        "name": "Standard (8GB cap)",
        "description": "RefSeq bacteria, viral, archaea, human — capped at 8GB for smaller systems",
        "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_standard_08_GB_20260226.tar.gz",
        "archive_size_gb": 5.5,
        "index_size_gb": 7.5,
    },
    {
        "id": "standard-16",
        "name": "Standard (16GB cap)",
        "description": "Standard database with more resolution",
        "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_standard_16_GB_20260226.tar.gz",
        "archive_size_gb": 11.2,
        "index_size_gb": 14.9,
    },
    {
        "id": "minusb",
        "name": "MinusB (no bacteria)",
        "description": "Archaea, viral, plasmid, human, UniVec — no bacterial sequences",
        "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_minusb_20260226.tar.gz",
        "archive_size_gb": 7.9,
        "index_size_gb": 11.1,
    },
    {
        "id": "standard",
        "name": "Standard (full)",
        "description": "Full RefSeq standard — requires ~100GB disk",
        "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_standard_20260226.tar.gz",
        "archive_size_gb": 74.7,
        "index_size_gb": 96.8,
    },
]

BIOINFORMATICS_TOOLS = [
    "bwa",
    "bwa-mem2",
    "bwa-mem2.avx512",
    "bwa-mem2.avx2",
    "bwa-mem2.sse42",
    "bwa-mem2.sse41",
    "minimap2",
    "samtools",
    "bcftools",
    "mosdepth",
    "gatk",
    "deepvariant",
    "kraken2",
    "cnvkit",
    "cnvkit.py",
    "manta",
    "configManta.py",
    "delly",
]

TOOL_VERSION_COMMANDS = {
    "bwa": ["bwa"],
    "bwa-mem2": ["bwa-mem2", "version"],
    "bwa-mem2.avx512": ["bwa-mem2.avx512", "version"],
    "bwa-mem2.avx2": ["bwa-mem2.avx2", "version"],
    "bwa-mem2.sse42": ["bwa-mem2.sse42", "version"],
    "bwa-mem2.sse41": ["bwa-mem2.sse41", "version"],
    "minimap2": ["minimap2", "--version"],
    "samtools": ["samtools", "--version"],
    "bcftools": ["bcftools", "--version"],
    "mosdepth": ["mosdepth", "--version"],
    "gatk": ["gatk", "--version"],
    "deepvariant": ["run_deepvariant", "--version"],
    "kraken2": ["kraken2", "--version"],
    "cnvkit": ["cnvkit", "version"],
    "cnvkit.py": ["cnvkit.py", "version"],
    "manta": ["manta", "--version"],
    "configManta.py": ["configManta.py", "--version"],
    "delly": ["delly", "--version"],
}

TOOL_BINARY_CANDIDATES = {
    "deepvariant": ["run_deepvariant", "deepvariant", "/opt/deepvariant/bin/run_deepvariant"],
}


def _input_dir() -> Path:
    path = Path(os.getenv("WGS_INPUT_DIR", "/data/input"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _classify_file(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq", ".fastq.bz2", ".fq.bz2")):
        return "fastq"
    if lower.endswith(".bam"):
        return "bam"
    if lower.endswith((".vcf", ".vcf.gz")):
        return "vcf"
    return "other"


def _supported_input_suffixes() -> tuple[str, ...]:
    return (
        ".fastq.gz",
        ".fq.gz",
        ".fastq",
        ".fq",
        ".fastq.bz2",
        ".fq.bz2",
        ".bam",
        ".vcf",
        ".vcf.gz",
    )


def _safe_input_path(path: str) -> Path:
    base_dir = _input_dir().resolve()
    raw = Path(path)
    target = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    if not target.is_relative_to(base_dir):
        raise HTTPException(400, "Path escapes input directory")
    return target


def _input_min_free_bytes() -> int:
    raw = os.getenv(INPUT_MIN_FREE_GB_ENV, "5").strip()
    try:
        gb = max(0.0, float(raw))
    except ValueError:
        gb = 5.0
    return int(gb * 1024**3)


def _nearest_existing_path(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current if current.exists() else Path("/")


def _storage_preflight(path: Path, incoming_bytes: int = 0) -> dict[str, Any]:
    usage = shutil.disk_usage(_nearest_existing_path(path))
    min_free_bytes = _input_min_free_bytes()
    projected_free_bytes = usage.free - max(0, int(incoming_bytes or 0))
    return {
        "path": str(path),
        "incoming_bytes": int(incoming_bytes or 0),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "min_free_bytes": min_free_bytes,
        "projected_free_bytes": projected_free_bytes,
        "ok": projected_free_bytes >= min_free_bytes,
    }


def _ensure_storage_headroom(path: Path, incoming_bytes: int, code: str) -> dict[str, Any]:
    preflight = _storage_preflight(path, incoming_bytes)
    if not preflight["ok"]:
        raise HTTPException(status_code=507, detail={"code": code, "storage": preflight})
    return preflight


def _index_candidates(path: Path) -> list[Path]:
    lower = path.name.lower()
    if lower.endswith(".bam"):
        return [Path(str(path) + ".bai"), path.with_suffix(".bai")]
    if lower.endswith(".vcf.gz"):
        return [Path(str(path) + ".tbi"), Path(str(path) + ".csi")]
    return []


def _index_ready(path: Path) -> bool:
    return any(candidate.exists() and candidate.stat().st_size > 0 for candidate in _index_candidates(path))


def _samtools_sort_order(path: Path) -> tuple[str | None, str | None]:
    if not shutil.which("samtools"):
        return None, "samtools_unavailable"
    try:
        completed = subprocess.run(
            ["samtools", "view", "-H", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "bam_header_probe_timeout"
    except Exception as exc:
        return None, f"bam_header_probe_failed:{type(exc).__name__}"
    if completed.returncode != 0:
        return None, "bam_header_unreadable"
    for line in completed.stdout.splitlines():
        if not line.startswith("@HD"):
            continue
        for field in line.split("\t"):
            if field.startswith("SO:"):
                return field[3:] or None, None
    return None, "bam_sort_order_missing"


def _input_file_preflight(path: Path) -> dict[str, Any]:
    lower = path.name.lower()
    if lower.endswith(".bam"):
        sort_order, sort_warning = _samtools_sort_order(path)
        sorted_ready = sort_order == "coordinate"
        index_ready = _index_ready(path)
        warnings: list[str] = []
        if not index_ready:
            warnings.append("bam_index_missing")
        if not sorted_ready:
            warnings.append("bam_not_coordinate_sorted" if sort_order else (sort_warning or "bam_sort_order_unknown"))
        action = None
        if not sorted_ready:
            action = "sort_and_index"
        elif not index_ready:
            action = "index"
        return {
            "required": True,
            "ready": sorted_ready and index_ready,
            "index_ready": index_ready,
            "sorted": sorted_ready,
            "sort_order": sort_order,
            "warnings": warnings,
            "prepare_action": action,
            "can_prepare": bool(action and shutil.which("samtools")),
            "index_candidates": [str(p.name) for p in _index_candidates(path)],
        }
    if lower.endswith(".vcf.gz"):
        index_ready = _index_ready(path)
        return {
            "required": True,
            "ready": index_ready,
            "index_ready": index_ready,
            "sorted": None,
            "sort_order": None,
            "warnings": [] if index_ready else ["vcf_index_missing"],
            "prepare_action": None if index_ready else "index",
            "can_prepare": bool((not index_ready) and shutil.which("tabix")),
            "index_candidates": [str(p.name) for p in _index_candidates(path)],
        }
    if lower.endswith(".vcf"):
        return {
            "required": True,
            "ready": False,
            "index_ready": False,
            "sorted": None,
            "sort_order": None,
            "warnings": ["vcf_not_bgzipped", "vcf_index_missing"],
            "prepare_action": "compress_and_index",
            "can_prepare": bool(shutil.which("bgzip") and shutil.which("tabix")),
            "index_candidates": [f"{path.name}.gz.tbi", f"{path.name}.gz.csi"],
        }
    return {"required": False, "ready": True, "warnings": []}


def _input_file_entry(path: Path, base_dir: Path) -> dict[str, Any]:
    rel_path = str(path.relative_to(base_dir))
    return {
        "name": path.name,
        "path": rel_path,
        "size": path.stat().st_size,
        "type": _classify_file(path.name),
        "paired": _pair_role(path.name),
        "vendor": _detect_vendor(path.name),
        "preflight": _input_file_preflight(path),
    }


def _pair_role(name: str) -> str | None:
    stem = name.lower()
    if re.search(r"_r1_", stem):
        return "R1"
    if re.search(r"_r2_", stem):
        return "R2"
    if re.search(r"[._-]r1(?:[._-]|$)", stem):
        return "R1"
    if re.search(r"[._-]r2(?:[._-]|$)", stem):
        return "R2"
    if re.search(r"_1\.f(?:ast)?q", stem):
        return "R1"
    if re.search(r"_2\.f(?:ast)?q", stem):
        return "R2"
    return None


def _detect_vendor(name: str) -> str:
    lower = name.lower()
    if "samplesheet" in lower or "sample_sheet" in lower:
        return "illumina"
    if re.match(r"srr\d+", lower) or re.match(r"err\d+", lower) or re.match(r"drr\d+", lower):
        return "sra"
    if re.search(r"_s\d+_l\d+_", lower):
        return "illumina"
    if ".hifi." in lower or ".ccs." in lower:
        return "pacbio"
    if re.search(r"_r[12]\.f", lower) and not re.search(r"_l\d+", lower):
        return "bgi"
    return "unknown"


def _fastq_pair_key(path: Path) -> tuple[str, str | None] | None:
    name = path.name
    lower = name.lower()
    if _classify_file(name) != "fastq":
        return None

    role = _pair_role(name)
    if not role:
        return None

    key = re.sub(r"\.f(?:ast)?q(?:\.(?:gz|bz2))?$", "", lower)
    key = re.sub(r"([._-])r[12]([._-]|$)", r"\1\2", key)
    key = re.sub(r"_r[12]_", "_", key)
    key = re.sub(r"_l\d{3}(?=_)|[._-]l\d{3}(?=[._-]|$)", "", key)
    key = re.sub(r"[._-][12]$", "", key)
    key = re.sub(r"[_ .-]+", "_", key).strip("_")
    return key or lower, role


def _directory_preset(path: Path, base_dir: Path) -> dict[str, Any] | None:
    try:
        children = list(path.iterdir())
    except OSError:
        return None

    files = [item for item in children if item.is_file()]
    supported = [item for item in files if item.name.lower().endswith(_supported_input_suffixes())]
    metadata_names = {item.name.lower() for item in files if item.name.lower() in {"samplesheet.csv", "sample_sheet.csv", "metadata.csv", "manifest.csv"}}
    if not supported and not metadata_names:
        return None

    counts = {"fastq": 0, "bam": 0, "vcf": 0, "other_supported": 0}
    vendors: dict[str, int] = {}
    pair_roles: dict[str, set[str]] = {}
    pair_paths: dict[str, dict[str, str]] = {}
    lanes: set[str] = set()
    warnings: list[str] = []

    for item in supported:
        ftype = _classify_file(item.name)
        if ftype in counts:
            counts[ftype] += 1
        else:
            counts["other_supported"] += 1

        vendor = _detect_vendor(item.name)
        vendors[vendor] = vendors.get(vendor, 0) + 1
        lane_match = re.search(r"[_-]L(\d{3})(?:[_-]|$)", item.name, re.I)
        if lane_match:
            lanes.add(lane_match.group(1))

        pair = _fastq_pair_key(item)
        if pair:
            key, role = pair
            pair_roles.setdefault(key, set()).add(role or "")
            pair_paths.setdefault(key, {})[role or ""] = str(item.relative_to(base_dir))

    complete_pair_keys = sorted(key for key, roles in pair_roles.items() if {"R1", "R2"}.issubset(roles))
    incomplete_pair_keys = sorted(key for key, roles in pair_roles.items() if roles and not {"R1", "R2"}.issubset(roles))
    if incomplete_pair_keys:
        warnings.append("incomplete_fastq_pairs")
    if counts["bam"] > 1:
        warnings.append("multiple_bam_inputs")
    if counts["vcf"] and not counts["fastq"] and not counts["bam"]:
        warnings.append("vcf_not_pipeline_start_input")

    recommended_paths: list[str] = []
    if complete_pair_keys:
        for key in complete_pair_keys:
            for role in ("R1", "R2"):
                recommended_paths.append(pair_paths[key][role])
    elif counts["bam"] == 1:
        recommended_paths = [str(item.relative_to(base_dir)) for item in supported if _classify_file(item.name) == "bam"]
    elif counts["vcf"]:
        recommended_paths = [str(item.relative_to(base_dir)) for item in supported if _classify_file(item.name) == "vcf"]

    if metadata_names or vendors.get("illumina", 0):
        preset_id = "illumina_fastq_folder" if counts["fastq"] else "illumina_metadata_folder"
        vendor = "illumina"
        label = "Illumina FASTQ folder" if counts["fastq"] else "Illumina metadata folder"
    elif vendors.get("sra", 0):
        preset_id = "sra_fastq_folder"
        vendor = "sra"
        label = "SRA FASTQ folder"
    elif vendors.get("pacbio", 0):
        preset_id = "pacbio_hifi_folder"
        vendor = "pacbio"
        label = "PacBio HiFi folder"
    elif counts["bam"]:
        preset_id = "prealigned_bam_folder"
        vendor = "prealigned"
        label = "Pre-aligned BAM folder"
    elif counts["vcf"]:
        preset_id = "vcf_folder"
        vendor = "vcf"
        label = "VCF folder"
    elif counts["fastq"]:
        preset_id = "generic_fastq_folder"
        vendor = "unknown"
        label = "FASTQ folder"
    else:
        preset_id = "input_folder"
        vendor = max(vendors, key=vendors.get) if vendors else "unknown"
        label = "Input folder"

    confidence = "high" if complete_pair_keys or metadata_names or vendor != "unknown" else "medium"
    return {
        "id": preset_id,
        "label": label,
        "vendor": vendor,
        "confidence": confidence,
        "counts": counts,
        "fastq_pairs": len(complete_pair_keys),
        "incomplete_fastq_pairs": len(incomplete_pair_keys),
        "lanes": sorted(lanes),
        "sample_keys": complete_pair_keys[:20],
        "recommended_paths": recommended_paths[:100],
        "recommended_action": "start_pipeline" if complete_pair_keys or counts["bam"] == 1 else "prepare_or_import",
        "warnings": warnings,
    }


def _scan_files(base_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(base_dir.rglob("*")):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if not lower.endswith(_supported_input_suffixes()):
            continue
        files.append(_input_file_entry(path, base_dir))
    return files


def _safe_filename_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    candidate = Path(parsed.path).name
    return candidate or f"download_{uuid4().hex[:8]}"


def _update_job(job_id: str, **kwargs: Any) -> None:
    with DOWNLOAD_JOBS_LOCK:
        if job_id in DOWNLOAD_JOBS:
            DOWNLOAD_JOBS[job_id].update(kwargs)


def _download_worker(job_id: str, url: str, destination: Path) -> None:
    start = time.time()
    downloaded = 0
    total_bytes: int | None = None
    _update_job(job_id, status="downloading", phase="downloading", started_at=start)

    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # nosec B310
            content_length = response.headers.get("Content-Length")
            if content_length and content_length.isdigit():
                total_bytes = int(content_length)
                storage = _storage_preflight(destination.parent, total_bytes)
                _update_job(job_id, total_bytes=total_bytes, storage_preflight=storage)
                if not storage["ok"]:
                    raise RuntimeError("insufficient_input_storage")

            with destination.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    _ensure_storage_headroom(destination.parent, len(chunk), "insufficient_input_storage")
                    out.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.time() - start, 1e-6)
                    speed = int(downloaded / elapsed)
                    _update_job(
                        job_id,
                        downloaded_bytes=downloaded,
                        speed_bps=speed,
                        total_bytes=total_bytes,
                    )

        elapsed = max(time.time() - start, 1e-6)
        _update_job(
            job_id,
            status="done",
            phase="done",
            downloaded_bytes=downloaded,
            total_bytes=total_bytes,
            speed_bps=int(downloaded / elapsed),
            finished_at=time.time(),
        )
    except Exception as exc:
        destination.unlink(missing_ok=True)
        _update_job(job_id, status="failed", phase="failed", error=str(exc), finished_at=time.time())


class ImportUrlRequest(BaseModel):
    url: str
    filename: str | None = None


class ImportUrlResponse(BaseModel):
    job_id: str
    status: str


class DataPrepareRequest(BaseModel):
    path: str
    action: str | None = None


@router.get("/data/scan")
def data_scan() -> dict[str, Any]:
    base_dir = _input_dir()
    return {"input_dir": str(base_dir), "items": _scan_files(base_dir)}


@router.get("/data/browse")
def data_browse(path: str = "") -> dict[str, Any]:
    """Browse the input directory tree with sub-folder support."""
    base_dir = _input_dir()
    target = (base_dir / path).resolve()
    # Security: ensure we stay within input dir
    if not str(target).startswith(str(base_dir.resolve())):
        raise HTTPException(400, "Path escapes input directory")
    if not target.is_dir():
        raise HTTPException(404, f"Directory not found: {path}")

    entries: list[dict[str, Any]] = []
    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        is_dir = item.is_dir()
        if is_dir:
            # Count children for directories
            child_count = sum(1 for _ in item.iterdir())
            preset = _directory_preset(item, base_dir)
            entries.append({
                "name": item.name,
                "path": str(item.relative_to(base_dir)),
                "type": "directory",
                "size": 0,
                "child_count": child_count,
                "preset": preset,
            })
        else:
            lower = item.name.lower()
            is_supported = lower.endswith(_supported_input_suffixes())
            if is_supported:
                entry = _input_file_entry(item, base_dir)
                entry["supported"] = True
                entries.append(entry)
            else:
                entries.append({
                    "name": item.name,
                    "path": str(item.relative_to(base_dir)),
                    "type": "other",
                    "size": item.stat().st_size,
                    "supported": False,
                    "paired": None,
                    "vendor": "unknown",
                    "preflight": {"required": False, "ready": True, "warnings": []},
                })

    rel = str(target.relative_to(base_dir)) if target != base_dir else ""
    return {
        "input_dir": str(base_dir),
        "current_path": rel,
        "parent_path": str(Path(rel).parent) if rel else None,
        "items": entries,
    }


@router.post("/data/import-url", response_model=ImportUrlResponse)
def import_from_url(req: ImportUrlRequest) -> ImportUrlResponse:
    base_dir = _input_dir()
    filename = req.filename.strip() if req.filename else _safe_filename_from_url(req.url)
    if not filename:
        raise HTTPException(status_code=400, detail="invalid_filename")

    destination = base_dir / Path(filename).name
    job_id = f"job_{uuid4().hex[:12]}"

    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = {
            "job_id": job_id,
            "status": "downloading",
            "phase": "queued",
            "url": req.url,
            "filename": destination.name,
            "path": str(destination),
            "downloaded_bytes": 0,
            "total_bytes": None,
            "speed_bps": 0,
            "started_at": None,
            "finished_at": None,
        }

    thread = threading.Thread(target=_download_worker, args=(job_id, req.url, destination), daemon=True)
    thread.start()

    return ImportUrlResponse(job_id=job_id, status="downloading")


@router.get("/data/import-url/{job_id}")
def import_from_url_status(job_id: str) -> dict[str, Any]:
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    downloaded = int(job.get("downloaded_bytes", 0) or 0)
    total = job.get("total_bytes")
    speed = int(job.get("speed_bps", 0) or 0)
    started_at = job.get("started_at")
    finished_at = job.get("finished_at")
    elapsed_sec = round((finished_at or time.time()) - started_at, 1) if started_at else None
    eta_sec = None
    if total and speed > 0 and downloaded < int(total):
        eta_sec = max(0, int((int(total) - downloaded) / speed))

    payload = {
        "job_id": job["job_id"],
        "status": job.get("status", "unknown"),
        "phase": job.get("phase") or job.get("status", "unknown"),
        "downloaded_bytes": downloaded,
        "total_bytes": total,
        "speed_bps": speed,
        "progress_pct": round((downloaded / int(total)) * 100, 2) if total else None,
        "elapsed_sec": elapsed_sec,
        "eta_sec": eta_sec,
    }
    for key in ("error", "storage_preflight", "checksum", "reference_ready", "fasta_path", "filename", "path", "destination"):
        if key in job:
            payload[key] = job.get(key)
    return payload


@router.post("/data/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    base_dir = _input_dir()
    destination = base_dir / Path(file.filename or f"upload_{uuid4().hex[:8]}").name
    size = 0
    storage_preflight = _storage_preflight(base_dir)

    try:
        with destination.open("wb") as out:
            while True:
                chunk = await file.read(4 * 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="file_too_large_max_10gb")
                storage_preflight = _ensure_storage_headroom(base_dir, len(chunk), "insufficient_input_storage")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {"filename": destination.name, "size": size, "path": str(destination), "storage_preflight": storage_preflight}


def _relative_input_path(path: Path) -> str:
    return str(path.resolve().relative_to(_input_dir().resolve()))


def _update_prep_job(job_id: str, **kwargs: Any) -> None:
    with DATA_PREP_JOBS_LOCK:
        if job_id in DATA_PREP_JOBS:
            DATA_PREP_JOBS[job_id].update(kwargs)


def _unique_neighbor(path: Path, name: str) -> Path:
    candidate = path.with_name(name)
    if not candidate.exists():
        return candidate
    parsed = Path(name)
    stem = parsed.stem
    suffix = parsed.suffix
    for idx in range(1, 1000):
        numbered = path.with_name(f"{stem}.{idx}{suffix}")
        if not numbered.exists():
            return numbered
    raise RuntimeError("could_not_allocate_output_filename")


def _sorted_bam_output_path(path: Path) -> Path:
    name = path.name
    if name.lower().endswith(".bam"):
        name = name[:-4]
    return _unique_neighbor(path, f"{name}.sorted.bam")


def _bgzipped_vcf_output_path(path: Path) -> Path:
    return _unique_neighbor(path, f"{path.name}.gz")


def _estimate_prepare_incoming_bytes(path: Path, action: str | None) -> int:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if action == "sort_and_index":
        return int(size * 1.25) + 256 * 1024 * 1024
    if action == "compress_and_index":
        return size + 64 * 1024 * 1024
    if action == "index":
        return 256 * 1024 * 1024
    return 0


def _run_checked(cmd: list[str], stdout_path: Path | None = None) -> None:
    if stdout_path:
        with stdout_path.open("wb") as stdout:
            completed = subprocess.run(cmd, stdout=stdout, stderr=subprocess.PIPE, text=True, check=False)
    else:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(stderr[-1200:] or f"command_failed:{cmd[0]}:{completed.returncode}")


def _run_data_prepare_job(job_id: str, input_path: Path, requested_action: str | None) -> None:
    tmp_path: Path | None = None
    try:
        preflight = _input_file_preflight(input_path)
        action = requested_action or preflight.get("prepare_action")
        if not action:
            _update_prep_job(
                job_id,
                status="done",
                progress_pct=100,
                step="ready",
                output_path=str(input_path),
                output_relative_path=_relative_input_path(input_path),
                finished_at=time.time(),
            )
            return

        lower = input_path.name.lower()
        threads = max(1, int(os.getenv("WGS_DATA_PREP_THREADS", "2") or "2"))
        _update_prep_job(job_id, status="running", action=action, progress_pct=5, step="starting")

        if lower.endswith(".bam"):
            if not shutil.which("samtools"):
                raise RuntimeError("samtools_not_available")
            if action == "index":
                _update_prep_job(job_id, progress_pct=30, step="indexing", output_path=str(input_path))
                _run_checked(["samtools", "index", "-@", str(threads), str(input_path)])
                output_path = input_path
            elif action == "sort_and_index":
                output_path = _sorted_bam_output_path(input_path)
                tmp_path = output_path.with_name(f".{output_path.name}.{job_id}.tmp")
                _update_prep_job(job_id, progress_pct=15, step="sorting", output_path=str(output_path))
                _run_checked(["samtools", "sort", "-@", str(threads), "-o", str(tmp_path), str(input_path)])
                tmp_path.replace(output_path)
                tmp_path = None
                _update_prep_job(job_id, progress_pct=78, step="indexing", output_path=str(output_path))
                _run_checked(["samtools", "index", "-@", str(threads), str(output_path)])
            else:
                raise RuntimeError(f"unsupported_bam_prepare_action:{action}")

        elif lower.endswith(".vcf.gz"):
            if action != "index":
                raise RuntimeError(f"unsupported_vcfgz_prepare_action:{action}")
            if not shutil.which("tabix"):
                raise RuntimeError("tabix_not_available")
            output_path = input_path
            _update_prep_job(job_id, progress_pct=50, step="indexing", output_path=str(output_path))
            _run_checked(["tabix", "-f", "-p", "vcf", str(output_path)])

        elif lower.endswith(".vcf"):
            if action != "compress_and_index":
                raise RuntimeError(f"unsupported_vcf_prepare_action:{action}")
            if not shutil.which("bgzip") or not shutil.which("tabix"):
                raise RuntimeError("bgzip_or_tabix_not_available")
            output_path = _bgzipped_vcf_output_path(input_path)
            tmp_path = output_path.with_name(f".{output_path.name}.{job_id}.tmp")
            _update_prep_job(job_id, progress_pct=30, step="compressing", output_path=str(output_path))
            _run_checked(["bgzip", "-c", str(input_path)], stdout_path=tmp_path)
            tmp_path.replace(output_path)
            tmp_path = None
            _update_prep_job(job_id, progress_pct=80, step="indexing", output_path=str(output_path))
            _run_checked(["tabix", "-f", "-p", "vcf", str(output_path)])
        else:
            raise RuntimeError("unsupported_input_type_for_prepare")

        _update_prep_job(
            job_id,
            status="done",
            progress_pct=100,
            step="done",
            output_path=str(output_path),
            output_relative_path=_relative_input_path(output_path),
            preflight=_input_file_preflight(output_path),
            finished_at=time.time(),
        )
    except Exception as exc:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
        _update_prep_job(job_id, status="failed", error=str(exc), finished_at=time.time())


@router.post("/data/prepare")
def prepare_input_file(req: DataPrepareRequest) -> dict[str, Any]:
    input_path = _safe_input_path(req.path)
    if not input_path.is_file():
        raise HTTPException(404, "input_file_not_found")

    preflight = _input_file_preflight(input_path)
    action = req.action or preflight.get("prepare_action")
    if preflight.get("required") and action and not preflight.get("can_prepare") and action == preflight.get("prepare_action"):
        raise HTTPException(400, {"code": "prepare_tool_missing", "message": "Required indexing/sorting tool is not available", "preflight": preflight})
    storage_preflight = _ensure_storage_headroom(
        input_path.parent,
        _estimate_prepare_incoming_bytes(input_path, action),
        "insufficient_input_storage_for_prepare",
    )

    job_id = f"prep_{uuid4().hex[:10]}"
    with DATA_PREP_JOBS_LOCK:
        DATA_PREP_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress_pct": 0,
            "step": "queued",
            "action": action,
            "input_path": str(input_path),
            "input_relative_path": _relative_input_path(input_path),
            "output_path": None,
            "output_relative_path": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "preflight": preflight,
            "storage_preflight": storage_preflight,
        }

    thread = threading.Thread(target=_run_data_prepare_job, args=(job_id, input_path, req.action), daemon=True)
    thread.start()
    return DATA_PREP_JOBS[job_id]


@router.get("/data/prepare/{job_id}")
def get_prepare_status(job_id: str) -> dict[str, Any]:
    with DATA_PREP_JOBS_LOCK:
        job = DATA_PREP_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "prepare_job_not_found")
    return job


def _refs_meta_path() -> Path:
    return CUSTOM_REFS_DIR / "_meta.json"


def _load_refs_meta() -> list[dict]:
    p = _refs_meta_path()
    if p.exists():
        return json.loads(p.read_text())
    return []


def _save_refs_meta(refs: list[dict]) -> None:
    CUSTOM_REFS_DIR.mkdir(parents=True, exist_ok=True)
    _refs_meta_path().write_text(json.dumps(refs, indent=2))


def _gb_to_bytes(value: Any) -> int:
    try:
        return int(max(0.0, float(value)) * 1024**3)
    except (TypeError, ValueError):
        return 0


def _taxonomy_install_storage_preflight(db_info: dict[str, Any]) -> dict[str, Any]:
    # During install the compressed archive and extracted database can coexist.
    # Keep the operator-visible estimate conservative for large Kraken2 DBs.
    required_bytes = _gb_to_bytes(db_info.get("archive_size_gb")) + _gb_to_bytes(db_info.get("index_size_gb"))
    required_bytes += 2 * 1024**3
    usage = shutil.disk_usage(_nearest_existing_path(TAXONOMY_DB_DIR))
    return {
        "path": str(TAXONOMY_DB_DIR),
        "archive_size_gb": db_info.get("archive_size_gb"),
        "index_size_gb": db_info.get("index_size_gb"),
        "required_bytes": required_bytes,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "ok": usage.free >= required_bytes if required_bytes else True,
    }


def _taxonomy_install_jobs_path() -> Path:
    return TAXONOMY_DB_DIR / ".install_jobs.json"


def _load_taxonomy_install_jobs() -> None:
    path = _taxonomy_install_jobs_path()
    if not path.exists():
        return
    try:
        loaded = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(loaded, dict):
        return
    with TAXONOMY_INSTALL_JOBS_LOCK:
        for job_id, job in loaded.items():
            if not isinstance(job, dict):
                continue
            current = TAXONOMY_INSTALL_JOBS.get(job_id)
            if current and current.get("status") in {"downloading", "extracting"}:
                continue
            restored = {**job}
            if restored.get("status") in {"downloading", "extracting"}:
                restored["status"] = "interrupted"
                restored["phase"] = "interrupted"
                restored["error"] = "api_restarted_or_job_lost; POST install again to resume"
            TAXONOMY_INSTALL_JOBS[job_id] = restored


def _save_taxonomy_install_jobs() -> None:
    TAXONOMY_DB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _taxonomy_install_jobs_path().with_suffix(".json.tmp")
    with TAXONOMY_INSTALL_JOBS_LOCK:
        payload = json.dumps(TAXONOMY_INSTALL_JOBS, indent=2, sort_keys=True)
    tmp.write_text(payload)
    tmp.replace(_taxonomy_install_jobs_path())


def _set_taxonomy_install_job(job_id: str, job: dict[str, Any]) -> None:
    with TAXONOMY_INSTALL_JOBS_LOCK:
        TAXONOMY_INSTALL_JOBS[job_id] = job
    _save_taxonomy_install_jobs()


def _update_taxonomy_install_job(job_id: str, **kwargs: Any) -> None:
    with TAXONOMY_INSTALL_JOBS_LOCK:
        if job_id not in TAXONOMY_INSTALL_JOBS:
            return
        TAXONOMY_INSTALL_JOBS[job_id].update(kwargs)
    _save_taxonomy_install_jobs()


def _content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"/(\d+)$", value)
    return int(match.group(1)) if match else None


def _safe_extract_tar(tf: tarfile.TarFile, destination: Path) -> None:
    dest = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if not target.is_relative_to(dest):
            raise ValueError(f"unsafe archive member: {member.name}")
    tf.extractall(path=destination, filter="data")


@router.get("/data/taxonomy-databases")
def list_taxonomy_databases() -> list[dict[str, Any]]:
    TAXONOMY_DB_DIR.mkdir(parents=True, exist_ok=True)
    _load_taxonomy_install_jobs()
    result = []
    for db in TAXONOMY_DATABASES:
        installed = (TAXONOMY_DB_DIR / db["id"]).is_dir()
        if installed:
            db_dir = TAXONOMY_DB_DIR / db["id"]
            installed = (db_dir / "hash.k2d").exists()
        archive = TAXONOMY_DB_DIR / f"{db['id']}.tar.gz"
        archive_status = None
        if archive.exists():
            stat = archive.stat()
            archive_status = {
                "path": str(archive),
                "size_bytes": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "partial": not installed,
            }
        result.append({
            **db,
            "installed": installed,
            "storage_preflight": _taxonomy_install_storage_preflight(db),
            "archive_status": archive_status,
        })
    return result


@router.post("/data/taxonomy-databases/install")
def install_taxonomy_database(body: dict[str, Any]) -> dict[str, Any]:
    db_id = body.get("database", "")
    db_info = next((d for d in TAXONOMY_DATABASES if d["id"] == db_id), None)
    if not db_info:
        raise HTTPException(404, f"Unknown database: {db_id}")
    storage_preflight = _taxonomy_install_storage_preflight(db_info)
    if not storage_preflight["ok"]:
        raise HTTPException(
            status_code=507,
            detail={
                "code": "taxonomy_database_insufficient_storage",
                "database": db_id,
                "storage": storage_preflight,
            },
        )

    job_id = f"taxdb_{db_id}"
    archive_path = TAXONOMY_DB_DIR / f"{db_id}.tar.gz"
    existing_bytes = archive_path.stat().st_size if archive_path.exists() else 0
    _set_taxonomy_install_job(job_id, {
        "job_id": job_id,
        "status": "downloading",
        "phase": "queued",
        "db_id": db_id,
        "progress": 0,
        "progress_pct": 0,
        "downloaded_bytes": existing_bytes,
        "total_bytes": None,
        "resumable": True,
        "resumed_from_bytes": existing_bytes,
        "archive_path": str(archive_path),
        "database_path": str(TAXONOMY_DB_DIR / db_id),
        "storage_preflight": storage_preflight,
        "started_at": time.time(),
        "finished_at": None,
    })

    def _download_and_extract() -> None:
        try:
            TAXONOMY_DB_DIR.mkdir(parents=True, exist_ok=True)
            resume_from = archive_path.stat().st_size if archive_path.exists() else 0
            headers = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else {}
            req = urllib.request.Request(db_info["url"], headers=headers)
            with urllib.request.urlopen(req) as resp:  # nosec B310
                status_code = getattr(resp, "status", None) or getattr(resp, "getcode", lambda: None)()
                content_length = int(resp.headers.get("Content-Length", 0) or 0)
                range_total = _content_range_total(resp.headers.get("Content-Range"))
                resume_accepted = resume_from > 0 and status_code == 206
                if resume_from > 0 and not resume_accepted:
                    resume_from = 0
                total = range_total or (resume_from + content_length if content_length else 0)
                downloaded = resume_from
                mode = "ab" if resume_accepted else "wb"
                _update_taxonomy_install_job(
                    job_id,
                    status="downloading",
                    phase="downloading",
                    total_bytes=total or None,
                    downloaded_bytes=downloaded,
                    resumed_from_bytes=resume_from,
                    resume_accepted=resume_accepted,
                )
                with open(archive_path, mode) as f:
                    while True:
                        chunk = resp.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = round(downloaded / total * 100, 2) if total else None
                        _update_taxonomy_install_job(
                            job_id,
                            downloaded_bytes=downloaded,
                            total_bytes=total or None,
                            progress=progress if progress is not None else 0,
                            progress_pct=progress,
                        )

            _update_taxonomy_install_job(job_id, status="extracting", phase="extracting", progress=100, progress_pct=100)

            with tarfile.open(archive_path, "r:gz") as tar:
                _safe_extract_tar(tar, TAXONOMY_DB_DIR / db_id)

            archive_path.unlink(missing_ok=True)
            _update_taxonomy_install_job(job_id, status="done", phase="done", finished_at=time.time())
        except Exception as e:
            partial_bytes = archive_path.stat().st_size if archive_path.exists() else 0
            _update_taxonomy_install_job(
                job_id,
                status="error",
                phase="error",
                error=str(e),
                downloaded_bytes=partial_bytes,
                partial_archive_preserved=archive_path.exists(),
                finished_at=time.time(),
            )

    thread = threading.Thread(target=_download_and_extract, daemon=True)
    thread.start()
    return TAXONOMY_INSTALL_JOBS[job_id]


@router.get("/data/taxonomy-databases/install/{job_id}")
def get_taxonomy_install_status(job_id: str) -> dict[str, Any]:
    _load_taxonomy_install_jobs()
    job = TAXONOMY_INSTALL_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.delete("/data/taxonomy-databases/{db_id}")
def delete_taxonomy_database(db_id: str) -> dict[str, Any]:
    db_dir = TAXONOMY_DB_DIR / db_id
    if not db_dir.is_dir():
        raise HTTPException(404, f"Database not found: {db_id}")
    shutil.rmtree(db_dir)
    return {"deleted": db_id}


@router.post("/data/taxonomy-databases")
def add_custom_taxonomy_database(body: dict[str, Any]) -> dict[str, Any]:
    """Add a custom/proprietary taxonomy database."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")

    description = body.get("description", "Custom/proprietary database")
    path = body.get("path")
    url = body.get("url")

    db_id = name.lower().replace(" ", "_").replace("/", "_")[:40]

    # Check if already exists
    if any(d["id"] == db_id for d in TAXONOMY_DATABASES):
        raise HTTPException(409, f"Database '{db_id}' already exists")

    db_entry = {
        "id": db_id,
        "name": name,
        "description": description,
        "archive_size_gb": "?",
        "url": url or "",
        "custom": True,
    }

    # If local path provided, verify it exists
    if path:
        db_path = Path(path)
        if db_path.is_dir() and (db_path / "hash.k2d").exists():
            # Link or copy to taxonomy db dir
            dest = TAXONOMY_DB_DIR / db_id
            if not dest.exists():
                TAXONOMY_DB_DIR.mkdir(parents=True, exist_ok=True)
                try:
                    dest.symlink_to(db_path.resolve())
                except OSError:
                    import shutil
                    shutil.copytree(db_path, dest)
            db_entry["installed"] = True
        else:
            db_entry["installed"] = False
            db_entry["note"] = f"Path not found or missing hash.k2d: {path}"

    TAXONOMY_DATABASES.append(db_entry)
    return db_entry


@router.post("/samples/{sample_id}/taxonomy/classify")
def classify_sample_taxonomy(sample_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Run Kraken2 taxonomy classification on a sample with a specific database."""
    from app.store.memory_store import samples, taxonomy_hits, add_taxonomy_hit
    from app.db.models import TaxonomyHit

    database = body.get("database", "")
    if not database:
        raise HTTPException(400, "database is required")

    # Resolve sample
    sample = next((s for s in samples if s.id == sample_id or s.sample_id == sample_id), None)
    if not sample:
        raise HTTPException(404, "sample not found")

    # Check database exists
    db_dir = TAXONOMY_DB_DIR / database
    if not db_dir.is_dir():
        # Check custom databases
        db_info = next((d for d in TAXONOMY_DATABASES if d["id"] == database), None)
        if db_info and db_info.get("path"):
            db_dir = Path(db_info["path"])
        else:
            raise HTTPException(404, f"Database '{database}' not installed")

    # Run classification in background
    job_id = f"classify_{uuid4().hex[:8]}"

    def _classify():
        try:
            import subprocess as sp

            # Resolve input files to absolute paths under /data/input/
            r1 = sample.r1_path or ""
            r2 = sample.r2_path or ""
            if r1 and not Path(r1).is_absolute():
                r1 = str(Path("/data/input") / r1)
            if r2 and not Path(r2).is_absolute():
                r2 = str(Path("/data/input") / r2)
            if not Path(r1).exists():
                return

            cmd = [
                "kraken2",
                "--db", str(db_dir),
                "--paired" if r2 else "--single",
                "--report", f"/tmp/{sample.sample_id}_kraken2_report.txt",
                "--output", f"/tmp/{sample.sample_id}_kraken2_output.txt",
            ]
            if r2:
                cmd.extend([r1, r2])
            else:
                cmd.append(r1)

            result = sp.run(cmd, capture_output=True, text=True, timeout=300)

            if result.returncode == 0:
                report_path = Path(f"/tmp/{sample.sample_id}_kraken2_report.txt")
                if report_path.exists():
                    from app.core.taxonomy_parser import parse_taxonomy_report
                    parsed = parse_taxonomy_report(report_path)
                    skey = sample.sample_id
                    for hit in parsed:
                        add_taxonomy_hit(TaxonomyHit(
                            id=f"tax_{uuid4().hex[:10]}",
                            sample_id=skey,
                            run_id="",
                            reference_id=sample.reference_id,
                            organism=hit.get("organism", "unknown"),
                            kingdom=hit.get("kingdom", "microbiome"),
                            read_count=hit.get("read_count", 0),
                            confidence=hit.get("confidence", 0),
                            evidence_score=hit.get("evidence_score", 0),
                            tools=hit.get("tools", ["Kraken2"]),
                            likely_contaminant=hit.get("likely_contaminant", False),
                            warning=hit.get("warning"),
                            non_diagnostic=True,
                        ))
        except Exception as e:
            print(f"taxonomy classify failed for sample {sample_id}: {e}", flush=True)

    thread = threading.Thread(target=_classify, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "started", "database": database}


@router.get("/data/references/custom")
def list_custom_references() -> list[dict]:
    return _load_refs_meta()


@router.post("/data/references/upload")
async def upload_custom_reference(
    file: UploadFile = File(...),
    name: str = Form(...),
    organism: str = Form(""),
    description: str = Form(""),
) -> dict[str, Any]:
    CUSTOM_REFS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    ref_dir = CUSTOM_REFS_DIR / safe_name
    ref_dir.mkdir(parents=True, exist_ok=True)

    fname = "reference.fa.gz" if file.filename and file.filename.endswith(".gz") else "reference.fa"
    dest = ref_dir / fname

    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(4 * 1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            size += len(chunk)

    refs = _load_refs_meta()
    refs = [r for r in refs if r["name"] != safe_name]
    refs.append(
        {
            "name": safe_name,
            "organism": organism,
            "description": description,
            "path": str(dest),
            "size": size,
            "indexed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_refs_meta(refs)

    return {"name": safe_name, "path": str(dest), "size": size}


@router.post("/data/references/{name}/index")
def index_custom_reference(name: str) -> dict[str, Any]:
    refs = _load_refs_meta()
    ref = next((r for r in refs if r["name"] == name), None)
    if not ref:
        raise HTTPException(404, f"Reference not found: {name}")

    job_id = f"refidx_{uuid4().hex[:8]}"
    REFERENCE_INDEX_JOBS[job_id] = {"status": "indexing", "name": name, "steps": []}

    def _run_index() -> None:
        ref_path = ref["path"]
        try:
            REFERENCE_INDEX_JOBS[job_id]["steps"].append("faidx")
            subprocess.run(["samtools", "faidx", ref_path], check=True, capture_output=True)

            REFERENCE_INDEX_JOBS[job_id]["steps"].append("dict")
            dict_path = ref_path.replace(".fa.gz", ".dict").replace(".fa", ".dict")
            if not dict_path.endswith(".dict"):
                dict_path += ".dict"
            subprocess.run(["samtools", "dict", "-o", dict_path, ref_path], check=True, capture_output=True)

            REFERENCE_INDEX_JOBS[job_id]["steps"].append("bwa-mem2")
            subprocess.run(["bwa-mem2", "index", ref_path], check=True, capture_output=True)

            refs_meta = _load_refs_meta()
            for r in refs_meta:
                if r["name"] == name:
                    r["indexed"] = True
            _save_refs_meta(refs_meta)

            REFERENCE_INDEX_JOBS[job_id]["status"] = "done"
        except Exception as e:
            REFERENCE_INDEX_JOBS[job_id]["status"] = "error"
            REFERENCE_INDEX_JOBS[job_id]["error"] = str(e)

    thread = threading.Thread(target=_run_index, daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "indexing"}


@router.get("/data/references/{name}/index-status")
def get_index_status(name: str) -> dict[str, Any]:
    for job_id, job in sorted(REFERENCE_INDEX_JOBS.items(), reverse=True):
        if job.get("name") == name:
            return job
    return {"status": "no_job"}


@router.delete("/data/references/{name}")
def delete_custom_reference(name: str) -> dict[str, Any]:
    refs = _load_refs_meta()
    ref = next((r for r in refs if r["name"] == name), None)
    if not ref:
        raise HTTPException(404, f"Reference not found: {name}")

    ref_dir = Path(ref["path"]).parent
    if ref_dir.exists():
        shutil.rmtree(ref_dir)

    refs = [r for r in refs if r["name"] != name]
    _save_refs_meta(refs)
    return {"deleted": name}


def _read_cpuinfo() -> str:
    try:
        return Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _read_meminfo_total_bytes() -> int | None:
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return None


def _detect_gpu() -> list[dict[str, Any]]:
    # Check entrypoint env vars first (set at container startup)
    if os.getenv("WGS_GPU_AVAILABLE") == "true":
        gpu_info = os.getenv("WGS_GPU_INFO", "NVIDIA GPU")
        # Parse VRAM from info string (e.g. "Quadro P2000, 4096 MiB")
        vram_mb = None
        if "," in gpu_info:
            parts = gpu_info.split(",", 1)
            vram_str = parts[1].replace("MiB", "").replace("MB", "").strip()
            vram_mb = int(vram_str) if vram_str.isdigit() else None
        return [{"name": gpu_info, "vram_mb": vram_mb}]
    # Try nvidia-smi first
    if shutil.which("nvidia-smi"):
        try:
            completed = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                check=False,
            )
            output = (completed.stdout or "").strip()
            if output:
                gpus: list[dict[str, Any]] = []
                for line in output.splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 2:
                        vram_str = parts[1].replace("MiB", "").replace("MB", "").strip()
                        vram_mb = int(vram_str) if vram_str.isdigit() else None
                        gpus.append({"name": parts[0], "vram_mb": vram_mb})
                if gpus:
                    return gpus
        except Exception:
            pass
    # Fallback: check for /dev/nvidia* (Docker Desktop/WSL2)
    import glob as glob_mod
    nvidia_devs = glob_mod.glob("/dev/nvidia*")
    if nvidia_devs:
        return [{"name": "NVIDIA GPU (detected via /dev/nvidia*)", "vram_mb": None}]
    return []


def _estimate_wgs_30x(cpu_count: int, has_gpu: bool) -> dict[str, Any]:
    effective_threads = max(cpu_count, 1)
    baseline_threads = 6
    scale = baseline_threads / effective_threads

    align_min = max(1.0, 8.0 * scale)
    align_max = max(align_min, 16.0 * scale)

    estimates: dict[str, Any] = {
        "workload": "30x WGS (~100GB FASTQ, ~1B read pairs)",
        "alignment_cpu_hours": {"min": round(align_min, 2), "max": round(align_max, 2)},
        "coverage_minutes": {"min": 30, "max": 60},
        "variant_calling_bcftools_hours": {"min": 2, "max": 4},
        "variant_calling_deepvariant_cpu_hours": {"min": 6, "max": 12},
    }
    if has_gpu:
        estimates["variant_calling_deepvariant_gpu_hours"] = {"min": 1, "max": 2}
    return estimates


def _recommended_compute_profile(cpu_count: int, ram_bytes: int | None) -> str:
    ram_gb = (ram_bytes or 0) / (1024 ** 3)
    if ram_gb and ram_gb < 48:
        return "lowmem"
    if ram_gb >= 128 and cpu_count >= 16:
        return "highmem"
    return "standard"


def _summarize_version_output(output: str) -> str | None:
    for line in output.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:180]
    return None


def _first_tool_path(candidates: list[str]) -> str | None:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if candidate.startswith("/") and Path(candidate).exists():
            return candidate
    return None


def _probe_tool(tool: str) -> dict[str, Any]:
    candidates = TOOL_BINARY_CANDIDATES.get(tool, [tool])
    path = _first_tool_path(candidates)
    if not path:
        return {"installed": False, "path": None, "version": None, "version_probe": "missing"}

    cmd = TOOL_VERSION_COMMANDS.get(tool, [path, "--version"])
    if tool in TOOL_BINARY_CANDIDATES:
        cmd = [path, *cmd[1:]]
    timeout_seconds = 10 if tool in {"cnvkit", "cnvkit.py", "gatk"} else 5
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"installed": True, "path": path, "version": None, "version_probe": "timeout"}
    except Exception as exc:
        return {"installed": True, "path": path, "version": None, "version_probe": f"error:{type(exc).__name__}"}

    version = _summarize_version_output(f"{completed.stdout}\n{completed.stderr}")
    return {
        "installed": True,
        "path": path,
        "version": version,
        "version_probe": "ok" if version else f"empty:{completed.returncode}",
    }


def _build_data_capabilities() -> dict[str, Any]:
    cpuinfo = _read_cpuinfo()
    cpu_model = "unknown"
    flags: set[str] = set()

    for line in cpuinfo.splitlines():
        if line.lower().startswith("model name") and cpu_model == "unknown":
            cpu_model = line.split(":", 1)[1].strip()
        if line.lower().startswith("flags"):
            flags.update(line.split(":", 1)[1].strip().split())

    simd = {
        "sse42": "sse4_2" in flags,
        "avx2": "avx2" in flags,
        "avx512": any(flag.startswith("avx512") for flag in flags),
    }

    tool_details = {tool: _probe_tool(tool) for tool in BIOINFORMATICS_TOOLS}
    tool_status = {tool: bool(details["installed"]) for tool, details in tool_details.items()}

    gpus = _detect_gpu()
    cpu_count = os.cpu_count() or 1
    ram_bytes = _read_meminfo_total_bytes()
    recommended_profile = _recommended_compute_profile(cpu_count, ram_bytes)

    return {
        "cpu": {
            "model_name": cpu_model,
            "threads": cpu_count,
            "simd": simd,
        },
        "ram": {
            "total_bytes": ram_bytes,
        },
        "gpu": {
            "available": len(gpus) > 0,
            "items": gpus,
        },
        "tools": tool_status,
        "tool_details": tool_details,
        "compute": {
            "configured_profile": os.getenv("WGS_COMPUTE_PROFILE", "auto"),
            "recommended_profile": recommended_profile,
            "profile_threads": {"lowmem": 2, "standard": 4, "highmem": 12},
            "pipeline_threads_override": os.getenv("WGS_PIPELINE_THREADS", ""),
            "gpu_fallback_policy": "explicit_status_required",
        },
        "estimates_30x_wgs": _estimate_wgs_30x(cpu_count=cpu_count, has_gpu=len(gpus) > 0),
    }


@router.get("/data/capabilities")
def data_capabilities(refresh: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not refresh:
        with CAPABILITIES_CACHE_LOCK:
            cached = CAPABILITIES_CACHE.get("data")
            expires_at = float(CAPABILITIES_CACHE.get("expires_at") or 0)
            if cached is not None and expires_at > now:
                return copy.deepcopy(cached)

    capabilities = _build_data_capabilities()
    with CAPABILITIES_CACHE_LOCK:
        CAPABILITIES_CACHE["data"] = copy.deepcopy(capabilities)
        CAPABILITIES_CACHE["expires_at"] = time.monotonic() + CAPABILITIES_CACHE_TTL_SECONDS
    return capabilities
