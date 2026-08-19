#!/usr/bin/env bash
# Rebuild static/tailwind.css after editing classes in templates/index.html.
# You only need this if you change the UI — the compiled CSS is committed,
# so the app runs with no Node.js installed at all.
#
#   ./build_css.sh
#
set -euo pipefail
cd "$(dirname "$0")"
command -v npm >/dev/null || { echo "Node.js/npm required: https://nodejs.org"; exit 1; }
npm install --silent
npm run build:css
echo "✓ static/tailwind.css rebuilt"
