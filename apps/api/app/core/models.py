from typing import Literal, Optional

from pydantic import BaseModel, Field

AnalysisMode = Literal["qc-only", "full-wgs", "benchmark", "prs", "contamination"]
VariantType = Literal["SNV", "indel", "MNV", "complex", "SV", "CNV", "repeat"]


class Provenance(BaseModel):
    tool: str
    tool_version: str
    reference_profile: str
    parameters: dict = Field(default_factory=dict)
    timestamp_utc: str


class InputValidationRequest(BaseModel):
    sample_id: str
    r1_path: str
    r2_path: Optional[str] = None
    mode: AnalysisMode
    reference_profile: str
    non_diagnostic_confirmed: bool
    sample_sheet_path: Optional[str] = None
    min_free_space_gb: float = 150.0


class InputValidationResult(BaseModel):
    valid: bool
    status: Literal["OK", "warning", "stop"]
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    estimated_output_gb: Optional[float] = None
    checksums: dict[str, str] = Field(default_factory=dict)
    preflight: dict = Field(default_factory=dict)


class VariantRecord(BaseModel):
    chrom: str
    pos: int = Field(ge=1)
    ref: str
    alt: str
    variant_type: VariantType
    callers: list[str] = Field(default_factory=list)
    caller_agreement_score: float = 0.0
    trust_score: float = 0.0
    clinical_annotation: Optional[str] = None
    population_annotation: Optional[str] = None
    technical_annotation: Optional[str] = None
