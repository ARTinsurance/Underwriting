#!/usr/bin/env bash
set -euo pipefail

python -m marine_uw_agent.run \
  --quotation-reference "${1:?quotation reference required}" \
  --template-workbook "${TEMPLATE_WORKBOOK_PATH:-./input/UW Review - HK.xlsx}" \
  --output-dir "${OUTPUT_DIR:-./output}" \
  --as-of-date "${AS_OF_DATE:-$(date +%F)}" \
  --headful true
