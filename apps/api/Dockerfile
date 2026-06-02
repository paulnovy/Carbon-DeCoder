# syntax=docker/dockerfile:1

FROM python:3.12-slim AS kraken2-builder

ARG KRAKEN2_REPO=https://github.com/DerrickWood/kraken2.git

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git make g++ perl zlib1g-dev libbz2-dev liblzma-dev && \
    git clone --depth 1 "$KRAKEN2_REPO" /tmp/kraken2 && \
    cd /tmp/kraken2 && ./install_kraken2.sh /opt/kraken2 && \
    rm -rf /tmp/kraken2 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

FROM python:3.12-slim

ARG BWA_MEM2_VERSION=2.2.1
ARG MOSDEPTH_VERSION=0.3.8
ARG DELLY_VERSION=1.2.6
ARG MANTA_VERSION=1.6.0
ARG GATK_VERSION=4.6.2.0

ENV PATH="/opt/kraken2:/opt/gatk-${GATK_VERSION}:/opt/manta-${MANTA_VERSION}.centos6_x86_64/bin:${PATH}"

WORKDIR /app

# Runtime system dependencies only. Build dependencies stay in kraken2-builder.
RUN apt-get update && apt-get install -y --no-install-recommends \
    samtools bcftools bwa minimap2 wget bzip2 ca-certificates libhts3 curl unzip \
    default-jre-headless openssh-server perl libgomp1 && \
    mkdir -p /run/sshd && \
    echo 'Port 2222' >> /etc/ssh/sshd_config && \
    echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config && \
    echo 'PubkeyAuthentication yes' >> /etc/ssh/sshd_config && \
    echo 'PermitRootLogin no' >> /etc/ssh/sshd_config && \
    useradd -m -s /bin/bash wgs && \
    mkdir -p /home/wgs/.ssh && \
    chmod 700 /home/wgs/.ssh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python dependencies: cached unless pyproject/dependency pins change.
COPY pyproject.toml /app/
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.9.2 \
    python-multipart>=0.0.9 \
    sqlalchemy>=2.0 \
    alembic \
    psycopg2-binary \
    greenlet \
    "pyarrow>=16.1,<18" \
    cnvkit

# Kraken2 built in a separate stage so compiler/git/build deps are not in final image.
COPY --from=kraken2-builder /opt/kraken2/ /opt/kraken2/
RUN ln -sf /opt/kraken2/kraken2 /usr/local/bin/kraken2 && \
    ln -sf /opt/kraken2/kraken2-build /usr/local/bin/kraken2-build && \
    ln -sf /opt/kraken2/kraken2-inspect /usr/local/bin/kraken2-inspect

# BWA-MEM2: one stable cached layer.
RUN wget -qO /tmp/bwa-mem2.tar.bz2 \
      "https://github.com/bwa-mem2/bwa-mem2/releases/download/v${BWA_MEM2_VERSION}/bwa-mem2-${BWA_MEM2_VERSION}_x64-linux.tar.bz2" && \
    tar xjf /tmp/bwa-mem2.tar.bz2 -C /tmp/ && \
    cp /tmp/bwa-mem2-${BWA_MEM2_VERSION}_x64-linux/bwa-mem2 /usr/local/bin/ && \
    (cp /tmp/bwa-mem2-${BWA_MEM2_VERSION}_x64-linux/bwa-mem2.avx2 /usr/local/bin/ 2>/dev/null || true) && \
    (cp /tmp/bwa-mem2-${BWA_MEM2_VERSION}_x64-linux/bwa-mem2.sse41 /usr/local/bin/ 2>/dev/null || true) && \
    (cp /tmp/bwa-mem2-${BWA_MEM2_VERSION}_x64-linux/bwa-mem2.sse42 /usr/local/bin/ 2>/dev/null || true) && \
    rm -rf /tmp/bwa-mem2*

