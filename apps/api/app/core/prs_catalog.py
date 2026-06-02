from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_header(path: Path) -> dict:
    meta: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            raw = line.strip("#\n ")
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            meta[key.strip().lower()] = value.strip()
    return {
        "pgs_id": meta.get("pgs_id"),
        "pgs_name": meta.get("pgs_name"),
        "trait_reported": meta.get("trait_reported"),
        "trait_mapped": meta.get("trait_mapped"),
        "weight_type": meta.get("weight_type"),
        "genome_build": meta.get("genome_build"),
        "variants_number": int(meta.get("variants_number", "0") or 0),
    }


def download_pgs_score(pgs_id: str, dest_dir: str = "/data/references/pgs") -> dict:
    pgs_id = (pgs_id or "").strip().upper()
    if not pgs_id.startswith("PGS"):
        raise ValueError("invalid_pgs_id")

    target_dir = Path(dest_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{pgs_id}.txt.gz"

    ftp_url = f"https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/{pgs_id}/ScoringFiles/{pgs_id}.txt.gz"
    with urlopen(ftp_url, timeout=60) as r:
        out_path.write_bytes(r.read())

    metadata = _extract_header(out_path)
    metadata.update(
        {
            "pgs_id": pgs_id,
            "ftp_url": ftp_url,
            "local_path": str(out_path),
            "downloaded_at": _now_iso(),
        }
    )
    (target_dir / f"{pgs_id}.meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def parse_scoring_file(path: str) -> list[dict]:
    rows: list[dict] = []
    p = Path(path)
    with gzip.open(p, "rt", encoding="utf-8", errors="ignore") as fh:
        header: list[str] = []
        for line in fh:
            if line.startswith("#"):
                continue
            if not header:
                header = line.strip().split("\t")
                continue
            cols = line.rstrip("\n").split("\t")
            row = {header[idx]: cols[idx] if idx < len(cols) else "" for idx in range(len(header))}
            rsid = row.get("rsID") or row.get("rsid") or row.get("hm_rsID") or ""
            if not rsid:
                chr_name = row.get("chr_name") or row.get("hm_chr")
                chr_pos = row.get("chr_position") or row.get("hm_pos")
                if chr_name and chr_pos:
                    rsid = f"{chr_name}:{chr_pos}"
            weight_raw = row.get("effect_weight") or row.get("weight") or row.get("OR") or "0"
            try:
                weight = float(weight_raw)
            except Exception:
                continue
            rows.append(
                {
                    "rsid": rsid,
                    "effect_allele": row.get("effect_allele", ""),
                    "other_allele": row.get("other_allele", ""),
                    "weight": weight,
                    "chr_name": row.get("chr_name") or row.get("hm_chr"),
                    "chr_position": row.get("chr_position") or row.get("hm_pos"),
                }
            )
    return rows


def _variant_index(variants: list) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for v in variants:
        rsid = (v.get("rsid") or "").strip()
        if rsid:
            idx[rsid] = v
        chrom = v.get("chrom")
        pos = v.get("pos")
        if chrom and pos is not None:
            idx[f"{str(chrom).replace('chr', '')}:{pos}"] = v
            idx[f"chr{str(chrom).replace('chr', '')}:{pos}"] = v
    return idx


def _infer_dosage(variant: dict, effect_allele: str) -> float:
    genotype = str(variant.get("genotype") or variant.get("gt") or "")
    if genotype:
        alleles = genotype.replace("|", "/").split("/")
        try:
            return float(sum(1 for a in alleles if a == "1"))
        except Exception:
            pass

    alt = str(variant.get("alt") or "")
    ref = str(variant.get("ref") or "")
    effect = str(effect_allele or "")
    if effect and alt and effect.upper() == alt.upper():
        return 1.0
    if effect and ref and effect.upper() == ref.upper():
        return 0.0
    return 0.0


def _normal_percentile(score: float, weights: list[float]) -> float:
    import math

    if not weights:
        return 50.0
    # rough population std approximation assuming independent dosages
    variance = sum((w * w) * 0.5 for w in weights)
    std = math.sqrt(variance) if variance > 0 else 1.0
    z = score / std
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return max(0.0, min(100.0, cdf * 100.0))


def _risk_band(percentile: float) -> str:
    if percentile >= 90:
        return "very_high"
    if percentile >= 75:
        return "high"
    if percentile <= 10:
        return "very_low"
    if percentile <= 25:
        return "low"
    return "average"


def calculate_prs(variants: list, scoring_file_path: str) -> dict:
    scores = parse_scoring_file(scoring_file_path)
    idx = _variant_index(variants)
    header = _extract_header(Path(scoring_file_path))

    total = len(scores)
    matched = 0
    score = 0.0
    contributors: list[dict] = []
    used_weights: list[float] = []

    for s in scores:
        key = s.get("rsid")
        candidate = idx.get(key)
        if not candidate and s.get("chr_name") and s.get("chr_position"):
            # support both GRCh37/38 naming conventions via normalized chr matching
            c = str(s["chr_name"]).replace("chr", "")
            p = s["chr_position"]
            candidate = idx.get(f"{c}:{p}") or idx.get(f"chr{c}:{p}")
        if not candidate:
            continue

        dosage = _infer_dosage(candidate, s.get("effect_allele") or "")
        weight = float(s["weight"])
        contribution = weight * dosage
        score += contribution
        matched += 1
        used_weights.append(weight)
        contributors.append(
            {
                "rsid": s.get("rsid"),
                "weight": weight,
                "genotype": candidate.get("genotype") or candidate.get("gt") or f"{candidate.get('ref')}/{candidate.get('alt')}",
                "contribution": contribution,
            }
        )

    contributors = sorted(contributors, key=lambda x: abs(float(x.get("contribution") or 0.0)), reverse=True)[:5]
    match_rate = (matched / total) if total else 0.0
    percentile = _normal_percentile(score, used_weights)
    interpretable = matched >= 20 and match_rate >= 0.3
    return {
        "trait": header.get("trait_reported") or header.get("pgs_name") or "Unknown trait",
        "score": score,
        "percentile": percentile,
        "risk_band": _risk_band(percentile),
        "variants_matched": matched,
        "variants_total": total,
        "match_rate": match_rate,
        "interpretable": interpretable,
        "top_contributors": contributors,
        "genome_build": header.get("genome_build"),
    }


def list_downloaded_scores(dest_dir: str = "/data/references/pgs") -> list[dict]:
    root = Path(dest_dir)
    if not root.exists():
        return []
    items: list[dict] = []
    for meta_file in sorted(root.glob("PGS*.meta.json")):
        try:
            items.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items
