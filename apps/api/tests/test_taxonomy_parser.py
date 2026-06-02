from pathlib import Path

from app.core.taxonomy_parser import enrich_taxonomy_hits_with_lineage, parse_taxonomy_report


def test_parse_taxonomy_generic_tsv(tmp_path: Path):
    p = tmp_path / "taxonomy.tsv"
    p.write_text(
        "organism\tkingdom\tread_count\tconfidence\tevidence_score\ttools\tlikely_contaminant\tbreadth_pct\tcoverage_depth\tgenome_covered_bp\tgenome_length_bp\tcoverage_method\n"
        "Escherichia coli\tbacteria\t77\t0.64\t0.55\tKraken2|Bracken\ttrue\t12.5\t3.7\t580000\t4641652\tminimap2_bam_breadth\n",
        encoding="utf-8",
    )

    hits = parse_taxonomy_report(p)
    assert len(hits) == 1
    assert hits[0]["organism"] == "Escherichia coli"
    assert hits[0]["likely_contaminant"] is True
    assert hits[0]["breadth_fraction"] == 0.125
    assert hits[0]["coverage_depth"] == 3.7
    assert hits[0]["genome_covered_bp"] == 580000
    assert hits[0]["genome_length_bp"] == 4641652
    assert hits[0]["coverage_method"] == "minimap2_bam_breadth"


def test_parse_taxonomy_kraken_report(tmp_path: Path):
    p = tmp_path / "kraken.report"
    p.write_text(
        "90.00\t1000\t0\tR\t1\troot\n"
        "80.00\t900\t0\tD\t2\t  Bacteria\n"
        "2.50\t123\t45\tS\t562\t    Escherichia coli\n",
        encoding="utf-8",
    )

    hits = parse_taxonomy_report(p)
    ecoli = next(hit for hit in hits if hit["organism"] == "Escherichia coli")
    assert ecoli["tools"] == ["Kraken2"]
    assert ecoli["taxid"] == "562"
    assert ecoli["rank"] == "species"
    assert ecoli["top_clade"] == "Bacteria"
    assert [node["name"] for node in ecoli["lineage"]] == ["root", "Bacteria", "Escherichia coli"]


def test_parse_taxonomy_bracken_native_tsv(tmp_path: Path):
    p = tmp_path / "bracken.tsv"
    p.write_text(
        "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads\n"
        "Cutibacterium acnes\t1747\tS\t184\t37\t221\t0.0285\n",
        encoding="utf-8",
    )

    hits = parse_taxonomy_report(p)

    assert len(hits) == 1
    assert hits[0]["organism"] == "Cutibacterium acnes"
    assert hits[0]["kingdom"] == "species"
    assert hits[0]["read_count"] == 221
    assert hits[0]["confidence"] == 0.0285
    assert hits[0]["tools"] == ["Kraken2", "Bracken"]
    assert hits[0]["taxid"] == "1747"
    assert "added_reads=37" in hits[0]["warning"]


def test_enrich_bracken_hits_from_kraken_lineage(tmp_path: Path):
    report = tmp_path / "kraken.report"
    report.write_text(
        "90.00\t1000\t0\tR\t1\troot\n"
        "80.00\t900\t0\tD\t2\t  Bacteria\n"
        "1.20\t42\t7\tS\t729\t    Haemophilus influenzae\n"
        "0.40\t12\t2\tD\t10239\t  Viruses\n"
        "0.30\t9\t1\tS\t11320\t    Influenza A virus\n",
        encoding="utf-8",
    )
    bracken_hits = [
        {"organism": "Haemophilus influenzae", "taxid": "729", "kingdom": "species"},
        {"organism": "Influenza A virus", "taxid": "11320", "kingdom": "species"},
    ]

    enriched = enrich_taxonomy_hits_with_lineage(bracken_hits, report)

    by_name = {hit["organism"]: hit for hit in enriched}
    assert by_name["Haemophilus influenzae"]["top_clade"] == "Bacteria"
    assert by_name["Influenza A virus"]["top_clade"] == "Viruses"
