from pathlib import Path

from app.core.variant_parser import parse_variants_vcf


def test_parse_variants_vcf_reads_records(tmp_path: Path):
    p = tmp_path / "variants.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr7\t117199645\t.\tC\tT\t.\tPASS\tCALLERS=HaplotypeCaller,DeepVariant;CALLER_AGREEMENT=0.82;GNOMAD_AF=0.0042;CSQ=missense_variant\n",
        encoding="utf-8",
    )

    items = parse_variants_vcf(p)
    assert len(items) == 1
    assert items[0]["chrom"] == "chr7"
    assert items[0]["variant_type"] == "SNV"
    assert items[0]["caller_agreement_score"] == 0.82
    assert items[0]["gnomad_freq"] == 0.0042


def test_parse_variants_vcf_derives_format_quality_and_explainability(tmp_path: Path):
    p = tmp_path / "deepvariant.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DeepVariant\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "chr1\t12345\trs123\tA\tG\t85\tPASS\tGNOMAD_AF=0.001;CSQ=missense_variant;CLNSIG=Uncertain_significance\tGT:GQ:DP:AD\t0/1:72:41:20,21\n",
        encoding="utf-8",
    )

    items = parse_variants_vcf(p)
    assert len(items) == 1
    item = items[0]
    assert item["caller_list"] == ["DeepVariant"]
    assert item["trust_score"] > 70
    assert item["genotype"] == "0/1"
    assert item["zygosity"] == "heterozygous"
    assert item["explainability"]["depth"] == 41.0
    assert item["explainability"]["genotype_quality"] == 72.0
    assert 0.50 < item["explainability"]["allele_balance"] < 0.52
    assert item["clinical_annotation"] == "Uncertain_significance"
    assert item["gnomad_freq"] == 0.001


def test_parse_variants_vcf_penalizes_filtered_low_quality_records(tmp_path: Path):
    p = tmp_path / "lowq.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=bcftools\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "2\t200\t.\tAT\tA\t12\tLowQual\tDP=4\tGT:GQ:AD\t0/1:5:3,1\n",
        encoding="utf-8",
    )

    items = parse_variants_vcf(p)
    assert len(items) == 1
    item = items[0]
    assert item["variant_type"] == "DEL"
    assert item["caller_list"] == ["bcftools"]
    assert item["trust_score"] < 45
    assert item["explainability"]["filter_pass_score"] == 0.15


def test_parse_variants_vcf_derives_homozygous_alt_zygosity(tmp_path: Path):
    p = tmp_path / "homalt.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "chr3\t333\t.\tG\tA\t90\tPASS\t.\tGT:GQ:DP:AD\t1/1:80:35:0,35\n",
        encoding="utf-8",
    )

    items = parse_variants_vcf(p)
    assert items[0]["genotype"] == "1/1"
    assert items[0]["zygosity"] == "homozygous_alt"
