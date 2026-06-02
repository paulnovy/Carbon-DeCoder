def compute_trust_score(
    *,
    caller_agreement_score: float,
    region_confidence: float,
    mapping_quality_score: float,
    giab_stratified_f1: float | None,
) -> float:
    giab = giab_stratified_f1 if giab_stratified_f1 is not None else 0.5
    raw = (0.35 * caller_agreement_score) + (0.25 * region_confidence) + (0.2 * mapping_quality_score) + (0.2 * giab)
    return max(0.0, min(1.0, round(raw, 4)))


def trust_score_100(score01: float) -> float:
    return round(max(0.0, min(1.0, score01)) * 100.0, 2)


def trust_label(score100: float) -> str:
    if score100 >= 80:
        return "high"
    if score100 >= 55:
        return "medium"
    if score100 > 0:
        return "low"
    return "unknown"
