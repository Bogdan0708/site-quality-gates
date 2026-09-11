#!/usr/bin/env bash
# Prohibited/suspect claims wording must not appear in operational docs.
# Broad patterns flag EVERY occurrence; reviewed-legitimate service-description
# lines are recorded verbatim in scripts/claims-allowlist.txt (one exact line
# per entry, format "path:line-text"). Canonical personal-credential wording
# ("HACCP-trained" / "instruire HACCP") is accepted directly, never allowlisted.
# Path exemptions apply only to the matched file path, not to its line text.
set -u

# CLAIMS_ROOT: directory tree to scan (default: this script's own directory,
# i.e. run it from the site checkout you want gated, or pass CLAIMS_ROOT).
ROOT=${CLAIMS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}
cd "$ROOT"

ALLOW=${CLAIMS_ALLOWLIST:-claims-allowlist.txt}
fail=0

is_exempt() {
  case "$1" in
    ./docs/research/*|./docs/superpowers/*|./docs/founders/*|./.superpowers/*|./.git/*) return 0 ;;
    *) return 1 ;;
  esac
}

check() {  # grep-pattern, label, optional mode
  local pattern=$1 label=$2 mode=${3:-} hits="" path line_no line_text key residual
  while IFS=: read -r path line_no line_text; do
    [ -z "$path" ] && continue
    is_exempt "$path" && continue
    if [ "$mode" = "haccp" ]; then
      residual=${line_text//HACCP-trained/}
      residual=${residual//instruire HACCP/}
      [[ "$residual" != *HACCP* ]] && continue
    fi
    key="${path}:${line_text}"
    grep -qxF "$key" "$ALLOW" || hits+="${path}:${line_no}:${line_text}"$'\n'
  done < <(grep -rn "$pattern" --include='*.md' --include='*.html' . 2>/dev/null || true)
  hits=${hits%$'\n'}
  if [ -n "$hits" ]; then echo "FAIL ($2) — fix or add reviewed line to $ALLOW:"; echo "$hits"; fail=1; fi
}
check 'a chef from two of London'  'old Ava phrase'
check 'bucătar-șef'                'RO head-chef overstatement'
check '\bSCA\b'                    'any SCA mention (unverified credential)'
check 'HACCP'                      'any HACCP mention (only -trained/service-description allowed)' haccp
[ $fail -eq 0 ] && echo "PASS: no unreviewed claims wording"
exit $fail
