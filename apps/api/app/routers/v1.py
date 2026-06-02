from datetime import datetime, timezone
from fastapi import APIRouter

from app.core.input_validator import validate_input
from app.core.models import InputValidationRequest
from app.core.trust import compute_trust_score

router = APIRouter(prefix="/v1")


@router.post("/input/validate")
def validate_payload(req: InputValidationRequest):
    return validate_input(req)


@router.post("/analysis")
def submit_analysis(req: InputValidationRequest):
    vr = validate_input(req)
    if not vr.valid:
        return {"accepted": False, "validation": vr}

    return {
        "accepted": True,
        "job_id": f"job-{req.sample_id.lower()}-{int(datetime.now().timestamp())}",
        "status": "queued",
        "validation": vr,
    }


@router.get("/trust/example")
def trust_example():
    score = compute_trust_score(
        caller_agreement_score=0.87,
        region_confidence=0.9,
        mapping_quality_score=0.81,
        giab_stratified_f1=0.94,
    )
    return {
        "trust_score": score,
        "explanation": "Demo trust score. Not clinical interpretation.",
    }
