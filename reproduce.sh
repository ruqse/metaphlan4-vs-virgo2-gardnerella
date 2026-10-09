#!/usr/bin/env bash
# Rebuild every table under data/ from pinned upstream inputs.
#
#   ./reproduce.sh                 download inputs, verify SHA-256, regenerate data/
#   ./reproduce.sh --check         same, but write to a temp dir and diff against the committed data/
#                                  (exit 1 on any difference)
#   ./reproduce.sh --inputs DIR    keep downloads in DIR and reuse them on later runs
#
# Inputs (about 235 MB) and their checksums are listed in ref/inputs.tsv. Requires bash, curl and
# python3 (standard library only). Works with macOS BSD tools and GNU coreutils.
set -euo pipefail
export LC_ALL=C

repo="$(cd "$(dirname "$0")" && pwd)"
mode=write
inputs=""

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --check) mode=check ;;
    --inputs) [ $# -ge 2 ] || { usage; exit 2; }; inputs="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
[ -n "$inputs" ] || inputs="$work/inputs"
mkdir -p "$inputs"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

echo "== 1) Fetch and verify pinned inputs (ref/inputs.tsv)"
tab="$(printf '\t')"
while IFS="$tab" read -r name expected url; do
  case "$name" in ''|\#*) continue ;; esac
  dest="$inputs/$name"
  if [ -f "$dest" ] && [ "$(sha256 "$dest")" = "$expected" ]; then
    echo "   cached   $name"
    continue
  fi
  echo "   fetching $name"
  curl -fsSL --retry 3 --retry-delay 5 -o "$dest.part" "$url"
  mv "$dest.part" "$dest"
  actual="$(sha256 "$dest")"
  if [ "$actual" != "$expected" ]; then
    echo "SHA-256 mismatch for $name" >&2
    echo "  expected $expected" >&2
    echo "  actual   $actual" >&2
    echo "The upstream file has changed since it was pinned; review it before updating ref/inputs.tsv." >&2
    exit 1
  fi
done < "$repo/ref/inputs.tsv"

if [ "$mode" = check ]; then out="$work/data"; else out="$repo/data"; fi

echo "== 2) Derive tables into ${out#$repo/}"
python3 "$repo/scripts/derive.py" --inputs "$inputs" --out "$out" --ref "$repo/ref"

if [ "$mode" = check ]; then
  echo "== 3) Compare with committed data/"
  if diff -ru "$repo/data" "$out"; then
    echo "OK: committed data/ matches a fresh rebuild."
  else
    echo "FAIL: committed data/ differs from a fresh rebuild (diff above)." >&2
    exit 1
  fi
fi
