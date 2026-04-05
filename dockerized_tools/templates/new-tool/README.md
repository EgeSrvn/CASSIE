# New Tool Template

This scaffold is the fastest way to add a new bioinformatics tool to CASSIE.

## Files

- `Dockerfile`: image build template
- `runtool.sh`: wrapper script template

## Suggested Workflow

1. Copy this folder to `dockerized_tools/<tool-name>`.
2. Rename `runtool.sh` to `run<tool-name>.sh` if you want a tool-specific wrapper.
3. Replace the placeholder command in both files.
4. Add the tool to [`tool_registry.py`](/Users/Eren/Desktop/CASSIE/tool_registry.py).
5. Build and test the image locally before wiring it into Kubernetes or the UI.
