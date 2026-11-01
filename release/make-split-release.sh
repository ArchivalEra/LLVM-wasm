#!/bin/sh
# make-split-release.sh —— 把一次 release 做成「分片静态分发」形态（契约 schema 2）。
#
# 为什么有它（额外内容仓 mail/016，本仓 016）：宿主现在只能整包拉 34.7 MB 的
# tar.gz，而 EdgeOne 的降速点落在 10–20 MB 之间（对方实测：20.9 MB / 29.6 MB
# 都掉到 0.93 MB/s，20 秒传不完）。分片 + zstd 后合计 26.68 MB（−23%），且客户端
# 能并发拉。这是**分发形态**的改变，不是内容语义的 —— 每个载荷的 bytes/sha256
# 一个都不变。
#
# ★ 三条不许自己发明的规矩：
#   1. 生成器与校验器**用契约仓的**（Octave-Extra-Content/tools/），不在这里
#      重写一份 —— 两份实现必然漂移（本仓的老教训）。本脚本只做「摆文件 + 调它」。
#   2. **元数据不进载荷**：release/out/ 里有 manifest.json（构建描述）和
#      content-list.json（接缝记录），它们本身是索引。直接把 out/ 喂给生成器会
#      把它俩切成 6 个分片（实测：16 entries 而不是 14）。所以先按 out 的
#      manifest 列出的资产名，拷一份干净目录。
#   3. **旧形态不删**：整包 tar.gz 继续作为同一 tag 的另一个 asset。宿主
#      provision 读的是 tar 内那份 manifest.json，分片形态是增量，不是替换。
#
# 用法：
#   sh release/make-split-release.sh v0.1.5 [输出目录]
#   ⇒ 输出目录（默认 release/split/）里是 manifest.json + 全部扁平 asset
#
# 前置：pip install zstandard；契约工具在 $EXTRA_CONTENT（默认 /tmp/ec）。
set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

TAG=${1:?用法: make-split-release.sh <tag> [outdir]}
OUT=${2:-"$ROOT/release/split"}
SRC="$ROOT/release/out"
# 契约工具不 vendor 进本仓（那是另一条产品线，同步方式未定）；没有就明说怎么拿。
EC=${EXTRA_CONTENT:-/tmp/ec}

[ -f "$SRC/manifest.json" ] || { echo "FATAL: 没有 $SRC/manifest.json —— 先跑 make-release.sh"; exit 2; }
[ -f "$EC/tools/make-manifest-v4.py" ] || {
  echo "FATAL: 契约工具不在 $EC。先："
  echo "  git clone https://github.com/ArchivalEra/Octave-Extra-Content /tmp/ec"
  exit 2
}
python3 -c "import zstandard" 2>/dev/null || { echo "FATAL: 需要 zstandard：pip install zstandard"; exit 2; }

# ── 1) 干净载荷目录：只放 out/manifest.json 里列出的资产 ─────────────────────
CLEAN="$OUT/payload"
rm -rf "$OUT"
mkdir -p "$CLEAN"
python3 - "$SRC" "$CLEAN" <<'PY'
import json, os, shutil, sys
src, dst = sys.argv[1], sys.argv[2]
man = json.load(open(os.path.join(src, 'manifest.json'), encoding='utf-8'))
names = [a['name'] for a in man['assets']]
missing = [n for n in names if not os.path.exists(os.path.join(src, n))]
if missing:
    sys.exit('FATAL: manifest 列了但盘上没有：%s' % ', '.join(missing))
for n in names:
    p = os.path.join(dst, n)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    shutil.copy2(os.path.join(src, n), p)
print('payload: %d assets（元数据未进载荷）' % len(names))
PY

# ── 2) 生成分片 manifest（契约的工具，不重写）───────────────────────────────
python3 "$EC/tools/make-manifest-v4.py" --out "$OUT" \
  --id "LLVM-wasm/$TAG" --product "toolchain:file:$CLEAN"

# ── 3) 立刻验一遍（同一套工具的校验器）──────────────────────────────────────
python3 "$EC/tools/check-release-v4.py" "$OUT/manifest.json" --base "$OUT" | tail -2

# ── 4) ARTIFACT 行：体积/条数由这里量，不手抄 ───────────────────────────────
python3 - "$OUT" <<'PY'
import json, os, sys
d = json.load(open(os.path.join(sys.argv[1], 'manifest.json'), encoding='utf-8'))
tot, n, biggest = {}, 0, 0
for e in d['entries']:
    for v in e['variants']:
        n += len(v['chunks'])
        tot[v['codec']] = tot.get(v['codec'], 0) + sum(c['bytes'] for c in v['chunks'])
        for c in v['chunks']:
            biggest = max(biggest, c['bytes'])
print('ARTIFACT split_entries %d' % len(d['entries']))
print('ARTIFACT split_assets %d' % n)
print('ARTIFACT split_zstd_bytes %d' % tot.get('zstd', 0))
print('ARTIFACT split_max_chunk %d' % biggest)
PY

# ── 5) 契约判据 1 的核查：asset 名必须扁平（无斜杠）且 manifest 要的文件都在。
#      生成器本来就输出扁平名（toolchain__clang.wasm.zstd.000），这一步只是
#      **断言它没变**——实测过它确实不产生子目录，所以这里不写搬运逻辑
#      （第一版写了，跑出 "flattened 0 files"：一段永远不会干活的代码）。
python3 - "$OUT" <<'PY'
import json, os, sys
out = sys.argv[1]
man = json.load(open(os.path.join(out, 'manifest.json'), encoding='utf-8'))
wanted = {c['file'] for e in man['entries'] for v in e['variants'] for c in v['chunks']}
slashed = [f for f in wanted if '/' in f or '\\' in f]
if slashed:
    sys.exit('FATAL: 契约判据 1 要求扁平 asset 名，但这些带斜杠：%s'
             % ', '.join(sorted(slashed)[:5]))
present = {f for f in os.listdir(out) if os.path.isfile(os.path.join(out, f))}
missing = wanted - present
if missing:
    sys.exit('FATAL: manifest 要的 %d 个 asset 不在根层：%s'
             % (len(missing), ', '.join(sorted(missing)[:5])))
print('flat-name check: %d assets, all present at root, none contains a slash' % len(wanted))
PY

# payload/ 是中间产物（14 个未切的原件，122 MB）。生成器读完就不需要了，
# 上传前必须清掉 —— 否则 `gh release upload $OUT/*` 会把它们当资产传，
# 而契约判据 1 只白名单 asset 名（实测漏删过：release/split/ 里多出 payload/）。
rm -rf "$OUT/payload"

echo ""
echo "== split release ready at $OUT =="
echo "上传（与整包 tar.gz 挂在同一个 tag 下，旧形态不删）："
echo "  gh release upload $TAG $OUT/manifest.json $OUT/*.zstd.* $OUT/*.gzip.* $OUT/*.identity.* --clobber"
echo "(105 个分片 + manifest.json；每个 ≤ 5 MiB)"