#!/usr/bin/env bash
# 依次跑一批「只改链接期旗标」的实验（不重编，秒级）——见 m1/OPT-RESULTS.md §2。
# 用法: sh m1/exp-relink-batch.sh <tool> <name1:flags1> <name2:flags2> ...
#   sh m1/exp-relink-batch.sh clang "emcc_o2:-O1" "emcc_oz:-Oz -flto"
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOL="${1:?usage: exp-relink-batch.sh <tool> <name:flags>...}"; shift
BUILD="$ROOT/m1/build-$TOOL"
for spec in "$@"; do
  name="${spec%%:*}"; flags="${spec#*:}"
  echo "=============== relink $TOOL :: $name :: $flags"
  python3 "$ROOT/m1/exp-relink.py" --tool "$TOOL" --name "$name" --build "$BUILD" \
      --emcc-flags="$flags" 2>&1 | grep -E "ARTIFACT|FATAL|error|linked in|inputs:"
done
echo "=============== batch done"
