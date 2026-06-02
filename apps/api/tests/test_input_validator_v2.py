from pathlib import Path

from app.core.input_validator import validate_input
from app.core.models import InputValidationRequest


def test_input_validator_rejects_missing_non_diagnostic(tmp_path: Path):
    r1 = tmp_path / "sample_R1.fastq"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")

    req = InputValidationRequest(
        sample_id="S1",
        r1_path=str(r1),
        mode="qc-only",
        reference_profile="GRCh38_standard",
        non_diagnostic_confirmed=False,
        min_free_space_gb=0.0,
    )

    result = validate_input(req)
    assert result.valid is False
    assert "non_diagnostic_confirmation_required" in result.errors


def test_input_validator_accepts_minimal_fastq(tmp_path: Path):
    r1 = tmp_path / "sample_R1.fastq"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")

    req = InputValidationRequest(
        sample_id="S1",
        r1_path=str(r1),
        mode="qc-only",
        reference_profile="GRCh38_standard",
        non_diagnostic_confirmed=True,
        min_free_space_gb=0.0,
    )

    result = validate_input(req)
    assert result.valid is True
    assert result.status in {"OK", "warning"}
