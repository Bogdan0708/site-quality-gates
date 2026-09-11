#!/usr/bin/env bash
# Operational docs must not reference the legacy domain/email.
# Historical paths are exempt (superseded-not-rewritten policy). Exemptions
# apply to the matched file path only, never to text later on the same line.
set -u

# CLAIMS_ROOT: directory tree to scan (default: this script's own directory).
# LEGACY_DOMAIN: the retired domain/email fragment that must not leak into
# operational docs — default below is the example this gate shipped with.
ROOT=${CLAIMS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
cd "$ROOT"
LEGACY_DOMAIN=${LEGACY_DOMAIN:-saltandstandard.co.uk}

is_exempt() {
  case "$1" in
    ./docs/research/*|./docs/superpowers/*|./.superpowers/*|./.git/*) return 0 ;;
    *) return 1 ;;
  esac
}

hits=""
while IFS=: read -r path line_no line_text; do
  [ -z "$path" ] && continue
  is_exempt "$path" && continue
  hits+="${path}:${line_no}:${line_text}"$'\n'
done < <(grep -rn "${LEGACY_DOMAIN//./\\.}" --include='*.md' --include='*.html' --include='*.css' --include='*.svg' . 2>/dev/null || true)

hits=${hits%$'\n'}
if [ -n "$hits" ]; then echo "FAIL: legacy domain references:"; echo "$hits"; exit 1; fi
echo "PASS: no legacy domain in operational docs"
