# Licences

Carbon DeCoder is licensed under the GNU Affero General Public License version 3 or later (`AGPL-3.0-or-later`). See `LICENSE`.

This file records third-party components that the application directly depends on, installs into its Docker images, invokes from the backend or pipeline, or documents as supported runtime backends. Those components remain under their own licences. This notice is informational and not legal advice; when redistributing binaries, container images, reference data, or generated bundles, keep the upstream notices required by each component.

## Application Code

| Component | Use | Licence |
| --- | --- | --- |
| Carbon DeCoder application code | API, frontend, scripts, schemas, and pipeline glue in this repository | AGPL-3.0-or-later |

## Python Backend Dependencies

| Component | Use | Licence / upstream notice |
| --- | --- | --- |
| FastAPI | API framework | MIT, https://github.com/fastapi/fastapi/blob/master/LICENSE |
| Uvicorn | ASGI server | BSD-3-Clause, https://github.com/Kludex/uvicorn/blob/main/LICENSE.md |
| Pydantic | API/data validation models | MIT, https://github.com/pydantic/pydantic/blob/main/LICENSE |
| python-multipart | Multipart/form upload parsing | Apache-2.0, https://github.com/Kludex/python-multipart/blob/main/LICENSE.txt |
| SQLAlchemy | Database ORM/core | MIT, https://github.com/sqlalchemy/sqlalchemy/blob/main/LICENSE |
| Alembic | Database migrations | MIT, https://github.com/sqlalchemy/alembic/blob/main/LICENSE |
| psycopg2-binary | PostgreSQL driver | psycopg2 upstream licence notice, https://github.com/psycopg/psycopg2/blob/master/LICENSE |
| greenlet | SQLAlchemy support dependency | greenlet upstream licence notice, https://github.com/python-greenlet/greenlet/blob/master/LICENSE |
| Apache Arrow / pyarrow | Columnar data and Parquet support | Apache-2.0, https://github.com/apache/arrow/blob/main/LICENSE.txt |
| CNVkit | CNV analysis backend, installed in the API image | CNVkit upstream licence notice, https://github.com/etal/cnvkit/blob/master/LICENSE |
| pytest | Development and test dependency | MIT, https://github.com/pytest-dev/pytest/blob/main/LICENSE |

## Frontend Dependencies

| Component | Use | Licence / upstream notice |
| --- | --- | --- |
| Next.js | Frontend framework | MIT, https://github.com/vercel/next.js/blob/canary/license.md |
| React | UI runtime | MIT, https://github.com/facebook/react/blob/main/LICENSE |
| React DOM | Browser rendering runtime | MIT, https://github.com/facebook/react/blob/main/LICENSE |
| igv.js | Genome browser | MIT, https://github.com/igvteam/igv.js/blob/master/LICENSE |
| Tailwind CSS | CSS utility framework | MIT, https://github.com/tailwindlabs/tailwindcss/blob/main/LICENSE |
| PostCSS | CSS processing | MIT, https://github.com/postcss/postcss/blob/main/LICENSE |

The frontend lockfile also contains transitive packages under MIT, Apache-2.0, BSD-family, ISC, MPL-2.0, LGPL-3.0-or-later, CC-BY-4.0, and combined notices. Use `apps/frontend/package-lock.json` as the package-level source for the exact installed graph.

## Runtime Services And Base Images

| Component | Use | Licence / upstream notice |
| --- | --- | --- |
| Python official image (`python:3.12-slim`) | API and reference-manager base image | Python image contents include Python Software Foundation and Debian package notices; preserve image/package notices when redistributing images |
| Node official image (`node:20.15.1-alpine`) | Frontend base image | Node.js and Alpine package notices apply; preserve image/package notices when redistributing images |
| PostgreSQL (`postgres:16.3-alpine`) | Metadata database | PostgreSQL Licence, https://github.com/postgres/postgres/blob/master/COPYRIGHT |
| Redis (`redis:7.2.5-alpine`) | Optional worker queue | Redis upstream licence notice, https://github.com/redis/redis/blob/unstable/LICENSE.txt |
| MinIO (`minio/minio`) | Object storage service | AGPL-3.0, https://github.com/minio/minio/blob/master/LICENSE |
| Nextflow (`nextflow/nextflow:24.10.0`) | Pipeline runner | Apache-2.0, https://github.com/nextflow-io/nextflow/blob/master/COPYING |

