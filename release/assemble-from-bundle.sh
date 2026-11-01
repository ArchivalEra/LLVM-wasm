#!/bin/sh
# assemble-from-bundle.sh —— 从**已发布的 bundle** 组装一次新发布（CI 用）。
#
# 为什么需要它（用户 2026-11-01 的裁定：发布走 GitHub Action，手动触发自动出 release）：
#   `make-release.sh` 需要 `toolchain/emsdk`（300 MB）+ `m1/build-*/bin` 里
#   数小时才建出来的 clang.wasm / lld.wasm。这些都不在库里（.gitignore 排除），
#   **CI 上不可能重建**。硬要在 CI 里跑 make-release.sh，只会跑出一个"看起来
#   做了、其实输入是空的"的假结果。
#
# 所以 CI 的发布动作是**搬运而不是重建**：把上一个已发布 bundle 里的 14 个资产
# 取出来，重打一份 + 换 tag/pin。字节与来源完全相同，唯一的差别是元数据里的
# tag —— 这正是"同一个 tag 永远是同一份字节"的反面用法：**同一份字节可以
# 有多个 tag**，而每个 tag 仍指向确定的内容。
#
# ★ 这条路径只适用于**载荷没变**的发布（换分发形态、改元数据、补 tag）。
#   载荷真变了（重编 clang、换 sysroot）必须在有工具链的机器上跑
#   make-release.sh —— 那种发布 CI 做不了，Action 会明确失败而不是偷偷
#   发出一个旧载荷的新 tag。
#
# 用法：
#   sh release/assemble-from-bundle.sh <source-bundle.tar.gz> <new-tag>
set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

SRC=${1:?用法: assemble-from-bundle.sh <source-bundle.tar.gz> <new-tag>}
TAG=${2:?用法: assemble-from-bundle.sh <source-bundle.tar.gz> <new-tag>}
OUT="$ROOT/release/out"

[ -f "$SRC" ] || { echo "FATAL: $SRC 不存在"; exit 2; }

rm -rf "$OUT"
mkdir -p "$OUT"
tar xzf "$SRC" -C "$OUT"

# 源 bundle 必须自带 manifest.json —— 它是"该有哪些资产"的权威，也是
# 逐资产 sha 的产地。没有就 die，不猜。
[ -s "$OUT/manifest.json" ] || { echo "FATAL: 源 bundle 里没有 manifest.json"; exit 2; }

# 换 pin：content-list 的 pin 指向新 tag，其余字节一律不动。
# `--pin` 收**裸 tag**（脚本自己加 `release:` 前缀）—— 传 `release:vX` 会得
# 到 `release:release:vX`（v0.1.4 踩过）。
node "$ROOT/release/make-content-list.mjs" "$OUT" "$OUT/content-list.json" --pin "${TAG#v}"
cp "$OUT/content-list.json" "$ROOT/release/content-list.json"

( cd "$OUT" && tar -czf "../llvm-wasm-bundle-${TAG}.tar.gz" . )

echo "== assembled $TAG from $(basename "$SRC") =="
ls -la "$ROOT/release/llvm-wasm-bundle-${TAG}.tar.gz"
echo ""
echo "载荷字节未变（搬运而非重建）。若本次发布**应当**包含新载荷，"
echo "这条路是错的 —— 去有工具链的机器跑 make-release.sh。"