FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Core dependencies
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    perl \
    openjdk-11-jre-headless \
    unzip \
    wget \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install FastQC 0.12.1
RUN wget -q https://www.bioinformatics.babraham.ac.uk/projects/fastqc/fastqc_v0.12.1.zip -O /tmp/fastqc.zip \
 && unzip -q /tmp/fastqc.zip -d /opt \
 && chmod +x /opt/FastQC/fastqc \
 && ln -sf /opt/FastQC/fastqc /usr/local/bin/fastqc \
 && rm -f /tmp/fastqc.zip

ENTRYPOINT ["fastqc"]
