import subprocess
from pathlib import Path


def test_fastq_to_fasta_assembly_script(tmp_path: Path):
    r1 = tmp_path / "S1_R1.fastq"
    r2 = tmp_path / "S1_R2.fastq"
    r1.write_text(
        "@r1_1\nACGT\n+\n####\n"
        "@r1_2\nTTAA\n+\n####\n",
        encoding="utf-8",
    )
    r2.write_text(
        "@r2_1\nCCCC\n+\n####\n"
        "@r2_2\nGGGG\n+\n####\n",
        encoding="utf-8",
    )

    out = tmp_path / "pipeline_assembly.fasta"
    script = Path(__file__).resolve().parents[3] / "pipelines/nextflow/scripts/fastq_to_fasta_assembly.py"
    subprocess.run(
        [
            "python3",
            str(script),
            "--r1",
            str(r1),
            "--r2",
            str(r2),
            "--max-reads",
            "3",
            "--output",
            str(out),
        ],
        check=True,
    )

    text = out.read_text(encoding="utf-8")
    assert text.startswith(">pipeline_assembly\n")
    assert "ACGT" in text
    assert "TTAA" in text
    assert "CCCC" in text
