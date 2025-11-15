FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y wget bzip2 python3

# Download SPAdes release tarball
RUN wget https://github.com/ablab/spades/releases/download/v3.15.5/SPAdes-3.15.5-Linux.tar.gz -O /tmp/spades.tar.gz && \
    tar -xzf /tmp/spades.tar.gz -C /opt && \
    ln -s /opt/SPAdes-3.15.5-Linux/bin/spades.py /usr/local/bin/spades.py

ENTRYPOINT ["spades.py"]
