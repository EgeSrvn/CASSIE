#!/bin/bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: runtool <input> <output_dir> [extra args...]"
  exit 1
fi

INPUT_PATH="$1"
OUTPUT_DIR="$2"
shift 2

if [ ! -e "$INPUT_PATH" ]; then
  echo "Error: input path not found: $INPUT_PATH"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "[runtool] Input: $INPUT_PATH"
echo "[runtool] Output: $OUTPUT_DIR"

# Replace the placeholder command below with the real tool invocation.
# Example:
# my-tool --input "$INPUT_PATH" --output "$OUTPUT_DIR" "$@"

echo "Replace the placeholder command in dockerized_tools/templates/new-tool/runtool.sh"
exit 1
