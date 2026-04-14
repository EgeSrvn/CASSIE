FROM mambaorg/micromamba:2.0.5

USER root
RUN micromamba install -y -n base -c conda-forge -c bioconda \
    bash \
    luigi \
    comparative-annotation-toolkit \
    && micromamba clean --all --yes

SHELL ["/bin/bash", "-lc"]
WORKDIR /work
