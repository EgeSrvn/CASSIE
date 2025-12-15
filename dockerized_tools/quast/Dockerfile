FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    r-base \
    jellyfish \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN R -e "install.packages('genomescope2', repos='https://cloud.r-project.org')"

WORKDIR /data
