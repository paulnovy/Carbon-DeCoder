nextflow.enable.dsl=2

params.input = params.input ?: 'fastq/*_{R1,R2}*.fastq.gz'
params.outdir = params.outdir ?: 'results/qc'
params.enable_fastp = params.enable_fastp ?: false
params.fastqc_threads = params.fastqc_threads ?: 2
params.fastp_threads = params.fastp_threads ?: 2
params.enable_alignment = params.enable_alignment ?: false
params.enable_coverage = params.enable_coverage ?: false
params.reference_fasta = params.reference_fasta ?: 'references/GRCh38.fa'
params.coverage_tile_level = params.coverage_tile_level ?: '1mb'
params.enable_vendor_validation = params.enable_vendor_validation ?: false
params.alignment_threads = params.alignment_threads ?: 2
params.coverage_threads = params.coverage_threads ?: 2
params.coverage_window_size = params.coverage_window_size ?: 1000000
params.allow_dev_fallback = params.allow_dev_fallback ?: true
params.enable_variant_calling = params.enable_variant_calling ?: false
params.variant_caller = params.variant_caller ?: 'bcftools'  // bcftools | gatk | deepvariant
params.variant_calling_threads = params.variant_calling_threads ?: 2
params.deepvariant_model = params.deepvariant_model ?: 'WGS'  // WGS | WES | PACBIO
params.enable_variant_normalization = params.enable_variant_normalization ?: false
params.variant_vcf = params.variant_vcf ?: null
params.variant_sample_id = params.variant_sample_id ?: params.run_id
params.enable_taxonomy = params.enable_taxonomy ?: false
params.enable_unknown_reads = params.enable_unknown_reads ?: false
params.taxonomy_threads = params.taxonomy_threads ?: 2
params.kraken2_db = params.kraken2_db ?: '/data/databases/kraken2'
params.taxonomy_route = params.taxonomy_route ?: 'human_wgs_host_depleted'
params.taxonomy_low_mapq_threshold = params.taxonomy_low_mapq_threshold ?: 10
params.enable_mtdna = params.enable_mtdna ?: false
params.enable_sv_calling = params.enable_sv_calling ?: false
params.sv_calling_threads = params.sv_calling_threads ?: 2
params.enable_cnv_calling = params.enable_cnv_calling ?: false
params.cnv_calling_threads = params.cnv_calling_threads ?: 2
params.enable_prs = params.enable_prs ?: false
params.vendor_assembly_fasta = params.vendor_assembly_fasta ?: null
params.pipeline_assembly_fasta = params.pipeline_assembly_fasta ?: null
params.enable_pipeline_assembly = params.enable_pipeline_assembly ?: false
params.vendor_validation_method = params.vendor_validation_method ?: 'proxy'
params.vendor_validation_kmer_size = params.vendor_validation_kmer_size ?: 21
params.vendor_validation_pass_threshold = params.vendor_validation_pass_threshold ?: 0.98
params.enable_vendor_validation_ingest_event = params.enable_vendor_validation_ingest_event ?: false
params.enable_vendor_validation_auto_ingest = params.enable_vendor_validation_auto_ingest ?: false
params.api_base_url = params.api_base_url ?: 'http://api:8000'
params.run_id = params.run_id ?: 'run_demo'

