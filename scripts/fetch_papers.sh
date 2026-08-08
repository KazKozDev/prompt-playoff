#!/bin/bash
# Fetch the reference papers listed in references/README.md from arXiv.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p references/papers

for id in 2406.06608 2604.14197 2407.12994 2502.11560 2401.14043 2402.07927 2312.03740; do
    target="references/papers/$id.pdf"
    if [ -s "$target" ]; then
        echo "have  $id"
        continue
    fi
    printf 'get   %s ... ' "$id"
    if curl -sSL --max-time 120 -A "prompt-selector-research/0.1" -o "$target" "https://arxiv.org/pdf/$id" \
       && [ "$(stat -f%z "$target" 2>/dev/null || echo 0)" -gt 50000 ]; then
        echo "$(( $(stat -f%z "$target") / 1024 )) KB"
    else
        echo "failed"; rm -f "$target"
    fi
    sleep 3   # arXiv asks for a delay between automated requests
done
