FROM mambaorg/micromamba:2.0.5

USER root
RUN micromamba install -y -n base -c conda-forge -c bioconda \
    bash \
    python=3.10 \
    verkko=1.4.1 \
    'snakemake<8' \
    && micromamba clean --all --yes

RUN mv /opt/conda/bin/snakemake /opt/conda/bin/snakemake-real \
    && printf '%s\n' \
    '#!/usr/bin/env bash' \
    'set -euo pipefail' \
    '' \
    'args=()' \
    'for arg in "$@"; do' \
    '  case "$arg" in' \
    '    --reason)' \
    '      ;;' \
    '    *)' \
    '      args+=("$arg")' \
    '      ;;' \
    '  esac' \
    'done' \
    '' \
    'exec /opt/conda/bin/snakemake-real "${args[@]}"' \
    > /opt/conda/bin/snakemake \
    && chmod +x /opt/conda/bin/snakemake

RUN printf '%s\n' \
    'rule all:' \
    '    shell: "true"' \
    > /tmp/Snakefile \
    && snakemake --version | grep -E '^7\.' \
    && snakemake --snakefile /tmp/Snakefile --cores 1 --reason --dry-run \
    && rm -f /tmp/Snakefile

SHELL ["/bin/bash", "-lc"]
WORKDIR /work