workflow {
  reads_ch = Channel.fromFilePairs(params.input, flat: true)
  aligned_ch = Channel.empty()

  pre_fastqc = FASTQC_PRE(reads_ch)
  qc_inputs = pre_fastqc

  if (params.enable_fastp) {
    trimmed = FASTP(reads_ch)
    post_fastqc = FASTQC_POST(trimmed)
    qc_inputs = pre_fastqc.mix(post_fastqc)

    if (params.enable_alignment) {
      aligned_ch = ALIGNMENT_FROM_TRIMMED(trimmed)
    }
  } else if (params.enable_alignment) {
    aligned_ch = ALIGNMENT_FROM_RAW(reads_ch)
  }

  if (params.enable_alignment && params.enable_coverage) {
    COVERAGE_MOSDEPTH(aligned_ch)
  }

  if (params.enable_alignment && params.enable_variant_calling) {
    if (params.variant_caller == 'gatk') {
      GATK_VARIANT_CALLING(aligned_ch)
    } else if (params.variant_caller == 'deepvariant') {
      DEEPVARIANT_CALLING(aligned_ch)
    } else {
      BCFTOOLS_VARIANT_CALLING(aligned_ch)
    }
  }

  if (params.enable_taxonomy) {
    TAXONOMY_CLASSIFICATION(reads_ch)
  }

  if (params.enable_alignment && params.enable_mtdna) {
    MTDNA_ANALYSIS(aligned_ch)
  }

  if (params.enable_alignment && params.enable_sv_calling) {
    SV_CALLING(aligned_ch)
  }

  if (params.enable_alignment && params.enable_cnv_calling) {
    CNV_CALLING(aligned_ch)
  }

  if (params.enable_alignment && params.enable_variant_calling && params.enable_prs) {
    PRS_SCORING(aligned_ch)
  }

  if (params.enable_unknown_reads && params.enable_alignment) {
    UNKNOWN_READS_ANALYSIS_FROM_ALIGNMENT(aligned_ch)
  } else if (params.enable_unknown_reads) {
    UNKNOWN_READS_ANALYSIS(reads_ch)
  }

  if (params.enable_variant_normalization) {
    if (!params.variant_vcf) {
      error "enable_variant_normalization=true requires --variant_vcf"
    }
    variant_input_ch = Channel.of(tuple(params.variant_sample_id, file(params.variant_vcf)))
    VARIANT_NORMALIZATION(variant_input_ch)
  }

  if (params.enable_vendor_validation) {
    if (!params.vendor_assembly_fasta) {
      error "enable_vendor_validation=true requires --vendor_assembly_fasta"
    }

    sample_ids_ch = reads_ch.map { sample_id, reads -> sample_id }
    pipeline_assembly_ch = Channel.empty()

    if (params.pipeline_assembly_fasta) {
      pipeline_assembly_ch = sample_ids_ch.map { sample_id -> tuple(sample_id, file(params.pipeline_assembly_fasta)) }
    } else if (params.enable_pipeline_assembly) {
      pipeline_assembly_ch = PIPELINE_ASSEMBLY_FROM_READS(reads_ch)
    } else {
      error "enable_vendor_validation=true requires either --pipeline_assembly_fasta or --enable_pipeline_assembly=true"
    }

    validation_reports_ch = VENDOR_VALIDATION(pipeline_assembly_ch)

    if (params.enable_vendor_validation_ingest_event) {
      ingest_contracts_ch = VENDOR_VALIDATION_INGEST_EVENT(validation_reports_ch)

      if (params.enable_vendor_validation_auto_ingest) {
        VENDOR_VALIDATION_POST_INGEST(ingest_contracts_ch)
      }
    }
  }

  MULTIQC(qc_inputs)
}

process FASTQC_PRE {
  tag { sample_id }
  publishDir "${params.outdir}/fastqc_pre", mode: 'copy'
  container 'staphb/fastqc:0.12.1'

  input:
    tuple val(sample_id), path(reads)

  output:
    path "${sample_id}_fastqc_pre.txt"

  script:
  """
  if command -v fastqc >/dev/null 2>&1; then
    fastqc -q -t ${params.fastqc_threads} -o . ${reads}
    : > ${sample_id}_fastqc_pre.txt
    for zip in *_fastqc.zip; do
      [ -e "\$zip" ] || continue
      echo "## source_file=\${zip}" >> ${sample_id}_fastqc_pre.txt
      unzip -p "\$zip" "*/fastqc_data.txt" >> ${sample_id}_fastqc_pre.txt
      echo "" >> ${sample_id}_fastqc_pre.txt
    done
    [ -s ${sample_id}_fastqc_pre.txt ] || { echo "status\tfastqc_no_data" > ${sample_id}_fastqc_pre.txt; exit 1; }
  elif [ "${params.allow_dev_fallback}" = "true" ]; then
    {
      echo "status\tfastqc_not_available"
      echo "sample_id\t${sample_id}"
      echo "input_files\t${reads}"
    } > ${sample_id}_fastqc_pre.txt
  else
    echo "FastQC is required when allow_dev_fallback=false" >&2
    exit 127
  fi
  """
}

