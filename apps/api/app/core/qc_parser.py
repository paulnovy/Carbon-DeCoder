import json
import re
from pathlib import Path

from app.db.models import QCSummary


def parse_fastqc_data_txt(path: Path) -> dict:
    """Light parser for FastQC `fastqc_data.txt` essentials."""
    metrics: dict = {}
    if not path.exists():
        return metrics

    text = path.read_text(encoding="utf-8", errors="ignore")

    total_seq = re.search(r"Total Sequences\t(\d+)", text)
    gc_pct = re.search(r"%GC\t(\d+)", text)
    seq_len = re.search(r"Sequence length\t([\d\-]+)", text)

    if total_seq:
        metrics["total_reads"] = int(total_seq.group(1))
    if gc_pct:
        metrics["gc_content_pct"] = float(gc_pct.group(1))
    if seq_len:
        metrics["sequence_length"] = seq_len.group(1)

    return metrics


def parse_multiqc_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}


def build_qc_summary(
    *,
    sample_id: str,
    run_id: str,
    fastqc_data_txt: Path | None = None,
    multiqc_json: Path | None = None,
) -> QCSummary:
    f_metrics = parse_fastqc_data_txt(fastqc_data_txt) if fastqc_data_txt else {}
    m_metrics = parse_multiqc_json(multiqc_json) if multiqc_json else {}

    total_reads = f_metrics.get("total_reads")
    gc_content_pct = f_metrics.get("gc_content_pct")

    duplication_rate = None
    if isinstance(m_metrics, dict):
        # placeholder field path for future parser stabilization
        duplication_rate = m_metrics.get("duplication_rate_pct")

    status = "unknown"
    if total_reads and total_reads > 0:
        status = "OK"

    sources = []
    if fastqc_data_txt:
        sources.append(str(fastqc_data_txt))
    if multiqc_json:
        sources.append(str(multiqc_json))

    return QCSummary(
        sample_id=sample_id,
        run_id=run_id,
        total_reads=total_reads,
        gc_content_pct=gc_content_pct,
        duplication_rate_pct=duplication_rate,
        mean_read_length=None,
        status=status,
        source_files=sources,
    )
