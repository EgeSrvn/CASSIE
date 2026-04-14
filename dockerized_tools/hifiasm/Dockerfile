FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    git \
    gawk \
    make \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/chhylp123/hifiasm.git /opt/hifiasm \
    && make -C /opt/hifiasm \
    && ln -sf /opt/hifiasm/hifiasm /usr/local/bin/hifiasm

WORKDIR /work
