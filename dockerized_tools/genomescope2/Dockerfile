FROM ubuntu:22.04

RUN apt-get update && \
    apt-get install -y git r-base wget build-essential zlib1g-dev jellyfish

# Install devtools to install genomescope2.0
RUN R -e 'install.packages("devtools", repos="https://cloud.r-project.org")'

# Install GenomeScope2.0 from GitHub
RUN R -e 'devtools::install_github("tbenavi1/genomescope2.0")'

# Wrapper script
COPY run_genomescope.sh /usr/local/bin/run_genomescope.sh
RUN chmod +x /usr/local/bin/run_genomescope.sh

ENTRYPOINT ["run_genomescope.sh"]
