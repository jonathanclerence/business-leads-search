#!/usr/bin/env bash
# Deploy the sales tracker to Vercel (https://salespipeline.dunous.com).
#   deploy/vercel.sh            production
#   deploy/vercel.sh --preview  a preview deployment to try first
# Builds .cloud-build/ from cloud/ (the Vercel entry points) plus pipeline/
# (the tracker itself), so only what the tracker needs is uploaded: never
# .env, batches/ (the leads) or the virtualenv.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=.cloud-build
mkdir -p "$OUT"
rsync -a --delete --exclude .vercel --exclude /pipeline --exclude node_modules cloud/ "$OUT/"
rsync -a --delete --exclude __pycache__ --exclude .DS_Store --exclude hero3d \
  --exclude enrich.py --exclude __main__.py pipeline/ "$OUT/pipeline/"
if [ "${1:-}" = "--preview" ]; then
  vercel deploy --cwd "$OUT" --yes
else
  vercel deploy --cwd "$OUT" --prod --yes
fi