process FASTP {
  tag { sample_id }
  publishDir "${params.outdir}/fastp", mode: 'copy'
  container 'staphb/fastp:0.24.0'

  input:
    tuple val(sample_id), path(reads)

  output:
    tuple val(sample_id), path("${sample_id}_R1.trimmed.fastq.gz"), path("${sample_id}_R2.trimmed.fastq.gz")

  script:
  """
  if command -v fastp >/dev/null 2>&1; then
    fastp \
      --thread ${params.fastp_threads} \
      --in1 ${reads[0]} \
      --in2 ${reads[1]} \
      --out1 ${sample_id}_R1.trimmed.fastq.gz \
      --out2 ${sample_id}_R2.trimmed.fastq.gz \
      --html ${sample_id}.fastp.html \
      --json ${sample_id}.fastp.json
  elif [ "${params.allow_dev_fallback}" = "true" ]; then
    cp ${reads[0]} ${sample_id}_R1.trimmed.fastq.gz
    cp ${reads[1]} ${sample_id}_R2.trimmed.fastq.gz
  else
    echo "fastp is required when allow_dev_fallback=false" >&2
    exit 127
  fi
  """
}

process FASTQC_POST {
  tag { sample_id }
  publishDir "${params.outdir}/fastqc_post", mode: 'copy'
  container 'staphb/fastqc:0.12.1'

  input:
    tuple val(sample_id), path(r1), path(r2)

  output:
    path "${sample_id}_fastqc_post.txt"

  script:
  """
  if command -v fastqc >/dev/null 2>&1; then
    fastqc -q -t ${params.fastqc_threads} -o . ${r1} ${r2}
    : > ${sample_id}_fastqc_post.txt
    for zip in *_fastqc.zip; do
      [ -e "\$zip" ] || continue
      echo "## source_file=\${zip}" >> ${sample_id}_fastqc_post.txt
      unzip -p "\$zip" "*/fastqc_data.txt" >> ${sample_id}_fastqc_post.txt
      echo "" >> ${sample_id}_fastqc_post.txt
    done
    [ -s ${sample_id}_fastqc_post.txt ] || { echo "status\tfastqc_no_data" > ${sample_id}_fastqc_post.txt; exit 1; }
  elif [ "${params.allow_dev_fallback}" = "true" ]; then
    {
      echo "status\tfastqc_not_available"
      echo "sample_id\t${sample_id}"
      echo "input_files\t${r1} ${r2}"
    } > ${sample_id}_fastqc_post.txt
  else
    echo "FastQC is required when allow_dev_fallback=false" >&2
    exit 127
  fi
  """
}

