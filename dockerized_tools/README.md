# Dockerized Tools

This folder contains the Docker build contexts and wrapper scripts for each bioinformatics tool that CASSIE can execute.

## Current Layout

- `fastqc/`, `genomescope2/`, `quast/`, `spades/`, `metaspades/`, `hifiasm/`, `verkko/`, `liftoff/`, `cat/`, `busco/`, `merqury/`: Docker build contexts.
- `buildtools.sh`: builds the tool images used by the emulator.
- `runfastqc.sh`, `rungenomescope2.sh`, `runquast.sh`, `runspades.sh`: wrapper scripts called by Nextflow and tenant containers.
- `templates/new-tool/`: scaffold files for onboarding a new tool.

## Build All Tool Images

```bash
cd dockerized_tools
bash buildtools.sh
```

## Add A New Tool

1. Copy [`templates/new-tool`](/Users/Eren/Desktop/CASSIE/dockerized_tools/templates/new-tool) to a new folder such as `dockerized_tools/my_tool`.
2. Update the Dockerfile and wrapper script to run the real bioinformatics command.
3. Register the tool in [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py).
4. If the image should be built by the shared helper, add it to [`buildtools.sh`](/Users/Eren/Desktop/CASSIE/dockerized_tools/buildtools.sh).
5. If you want a Kubernetes example job, adapt [`kubernetes/templates/tool-job-template.yaml`](/Users/Eren/Desktop/CASSIE/kubernetes/templates/tool-job-template.yaml).

## Wrapper Script Guidance

Wrapper scripts should:

- accept clear positional inputs and an output directory
- validate that input files exist before running the container
- create or clean the output directory explicitly
- print actionable logs to stdout/stderr
- exit non-zero when the tool fails

Keeping those rules consistent makes the emulator, backend logs, and Kubernetes debugging much easier to manage.
