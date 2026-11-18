#!/usr/bin/env bash
# Deploy the sales tracker to Vercel (https://salespipeline.dunous.com).
#   deploy/vercel.sh            production
#   deploy/vercel.sh --preview  a preview deployment to try first
#   VERCEL_TOKEN=… deploy/vercel.sh   deploy with an access token (no `vercel login`);
#                                     read from .env when not given
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
# The token lives in .env (gitignored) unless one is passed in.
if [ -z "${VERCEL_TOKEN:-}" ] && [ -f .env ]; then
  VERCEL_TOKEN=$(sed -n 's/^VERCEL_TOKEN=//p' .env | tail -1)
fi
AUTH=()
[ -n "${VERCEL_TOKEN:-}" ] && AUTH=(--token "$VERCEL_TOKEN")
# A token scoped to the project cannot read the user or team, which the CLI
# needs; the REST API can still deploy with it.
if [ -n "${VERCEL_TOKEN:-}" ] && ! vercel whoami --token "$VERCEL_TOKEN" >/dev/null 2>&1; then
  VERCEL_TOKEN="$VERCEL_TOKEN" exec python3 deploy/vercel_api.py "$@"
fi
if [ "${1:-}" = "--preview" ]; then
  vercel deploy --cwd "$OUT" --yes ${AUTH[@]+"${AUTH[@]}"}
else
  vercel deploy --cwd "$OUT" --prod --yes ${AUTH[@]+"${AUTH[@]}"}
fi
