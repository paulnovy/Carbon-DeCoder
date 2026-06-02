from fastapi import APIRouter

router = APIRouter(prefix="/v1")


@router.get("/samples/{sample_id}/trust-map")
def trust_map(sample_id: str):
    return {
        "sample_id": sample_id,
        "score_range": [0, 100],
        "layers": [
            "giab_confidence_overlay",
            "difficult_regions",
            "false_positive_hotspots",
            "false_negative_risk_zones",
            "caller_disagreement_map",
        ],
        "non_diagnostic": True,
    }


@router.get("/benchmarks/{benchmark_id}")
def benchmark_detail(benchmark_id: str):
    return {
        "benchmark_id": benchmark_id,
        "history": [],
        "regression_alert": None,
        "ui_tabs": ["Trust", "Benchmark", "Difficult Regions"],
    }
