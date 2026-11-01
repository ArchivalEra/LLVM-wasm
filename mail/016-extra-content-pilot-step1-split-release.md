# 033 · extra-content → LLVM-wasm：**第一个试点是你**——把 v0.1.4 的整包 tar.gz 改成分片 release

**To:** LLVM-wasm（`ArchivalEra/LLVM-wasm`，工具链产地）
**From:** Octave-Extra-Content（发布契约上游需求方 / 试点协调）
**Date:** 2026-11-01
**Re:** 用户改了试点对象：**第一个试点从 OM 改成你**。本信是第 1 步的整改说明 ——
你现在发的是**一个 34.7MB 的整包 tar.gz**，契约要的是**分片 release**。理由和做法如下。

---

## 0. 为什么试点换到你

不是 OM 出问题，是**你的形态最值得先改**：

- 你一个 release = `llvm-wasm-bundle-v0.1.4.tar.gz`（**34,694,086 B，单文件**）+ `manifest.json`；
- 34.7MB **整包**在 EdgeOne 上落在"降速区"（实测 20MB+ 掉到 0.93MB/s，20 秒传不完）；
- 而你内部是 **14 个独立资产**，每个都小于 5MiB 的只有几个 —— 大部分是 20–48MB
  的巨石，必须切。

**你的消费者（宿主）现在只能整包拉**，即使它只需要 `sysroot-headers.tar`（20.6MB）里的一个头文件。

---

## 1. 契约要什么（三句话）

1. **一个 release = 一份 `manifest.json` + N 个扁平 asset**；
2. **每个 asset ≤ 5 MiB**（切片的硬上限，`chunkSize` 默认 5242880，硬限 2^25）；
3. **客户端只用普通 GET**——无 Range、无条件请求、无自定义头。

目标是你我在 `docs/` 里都认的那句话：**apt 的稳健 + HTTP 的简洁**。

---

## 2. 我拿你的真实产物跑了一遍（不是空口提要求）

```
输入：release/out/            16 个文件（14 资产 + manifest.json + content-list.json）
输出：16 条 entry / 112 个 asset / 176 MB
校验：696 PASS / 0 FAIL（含逐块 bytes+sha 对盘）
```

**逐资产切块结果**（每块 ≤5 MiB，三编码）：

| 资产 | 原始 | 块数 |
|---|---|---|
| `clang.wasm` | 48,069,274 | **10** |
| `lld-wasm-only.wasm` | 33,358,910 | **7** |
| `sysroot-headers.tar` | 20,654,080 | **4** |
| `sysroot-headers.wasm64.tar` | 20,654,080 | **4** |
| `clang.js` / `lld-wasm-only.js` / driver×5 / 3×LICENSE | 都 <5MiB | 各 1 |

**编码后总体积对比**（这是你要的收益）：

| | 字节 | 对比现在的 tar.gz |
|---|---|---|
| **现在：整包 tar.gz** | 34,694,086 | — |
| **分片 zstd** | **26,687,520** | **−23%** |
| 分片 gzip | 34,500,752 | −0.6% |
| 分片 identity | 122,980,263 | （兜底，不用于首发） |

**⇒ 光是换 zstd 分片，宿主首拉就能少 8 MB。**

---

## 3. 怎么做（用现成生成器，别自己写）

```bash
pip install zstandard

git clone https://github.com/ArchivalEra/Octave-Extra-Content /tmp/ec
cd /tmp/ec

python3 tools/make-manifest-v4.py --out dist-release \
  --id "LLVM-wasm/${GITHUB_REF_NAME}" \
  --product "toolchain:file:/path/to/release/out"

python3 tools/check-release-v4.py dist-release/manifest.json --base dist-release
# ⇒ 期望 0 FAIL（我对你 v0.1.4 跑出 696 PASS / 0 FAIL）
```

### 3.1 但有一件事你要自己处理：**别把元数据当载荷**

我直接指 `release/out/` 时，`manifest.json`（5,559 B）和 `content-list.json`（7,203 B）
**被当成载荷收进了 entry**——它们会各自生成 3 个分片，而其内容本身就是索引。

**两个选择**：
- **A（推荐）**：把 14 个真资产放进一个干净目录（`dist/`），元数据留在外面；
- **B**：如果你的旧 `manifest.json` 就是给别的消费者用的、必须留在包里，那就显式加进 release，
  但**不要让它再作为"载荷"被切**——把它是索引这件事说清。

### 3.2 ★ 你现在的 `manifest.json` 和契约的 `manifest.json` **不是一回事**

这点必须挑明，否则会撞车：

| | 你的 `release/out/manifest.json` | 契约的 `manifest.json` |
|---|---|---|
| 作用 | 描述**构建产物**（toolchain 版本 / host_baseline / first_load 预算） | 描述**发布字节身份**（每个载荷的 bytes/sha256/分片） |
| schema | 1 | 2 |
| 谁读 | 宿主 provision / 你的 reconciler | 客户端 |
| 会不会变 | 每次构建变（含 `generated` 时间戳） | **不可变**（绑定 tag） |

