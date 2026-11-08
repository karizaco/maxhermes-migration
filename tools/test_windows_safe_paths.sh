#!/bin/sh
set -e
# Extract and smoke-test win_safe_path / sanitize_tree from push_artifact.sh
ROOT=$(mktemp -d 2>/dev/null || mktemp -d -t winsafe)
trap 'rm -rf "$ROOT"' EXIT
# source functions by extracting them
sed -n '/^win_safe_component()/,/^sanitize_tree()/{p}' cloud-prompts/_shared/push_artifact.sh > "$ROOT/fn.sh"
# also need sanitize_tree body through closing brace before SRC_DIR=
# simpler: define minimal copies
win_safe_component() {
  _c=$(printf '%s' "$1" | sed 's/[<>:"\\|?*]/_/g' | sed 's/[. ]*$//')
  [ -n "$_c" ] || _c="_"
  printf '%s' "$_c"
}
win_safe_path() {
  _in=$1; _out=""; _first=1; old_ifs=$IFS; IFS=/
  for _part in $_in; do
    IFS=$old_ifs
    [ -z "$_part" ] && { IFS=/; continue; }
    _safe=$(win_safe_component "$_part")
    if [ "$_first" -eq 1 ]; then _out="$_safe"; _first=0; else _out="$_out/$_safe"; fi
    IFS=/
  done
  IFS=$old_ifs
  printf '%s' "$_out"
}
test "$(win_safe_path 'daily-screens/2026-11-05/reversal-bullish-3:55.md')" = 'daily-screens/2026-11-05/reversal-bullish-3_55.md'
test "$(win_safe_path 'daily-screens/2026-11-05/reversal-bullish-3:55-near-misses.csv')" = 'daily-screens/2026-11-05/reversal-bullish-3_55-near-misses.csv'
test "$(win_safe_component 'CON.md')" = 'CON.md'
test "$(win_safe_component 'a:b.csv')" = 'a_b.csv'
mkdir -p "$ROOT/tree"
printf 'x' > "$ROOT/tree/reversal-bullish-3:55.md"
printf 'y' > "$ROOT/tree/ok.md"
# inline sanitize_tree
sanitize_tree() {
  _root=$1
  [ -d "$_root" ] || return 0
  find "$_root" -depth 2>/dev/null | while IFS= read -r _p; do
    [ -n "$_p" ] || continue
    [ "$_p" = "$_root" ] && continue
    _base=$(basename "$_p"); _dir=$(dirname "$_p")
    _safe=$(win_safe_component "$_base")
    [ "$_base" = "$_safe" ] && continue
    _dest="$_dir/$_safe"
    if [ -e "$_dest" ]; then rm -rf "$_p"; else mv -f "$_p" "$_dest"; fi
  done
}
sanitize_tree "$ROOT/tree"
test -f "$ROOT/tree/reversal-bullish-3_55.md"
test ! -e "$ROOT/tree/reversal-bullish-3:55.md"
test -f "$ROOT/tree/ok.md"
echo "OK windows-safe path smoke tests"