process MULTIQC {
  publishDir "${params.outdir}/multiqc", mode: 'copy'
  container 'ewels/multiqc:1.21'

  input:
    path qc_inputs

  output:
    path 'multiqc_report.html'
    path 'multiqc_data.json'

  script:
  """
  if command -v multiqc >/dev/null 2>&1; then
    multiqc -q . --filename multiqc_report.html --outdir .
    if [ -f multiqc_data/multiqc_data.json ]; then
      cp multiqc_data/multiqc_data.json multiqc_data.json
    else
      echo '{"status":"available","note":"MultiQC completed but no data JSON was emitted"}' > multiqc_data.json
    fi
  elif [ "${params.allow_dev_fallback}" = "true" ]; then
    cat > multiqc_report.html <<'HTML'
<html><body><h1>MultiQC not available</h1><p>Install MultiQC or run with a container profile to generate the aggregate QC report.</p></body></html>
HTML
    cat > multiqc_data.json <<'JSON'
{"status":"tool_missing","tool":"multiqc","note":"No synthetic MultiQC metrics were generated"}
JSON
  else
    echo "MultiQC is required when allow_dev_fallback=false" >&2
    exit 127
  fi
  """
}

process ALIGNMENT_FROM_RAW {
  tag { sample_id }
  publishDir "${params.outdir}/alignment", mode: 'copy'
  container 'biocontainers/bwa-mem2:v2.2.1_cv1'

  input:
    tuple val(sample_id), path(reads)

  output:
    tuple val(sample_id), path("${sample_id}.sorted.markdup.bam"), path("${sample_id}.sorted.markdup.bam.bai"), path("${sample_id}.flagstat.txt"), path("${sample_id}.idxstats.txt"), path("${sample_id}.alignment.ingest.json")

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_alignment_stage.sh \
    ${sample_id} \
    ${params.reference_fasta} \
    ${reads[0]} \
    ${reads[1]} \
    ${params.alignment_threads} \
    ${params.allow_dev_fallback}
  """
}

process ALIGNMENT_FROM_TRIMMED {
  tag { sample_id }
  publishDir "${params.outdir}/alignment", mode: 'copy'
  container 'biocontainers/bwa-mem2:v2.2.1_cv1'

  input:
    tuple val(sample_id), path(r1), path(r2)

  output:
    tuple val(sample_id), path("${sample_id}.sorted.markdup.bam"), path("${sample_id}.sorted.markdup.bam.bai"), path("${sample_id}.flagstat.txt"), path("${sample_id}.idxstats.txt"), path("${sample_id}.alignment.ingest.json")

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_alignment_stage.sh \
    ${sample_id} \
    ${params.reference_fasta} \
    ${r1} \
    ${r2} \
    ${params.alignment_threads} \
    ${params.allow_dev_fallback}
  """
}

process COVERAGE_MOSDEPTH {
  tag { sample_id }
  publishDir "${params.outdir}/coverage", mode: 'copy'
  container 'biocontainers/mosdepth:0.3.11--hdfd78af_0'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.mosdepth.summary.txt"
    path "${sample_id}.regions.bed.gz"
    path "${sample_id}.coverage.tiles.${params.coverage_tile_level}.json"
    path "${sample_id}.coverage.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_coverage_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.coverage_threads} \
    ${params.coverage_window_size} \
    ${params.coverage_tile_level} \
    ${params.allow_dev_fallback}
  """
}

process BCFTOOLS_VARIANT_CALLING {
  tag { sample_id }
  publishDir "${params.outdir}/variants", mode: 'copy'
  container 'biocontainers/bcftools:v1.16-1-deb_cv1'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.bcftools.raw.vcf"
    path "${sample_id}.bcftools.raw.vcf.gz"
    path "${sample_id}.bcftools.raw.vcf.gz.tbi"
    path "${sample_id}.bcftools.stats.txt"
    path "${sample_id}.variants.bcftools.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_bcftools_variant_calling_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.variant_calling_threads} \
    ${params.allow_dev_fallback}
  """
}

