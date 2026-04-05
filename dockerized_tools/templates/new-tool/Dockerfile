FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tool

# Install the real tool here.
# Example:
# RUN curl -L <tool-tarball-url> | tar -xz -C /opt/tool

COPY runtool.sh /usr/local/bin/runtool
RUN chmod +x /usr/local/bin/runtool

ENTRYPOINT ["/usr/local/bin/runtool"]