Container images include operating-system packages and transitive packages that are not copied into this repository. Keep the notices from the image distributor and installed package manager metadata when publishing derived images.

## Bioinformatics Backends And Pipeline Tools

| Component | Use | Licence / upstream notice |
| --- | --- | --- |
| bwa | Alignment backend | GPL-3.0, https://github.com/lh3/bwa/blob/master/COPYING |
| bwa-mem2 | Alignment backend | bwa-mem2 upstream licence notice, https://github.com/bwa-mem2/bwa-mem2/blob/master/LICENSE |
| minimap2 | Alignment backend | minimap2 upstream licence notice, https://github.com/lh3/minimap2/blob/master/LICENSE.txt |
| samtools | BAM/SAM processing | samtools upstream licence notice, https://github.com/samtools/samtools/blob/develop/LICENSE |
| htslib | HTS file support used by samtools/bcftools and related tools | htslib upstream licence notice, https://github.com/samtools/htslib/blob/develop/LICENSE |
| bcftools | SNV/indel calling, VCF normalization, and annotation helpers | bcftools upstream licence notice, https://github.com/samtools/bcftools/blob/develop/LICENSE |
| mosdepth | Coverage backend | MIT, https://github.com/brentp/mosdepth/blob/master/LICENSE |
| Kraken2 | Taxonomy backend | MIT, https://github.com/DerrickWood/kraken2/blob/master/LICENSE |
| Bracken | Optional abundance estimation from Kraken reports | Check the Bracken upstream notice before enabling or redistributing Bracken binaries/databases |
| FastQC | Optional read QC stage | GPL-3.0, https://github.com/s-andrews/FastQC/blob/master/LICENSE |
| fastp | Optional read trimming/QC stage | MIT, https://github.com/OpenGene/fastp/blob/master/LICENSE |
| MultiQC | Optional report aggregation stage | GPL-3.0, https://github.com/MultiQC/MultiQC/blob/main/LICENSE |
| GATK | Optional variant/mtDNA backend | GATK upstream licence notice, https://github.com/broadinstitute/gatk/blob/master/LICENSE.TXT |
| DeepVariant | Optional variant backend | BSD-3-Clause, https://github.com/google/deepvariant/blob/r1.10/LICENSE |
| Manta | Structural variant backend | Manta upstream licence notice, https://github.com/Illumina/manta/blob/master/LICENSE.txt |
| Delly | Structural variant backend | BSD-3-Clause, https://github.com/dellytools/delly/blob/main/LICENSE |
| CNVkit | CNV backend | CNVkit upstream licence notice, https://github.com/etal/cnvkit/blob/master/LICENSE |
| PharmCAT | Optional PGx backend | MPL-2.0, https://github.com/PharmGKB/PharmCAT/blob/development/LICENSE |
| HaploGrep3 | Optional mtDNA haplogroup backend | MIT, https://github.com/genepi/haplogrep3/blob/main/LICENSE |
| pgsc_calc | Optional PRS backend | Check the pgsc_calc upstream notice before enabling or redistributing binaries/images |

## Reference Data And Knowledge Bases

Reference datasets and knowledge bases are not relicensed by Carbon DeCoder. Their own terms govern download, redistribution, citation, and clinical/research use.

| Resource | Use | Notice |
| --- | --- | --- |
| ClinVar | Variant interpretation annotations and Fast ClinVar Screening targets | Use and cite according to NCBI ClinVar terms and documentation |
| NCBI taxonomy / Kraken2 databases | Taxonomic classification | Database contents come from upstream sources with their own attribution and redistribution terms |
| GIAB / NIST resources | Benchmark masks and confidence regions | Use and cite according to GIAB/NIST terms |
| PGS Catalog / PRS resources | Polygenic score catalog and scoring data | Use and cite according to PGS Catalog and score-specific terms |
| Reference genomes (`GRCh38`, `GRCh37`, `T2T-CHM13`, `rCRS`) | Alignment and analysis references | Use the terms attached to the specific downloaded reference package |

## Practical Redistribution Notes

- Do not remove upstream licence files from bundled third-party binaries or derived container images.
- If publishing container images, include or preserve package-manager licence metadata and image-layer notices.
- If bundling databases or references, include their source, version, citation, and redistribution terms next to the data.
- AGPL-3.0-or-later applies to Carbon DeCoder's own application code and network service modifications, not to independently licensed third-party components.
