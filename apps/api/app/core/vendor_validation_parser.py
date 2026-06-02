import csv
import json
from pathlib import Path


def _to_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _to_bool(v: str | None) -> bool | None:
    if v is None:
        return None
    x = str(v).strip().lower()
    if x in {"1", "true", "yes", "y"}:
        return True
    if x in {"0", "false", "no", "n"}:
        return False
    return None


def _to_int(v: str | None) -> int | None:
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def parse_vendor_validation_report(path: Path) -> dict:
    """Parse vendor-assembly acceptance validation report.

    Supports:
    - JSON object
    - key=value lines
    - single-row TSV/CSV with header
    """
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return {}

    out: dict = {"summary": {}}

    def feed(k: str, v: str):
        key = k.strip().lower()
        val = v.strip()
        if key in {"vendor_assembly_path", "vendor_assembly"}:
            out["vendor_assembly_path"] = val
        elif key in {"pipeline_assembly_path", "pipeline_assembly"}:
            out["pipeline_assembly_path"] = val
        elif key in {"similarity_score", "snv_concordance", "indel_concordance", "structural_concordance", "pass_threshold"}:
            fv = _to_float(val)
            if fv is not None:
                out[key] = fv
        elif key in {"comparator_method", "comparison_method", "method"}:
            m = val.lower()
            if m in {"proxy", "kmer", "exact"}:
                out["comparator_method"] = m
        elif key in {"kmer_size", "k", "kmer_k"}:
            iv = _to_int(val)
            if iv is not None:
                out["kmer_size"] = iv
        elif key == "status":
            s = val.lower()
            if s in {"passed", "failed", "unknown"}:
                out["status"] = s
        elif key == "non_diagnostic":
            bv = _to_bool(val)
            if bv is not None:
                out["non_diagnostic"] = bv
        elif key == "summary_json":
            try:
                obj = json.loads(val)
                if isinstance(obj, dict):
                    out["summary"].update(obj)
            except Exception:
                pass
        elif key.startswith("summary_"):
            sv = key.replace("summary_", "", 1)
            fv = _to_float(val)
            out["summary"][sv] = fv if fv is not None else val

    # JSON mode
    if lines[0].startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "summary" and isinstance(v, dict):
                    out["summary"].update(v)
                    continue
                feed(str(k), str(v))
            return out

    if any("=" in ln for ln in lines):
        for ln in lines:
            if "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            feed(k, v)
        return out

    delim = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else None)
    if not delim:
        return out

    reader = csv.DictReader(lines, delimiter=delim)
    row = next(reader, None)
    if not row:
        return out
    for k, v in row.items():
        if v is None:
            continue
        feed(str(k), str(v))

    return out
