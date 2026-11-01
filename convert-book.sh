#!/usr/bin/env bash
# convert-book.sh <input>  ->  writes ./data/<stem>.md and prints the path.
# Handles epub (pandoc), pdf (pdftotext -layout), mobi/azw (calibre ebook-convert),
# txt/md (copy). pandoc/poppler run via nix shell (not installed system-wide); calibre
# is a system package (configuration.nix). Idempotent-ish: overwrites the output .md.
set -euo pipefail
in="${1:?usage: convert-book.sh <input>}"
[ -f "$in" ] || { echo "not a file: $in"; exit 1; }
stem=$(basename "${in%.*}")
out="./data/${stem}.md"
mkdir -p ./data
ext=$(basename "$in" | tr '[:upper:]' '[:lower:]' | sed 's/.*\.//')
case "$ext" in
  epub) nix shell nixpkgs#pandoc -c pandoc "$in" -f epub -t gfm --wrap=none -o "$out" ;;
  pdf)  nix shell nixpkgs#poppler-utils -c pdftotext -layout "$in" "$out" ;;
  html|htm|docx) nix shell nixpkgs#pandoc -c pandoc "$in" -t gfm --wrap=none -o "$out" ;;
  mobi|azw|azw3)
    if command -v ebook-convert >/dev/null 2>&1; then
      EC=(ebook-convert)
    else
      EC=(nix shell nixpkgs#calibre -c ebook-convert)
    fi
    if ! "${EC[@]}" "$in" "$out"; then
      "${EC[@]}" "$in" "${out%.md}.txt" && mv -f "${out%.md}.txt" "$out"
    fi ;;
  txt) cp -f "$in" "$out" ;;
  md)  cp -f "$in" "$out" ;;
  *) echo "unsupported type: .$ext ($in)"; exit 1 ;;
esac
echo "$out"
