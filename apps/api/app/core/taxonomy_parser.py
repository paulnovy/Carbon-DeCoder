from pathlib import Path


RANK_MAP = {
    "D": "domain",
    "K": "kingdom",
    "P": "phylum",
    "C": "class",
    "O": "order",
    "F": "family",
    "G": "genus",
    "S": "species",
    "U": "unclassified",
    "R": "root",
}

TOP_CLADE_NAMES = {
    "archaea": "Archaea",
    "bacteria": "Bacteria",
    "eukaryota": "Eukaryota",
    "viruses": "Viruses",
    "fungi": "Fungi",
}


def _optional_float(parts: list[str], idx: dict[str, int], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name not in idx:
            continue
        try:
            raw = parts[idx[name]]
        except IndexError:
            continue
        if raw in {"", "."}:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _optional_int(parts: list[str], idx: dict[str, int], names: tuple[str, ...]) -> int | None:
    value = _optional_float(parts, idx, names)
    return int(value) if value is not None else None


def _optional_text(parts: list[str], idx: dict[str, int], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name not in idx:
            continue
        try:
            value = parts[idx[name]].strip()
        except IndexError:
            continue
        return value or None
    return None


def _rank_label(rank: str | None) -> str:
    return RANK_MAP.get((rank or "").strip().upper(), (rank or "taxon").strip().lower() or "taxon")


def _taxonomy_lineage_top_clade(lineage: list[dict]) -> str | None:
    for node in lineage:
        name = str(node.get("name") or "").strip()
        key = name.lower()
        if key in TOP_CLADE_NAMES:
            return TOP_CLADE_NAMES[key]
    return None


def _lineage_index_from_kraken_lines(lines: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_taxid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    stack: list[dict] = []

    for row in lines:
        parts = row.split("\t")
        if len(parts) < 6:
            continue
        try:
            rank_code = parts[3].strip()
            taxid = parts[4].strip()
        except IndexError:
            continue
        raw_name = parts[5].rstrip()
        name = raw_name.strip()
        if not name:
            continue

        indent = len(raw_name) - len(raw_name.lstrip(" "))
        depth = indent // 2
        node = {"taxid": taxid, "rank": _rank_label(rank_code), "name": name}
        stack = stack[:depth]
        stack.append(node)
        lineage = [dict(item) for item in stack]
        top_clade = _taxonomy_lineage_top_clade(lineage)
        metadata = {
            "taxid": taxid,
            "rank": node["rank"],
            "lineage": lineage,
            "top_clade": top_clade,
        }
        if taxid:
            by_taxid[taxid] = metadata
        by_name.setdefault(name.lower(), metadata)

    return by_taxid, by_name


def build_taxonomy_lineage_index(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    if not path.exists():
        return {}, {}
    lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    return _lineage_index_from_kraken_lines(lines)


def enrich_taxonomy_hits_with_lineage(hits: list[dict], kraken_report_path: Path | None) -> list[dict]:
    if not kraken_report_path:
        return hits
    by_taxid, by_name = build_taxonomy_lineage_index(kraken_report_path)
    if not by_taxid and not by_name:
        return hits

    out: list[dict] = []
    for hit in hits:
        metadata = by_taxid.get(str(hit.get("taxid") or "")) or by_name.get(str(hit.get("organism") or "").lower())
        if metadata:
            merged = {**hit}
            for key in ("taxid", "rank", "lineage", "top_clade"):
                merged.setdefault(key, metadata.get(key))
            out.append(merged)
        else:
            out.append(hit)
    return out


def parse_taxonomy_report(path: Path) -> list[dict]:
    """Parse lightweight taxonomy report formats.

    Supported formats:
    1) Generic TSV/CSV header with columns:
       organism, kingdom/rank, read_count, confidence, evidence_score,
       tools(optional), likely_contaminant(optional), warning(optional),
       breadth_fraction/breadth_pct(optional), coverage_depth(optional),
       genome_covered_bp/genome_length_bp(optional), coverage_method(optional),
       taxid(optional), lineage(optional), top_clade(optional)
    2) Kraken-style report rows:
       pct\treads_clade\treads_direct\trank\ttaxid\tname
       -> mapped to organism/read_count/confidence (pct/100)
    """
    if not path.exists():
        return []

    lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    if not lines:
        return []

    first = lines[0]
    delim = "\t" if "\t" in first else ("," if "," in first else None)

    if delim:
        cols = [c.strip().lower() for c in first.split(delim)]
        if {"name", "taxonomy_id", "taxonomy_lvl", "new_est_reads", "fraction_total_reads"}.issubset(set(cols)):
            idx = {c: i for i, c in enumerate(cols)}
            out = []
            for row in lines[1:]:
                parts = [p.strip() for p in row.split(delim)]
                try:
                    organism = parts[idx["name"]]
                    rank = parts[idx["taxonomy_lvl"]]
                    read_count = int(float(parts[idx["new_est_reads"]]))
                    fraction_total = float(parts[idx["fraction_total_reads"]])
                except (KeyError, ValueError, IndexError):
                    continue
                if not organism:
                    continue
                kraken_assigned = _optional_int(parts, idx, ("kraken_assigned_reads",))
                added_reads = _optional_int(parts, idx, ("added_reads",))
                taxid = _optional_text(parts, idx, ("taxonomy_id",))
                out.append(
                    {
                        "organism": organism,
                        "kingdom": _rank_label(rank),
                        "rank": _rank_label(rank),
                        "taxid": taxid,
                        "read_count": read_count,
                        "confidence": round(max(0.0, min(1.0, fraction_total)), 6),
                        "evidence_score": round(max(0.0, min(1.0, fraction_total)), 6),
                        "tools": ["Kraken2", "Bracken"],
                        "likely_contaminant": False,
                        "warning": (
                            f"Bracken estimate; taxid={taxid}; kraken_assigned_reads={kraken_assigned}; added_reads={added_reads}"
                        ),
                    }
                )
            return out

        if {"organism", "kingdom", "read_count"}.issubset(set(cols)):
            idx = {c: i for i, c in enumerate(cols)}
            out = []
            for row in lines[1:]:
                parts = [p.strip() for p in row.split(delim)]
                try:
                    organism = parts[idx["organism"]]
                    kingdom = parts[idx["kingdom"]]
                    read_count = int(float(parts[idx["read_count"]]))
                except (KeyError, ValueError, IndexError):
                    continue

                confidence = 0.0
                evidence_score = 0.0
                if "confidence" in idx:
                    try:
                        confidence = float(parts[idx["confidence"]])
                    except (ValueError, IndexError):
                        confidence = 0.0
                if "evidence_score" in idx:
                    try:
                        evidence_score = float(parts[idx["evidence_score"]])
                    except (ValueError, IndexError):
                        evidence_score = 0.0

                tools = []
                if "tools" in idx:
                    try:
                        tools = [x.strip() for x in parts[idx["tools"]].split("|") if x.strip()]
                    except IndexError:
                        tools = []

                likely_contaminant = False
                if "likely_contaminant" in idx:
                    try:
                        val = parts[idx["likely_contaminant"]].strip().lower()
                        likely_contaminant = val in {"1", "true", "yes", "y"}
                    except IndexError:
                        likely_contaminant = False

                warning = None
                if "warning" in idx:
                    try:
                        warning = parts[idx["warning"]] or None
                    except IndexError:
                        warning = None

                breadth_fraction = _optional_float(
                    parts,
                    idx,
                    ("breadth_fraction", "coverage_breadth", "genome_breadth", "covered_fraction", "breadth"),
                )
                breadth_pct = _optional_float(parts, idx, ("breadth_pct", "coverage_breadth_pct", "genome_breadth_pct"))
                if breadth_fraction is None and breadth_pct is not None:
                    breadth_fraction = breadth_pct / 100.0
                coverage_depth = _optional_float(parts, idx, ("coverage_depth", "mean_depth", "depth", "mean_coverage"))
                genome_covered_bp = _optional_int(parts, idx, ("genome_covered_bp", "covered_bp", "covered_bases"))
                genome_length_bp = _optional_int(parts, idx, ("genome_length_bp", "genome_bp", "genome_length", "target_bp"))
                coverage_method = _optional_text(parts, idx, ("coverage_method", "breadth_method", "coverage_source"))
                taxid = _optional_text(parts, idx, ("taxid", "taxonomy_id", "ncbi_taxid"))
                rank = _optional_text(parts, idx, ("rank", "taxonomy_lvl"))
                lineage = _optional_text(parts, idx, ("lineage", "taxonomy_lineage"))
                top_clade = _optional_text(parts, idx, ("top_clade", "superkingdom", "domain", "clade"))

                out.append(
                    {
                        "organism": organism,
                        "kingdom": kingdom,
                        "rank": _rank_label(rank) if rank else kingdom,
                        "taxid": taxid,
                        "lineage": [{"name": item.strip()} for item in lineage.split(";") if item.strip()] if lineage else [],
                        "top_clade": top_clade,
                        "read_count": read_count,
                        "confidence": confidence,
                        "evidence_score": evidence_score,
                        "tools": tools,
                        "likely_contaminant": likely_contaminant,
                        "warning": warning,
                        "breadth_fraction": breadth_fraction,
                        "coverage_depth": coverage_depth,
                        "genome_covered_bp": genome_covered_bp,
                        "genome_length_bp": genome_length_bp,
                        "coverage_method": coverage_method,
                    }
                )
            return out

    # Kraken-style fallback
    out = []
    by_taxid, by_name = _lineage_index_from_kraken_lines(lines)
    for row in lines:
        parts = row.split("\t") if "\t" in row else row.split()
        if len(parts) < 6:
            continue
        try:
            pct = float(parts[0])
            read_count = int(parts[1])
            rank_code = parts[3].strip()
            taxid = parts[4].strip()
            name = parts[5].strip()
        except ValueError:
            continue

        if not name:
            continue
        metadata = by_taxid.get(taxid) or by_name.get(name.lower()) or {}

        out.append(
            {
                "organism": name,
                "kingdom": _rank_label(rank_code),
                "rank": _rank_label(rank_code),
                "taxid": taxid or None,
                "lineage": metadata.get("lineage", []),
                "top_clade": metadata.get("top_clade"),
                "read_count": read_count,
                "confidence": round(max(0.0, min(1.0, pct / 100.0)), 4),
                "evidence_score": round(max(0.0, min(1.0, pct / 100.0)), 4),
                "tools": ["Kraken2"],
                "likely_contaminant": False,
                "warning": None,
            }
        )

    return out