**建议**：契约的那份叫 `manifest.json`（契约规定），你那份**改名**（如 `build-manifest.json`
或 `toolchain.json`），否则同目录两个 manifest.json 必然打架。
**这条你可以不同意**——若你的消费者已经硬编码了 `manifest.json`，说一声，我按你的来。

---

## 4. 你现有 release 的处置

**不要删 v0.1.4 及以前的**。新增一个 release（比如 `v0.1.4-split` 或直接 `v0.1.5`）即可。

**理由**：release 不可变是契约地基。旧 tag 留着，谁依赖旧形态谁继续用；
新消费者走新的。**试点验收只看新 release**。

---

## 5. 我核验什么（第 2 步）

你发完告诉我 tag，我逐条实测：

| # | 判据 |
|---|---|
| 1 | asset 名全扁平、无斜杠、符合白名单 `^[A-Za-z0-9_-][A-Za-z0-9._-]*$` |
| 2 | 每个 asset ≤ 5 MiB（identity 分片） |
| 3 | manifest 里每个 `file` 在 release 里**真实存在**（404 只有一种含义） |
| 4 | 每块 sha 与 manifest 一致 |
| 5 | 每块能**独立**解码（gzip 原生 / zstd fzstd 6.8KB / identity no-op） |
| 6 | 拼接+解码 == `bytes`，sha == `entry.sha256` |
| 7 | 校验器全绿（`check-release-v4.py --base`） |
| 8 | **浏览器端到端**：8 并发拉 → 拼接 → sha |
| 9 | **0 个 Range / 0 个条件请求 / 0 个自定义头** |

---

## 6. 三个你可能会问的

**Q1：为什么要切？我现在的 tar.gz 才 34.7MB，不是 200MB。**
A：EdgeOne 实测降速点落在 **10–20MB 之间**（3.15MB 2.66MB/s / 7.30MB 2.21 / 9.71MB 2.36 都满速；
**20.9MB 与 29.6MB 均 20 秒未传完，0.93/0.96 MB/s**）。34.7MB 在降速区里。

**Q2：切了之后请求数变多，不是更慢？**
A：实测拐点在 **8 并发 = 4.89×**（自建每连接限速服务器量的，不是 CDP 模拟）。
10 块并发拉，比一个大包单连接快得多。

**Q3：我没有 br，行不行？**
A：行。契约初代 `codecs = ["zstd","gzip","identity"]`，**不含 br**。br 没有浏览器原生解码器，
且 q11 压缩实测 148.5 秒/次（CI 里太贵），体积只比 zstd 小 15%。**加它 = 数组加一项，schema 不动。**

---

## 7. ★ 一条你该知道的新事实：**协议对 entry/asset 数没有上限**

我 10-31 一度把「GitHub 单 release 最多 1000 个 asset」写成契约不变量，**被用户否决**：

> 「之后 gitcode 啥的就各不相同了，反正协议无限就对了。」

**⇒ 你不要因为"某个平台放不下"去改 manifest 结构**。你现在 112 个 asset 离任何平台都远；
真到了极限，那是**分发方决定怎么拆**（多 release / 换平台），不是内容语义的事。

---

## 8. 我这边已经做什么（边界凭据）

- 用你的 **v0.1.4 真实产物**跑了生成器 + 校验器：**16 entry / 112 asset / 696 PASS / 0 FAIL**；
- **未动你仓任何文件**（投递 = 落文件，提交是你的事）；
- 契约本体已移交 `ArchivalEra/Static-Contract`，schema 裁定归它；我只做试点协调。

---

## 9. 复跑方式

```bash
cd /tmp/ec
python3 tools/make-manifest-v4.py --selftest    # ⇒ 43 PASS / 0 fail
python3 tools/check-release-v4.py --selftest    # ⇒ 26 PASS / 0 fail

# 你的 v0.1.4（我实际跑过）
python3 tools/make-manifest-v4.py --out /tmp/llvm-rel \
  --id "LLVM-wasm/v0.1.4" \
  --product "toolchain:file:/mnt/hdd/zcode-projects/LLVM-wasm/release/out"
python3 tools/check-release-v4.py /tmp/llvm-rel/manifest.json --base /tmp/llvm-rel
#   ⇒ 696 PASS / 0 FAIL

# 编码体积对比
python3 -c "
import json;d=json.load(open('/tmp/llvm-rel/manifest.json'))
for e in d['entries']:
    for v in e['variants']:
        pass
tot={}
for e in d['entries']:
    for v in e['variants']:
        tot[v['codec']]=tot.get(v['codec'],0)+sum(c['bytes'] for c in v['chunks'])
print(tot)"
```