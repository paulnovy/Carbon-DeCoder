import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_alignment_stage_script_dev_fallback_emits_importable_contract(tmp_path: Path):
    r1 = tmp_path / "S1_R1.fastq.gz"
    r2 = tmp_path / "S1_R2.fastq.gz"
    ref = tmp_path / "missing.fa"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    r2.write_text("@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_alignment_stage.sh"
    subprocess.run(
        [str(script), "S1", str(ref), str(r1), str(r2), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.sorted.markdup.bam").exists()
    assert (tmp_path / "S1.sorted.markdup.bam.bai").exists()
    assert "mapped (97.00%" in (tmp_path / "S1.flagstat.txt").read_text(encoding="utf-8")
    contract = json.loads((tmp_path / "S1.alignment.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "alignment"
    assert contract["payload"]["flagstat_txt"] == "S1.flagstat.txt"
    assert contract["payload"]["alignment_mode"] == "dev_fallback"


def test_alignment_stage_script_blocks_selected_bwa_mem2_without_index(tmp_path: Path, monkeypatch):
    r1 = tmp_path / "S1_R1.fastq.gz"
    r2 = tmp_path / "S1_R2.fastq.gz"
    ref = tmp_path / "GRCh38.fa"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    r2.write_text("@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ["samtools", "bwa-mem2.avx2"]:
        path = bin_dir / tool
        path.write_text("#!/usr/bin/env sh\necho fake $0\n", encoding="utf-8")
        path.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("WGS_ALIGNMENT_BACKEND", "bwa-mem2")
    script = ROOT / "pipelines/nextflow/scripts/run_alignment_stage.sh"

    result = subprocess.run(
        [str(script), "S1", str(ref), str(r1), str(r2), "1", "false"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 127
    assert "bwa-mem2 index missing" in result.stderr
    assert ".bwt.2bit.64" in result.stderr


def test_coverage_stage_script_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    bam.write_text("not a real bam in dev fallback\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_coverage_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), "1", "1000000", "1mb", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert "total" in (tmp_path / "S1.mosdepth.summary.txt").read_text(encoding="utf-8")
    assert (tmp_path / "S1.regions.bed.gz").exists()
    assert (tmp_path / "S1.coverage.tiles.1mb.json").exists()
    contract = json.loads((tmp_path / "S1.coverage.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "coverage"
    assert contract["payload"]["mosdepth_summary_txt"] == "S1.mosdepth.summary.txt"
    assert contract["payload"]["coverage_mode"] == "dev_fallback"


def test_nextflow_config_exposes_strict_alignment_coverage_profile():
    config = (ROOT / "pipelines/nextflow/nextflow.config").read_text(encoding="utf-8")
    main = (ROOT / "pipelines/nextflow/main.nf").read_text(encoding="utf-8")
    assert "alignment_coverage" in config
    assert "params.allow_dev_fallback = false" in config
    assert "run_alignment_stage.sh" in main
    assert "run_coverage_stage.sh" in main
    assert "alignment.ingest.json" in main
    assert "coverage.ingest.json" in main


def test_variant_normalization_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    vcf = tmp_path / "raw.vcf"
    ref = tmp_path / "missing.fa"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    script = ROOT / "pipelines/nextflow/scripts/run_variant_normalization_stage.sh"
    subprocess.run(
        [str(script), "S1", str(vcf), str(ref), "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.variants.normalized.vcf").exists()
    assert (tmp_path / "S1.variants.normalized.vcf.gz").exists()
    assert (tmp_path / "S1.variants.normalized.vcf.gz.tbi").exists()
    contract = json.loads((tmp_path / "S1.variants.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "variants"
    assert contract["payload"]["variants_vcf_path"] == "S1.variants.normalized.vcf"
    assert contract["payload"]["normalization_mode"] in ("dev_fallback_copy", "bcftools_norm_copy_fallback", "bcftools_norm_split_only", "bcftools_norm_ref")


def test_nextflow_config_exposes_variant_normalization_profile():
    config = (ROOT / "pipelines/nextflow/nextflow.config").read_text(encoding="utf-8")
    main = (ROOT / "pipelines/nextflow/main.nf").read_text(encoding="utf-8")
    assert "variant_normalization" in config
    assert "dev_variant_normalization" in config
    assert "run_variant_normalization_stage.sh" in main
    assert "variants.ingest.json" in main


def test_bcftools_variant_calling_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("not a real bam in dev fallback\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_bcftools_variant_calling_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.bcftools.raw.vcf").exists()
    assert (tmp_path / "S1.bcftools.raw.vcf.gz").exists()
    assert (tmp_path / "S1.bcftools.raw.vcf.gz.tbi").exists()
    assert "number of SNPs" in (tmp_path / "S1.bcftools.stats.txt").read_text(encoding="utf-8")
    contract = json.loads((tmp_path / "S1.variants.bcftools.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "variants"
    assert contract["payload"]["variants_vcf_path"] == "S1.bcftools.raw.vcf"
    assert contract["payload"]["variant_calling_mode"] == "dev_fallback_bcftools_vcf"
    assert contract["payload"]["caller"] == "bcftools"


def test_nextflow_config_exposes_variant_calling_profile():
    config = (ROOT / "pipelines/nextflow/nextflow.config").read_text(encoding="utf-8")
    main = (ROOT / "pipelines/nextflow/main.nf").read_text(encoding="utf-8")
    assert "variant_calling" in config
    assert "dev_variant_calling" in config
    assert "BCFTOOLS_VARIANT_CALLING" in main
    assert "run_bcftools_variant_calling_stage.sh" in main
    assert "variants.bcftools.ingest.json" in main


def test_gatk_variant_calling_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("not a real bam in dev fallback\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_gatk_variant_calling_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.gatk.hc.raw.vcf").exists()
    assert (tmp_path / "S1.gatk.hc.raw.vcf.gz").exists()
    assert (tmp_path / "S1.gatk.hc.raw.vcf.gz.tbi").exists()
    assert "number of records" in (tmp_path / "S1.gatk.stats.txt").read_text(encoding="utf-8")
    contract = json.loads((tmp_path / "S1.variants.gatk.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "variants"
    assert contract["payload"]["variants_vcf_path"] == "S1.gatk.hc.raw.vcf"
    assert contract["payload"]["variant_calling_mode"] == "dev_fallback_gatk_vcf"
    assert contract["payload"]["caller"] == "GATK"


def test_deepvariant_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("not a real bam in dev fallback\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_deepvariant_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true", "WGS"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.deepvariant.raw.vcf").exists()
    assert (tmp_path / "S1.deepvariant.raw.vcf.gz").exists()
    assert (tmp_path / "S1.deepvariant.raw.vcf.gz.tbi").exists()
    contract = json.loads((tmp_path / "S1.variants.deepvariant.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "variants"
    assert contract["payload"]["variants_vcf_path"] == "S1.deepvariant.raw.vcf"
    assert contract["payload"]["variant_calling_mode"] == "dev_fallback_deepvariant_vcf"
    assert contract["payload"]["caller"] == "DeepVariant"


def test_nextflow_config_exposes_multi_caller_support():
    main = (ROOT / "pipelines/nextflow/main.nf").read_text(encoding="utf-8")
    assert "GATK_VARIANT_CALLING" in main
    assert "DEEPVARIANT_CALLING" in main
    assert "run_gatk_variant_calling_stage.sh" in main
    assert "run_deepvariant_stage.sh" in main
    assert "variants.gatk.ingest.json" in main
    assert "variants.deepvariant.ingest.json" in main
    assert "variant_caller" in main
    assert "broadinstitute/gatk" in main
    assert "google/deepvariant" in main


def test_annotation_stage_uses_vep_when_configured(tmp_path: Path, monkeypatch):
    vcf = tmp_path / "S1.vcf"
    ref = tmp_path / "ref.fa"
    gff = tmp_path / "genes.gff3"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t100\t.\tA\tG\t50\tPASS\t.\n",
        encoding="utf-8",
    )
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")
    gff.write_text("##gff-version 3\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    vep = bin_dir / "vep"
    vep.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
out=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --output_file) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cat > "$out" <<'VCF'
##fileformat=VCFv4.2
##INFO=<ID=CSQ,Number=.,Type=String,Description="Consequence annotations">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
chr1	100	.	A	G	50	PASS	CSQ=G|missense_variant|MODERATE|GENE1|ENSG1|Transcript|ENST1
VCF
""",
        encoding="utf-8",
    )
    vep.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("WGS_VEP_ENABLED", "true")
    script = ROOT / "pipelines/nextflow/scripts/run_annotation_stage.sh"
    subprocess.run(
        [str(script), "S1", str(vcf), str(ref), str(gff), "1", "false"],
        cwd=tmp_path,
        check=True,
    )

    contract = json.loads((tmp_path / "S1.annotation.ingest.json").read_text(encoding="utf-8"))
    annotated = (tmp_path / "S1.variants.annotated.vcf").read_text(encoding="utf-8")
    assert contract["stage"] == "annotation"
    assert contract["payload"]["annotation_mode"] == "vep"
    assert contract["payload"]["csq_field"] == "CSQ"
    assert "CSQ=G|missense_variant|MODERATE|GENE1" in annotated


def test_prs_stage_runs_configured_pgscalc_and_emits_importable_contract(tmp_path: Path, monkeypatch):
    vcf = tmp_path / "S1.vcf.gz"
    vcf.write_bytes(b"fake-vcf")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nextflow = bin_dir / "nextflow"
    nextflow.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
outdir=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --outdir) outdir="$2"; shift 2 ;;
    *) shift ;;
  esac
done
mkdir -p "$outdir/S1/score" "$outdir/S1/match"
python3 - "$outdir" <<'PY'
import gzip
import sys
from pathlib import Path
root = Path(sys.argv[1])
with gzip.open(root / "S1/score/aggregated_scores.txt.gz", "wt", encoding="utf-8") as fh:
    fh.write("sampleset FID IID PGS SUM DENOM AVG\\n")
    fh.write("S1 S1 S1 PGS000001 1.23 80 0.015\\n")
(root / "S1/match/S1_summary.csv").write_text(
    "dataset,accession,score_pass,match_status,count,percent\\n"
    "S1,PGS000001,True,matched,80,80\\n"
    "S1,PGS000001,True,unmatched,20,20\\n",
    encoding="utf-8",
)
PY
""",
        encoding="utf-8",
    )
    nextflow.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("WGS_PGSC_CALC_ENABLED", "true")
    monkeypatch.setenv("WGS_PGSC_CALC_PGS_IDS", "PGS000001")
    monkeypatch.setenv("WGS_PGSC_CALC_OUTDIR", str(tmp_path / "pgsc-out"))

    script = ROOT / "pipelines/nextflow/scripts/run_prs_stage.sh"
    subprocess.run(
        [str(script), "S1", str(vcf), "GRCh38_standard", "false"],
        cwd=tmp_path,
        check=True,
    )

    result = (tmp_path / "S1.prs.result.txt").read_text(encoding="utf-8")
    contract = json.loads((tmp_path / "S1.prs.ingest.json").read_text(encoding="utf-8"))

    assert "trait=PGS000001" in result
    assert "score_value=1.23" in result
    assert "overlap_pct=80.0000" in result
    assert "quality_label=high" in result
    assert contract["stage"] == "prs"
    assert contract["payload"]["prs_result_path"] == "S1.prs.result.txt"
    assert contract["payload"]["prs_mode"] == "pgsc_calc"


def test_benchmark_stage_runs_happy_and_emits_importable_contract(tmp_path: Path, monkeypatch):
    query = tmp_path / "query.vcf"
    truth = tmp_path / "truth.vcf"
    ref = tmp_path / "ref.fa"
    bed = tmp_path / "truth.bed"
    query.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        encoding="utf-8",
    )
    truth.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n",
        encoding="utf-8",
    )
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")
    bed.write_text("chr1\t1\t1000\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    happy = bin_dir / "hap.py"
    happy.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
prefix=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) prefix="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cat > "${prefix}.summary.csv" <<'CSV'
Type,TRUTH.TOTAL,QUERY.TOTAL,TRUTH.TP,QUERY.TP,TRUTH.FN,QUERY.FP,METRIC.Recall,METRIC.Precision,METRIC.F1_Score
TOTAL,10,10,9,9,1,1,0.9,0.9,0.9
CSV
""",
        encoding="utf-8",
    )
    happy.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("WGS_BENCHMARK_TRUTH_VCF", str(truth))
    monkeypatch.setenv("WGS_BENCHMARK_TRUTH_BED", str(bed))
    monkeypatch.setenv("WGS_BENCHMARK_MODE", "happy")

    script = ROOT / "pipelines/nextflow/scripts/run_benchmark_stage.sh"
    subprocess.run(
        [str(script), "S1", str(query), str(ref), "1", "false"],
        cwd=tmp_path,
        check=True,
    )

    summary = tmp_path / "S1.benchmark.happy.summary.csv"
    contract = json.loads((tmp_path / "S1.benchmark.ingest.json").read_text(encoding="utf-8"))

    assert summary.exists()
    assert contract["stage"] == "benchmark"
    assert contract["payload"]["benchmark_id"] == "S1_happy"
    assert contract["payload"]["benchmark_report_path"] == "S1.benchmark.happy.summary.csv"
    assert contract["payload"]["benchmark_mode"] == "happy"


def test_taxonomy_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    r1 = tmp_path / "S1_R1.fastq.gz"
    r2 = tmp_path / "S1_R2.fastq.gz"
    r1.write_text("dummy", encoding="utf-8")
    r2.write_text("dummy", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_taxonomy_stage.sh"
    subprocess.run(
        [str(script), "S1", str(r1), str(r2), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.kraken2.report").exists()
    assert (tmp_path / "S1.bracken.tsv").exists()
    bracken_text = (tmp_path / "S1.bracken.tsv").read_text(encoding="utf-8")
    assert "Cutibacterium" not in bracken_text
    assert bracken_text.strip() == "organism\tkingdom\tread_count\tconfidence\tevidence_score\ttools\tlikely_contaminant\twarning"
    contract = json.loads((tmp_path / "S1.taxonomy.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "taxonomy"
    assert contract["payload"]["taxonomy_mode"] == "dev_fallback"
    assert contract["payload"]["taxonomy_refinement_status"] == "dev_fallback"
    assert contract["payload"]["bracken_report_path"] == "S1.bracken.tsv"


def test_taxonomy_stage_uses_memory_mapping_and_clears_stale_artifacts(tmp_path: Path, monkeypatch):
    r1 = tmp_path / "S1_R1.fastq"
    r2 = tmp_path / "S1_R2.fastq"
    db = tmp_path / "kraken_standard"
    bin_dir = tmp_path / "bin"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    r2.write_text("@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")
    db.mkdir()
    bin_dir.mkdir()

    (tmp_path / "S1.kraken2.report").write_text("stale-report\n", encoding="utf-8")
    (tmp_path / "S1.kraken2.output").write_text("stale-output\n", encoding="utf-8")
    fake_kraken = bin_dir / "kraken2"
    fake_kraken.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > kraken.args
report=""
output=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --report) report="$2"; shift 2 ;;
    --output) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
cat > "$report" <<'EOF'
100.00\t2\t0\tU\t0\t\tUnclassified
EOF
printf 'fresh-output\n' > "$output"
""",
        encoding="utf-8",
    )
    fake_kraken.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    script = ROOT / "pipelines/nextflow/scripts/run_taxonomy_stage.sh"
    subprocess.run(
        [str(script), "S1", str(r1), str(r2), "1", "false", str(db)],
        cwd=tmp_path,
        check=True,
    )

    args = (tmp_path / "kraken.args").read_text(encoding="utf-8").splitlines()
    assert "--memory-mapping" in args
    assert (tmp_path / "S1.kraken2.report").read_text(encoding="utf-8") != "stale-report\n"
    assert (tmp_path / "S1.kraken2.output").read_text(encoding="utf-8") == "fresh-output\n"
    contract = json.loads((tmp_path / "S1.taxonomy.ingest.json").read_text(encoding="utf-8"))
    assert contract["payload"]["taxonomy_database"] == str(db)
    assert contract["payload"]["taxonomy_mode"] == "kraken2"


def test_unknown_reads_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    r1 = tmp_path / "S1_R1.fastq.gz"
    r2 = tmp_path / "S1_R2.fastq.gz"
    r1.write_text("@r1\nACGT\n+\n!!!!\n", encoding="utf-8")
    r2.write_text("@r2\nTGCA\n+\n!!!!\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_unknown_reads_stage.sh"
    subprocess.run(
        [str(script), "S1", str(r1), str(r2), "1", "true", str(tmp_path / "missing_kraken_db")],
        cwd=tmp_path,
        check=True,
    )

    contract = json.loads((tmp_path / "S1.unknown_reads.ingest.json").read_text(encoding="utf-8"))
    payload = contract["payload"]
    assert contract["stage"] == "unknown_reads"
    assert contract["event_type"] == "run.ingest.request"
    assert payload["collection_mode"] == "fastq_fallback_or_external"
    assert payload["host_depletion"]["tool"] == "fastq_fallback"
    assert payload["taxonomy_depletion"]["tool"] == "none"
    assert payload["assembly"]["tool"] == "none"
    assert payload["kmer_profile"]["tool"] == "internal_kmer_counter"
    assert payload["kmer_profile"]["status"] == "no_kmers"
    assert payload["kmer_clusters"] == []
    assert payload["files"]["host_stats"] == "S1_unknown_reads/S1_host_depletion.stats"
    assert payload["files"]["kmer_profile_json"] == "S1_unknown_reads/S1_kmer_profile.json"


def test_mtdna_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("dummy", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_mtdna_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.mtdna.vcf").exists()
    assert (tmp_path / "S1.mtdna.report.json").exists()
    assert "chrM\t150" not in (tmp_path / "S1.mtdna.vcf").read_text(encoding="utf-8")
    report_text = (tmp_path / "S1.mtdna.report.json").read_text(encoding="utf-8")
    assert "haplogroup=" not in report_text
    assert "num_variants=0" in report_text
    contract = json.loads((tmp_path / "S1.mtdna.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "mtdna"
    assert contract["payload"]["mtdna_mode"] == "dev_fallback"


def test_mtdna_stage_detects_mt_contig_from_idxstats(tmp_path: Path, monkeypatch):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "ref.fa"
    bam.write_text("fake bam accepted by fake samtools\n", encoding="utf-8")
    ref.write_text(">MT\nACGT\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    samtools = bin_dir / "samtools"
    samtools.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  quickcheck) exit 0 ;;
  idxstats)
    printf 'chr1\\t1000\\t10\\t0\\nMT\\t16569\\t100\\t0\\n'
    ;;
  view)
    [ "${4:-}" = "MT" ] || exit 21
    printf 'MT_READS\\n'
    ;;
  index)
    exit 0
    ;;
  *)
    exit 22
    ;;
esac
""",
        encoding="utf-8",
    )
    samtools.chmod(0o755)
    gatk = bin_dir / "gatk"
    gatk.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-O" ]; then
    out="$2"
    shift 2
  else
    shift
  fi
done
[ -n "$out" ] || exit 23
cat > "$out" <<'VCF'
##fileformat=VCFv4.2
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO
MT	73	.	A	G	50	PASS	DP=100
VCF
""",
        encoding="utf-8",
    )
    gatk.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    script = ROOT / "pipelines/nextflow/scripts/run_mtdna_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "false"],
        cwd=tmp_path,
        check=True,
    )

    report_text = (tmp_path / "S1.mtdna.report.json").read_text(encoding="utf-8")
    assert "mitochondrial_contig=MT" in report_text
    assert "status=called" in report_text
    assert "num_variants=1" in report_text


def test_mtdna_stage_without_mt_contig_emits_empty_unavailable_artifact(tmp_path: Path, monkeypatch):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "ref.fa"
    bam.write_text("fake bam accepted by fake samtools\n", encoding="utf-8")
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    samtools = bin_dir / "samtools"
    samtools.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  quickcheck) exit 0 ;;
  idxstats)
    printf 'chr1\\t1000\\t10\\t0\\n'
    ;;
  *)
    exit 0
    ;;
esac
""",
        encoding="utf-8",
    )
    samtools.chmod(0o755)
    gatk = bin_dir / "gatk"
    gatk.write_text(
        """#!/usr/bin/env bash
echo "gatk should not run when no mt contig is present" >&2
exit 31
""",
        encoding="utf-8",
    )
    gatk.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    script = ROOT / "pipelines/nextflow/scripts/run_mtdna_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "false"],
        cwd=tmp_path,
        check=True,
    )

    report_text = (tmp_path / "S1.mtdna.report.json").read_text(encoding="utf-8")
    assert "status=not_available" in report_text
    assert "mitochondrial_contig=unknown" in report_text
    assert "num_variants=0" in report_text


def test_sv_calling_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("dummy", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_sv_calling_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.sv.vcf").exists()
    assert "chr20\t5000" not in (tmp_path / "S1.sv.vcf").read_text(encoding="utf-8")
    contract = json.loads((tmp_path / "S1.sv.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "sv"
    assert contract["payload"]["sv_mode"] == "dev_fallback"
    assert contract["payload"]["sv_count"] == 0


def test_cnv_calling_stage_uses_wgs_fasta_not_cnvkit_reference():
    script = (ROOT / "pipelines/nextflow/scripts/run_cnv_calling_stage.sh").read_text(encoding="utf-8")
    assert "--method wgs" in script
    assert "--fasta \"$reference_fasta\"" in script
    assert "--reference \"$reference_fasta\"" not in script


def test_cnv_calling_stage_runs_cnvkit_wgs_and_imports_cns(tmp_path: Path, monkeypatch):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "ref.fa"
    bam.write_text("fake bam accepted by fake samtools\n", encoding="utf-8")
    ref.write_text(">chr1\nACGT\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    samtools = bin_dir / "samtools"
    samtools.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "quickcheck" ]; then
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    samtools.chmod(0o755)
    cnvkit = bin_dir / "cnvkit.py"
    cnvkit.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
outdir=""
bam=""
have_wgs=false
have_fasta=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    batch) shift ;;
    --normal) shift ;;
    --method)
      [ "$2" = "wgs" ] || exit 12
      have_wgs=true
      shift 2
      ;;
    --fasta)
      have_fasta=true
      shift 2
      ;;
    --reference)
      exit 13
      ;;
    --output-dir)
      outdir="$2"
      shift 2
      ;;
    --processes)
      shift 2
      ;;
    *)
      if [ -z "$bam" ]; then bam="$1"; fi
      shift
      ;;
  esac
done
[ "$have_wgs" = "true" ] || exit 14
[ "$have_fasta" = "true" ] || exit 15
mkdir -p "$outdir"
base="$(basename "$bam" .bam)"
cat > "$outdir/${base}.cns" <<'CNS'
chromosome	start	end	gene	log2	depth	probes	weight
chr1	1000	4000	GENE1	-0.65	41.2	34	0.99
CNS
""",
        encoding="utf-8",
    )
    cnvkit.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    script = ROOT / "pipelines/nextflow/scripts/run_cnv_calling_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "2", "false"],
        cwd=tmp_path,
        check=True,
    )

    cns_copy = tmp_path / "S1.cnv.segments.tsv"
    contract = json.loads((tmp_path / "S1.cnv.ingest.json").read_text(encoding="utf-8"))
    assert "GENE1" in cns_copy.read_text(encoding="utf-8")
    assert contract["stage"] == "cnv"
    assert contract["payload"]["cnv_mode"] == "cnvkit"
    assert contract["payload"]["segment_count"] == 1


def test_cnv_calling_stage_dev_fallback_emits_importable_contract(tmp_path: Path):
    bam = tmp_path / "S1.sorted.markdup.bam"
    ref = tmp_path / "missing.fa"
    bam.write_text("dummy", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_cnv_calling_stage.sh"
    subprocess.run(
        [str(script), "S1", str(bam), str(ref), "1", "true"],
        cwd=tmp_path,
        check=True,
    )

    assert (tmp_path / "S1.cnv.segments.tsv").exists()
    assert (tmp_path / "S1.cnv.segments.tsv").read_text(encoding="utf-8").strip() == "chromosome\tstart\tend\tgene\tlog2\tdepth\tprobes\tweight"
    contract = json.loads((tmp_path / "S1.cnv.ingest.json").read_text(encoding="utf-8"))
    assert contract["stage"] == "cnv"
    assert contract["payload"]["cnv_mode"] == "dev_fallback"
    assert contract["payload"]["segment_count"] == 0


def test_prs_stage_without_curated_panel_exits_unavailable_without_synthetic_output(tmp_path: Path):
    vcf = tmp_path / "S1.vcf"
    vcf.write_text("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\n", encoding="utf-8")

    script = ROOT / "pipelines/nextflow/scripts/run_prs_stage.sh"
    result = subprocess.run(
        [str(script), "S1", str(vcf), "GRCh38_standard", "true"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 127
    assert "curated PRS panel is not configured" in result.stderr
    assert not (tmp_path / "S1.prs_results.txt").exists()
    assert not (tmp_path / "S1.prs.ingest.json").exists()


def test_nextflow_config_exposes_all_pipeline_stages():
    main = (ROOT / "pipelines/nextflow/main.nf").read_text(encoding="utf-8")
    config = (ROOT / "pipelines/nextflow/nextflow.config").read_text(encoding="utf-8")
    # Processes
    assert "TAXONOMY_CLASSIFICATION" in main
    assert "MTDNA_ANALYSIS" in main
    assert "SV_CALLING" in main
    assert "CNV_CALLING" in main
    assert "PRS_SCORING" in main
    # Scripts
    assert "run_taxonomy_stage.sh" in main
    assert "run_mtdna_stage.sh" in main
    assert "run_sv_calling_stage.sh" in main
    assert "run_cnv_calling_stage.sh" in main
    assert "run_prs_stage.sh" in main
    assert "UNKNOWN_READS_ANALYSIS_FROM_ALIGNMENT" in main
    assert "run_unknown_reads_stage.sh" in main
    # Profiles
    assert "full_pipeline" in config
    assert "taxonomy" in config
    assert "unknown_reads" in config
    assert "mtdna" in config
