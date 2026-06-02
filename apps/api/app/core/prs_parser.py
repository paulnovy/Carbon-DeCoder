from pathlib import Path


def parse_prs_result(path: Path) -> dict:
    """Parse PRS result from key=value text.

    Supported keys:
    trait, score_value, overlap_pct, variant_count_total,
    variant_count_matched, quality_label, warning, non_diagnostic
    """
    if not path.exists():
        return {}

    out: dict = {}
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip().lower()
        val = v.strip()

        if key == "trait":
            out["trait"] = val
        elif key == "score_value":
            try:
                out["score_value"] = float(val)
            except ValueError:
                pass
        elif key == "overlap_pct":
            try:
                out["overlap_pct"] = float(val)
            except ValueError:
                pass
        elif key == "variant_count_total":
            try:
                out["variant_count_total"] = int(float(val))
            except ValueError:
                pass
        elif key == "variant_count_matched":
            try:
                out["variant_count_matched"] = int(float(val))
            except ValueError:
                pass
        elif key == "quality_label":
            out["quality_label"] = val
        elif key == "warning":
            out["warning"] = val
        elif key == "non_diagnostic":
            out["non_diagnostic"] = val.lower() in {"1", "true", "yes", "y"}

    return out
