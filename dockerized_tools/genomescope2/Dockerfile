FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    r-base \
    r-base-dev \
    jellyfish \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN R -e "install.packages('remotes', repos='https://cloud.r-project.org')"

RUN R -e "remotes::install_github('tbenavi1/genomescope2.0')"

WORKDIR /data