# Small static/single-binary tools: stable cached layer.
RUN wget -qO /usr/local/bin/mosdepth \
      "https://github.com/brentp/mosdepth/releases/download/v${MOSDEPTH_VERSION}/mosdepth" && \
    chmod +x /usr/local/bin/mosdepth && \
    wget -qO /usr/local/bin/delly \
      "https://github.com/dellytools/delly/releases/download/v${DELLY_VERSION}/delly_v${DELLY_VERSION}_linux_x86_64bit" && \
    chmod +x /usr/local/bin/delly

# Manta: stable cached layer.
RUN wget -qO /tmp/manta.tar.bz2 \
      "https://github.com/Illumina/manta/releases/download/v${MANTA_VERSION}/manta-${MANTA_VERSION}.centos6_x86_64.tar.bz2" && \
    tar xjf /tmp/manta.tar.bz2 -C /opt/ && \
    ln -sf /opt/manta-${MANTA_VERSION}.centos6_x86_64/bin/configManta.py /usr/local/bin/configManta.py && \
    ln -sf /opt/manta-${MANTA_VERSION}.centos6_x86_64/bin/RunWorkflow.py /usr/local/bin/RunWorkflow.py && \
    rm -f /tmp/manta.tar.bz2

# GATK: stable cached layer. Large, but downloaded once unless GATK_VERSION changes.
RUN wget -qO /tmp/gatk.zip \
      "https://github.com/broadinstitute/gatk/releases/download/${GATK_VERSION}/gatk-${GATK_VERSION}.zip" && \
    unzip -q /tmp/gatk.zip -d /opt/ && \
    ln -sf /opt/gatk-${GATK_VERSION}/gatk /usr/local/bin/gatk && \
    rm -f /tmp/gatk.zip

# PharmCAT: PGx diplotype→phenotype engine (Java JAR, installed at build time).
# Runtime install endpoint also available as fallback.
RUN mkdir -p /opt/pharmcat && \
    PHARMCAT_URL=$(curl -s https://api.github.com/repos/pharmcat/pharmcat/releases/latest | python3 -c "import sys,json; assets=json.load(sys.stdin).get('assets',[]); print(next((a['browser_download_url'] for a in assets if a['name'].endswith('.jar') and 'pharmcat' in a['name'].lower()),''))") && \
    if [ -n "$PHARMCAT_URL" ]; then wget -qO /opt/pharmcat/pharmcat.jar "$PHARMCAT_URL"; else echo 'WARN: PharmCAT release not found, install later via API'; fi

# HaploGrep3: mtDNA haplogroup classifier (Java JAR, installed at build time).
RUN mkdir -p /opt/haplogrep && \
    HAPLOGREP_URL=$(curl -s https://api.github.com/repos/genepi/haplogrep3/releases/latest | python3 -c "import sys,json; assets=json.load(sys.stdin).get('assets',[]); print(next((a['browser_download_url'] for a in assets if a['name'].endswith('.jar')),''))") && \
    if [ -n "$HAPLOGREP_URL" ]; then wget -qO /opt/haplogrep/haplogrep.jar "$HAPLOGREP_URL"; else echo 'WARN: HaploGrep release not found, install later via API'; fi

# Non-blocking sanity output. Runtime profile endpoint is the real source of truth.
RUN samtools --version | head -1 && \
    bcftools --version | head -1 && \
    (minimap2 --version 2>/dev/null || echo "WARN: minimap2 not found") && \
    bwa-mem2 version 2>&1 | head -1 && \
    mosdepth --version && \
    echo "--- optional tools ---" && \
    (cnvkit.py --version 2>/dev/null || cnvkit --version 2>/dev/null || echo "WARN: cnvkit not found") && \
    (kraken2 --version 2>/dev/null || echo "WARN: kraken2 not found") && \
    (delly --version 2>/dev/null || echo "WARN: delly not found") && \
    (configManta.py --version 2>/dev/null || echo "WARN: manta not found") && \
    (gatk --version 2>/dev/null || echo "WARN: gatk not found")

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && sed -i 's/\r$//' /entrypoint.sh

COPY app /app/app

EXPOSE 8000 2222
CMD ["/entrypoint.sh"]
