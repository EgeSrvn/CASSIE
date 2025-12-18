FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Core dependencies for QUAST
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    git \
    perl \
    wget \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Make sure "python" exists for scripts that use #!/usr/bin/env python
RUN ln -s "$(command -v python3)" /usr/local/bin/python || true

# Install QUAST from GitHub
RUN git clone https://github.com/ablab/quast.git /opt/quast && \
    cd /opt/quast && \
    ./setup.py install

# Ensure quast.py is on PATH (setup.py usually does this, but this is safe)
ENV PATH="/opt/quast:$PATH"

WORKDIR /data

# Make the container behave like the FastQC one: run QUAST by default
ENTRYPOINT ["quast.py"]
