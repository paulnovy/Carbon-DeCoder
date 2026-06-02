from pathlib import Path


def parse_mtdna_report(path: Path) -> dict:
    """Parse lightweight mtDNA report key/value text.

    Supported line forms:
    - haplogroup=H1
    - heteroplasmy_mean_vaf=0.12
    - num_variants=18
    - numts_warning=true
    - trust_score=59
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

        if key == "haplogroup":
            out["haplogroup"] = val
        elif key == "heteroplasmy_mean_vaf":
            try:
                out["heteroplasmy_mean_vaf"] = float(val)
            except ValueError:
                pass
        elif key == "num_variants":
            try:
                out["num_variants"] = int(float(val))
            except ValueError:
                pass
        elif key == "numts_warning":
            out["numts_warning"] = val.lower() in {"1", "true", "yes", "y"}
        elif key == "trust_score":
            try:
                out["trust_score"] = float(val)
            except ValueError:
                pass

    return out
