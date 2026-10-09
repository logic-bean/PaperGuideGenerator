#!/bin/bash
# Wait for the enrichment job to finish, then re-render the guide and validate it.
# Both processes are independent: enrichment writes _batches/llm_enrich.json, the
# renderer merges it at render time, so a re-render alone is enough to pick up
# new results -- no rebuild of guide_data.json is needed.
set -u
cd "$(dirname "$0")/.." || exit 1

NODE=/Users/haoyufeng/.workbuddy/binaries/node/versions/22.12.0/bin/node
NODE_PATH=/Users/haoyufeng/.workbuddy/binaries/node/workspace/node_modules
export NODE_PATH NODE_OPTIONS=--max-old-space-size=4096
PY=/Users/haoyufeng/.workbuddy/binaries/python/versions/3.13.12/bin/python3

echo "[finalize] waiting for llm_enrich DONE ..."
while ! grep -q "DONE total" _batches/llm_enrich.log 2>/dev/null; do
  sleep 60
done
echo "[finalize] batch done, regenerating HTML ..."
$PY render.py
echo "[finalize] render exit=$?"
$NODE validate_guide.js interspeech2026_authors.html > _batches/validate_final.log 2>&1
echo "[finalize] validate exit=$?"
tail -20 _batches/validate_final.log
echo "[finalize] FINALIZED"
