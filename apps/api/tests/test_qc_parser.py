from pathlib import Path

from app.core.qc_parser import build_qc_summary


def test_build_qc_summary_from_fastqc(tmp_path: Path):
    f = tmp_path / "fastqc_data.txt"
    f.write_text(
        """
>>Basic Statistics\tpass
Total Sequences\t12345
Sequence length\t150
%GC\t48
        """.strip(),
        encoding="utf-8",
    )

    summary = build_qc_summary(sample_id="S1", run_id="run_1", fastqc_data_txt=f)
    assert summary.total_reads == 12345
    assert summary.gc_content_pct == 48.0
    assert summary.status == "OK"
