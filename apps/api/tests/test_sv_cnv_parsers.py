from pathlib import Path

from app.core.sv_parser import parse_sv_vcf
from app.core.cnv_parser import parse_cnv_segments_tsv, parse_cnv_vcf


def test_parse_sv_vcf_reads_structural_records(tmp_path: Path):
    p = tmp_path / "manta.sv.vcf"
    p.write_text(
        """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO
chr3\t101\t.\tN\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=401;SVLEN=-300;CALLERS=Manta
""",
        encoding="utf-8",
    )

    items = parse_sv_vcf(p)
    assert len(items) == 1
    assert items[0]["chrom"] == "chr3"
    assert items[0]["sv_type"] == "DEL"
    assert items[0]["end"] == 401


def test_parse_sv_vcf_supports_delly_bnd_and_evidence(tmp_path: Path):
    p = tmp_path / "delly.sv.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DELLY\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\t.\tN\tN]chr2:2000]\t.\tPASS\tSVTYPE=BND;CHR2=chr2;PE=14;SR=7\n",
        encoding="utf-8",
    )

    items = parse_sv_vcf(p)
    assert len(items) == 1
    assert items[0]["sv_type"] == "BND"
    assert items[0]["end"] == 2000
    assert "PE" in items[0]["evidence_types"]
    assert "SR" in items[0]["evidence_types"]
    assert items[0]["caller_list"] == ["Delly"]


def test_parse_cnv_segments_tsv_reads_rows(tmp_path: Path):
    p = tmp_path / "cnv.tsv"
    p.write_text(
        "chrom\tstart\tend\tcopy_number\tcnv_type\tmethod\ttrust_score\n"
        "chr8\t1000\t4000\t1.7\tloss\tCNVnator\t71.0\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["chrom"] == "chr8"
    assert items[0]["copy_number"] == 1.7
    assert items[0]["method"] == "CNVnator"


def test_parse_cnv_segments_tsv_supports_gcnv_like_rows(tmp_path: Path):
    p = tmp_path / "gcnv.tsv"
    p.write_text(
        "contig\tstart\tend\tmean_log2_copy_ratio\tcall\n"
        "chr5\t100\t2100\t0.58\tDUP\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["chrom"] == "chr5"
    assert items[0]["method"] == "gCNV"
    assert items[0]["cnv_type"] == "gain"
    assert items[0]["copy_number"] > 2.0


def test_parse_cnv_segments_tsv_supports_cnvnator_event_lines(tmp_path: Path):
    p = tmp_path / "cnvnator.calls.txt"
    p.write_text(
        "deletion\tchr8:1000-2500\t1500\t0.42\t1e-6\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["chrom"] == "chr8"
    assert items[0]["start"] == 1000
    assert items[0]["end"] == 2500
    assert items[0]["method"] == "CNVnator"
    assert items[0]["cnv_type"] == "loss"


def test_parse_sv_vcf_uses_manta_format_evidence_and_trust(tmp_path: Path):
    p = tmp_path / "manta.format.sv.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=Manta\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR\n"
        "chr7\t10000\t.\tN\t<DUP>\t80\tPASS\tSVTYPE=DUP;END=18000;PRECISE\tGT:PR:SR\t0/1:18,9:20,11\n",
        encoding="utf-8",
    )

    items = parse_sv_vcf(p)
    assert len(items) == 1
    item = items[0]
    assert item["sv_type"] == "DUP"
    assert item["size_bp"] == 8000
    assert item["caller_list"] == ["Manta"]
    assert "PE" in item["evidence_types"]
    assert "SR" in item["evidence_types"]
    assert "PRECISE" in item["evidence_types"]
    assert item["trust_score"] > 80


def test_parse_sv_vcf_uses_delly_format_dv_rv_support(tmp_path: Path):
    p = tmp_path / "delly.format.sv.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=DELLY\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "chr12\t2000\t.\tN\t<INV>\t42\tPASS\tSVTYPE=INV;END=6200;IMPRECISE\tGT:DR:DV:RR:RV\t0/1:15:6:20:4\n",
        encoding="utf-8",
    )

    items = parse_sv_vcf(p)
    assert len(items) == 1
    assert items[0]["sv_type"] == "INV"
    assert items[0]["caller_list"] == ["Delly"]
    assert "PE" in items[0]["evidence_types"]
    assert "SR" in items[0]["evidence_types"]
    assert "IMPRECISE" in items[0]["evidence_types"]
    assert 50 <= items[0]["trust_score"] <= 100


def test_parse_cnv_segments_tsv_supports_gatk_modelsegments(tmp_path: Path):
    p = tmp_path / "sample.modelFinal.seg"
    p.write_text(
        "CONTIG\tSTART\tEND\tNUM_POINTS_COPY_RATIO\tMEAN_LOG2_COPY_RATIO\n"
        "chr1\t10000\t22000\t18\t-1.05\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["method"] == "GATK-ModelSegments"
    assert items[0]["cnv_type"] == "loss"
    assert items[0]["copy_number"] < 1.1


def test_parse_cnv_segments_tsv_supports_cnvkit_cns(tmp_path: Path):
    p = tmp_path / "sample.cns"
    p.write_text(
        "chromosome\tstart\tend\tgene\tlog2\tdepth\tprobes\tweight\n"
        "chr2\t5000\t16000\tGENE1\t0.72\t120.5\t42\t1.0\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["method"] == "CNVkit"
    assert items[0]["cnv_type"] == "gain"
    assert items[0]["copy_number"] > 3.0


def test_parse_cnv_segments_tsv_supports_control_freec_ratio_table(tmp_path: Path):
    p = tmp_path / "freec.ratio.txt"
    p.write_text(
        "Chromosome\tStart\tEnd\tRatio\tMedianRatio\tCopy Number\tStatus\n"
        "chr9\t1000\t9000\t0.51\t0.49\t1\tloss\n",
        encoding="utf-8",
    )

    items = parse_cnv_segments_tsv(p)
    assert len(items) == 1
    assert items[0]["method"] == "Control-FREEC"
    assert items[0]["copy_number"] == 1.0
    assert items[0]["cnv_type"] == "loss"


def test_parse_cnv_vcf_supports_gcnv_symbolic_records(tmp_path: Path):
    p = tmp_path / "sample.cnv.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=GATK-gCNV\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "chr4\t10000\t.\tN\t<DEL>\t90\tPASS\tSVTYPE=DEL;END=22000;CNQ=80\tGT:CN:GQ\t0/1:1:72\n"
        "chr5\t30000\t.\tN\t<DUP>\t60\tPASS\tSVTYPE=DUP;END=42000\tGT:CN:GQ\t0/1:3:48\n",
        encoding="utf-8",
    )

    items = parse_cnv_vcf(p)
    assert len(items) == 2
    assert items[0]["method"] == "GATK-gCNV"
    assert items[0]["copy_number"] == 1.0
    assert items[0]["cnv_type"] == "loss"
    assert items[0]["trust_score"] > 80
    assert items[1]["copy_number"] == 3.0
    assert items[1]["cnv_type"] == "gain"


def test_parse_cnv_vcf_skips_non_cnv_records(tmp_path: Path):
    p = tmp_path / "mixed.vcf"
    p.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t10\t.\tA\tT\t50\tPASS\t.\n"
        "chr1\t100\t.\tN\t<CNV>\t40\tPASS\tSVTYPE=CNV;END=500;CN=4\n",
        encoding="utf-8",
    )

    items = parse_cnv_vcf(p)
    assert len(items) == 1
    assert items[0]["cnv_type"] == "gain"
    assert items[0]["copy_number"] == 4.0
