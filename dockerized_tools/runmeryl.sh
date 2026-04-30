#!/bin/bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: runmeryl <out_dir> <reads1.fastq> [reads2.fastq ...]"
  exit 1
fi

OUT_DIR="$1"
shift

KMER_SIZE="${MERYL_KMER_SIZE:-21}"
THREADS="${MERYL_THREADS:-1}"
DB_DIR="${OUT_DIR}/reads.meryl"
ARCHIVE_PATH="${OUT_DIR}/reads.meryl.tar.gz"
TMP_DIR="${OUT_DIR}/tmp_reads"

mkdir -p "${OUT_DIR}" "${TMP_DIR}"
rm -rf "${DB_DIR}"

READ_ARGS=()
for read_path in "$@"; do
  base_name="$(basename "${read_path}")"
  lower_name="$(printf '%s' "${base_name}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${lower_name}" == *.gz ]]; then
    staged_path="${TMP_DIR}/${base_name%.gz}"
    gzip -dc "${read_path}" > "${staged_path}"
    READ_ARGS+=("${staged_path}")
  else
    READ_ARGS+=("${read_path}")
  fi
done

meryl count k="${KMER_SIZE}" threads="${THREADS}" output "${DB_DIR}" "${READ_ARGS[@]}"
tar -czf "${ARCHIVE_PATH}" -C "${OUT_DIR}" "$(basename "${DB_DIR}")"
