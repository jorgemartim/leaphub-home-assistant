#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-.}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
failed=0
while read -r expected path; do
  [[ -z "${expected:-}" || "$expected" == \#* ]] && continue
  full="$ROOT/$path"
  if [[ ! -f "$full" ]]; then
    echo "FALTA: $path" >&2; failed=1; continue
  fi
  actual="$(git -C "$ROOT" hash-object "$path")"
  if [[ "$actual" != "$expected" ]]; then
    echo "DIVERGENTE: $path" >&2
    echo "  esperado: $expected" >&2
    echo "  atual:    $actual" >&2
    failed=1
  else
    echo "OK: $path"
  fi
done < "$HERE/BASE-GIT-BLOBS.txt"
exit "$failed"
