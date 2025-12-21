FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Use bash for RUN
SHELL ["/bin/bash", "-c"]

# ----------------------------------------------------
# System packages: R, git, jellyfish, **Python 3**
# ----------------------------------------------------
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    r-base \
    r-base-dev \
    git \
    curl \
    ca-certificates \
    jellyfish \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Hint for findpython: where Python 3 lives
ENV PYTHON3=/usr/bin/python3
ENV PYTHON=/usr/bin/python3

# ----------------------------------------------------
# R dependencies required by GenomeScope2
# ----------------------------------------------------
RUN R -e "install.packages(c('argparse','minpack.lm'), repos='https://cloud.r-project.org')"

# ----------------------------------------------------
# Install GenomeScope2 from GitHub
# ----------------------------------------------------
RUN git clone --depth 1 https://github.com/tbenavi1/genomescope2.0.git /opt/genomescope2.0 \
 && cd /opt/genomescope2.0 \
 && Rscript install.R

WORKDIR /data