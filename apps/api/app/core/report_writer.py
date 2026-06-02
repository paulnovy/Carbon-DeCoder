from __future__ import annotations

import json
import hashlib
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "wgs.report.v1"


def _label(value: str) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "-"


def _format_scalar(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _render_compact_value(value: Any) -> str:
    if _is_scalar(value):
        return escape(_format_scalar(value))
    return f"<code>{escape(json.dumps(value, ensure_ascii=False, sort_keys=True))}</code>"


def _render_metric_cards(summary: dict[str, Any]) -> str:
    cards: list[str] = []
    skip = {"reference", "non_diagnostic", "items", "top_hits", "sections", "source_files"}
    for key, value in summary.items():
        if key in skip:
            continue
        if _is_scalar(value):
            cards.append(
                "<div class='metric-card'>"
                f"<span>{escape(_label(key))}</span>"
                f"<strong>{_render_compact_value(value)}</strong>"
                "</div>"
            )
        elif isinstance(value, dict):
            scalar_items = [(k, v) for k, v in value.items() if _is_scalar(v)]
            for nested_key, nested_value in scalar_items[:4]:
                cards.append(
                    "<div class='metric-card'>"
                    f"<span>{escape(_label(nested_key))}</span>"
                    f"<strong>{_render_compact_value(nested_value)}</strong>"
                    f"<small>{escape(_label(key))}</small>"
                    "</div>"
                )
    if not cards:
        cards.append("<div class='metric-card'><span>Status</span><strong>No summary metrics</strong></div>")
    return "<section class='metric-grid'>" + "".join(cards[:12]) + "</section>"


def _render_table_from_dict(data: dict[str, Any]) -> str:
    rows = []
    for key, value in data.items():
        rows.append(
            "<tr>"
            f"<th>{escape(_label(key))}</th>"
            f"<td>{_render_value(value)}</td>"
            "</tr>"
        )
    return "<table class='kv-table'><tbody>" + "".join(rows) + "</tbody></table>"


def _render_table_from_list(items: list[Any]) -> str:
    if not items:
        return "<p class='muted'>No rows.</p>"
    if not all(isinstance(item, dict) for item in items):
        return "<ul class='plain-list'>" + "".join(f"<li>{_render_value(item)}</li>" for item in items[:50]) + "</ul>"

    keys: list[str] = []
    for item in items[:20]:
        for key in item.keys():
            if key not in keys:
                keys.append(key)
            if len(keys) >= 8:
                break
        if len(keys) >= 8:
            break
    header = "".join(f"<th>{escape(_label(key))}</th>" for key in keys)
    rows = []
    for item in items[:50]:
        rows.append("<tr>" + "".join(f"<td>{_render_compact_value(item.get(key))}</td>" for key in keys) + "</tr>")
    footer = "<p class='muted'>Showing first 50 rows.</p>" if len(items) > 50 else ""
    return "<div class='table-wrap'><table class='data-table'><thead><tr>" + header + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>" + footer


def _render_value(value: Any) -> str:
    if isinstance(value, dict):
        return _render_table_from_dict(value)
    if isinstance(value, list):
        return _render_table_from_list(value)
    return _render_compact_value(value)


def _render_sections(summary: dict[str, Any]) -> str:
    sections: list[str] = []
    for key, value in summary.items():
        if key in {"non_diagnostic"} or _is_scalar(value):
            continue
        sections.append(
            "<section class='report-section'>"
            f"<h2>{escape(_label(key))}</h2>"
            f"{_render_value(value)}"
            "</section>"
        )
    return "".join(sections)


def _render_reference_provenance(summary: dict[str, Any]) -> str:
    reference = summary.get("reference")
    if not isinstance(reference, dict):
        return ""
    return (
        "<section class='report-section provenance'>"
        "<h2>Reference provenance</h2>"
        f"{_render_table_from_dict(reference)}"
        "</section>"
    )


def _report_css() -> str:
    return """
    :root { color-scheme: dark; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #08111f; color: #e6edf3; }
    .report-shell { max-width: 1180px; margin: 0 auto; padding: 32px 22px 52px; }
    .hero { border-bottom: 1px solid #263446; padding-bottom: 22px; margin-bottom: 22px; }
    .eyebrow { text-transform: uppercase; letter-spacing: .08em; color: #7dd3fc; font-size: 12px; font-weight: 700; }
    h1 { margin: 8px 0 8px; font-size: 30px; line-height: 1.15; }
    h2 { margin: 0 0 12px; font-size: 17px; }
    .muted { color: #94a3b8; }
    .notice { border: 1px solid #f59e0b; color: #fbbf24; background: rgba(245, 158, 11, .08); border-radius: 8px; padding: 10px 12px; margin: 16px 0; }
    .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0 22px; }
    .metric-card { border: 1px solid #263446; border-radius: 8px; background: #0f1b2b; padding: 12px; min-width: 0; }
    .metric-card span, .metric-card small { display: block; color: #94a3b8; font-size: 12px; overflow-wrap: anywhere; }
    .metric-card strong { display: block; margin-top: 5px; font-size: 19px; overflow-wrap: anywhere; }
    .report-section { margin: 18px 0; padding: 16px; border: 1px solid #263446; border-radius: 8px; background: #0b1624; }
    .table-wrap { overflow-x: auto; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #263446; padding: 8px 9px; text-align: left; vertical-align: top; font-size: 13px; }
    th { color: #cbd5e1; font-weight: 700; white-space: nowrap; }
    td { color: #e2e8f0; overflow-wrap: anywhere; }
    .kv-table th { width: 210px; }
    .plain-list { margin: 0; padding-left: 20px; }
    code, pre { background: #050b14; color: #d1e9ff; border: 1px solid #263446; border-radius: 6px; }
    code { padding: 1px 4px; }
    details { margin-top: 18px; }
    summary { cursor: pointer; color: #7dd3fc; font-weight: 700; }
    pre { padding: 14px; overflow-x: auto; }
    a { color: #7dd3fc; }
    """


def _html_from_summary(report_type: str, summary: dict[str, Any]) -> str:
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    sample_id = summary.get("sample_id") or "-"
    run_id = summary.get("run_id") or "-"
    generated_at = datetime.now(timezone.utc).isoformat()
    note = summary.get("note")
    non_diagnostic = bool(summary.get("non_diagnostic", True))
    return (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>"
        f"{escape(_label(report_type))}"
        "</title><style>"
        f"{_report_css()}"
        "</style></head><body>"
        "<main class='report-shell'>"
        "<header class='hero'>"
        f"<div class='eyebrow'>{escape(str(report_type))} report</div>"
        f"<h1>{escape(_label(report_type))}</h1>"
        f"<p class='muted'>Sample {escape(str(sample_id))} - Run {escape(str(run_id))} - Generated {escape(generated_at)}</p>"
        "</header>"
        + ("<div class='notice'>Non-diagnostic research/technical report. Do not use as a clinical diagnosis.</div>" if non_diagnostic else "")
        + (f"<p class='muted'>{escape(str(note))}</p>" if note else "")
        + _render_metric_cards(summary)
        + _render_reference_provenance(summary)
        + _render_sections({k: v for k, v in summary.items() if k != "reference"})
        + "<details><summary>Raw JSON payload</summary>"
        f"<pre>{escape(payload)}</pre>"
        "</details>"
        "</main>"
        "</body></html>\n"
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_payload(report_type: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        **summary,
        "_report": {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_type": report_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "format": "json",
        },
    }


def _scalar_row_value(value: Any) -> dict[str, Any]:
    numeric_value = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return {
        "value_type": type(value).__name__ if value is not None else "null",
        "scalar_string": None if value is None else _format_scalar(value),
        "numeric_value": float(numeric_value) if numeric_value is not None else None,
        "boolean_value": value if isinstance(value, bool) else None,
        "value_json": _json_text(value),
    }


def _flatten_report_rows(report_type: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(summary.get("run_id") or "")
    sample_id = str(summary.get("sample_id") or "")
    generated_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    def add_row(path: str, key: str, value: Any, item_index: int | None = None) -> None:
        rows.append(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "report_type": report_type,
                "run_id": run_id,
                "sample_id": sample_id,
                "generated_at": generated_at,
                "path": path,
                "key": key,
                "item_index": item_index,
                **_scalar_row_value(value),
            }
        )

    def walk(value: Any, path: str, key: str, item_index: int | None = None) -> None:
        if isinstance(value, dict):
            if not value:
                add_row(path, key, {}, item_index)
                return
            for child_key, child_value in value.items():
                child_path = f"{path}.{child_key}" if path else str(child_key)
                walk(child_value, child_path, str(child_key), item_index)
            return
        if isinstance(value, list):
            if not value:
                add_row(path, key, [], item_index)
                return
            for idx, item in enumerate(value):
                item_path = f"{path}[{idx}]"
                walk(item, item_path, key, idx)
            return
        add_row(path, key, value, item_index)

    walk(summary, "", "summary")
    if not rows:
        add_row("", "summary", None)
    return rows


def _write_parquet_summary(report_type: str, summary: dict[str, Any], parquet_path: str) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow_required_for_parquet_reports") from exc

    rows = _flatten_report_rows(report_type, summary)
    schema = pa.schema(
        [
            ("schema_version", pa.string()),
            ("report_type", pa.string()),
            ("run_id", pa.string()),
            ("sample_id", pa.string()),
            ("generated_at", pa.string()),
            ("path", pa.string()),
            ("key", pa.string()),
            ("item_index", pa.int64()),
            ("value_type", pa.string()),
            ("scalar_string", pa.string()),
            ("numeric_value", pa.float64()),
            ("boolean_value", pa.bool_()),
            ("value_json", pa.string()),
        ]
    )
    p = Path(parquet_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, p)


def write_report_artifacts(
    *,
    report_type: str,
    summary: dict[str, Any],
    html_path: str | None,
    json_path: str | None,
    parquet_path: str | None,
) -> dict[str, bool]:
    """Write HTML, stable JSON, and tabular Parquet artifacts for generated reports.

    Returns flags indicating which outputs were materialized.
    """
    written = {"html": False, "json": False, "parquet": False}

    if html_path:
        p = Path(html_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_html_from_summary(report_type, summary), encoding="utf-8")
        written["html"] = True

    if json_path:
        p = Path(json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_json_payload(report_type, summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written["json"] = True

    if parquet_path:
        _write_parquet_summary(report_type, summary, parquet_path)
        written["parquet"] = True

    return written


def write_report_bundle_manifest(*, run_id: str, items: list[dict[str, Any]], context: dict[str, Any] | None = None) -> str:
    """Write bundle manifest JSON and return file path."""

    def file_meta(path_value: Any) -> dict[str, Any]:
        if not path_value:
            return {"path": None, "exists": False, "size_bytes": None, "sha256": None}
        p = Path(str(path_value))
        if not p.exists() or not p.is_file():
            return {"path": str(p), "exists": False, "size_bytes": None, "sha256": None}
        data = p.read_bytes()
        return {
            "path": str(p),
            "exists": True,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    enriched_items: list[dict[str, Any]] = []
    for item in items:
        enriched_items.append(
            {
                **item,
                "file_meta": {
                    "html": file_meta(item.get("html_path")),
                    "json": file_meta(item.get("json_path")),
                    "parquet": file_meta(item.get("parquet_path")),
                },
            }
        )

    p = Path(f"results/reports/{run_id}/bundle_manifest.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "count": len(enriched_items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": context or {},
        "items": enriched_items,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(p)


def write_report_bundle_index_html(
    *,
    run_id: str,
    items: list[dict[str, Any]],
    manifest_path: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Write simple human-readable bundle index HTML and return file path."""
    p = Path(f"results/reports/{run_id}/index.html")
    p.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in items:
        report_type = item.get("report_type", "unknown")
        html_path = item.get("html_path")
        json_path = item.get("json_path")
        parquet_path = item.get("parquet_path")
        links = []
        if html_path:
            links.append(f"<a href='{escape(str(html_path), quote=True)}'>html</a>")
        if json_path:
            links.append(f"<a href='{escape(str(json_path), quote=True)}'>json</a>")
        if parquet_path:
            links.append(f"<a href='{escape(str(parquet_path), quote=True)}'>parquet</a>")
        rows.append(
            "<tr>"
            f"<td>{escape(str(report_type))}</td>"
            f"<td>{' | '.join(links) if links else '-'}</td>"
            f"<td>{escape(str(item.get('status') or '-'))}</td>"
            "</tr>"
        )

    reference = (context or {}).get("reference") if isinstance(context, dict) else None
    context_html = ""
    if isinstance(reference, dict):
        checksum = reference.get("download_checksum") if isinstance(reference.get("download_checksum"), dict) else {}
        checksum_label = checksum.get("algorithm") if checksum.get("status") != "not_configured" else "not configured"
        context_html = (
            "<section class='report-section provenance'>"
            "<h2>Reference provenance</h2>"
            "<table class='kv-table'>"
            f"<tr><th>reference</th><td>{escape(str(reference.get('id') or '-'))}</td></tr>"
            f"<tr><th>version</th><td>{escape(str(reference.get('version') or '-'))}</td></tr>"
            f"<tr><th>source</th><td>{escape(str(reference.get('source') or '-'))}</td></tr>"
            f"<tr><th>contig_style</th><td>{escape(str(reference.get('contig_style') or '-'))}</td></tr>"
            f"<tr><th>status</th><td>{escape(str(reference.get('status') or '-'))}</td></tr>"
            f"<tr><th>fasta</th><td>{escape(str(reference.get('fasta_path') or '-'))}</td></tr>"
            f"<tr><th>checksum</th><td>{escape(str(checksum_label))}</td></tr>"
            "</table>"
            "</section>"
        )

    html = (
        "<!doctype html>\n"
        "<html><head><meta charset='utf-8'><title>Report bundle index</title><style>"
        f"{_report_css()}"
        "</style></head><body><main class='report-shell'>"
        "<header class='hero'>"
        "<div class='eyebrow'>report bundle</div>"
        f"<h1>Report bundle index</h1>"
        f"<p class='muted'>Run {escape(str(run_id))}</p>"
        "</header>"
        f"<p>Manifest: <a href='{escape(str(manifest_path), quote=True)}'>{escape(str(manifest_path))}</a></p>"
        f"{context_html}"
        "<section class='report-section'>"
        "<h2>Artifacts</h2>"
        "<div class='table-wrap'><table class='data-table'>"
        "<thead><tr><th>Report type</th><th>Artifacts</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
        "</section>"
        "</main>"
        "</body></html>\n"
    )
    p.write_text(html, encoding="utf-8")
    return str(p)
