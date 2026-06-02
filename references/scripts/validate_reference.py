#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

REQUIRED_FIELDS = [
    "id",
    "aliases",
    "version",
    "source",
    "status",
    "contig_style",
    "mitochondrial_contig",
]
ALLOWED_STATUS = {"missing", "downloading", "indexed", "ready", "invalid"}


def load_yaml(path: Path):
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required for manifest validation") from exc

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_manifest(doc: dict, path: Path) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in doc:
            errors.append(f"missing_field:{field}")

    if "aliases" in doc and not isinstance(doc["aliases"], list):
        errors.append("invalid_aliases_type")

    status = doc.get("status")
    if status and status not in ALLOWED_STATUS:
        errors.append("invalid_status")

    contig_style = doc.get("contig_style")
    if contig_style and contig_style not in {"chr", "numeric", "chrM"}:
        errors.append("invalid_contig_style")

    if not doc.get("id"):
        errors.append("empty_id")

    if not str(doc.get("source", "")).startswith(("http://", "https://", "GIAB", "NCBI")):
        errors.append("suspicious_source")

    return errors


def main():
    p = argparse.ArgumentParser(description="Validate reference profile metadata and files")
    p.add_argument("--manifest", required=False, help="Path to single manifest YAML")
    p.add_argument("--dir", default="references/manifests", help="Directory with manifests")
    args = p.parse_args()

    paths = []
    if args.manifest:
        paths = [Path(args.manifest)]
    else:
        paths = sorted(Path(args.dir).glob("*.yaml"))

    if not paths:
        print("No manifests found", file=sys.stderr)
        sys.exit(2)

    failed = 0
    for path in paths:
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            print(f"{path}: invalid_yaml_root")
            failed += 1
            continue

        errors = validate_manifest(doc, path)
        if errors:
            print(f"{path}: FAIL -> {', '.join(errors)}")
            failed += 1
        else:
            print(f"{path}: OK")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
