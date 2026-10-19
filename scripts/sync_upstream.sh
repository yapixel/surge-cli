#!/bin/sh
# Sync the official Surge-bundled skill files into this skill.
#
#   sync_upstream.sh          copy from the local Surge.app
#   sync_upstream.sh <host>   copy from Surge.app on an SSH host
#
# Never touches SKILL.md, scripts/ or .env. Afterwards, diff
# references/upstream-SKILL.md and merge new guidance into SKILL.md by hand.
set -eu

SRC=/Applications/Surge.app/Contents/Resources/Skills/surge
DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

if [ $# -ge 1 ]; then
  scp -q -r "$1:$SRC/." "$TMP/"
else
  [ -d "$SRC" ] || { echo "Surge.app skill not found locally; pass an SSH host" >&2; exit 1; }
  cp -R "$SRC/." "$TMP/"
fi

# upstream-path:local-path
PAIRS="SKILL.md:references/upstream-SKILL.md
references/command-reference.md:references/command-reference.md
references/plugin-authoring.md:references/plugin-authoring.md
agents/openai.yaml:agents/openai.yaml
assets/logo.png:assets/logo.png"

# Verify everything first so a partial upstream never half-applies.
for pair in $PAIRS; do
  [ -f "$TMP/${pair%%:*}" ] || { echo "Missing upstream file: ${pair%%:*}" >&2; exit 1; }
done

for pair in $PAIRS; do
  src="$TMP/${pair%%:*}"; dst="$DIR/${pair#*:}"
  mkdir -p "$(dirname -- "$dst")"
  if cmp -s "$src" "$dst"; then
    echo "unchanged  ${pair#*:}"
  else
    cp "$src" "$dst.new" && chmod 644 "$dst.new" && mv "$dst.new" "$dst"
    echo "UPDATED    ${pair#*:}"
  fi
done
echo "If upstream-SKILL.md changed, merge its new guidance into SKILL.md."