process GATK_VARIANT_CALLING {
  tag { sample_id }
  publishDir "${params.outdir}/variants", mode: 'copy'
  container 'broadinstitute/gatk:4.6.1.0'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.gatk.hc.raw.vcf"
    path "${sample_id}.gatk.hc.raw.vcf.gz"
    path "${sample_id}.gatk.hc.raw.vcf.gz.tbi"
    path "${sample_id}.gatk.stats.txt"
    path "${sample_id}.variants.gatk.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_gatk_variant_calling_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.variant_calling_threads} \
    ${params.allow_dev_fallback}
  """
}

process DEEPVARIANT_CALLING {
  tag { sample_id }
  publishDir "${params.outdir}/variants", mode: 'copy'
  container 'google/deepvariant:1.8.0'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.deepvariant.raw.vcf"
    path "${sample_id}.deepvariant.raw.vcf.gz"
    path "${sample_id}.deepvariant.raw.vcf.gz.tbi"
    path "${sample_id}.deepvariant.stats.txt"
    path "${sample_id}.variants.deepvariant.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_deepvariant_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.variant_calling_threads} \
    ${params.allow_dev_fallback} \
    ${params.deepvariant_model}
  """
}

process TAXONOMY_CLASSIFICATION {
  tag { sample_id }
  publishDir "${params.outdir}/taxonomy", mode: 'copy'
  container 'staphb/kraken2:2.1.3'

  input:
    tuple val(sample_id), path(reads)

  output:
    path "${sample_id}.kraken2.report"
    path "${sample_id}.bracken.tsv"
    path "${sample_id}.taxonomy.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_taxonomy_stage.sh \
    ${sample_id} \
    ${reads[0]} \
    ${reads[1]} \
    ${params.taxonomy_threads} \
    ${params.allow_dev_fallback} \
    ${params.kraken2_db} \
    "" \
    ${params.taxonomy_route} \
    ${params.taxonomy_low_mapq_threshold}
  """
}

process UNKNOWN_READS_ANALYSIS {
  tag { sample_id }
  publishDir "${params.outdir}/unknown_reads", mode: 'copy'
  container 'wgs-cockpit-api:0.8.7'

  input:
    tuple val(sample_id), path(reads)

  output:
    path "${sample_id}.unknown_reads.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_unknown_reads_stage.sh \
    ${sample_id} \
    ${reads[0]} \
    ${reads[1]} \
    ${params.taxonomy_threads} \
    ${params.allow_dev_fallback} \
    ${params.kraken2_db}
  """
}

process UNKNOWN_READS_ANALYSIS_FROM_ALIGNMENT {
  tag { sample_id }
  publishDir "${params.outdir}/unknown_reads", mode: 'copy'
  container 'wgs-cockpit-api:0.8.7'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.unknown_reads.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_unknown_reads_stage.sh \
    ${sample_id} \
    "" \
    "" \
    ${params.taxonomy_threads} \
    ${params.allow_dev_fallback} \
    ${params.kraken2_db} \
    ${bam}
  """
}

process MTDNA_ANALYSIS {
  tag { sample_id }
  publishDir "${params.outdir}/mtdna", mode: 'copy'
  container 'broadinstitute/gatk:4.6.1.0'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.mtdna.vcf"
    path "${sample_id}.mtdna.report.json"
    path "${sample_id}.mtdna.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_mtdna_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.alignment_threads} \
    ${params.allow_dev_fallback}
  """
}

process SV_CALLING {
  tag { sample_id }
  publishDir "${params.outdir}/sv", mode: 'copy'
  container 'staphb/manta:1.6.0'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.sv.vcf"
    path "${sample_id}.sv.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_sv_calling_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.sv_calling_threads} \
    ${params.allow_dev_fallback}
  """
}

process CNV_CALLING {
  tag { sample_id }
  publishDir "${params.outdir}/cnv", mode: 'copy'
  container 'etal/cnvkit:0.9.10'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.cnv.segments.tsv"
    path "${sample_id}.cnv.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_cnv_calling_stage.sh \
    ${sample_id} \
    ${bam} \
    ${params.reference_fasta} \
    ${params.cnv_calling_threads} \
    ${params.allow_dev_fallback}
  """
}

