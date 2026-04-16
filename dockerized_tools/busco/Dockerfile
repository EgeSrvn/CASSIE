FROM mambaorg/micromamba:2.0.5

ARG BUSCO_DEFAULT_LINEAGE=eukaryota_odb12

USER root
RUN micromamba install -y -n base -c conda-forge -c bioconda \
    bash \
    busco \
    && micromamba clean --all --yes

RUN mkdir -p /opt/busco_downloads \
    && micromamba run -n base busco --download_path /opt/busco_downloads --download "${BUSCO_DEFAULT_LINEAGE}"

SHELL ["/bin/bash", "-lc"]
WORKDIR /work