process PRS_SCORING {
  tag { sample_id }
  publishDir "${params.outdir}/prs", mode: 'copy'
  container 'python:3.12-slim'

  input:
    tuple val(sample_id), path(bam), path(bai), path(flagstat), path(idxstats), path(alignment_ingest)

  output:
    path "${sample_id}.prs_results.txt"
    path "${sample_id}.prs.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_prs_stage.sh \
    ${sample_id} \
    ${sample_id}.bcftools.raw.vcf \
    ${params.reference_fasta} \
    ${params.allow_dev_fallback}
  """
}

process VARIANT_NORMALIZATION {
  tag { sample_id }
  publishDir "${params.outdir}/variants", mode: 'copy'
  container 'biocontainers/bcftools:v1.16-1-deb_cv1'

  input:
    tuple val(sample_id), path(input_vcf)

  output:
    path "${sample_id}.variants.normalized.vcf"
    path "${sample_id}.variants.normalized.vcf.gz"
    path "${sample_id}.variants.normalized.vcf.gz.tbi"
    path "${sample_id}.variants.ingest.json"

  script:
  """
  ${projectDir}/pipelines/nextflow/scripts/run_variant_normalization_stage.sh \
    ${sample_id} \
    ${input_vcf} \
    ${params.reference_fasta} \
    ${params.allow_dev_fallback}
  """
}

process VENDOR_VALIDATION {
  tag { sample_id }
  publishDir "${params.outdir}/validation", mode: 'copy'
  container 'python:3.12-slim'

  input:
    tuple val(sample_id), path(pipeline_assembly)

  output:
    tuple val(sample_id), path("${sample_id}.vendor_validation.report.json")

  script:
  """
  python ${projectDir}/pipelines/nextflow/scripts/vendor_validation_compare.py \
    --vendor ${params.vendor_assembly_fasta} \
    --pipeline ${pipeline_assembly} \
    --method ${params.vendor_validation_method} \
    --kmer-size ${params.vendor_validation_kmer_size} \
    --pass-threshold ${params.vendor_validation_pass_threshold} \
    --output ${sample_id}.vendor_validation.report.json
  """
}

process PIPELINE_ASSEMBLY_FROM_READS {
  tag { sample_id }
  publishDir "${params.outdir}/assembly", mode: 'copy'
  container 'python:3.12-slim'

  input:
    tuple val(sample_id), path(reads)

  output:
    tuple val(sample_id), path("${sample_id}.pipeline_assembly.fasta")

  script:
  """
  python ${projectDir}/pipelines/nextflow/scripts/fastq_to_fasta_assembly.py \
    --r1 ${reads[0]} \
    --r2 ${reads[1]} \
    --output ${sample_id}.pipeline_assembly.fasta
  """
}

process VENDOR_VALIDATION_INGEST_EVENT {
  tag { sample_id }
  publishDir "${params.outdir}/ingest_events", mode: 'copy'
  container 'python:3.12-slim'

  input:
    tuple val(sample_id), path(report_json)

  output:
    tuple val(sample_id), path("${sample_id}.vendor_validation.ingest.json")

  script:
  """
  python ${projectDir}/pipelines/nextflow/scripts/vendor_validation_to_ingest_event.py \
    --run-id ${params.run_id} \
    --report ${report_json} \
    --output ${sample_id}.vendor_validation.ingest.json
  """
}

process VENDOR_VALIDATION_POST_INGEST {
  tag { sample_id }
  publishDir "${params.outdir}/ingest_results", mode: 'copy'
  container 'python:3.12-slim'

  input:
    tuple val(sample_id), path(contract_json)

  output:
    path "${sample_id}.vendor_validation.ingest.result.json"

  script:
  """
  python ${projectDir}/pipelines/nextflow/scripts/vendor_validation_post_ingest.py \
    --api-base-url ${params.api_base_url} \
    --contract ${contract_json} \
    --output ${sample_id}.vendor_validation.ingest.result.json
  """
}
