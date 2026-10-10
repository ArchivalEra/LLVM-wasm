# M1 体积优化实验：配置 → brotli 体积对照表

> 任务来源：`/tmp/handoff-clang-wasm-size.md`（上一轮 agent 的交接单）。
> 时间盒：2 小时（含 ccache 接入）。测于 emsdk 6.0.12 / clang 24.0.0git，
> LLVM 源码 = emsdk 钉的 commit `55ea1f4e`，机器 24 核。
> 所有数字来自 `m1/evidence/opt-*.log` 与 `m1/evidence/relink/*/link.log` 的
> `ARTIFACT` 行（唯一产地），本文照抄它们。

---

## 0. 结论（先给答案）

| 问题 | 答案 |
|---|---|
| 哪根杠杆最有效？ | **`CMAKE_BUILD_TYPE=MinSizeRel`（真 · `-Os`）**，clang 的 brotli 从 16.40 MB → **13.30 MB（−18.9%）** |
| 第二有效？ | **lld 只留 wasm 驱动**，brotli 9.66 MB → **8.50 MB（−12.1%）** |
| 能到 15 MB 吗？ | **到不了。** 目前最好组合 **21.80 MB，超预算 45%**（差 6.80 MB） |
| 这个组合还能跑吗？ | **能。** 整链验收 **10 PASS / 0 FAIL**，`minifn.so` 976 B 与基线一致（§4） |
| 唯一可能达标的路径？ | 关掉 C++ 异常 + RTTI（见 §5：LLVM 自身的 `CrashRecoveryContext` 挡路，需要改源码打通 `emscripten_longjmp`）。**我没做成，这是本轮最值钱的负结果。** |

**本单最重要的一个发现**（改变了后面所有实验的解释方式）：
基线**根本不是 `-O1`**。`m1/build-clang-wasm.sh` 写 `-DCMAKE_C_FLAGS="-O1"`，
但 `CMAKE_BUILD_TYPE=Release` 会把 `-O3 -DNDEBUG` 追加在后面，
而 emcc 认**最后一个** `-O`。所以：

- 编译：`-O1 … -O3` ⇒ **实际 `-O3`**（`m1/build-exp-anchor/build.ninja` 里 FLAGS 行可查）
- 链接：emcc 同样吃这个 `-O3` ⇒ **binaryen 优化其实已经跑过了**

这就解释了交接单里那条"`wasm-opt -Oz` 只省 36 KB"的怪现象：不是 Binaryen 无能，
而是**它早就跑过一遍了**，交接单是在它的输出上又跑了一遍。
⇒ 「后处理」这条路已经被走完，「编译配置」才是唯一剩下的空间，与交接单的判断一致。

---

## 1. 对照表（按 brotli 排序）

两个尺寸口径都列出来。**q11 是定稿口径**（SPEC §6 的预算按 q11 比）；
`—` 表示该行没跑 q11、只跑了便宜的 q9（§2 有 q9/q11 的换算标定）。

### clang.wasm

| # | 配置 | raw | brotli q11 | 验收 | 复跑命令 |
|---|---|---|---|---|---|
| 1 | **`anchor`：`MinSizeRel`(`-Os`) + 链接 `-O3`** | **51,580,817** | **13,301,149** | **10 PASS** | `bash m1/exp-run.sh anchor` |
| 2 | `anchor_oz`：锚点对象 + 链接 `-Oz` | 50,748,892 | 13,307,575 | 未单测² | `python3 m1/exp-relink.py --tool clang --name anchor_oz --build m1/build-exp-anchor --emcc="-Oz"` |
| 3 | `baseline`：`Release`(实际 `-O3`) | 71,055,261 | 16,400,451 | **10 PASS** | `bash m1/build-clang-wasm.sh clang` |
| 4 | `baseline` + `wasm-opt -Oz --converge`（26 分钟） | 69,913,426 | — | 未测 | 见 §2 |

² `anchor_oz` 与 `anchor` 只差链接旗标（对象文件完全相同），验收结论由 #1 覆盖；
**注意链接 `-Oz` 让 raw 再降 0.8 MB，但 brotli 反而涨了 6 KB** —— 见下方"结论 3"。

> **结论 3（重要）**：链接期 `-Oz` 对 brotli **无效甚至微负**。
> 原因见 §0：emcc 默认已经跑 binaryen，且其 `-O3` 档带的 shrink 已经够了。
> 这条在 clang 和 lld 上都复现了（lld 那行：−24 KB / −0.25%，见下）。

### lld.wasm（wasm-ld）

| # | 配置 | raw | brotli q11 | 验收 | 复跑命令 |
|---|---|---|---|---|---|
| 1 | **`wasmonly`：只含 wasm 驱动的 lld** | **33,358,910** | **8,495,303** | **8 PASS** | `bash m1/patch-lld-wasm-only.sh && cd m1/build-lld && ninja lld-wasm-only` |
| 2 | `baseline`：上游 lld（五驱动全带） | 38,912,004 | 9,660,186 | **8 PASS** | `bash m1/build-clang-wasm.sh lld` |
| 3 | `baseline` + 链接 `-Oz`（对象不变） | 37,901,604 | 9,635,966 | 同 #2² | `python3 m1/exp-relink.py --tool lld --name lld_oz --build m1/build-lld --emcc="-Oz"` |
| 4 | `baseline` + 链接 `-Oz -flto` | 37,900,919 | 9,635,180 | 同 #2² | `python3 m1/exp-relink.py --tool lld --name lld_oz_lto --build m1/build-lld --emcc="-Oz -flto"` |

² 链接旗标不改代码语义，且 #2/#3/#4 的**输入对象完全相同**；验收按 #2 的 8 PASS 计。
`wasmonly` 是**唯一**换了实现的一行，它单独跑了验收（#1 = 8 PASS，产物 976 B 与基线一致）。

### 合计（SPEC §6 预算 = 15 MB）

| 组合 | clang | lld | 合计 | vs 15 MB |
|---|---|---|---|---|
| 基线 | 16,400,451 | 9,660,186 | **26,060,637**（24.85 MiB） | **+74%** |
| 本轮最好（`anchor` + `wasmonly`） | 13,301,149 | 8,495,303 | **21,796,452**（20.79 MiB） | **+45%** |

⇒ **省下 4,264,185 B（−16.4%）**，距离达标还差 **6,796,452 B**。

这个组合整链跑过验收（**10 PASS / 0 FAIL**，日志 `m1/evidence/opt-combo-acceptance.log`）：

```sh
M1_CLANG_BIN=m1/build-exp-anchor/bin M1_LLD_BIN=m1/build-lld/bin \
  M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs
```

⇒ 两份体积更小的产物**确实还能在 wasm 里编出 ABI 正确的 side module**（976 B，与基线同尺寸）。

---

## 2. 标定：brotli 质量与速度（为什么表里有两个口径）

在 `lld.wasm`（38.9 MB）上实测 `python3 -c "import brotli; ..."`：

| quality | bytes | 耗时 | 相对 q11 |
|---|---|---|---|
| 9 | 10,969,539 | 4.0 s | +13.5% |
| 10 | 10,005,779 | 30.9 s | +3.6% |
| 11 | 9,660,186 | 85.6 s | — |

锚点产物（51.6 MB）上的同口径复核：**q11 = 109 s**。
⇒ 一个 71 MB 的 wasm 做一次 q11 要 **5–10 分钟**。所以：
**筛选用 q9（快 20 倍），定稿用 q11**。上表的 q11 数字都是定稿口径，没有混用。

---

## 4. 验收：改了配置还能不能编

---

## 3. 试过但**没用**的路（省下你重试的时间）

| # | 做法 | 结果 | 为什么 |
|---|---|---|---|
| 1 | `wasm-opt -Oz`（交接单已做） | raw −1.13 MB，brotli **−36 KB（0.2%）** | binaryen 已经跑过（见 §0）；再跑一遍只是把已消化的冗余再扫一次 |
| 2 | `wasm-opt -Oz --converge`（跑到不动点，26 分钟） | raw **69,913,426**（−1.14 MB，−1.6%） | 同上；brotli 层面收益只会更小 |
| 3 | 链接期 `-Oz`（不动对象，只换链接旗标） | clang raw −0.8 MB 但 brotli **+6 KB**；lld raw −1.0 MB / brotli **−24 KB（−0.25%）** | emcc 链接默认已按 `-O3` 跑 binaryen，`-Oz` 只是把同一批 pass 换个挡 |
| 4 | 砍 `-O1`：以为基线是 `-O1`、换 `-Os` 能省一大截 | 基线实际是 `-O3`，见 §0 | `CMAKE_BUILD_TYPE=Release` 追加的 `-O3` 覆盖了 `-O1` |
| 5 | `-fno-exceptions -fno-rtti`（配置名 `lean`） | **链接失败** | `libLLVMSupport/CrashRecoveryContext.cpp.o` 引用 `emscripten_longjmp`，`-fno-exceptions` 下没有定义。详见 §5 |
| 6 | 只关 RTTI（`LLVM_ENABLE_RTTI=OFF`，配置名 `lean2`） | **cmake 直接拒绝** | `HandleLLVMOptions.cmake:1244`：`LLVM_ENABLE_EH=ON` 时 RTTI 必须 ON |
| 7 | `EM_COMPILER_WRAPPER=ccache`（交接单暗示的接法） | **完全无效**，命中数恒 0 | emsdk 6.0.12 的 `emcc.py:527` 读的是 `config.COMPILER_WRAPPER`，而**没有任何代码从环境变量给它赋值**。见 §6 |
| 8 | 只调 clang 的 C++ 开关（`CLANG_ENABLE_*`） | 没做（时间盒） | 那些开关在基线里**已经 OFF**，边际收益集中在 driver/诊断表，量级小于 `-Os` |

### 一个真实踩到的坑（不是"试过没用"，是"差点得到假结论"）

`ninja -t commands` 打印的链接行是 `: && em++ … -o bin/clang.js-24 && :` ——
**结尾还有一个 `&& :`**。把它原样喂给 em++ 会得到：

```
em++: error: &&: No such file or directory ("&&" was expected to be an input file)
```

更坑的是**另一半**：如果只把 `-o` 换掉、漏掉 `&& :` 的处理，emcc 会
**静默 exit 0 且只产出一个 121 B 的空壳 wasm**。我因此得到过一批"体积 −99.99%"的
假数据。判据：`bin/clang.wasm` 只有几百字节 ⇒ 链接其实没发生。
`m1/exp-relink.py` 里现在有显式检查（`FATAL: … missing after a successful link`）。

---

## 4. 验收：改了配置还能不能编

**硬约束是"体积降了但编不出东西 = 无效结果"**，所以每类改动的产物都过了验收：

| 产物 | 验收 | 结果 |
|---|---|---|
| **本轮最好组合**：clang `anchor` + lld `wasmonly` | `M1_CLANG_BIN=m1/build-exp-anchor/bin M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs` | **10 PASS / 0 FAIL**，`minifn.so` = 976 B（与基线同尺寸） |
| lld `wasmonly`（单查） | `M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js node m1/acceptance-lld-only.mjs` | **8 PASS / 0 FAIL** |
| lld `baseline`（对照） | `node m1/acceptance-lld-only.mjs` | 8 PASS / 0 FAIL |
| clang `anchor_oz` | 未单测（对象与 `anchor` 相同，只差链接旗标） | — |

`m1/acceptance-lld-only.mjs` 是本轮新增的：只跑"链接"那一半，输入固定为
`m1/acceptance/hello.o`，所以 lld 是唯一变量（`acceptance-full.mjs` 会先编译，慢一个数量级）。
`m1/acceptance-full.mjs` 也顺手参数化了（`M1_CLANG_BIN` / `M1_LLD_BIN` / `M1_LLD_JS`），
下一轮复核整体组合时不用再改脚本。

---

## 5. 唯一可能达标的路径（本轮没做完，诚实交代）

### 5.1 为什么"到不了 15 MB"不是因为没试够

代码体积分布（对基线 71 MB 跑一遍 wasm 解析）：

| 段 | 字节 | 占比 |
|---|---|---|
| `code` | 63,537,325 | 89.4% |
| `data` | 7,357,043 | 10.4% |
| 其他（type/import/export/elem/tag/global） | ~110 KB | 0.2% |
| **custom 段（含 name/debug）** | **0** | 0% |

- **没有调试信息可剥**（`--strip-debug` 已经生效）⇒ `--strip` 类手段收益 = 0。
- 函数体 62,491 个，**没有异常巨大的单个函数**（最大 461 KB，其余平滑下降）。
- ⇒ 体积就是"链进来的功能集合"本身：**62 K 个函数的真实代码**。
  这只能靠"少编功能"或"让每个函数更小"来降，没有后处理捷径。

### 5.2 最可能达标的一根杠杆：关异常 + 关 RTTI

C++ 异常对 wasm 的代价是双份的：每个函数一套 `__gcc_except_tab` 表 + landing pad 代码。
LLVM 官方支持 `LLVM_ENABLE_EH=OFF`，所以这不是歪门邪道。

**本轮实测结论：走不通，卡在 LLVM 自己的代码上。**

```
wasm-ld: error: lib/libLLVMSupport.a(CrashRecoveryContext.cpp.o):
                 undefined symbol: emscripten_longjmp   (×2)
```

`CrashRecoveryContext` 用 `setjmp/longjmp` 做崩溃恢复；`-fno-exceptions` 之后
emscripten 的 `longjmp` 支持路径对不上（emcc 侧默认转成了 `-lunwind-legacyexcept`
+ `-mllvm -wasm-use-legacy-eh`），链接期直接缺符号。

**要做成需要改源码**（超出 2 小时，也超出"不重写架构"的约束），两条路：
1. 给 wasm 平台编一份 `CrashRecoveryContext`（`#ifdef __EMSCRIPTEN__` 走空实现）——
   LLVM 已有 `LLVM_ENABLE_CRASH_OVERRIDES` 之类的旋钮可作为落点；
2. 用 `longjmp` 的原生支持：`-sSUPPORT_LONGJMP=wasm` + `-mllvm -wasm-enable-sjlj`
   显式打开（本轮没试，是**下一个最该试的命令**）。

预估收益：如果异常表和 typeinfo 合计占 10–20%（这是 C++ 大型工程的常见区间，
本轮没量到），两个 wasm 合计大约能到 **17–19 MB**，**仍然差 15 MB 一截**。
所以就算打通，15 MB 这个预算**大概也要改**——这条判断交给委托人定。

### 5.3 其它还没试、但按 §5.1 的量级判断收益有限的

- 裁 `clang/lib/Driver`：交接单点名过。但 `libclangDriver.a` 整档才 6.65 MB（未压缩），
  链接后进产物的部分更小；而且要保住 `-cc1` 就不能丢 `cc1_main.cpp` + `FrontendTool`。
  **判断：收益在 0.5–1.5 MB brotli 量级，不是决定性杠杆。**
- 分片懒加载（交接单实验 F）：这是改首拉体积的架构手段，不改总量。本轮没碰。

---

## 6. 复跑手册（照着敲就行）

### 6.1 ccache（**必须先做**，否则每个实验都是 10–20 分钟全量编译）

```sh
# 本仓工具链目录（不入库）
mkdir -p toolchain/ccache
printf 'max_size = 60G\ncache_dir = %s\ncompiler_check = content\n' \
  "$PWD/toolchain/ccache" > toolchain/ccache/ccache.conf
export CCACHE_CONFIGPATH="$PWD/toolchain/ccache/ccache.conf"
```

⚠️ **`EM_COMPILER_WRAPPER=ccache` 是死的**（emsdk 6.0.12）。能用的接法只有一个：
CMake 的 compiler launcher。`m1/exp-build.sh` 已经内置：

```
-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
```

验证命中（小样例，10 秒）：

```sh
cd /tmp && rm -rf ccl && mkdir ccl && cd ccl
printf 'int f(int x){return x+1;}\n' > a.cpp
printf 'cmake_minimum_required(VERSION 3.16)\nproject(t CXX)\nadd_executable(t a.cpp)\n' > CMakeLists.txt
export EM_CACHE=/mnt/hdd/zcode-projects/LLVM-wasm/toolchain/emsdk/upstream/emscripten/cache
emcmake cmake -G Ninja -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache . >/dev/null
ninja >/dev/null && ninja -t clean >/dev/null && ninja >/dev/null
ccache -s | grep Hits        # 期望 Hits ≥ 1
```

### 6.2 每个配置一条命令

```sh
cd /mnt/hdd/zcode-projects/LLVM-wasm

# 锚点：MinSizeRel(-Os)，24 核约 12–15 分钟（ccache 冷）
EXP_JOBS=20 bash m1/exp-run.sh anchor        # -> m1/evidence/opt-anchor.log

# lld 只留 wasm 驱动（复用已有 build-lld，只编 1 个文件 + 重链，约 25 秒）
bash m1/patch-lld-wasm-only.sh
cd m1/build-lld && ninja lld-wasm-only && cd ../..
bash m1/patch-lld-wasm-only.sh --revert       # 想还原源码树时

# 只改链接旗标（秒级–分钟级，不重编）
python3 m1/exp-relink.py --tool clang --name anchor_oz --build m1/build-exp-anchor --emcc="-Oz"
bash m1/exp-relink-batch.sh lld "lld_oz:-Oz" "lld_oz_lto:-Oz -flto"
```

### 6.3 量体积（口径必须一致）

```sh
# q11 定稿口径（慢，71 MB 要约 5–10 分钟）
python3 -c "import brotli,sys;print(len(brotli.compress(open(sys.argv[1],'rb').read(),quality=11)))" \
  m1/build-exp-anchor/bin/clang.wasm
# q9 筛选口径（快 20 倍，值比 q11 大约 13.5%，见 §2）
```

### 6.4 验收

```sh
node m1/acceptance-full.mjs                                   # 全链（基线产物）
M1_CLANG_BIN=m1/build-exp-anchor/bin M1_LLD_BIN=m1/build-lld/bin \
  M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs      # 本轮组合
M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js \
  node m1/acceptance-lld-only.mjs                             # 只查 lld（快）
```

---

## 7. 新增文件一览

| 文件 | 作用 |
|---|---|
| `m1/exp-build.sh` | 参数化构建（ccache launcher、build_type、flags），主脚本 `build-clang-wasm.sh` **未改动** |
| `m1/exp-run.sh` | 按配置名跑一组实验（`anchor` / `lean` / `lean2` / …） |
| `m1/exp-relink.py` | 复用已有对象，只换链接期旗标（最快的实验通道） |
| `m1/exp-relink-batch.sh` | 批量跑 relink |
| `m1/exp-link-sweep.sh` | `wasm-opt` 各种 pass 的扫描 |
| `m1/exp-collect.sh` | 汇总留档 + 统一量体积，打 `ARTIFACT` 行 |
| `m1/patch-lld-wasm-only.sh` | 把 COS-1（wasm-only lld）挂进/摘出 LLVM 源码树 |
| `m1/lld-wasm-only/` | COS-1 的源码与 cmake fragment |
| `m1/acceptance-lld-only.mjs` | 只验 lld 那一半的验收脚本 |
| `m1/evidence/opt-*.log`、`m1/evidence/relink/*/link.log` | 数字产地（`ARTIFACT` 行） |

---

## 8. 待办（交给下一轮）

1. 试 `-sSUPPORT_LONGJMP=wasm` + `-mllvm -wasm-enable-sjlj`，看能不能把
   `-fno-exceptions` 这条打通（§5.2；这是**最该试的下一条命令**，成本一次全量编译）。
2. 若第 1 条通了，量"关异常"的真实收益，再决定 15 MB 预算要不要改。
3. `anchor` 的 `clang.js` 胶水（75,755 B）本轮没优化；如果要抠首拉，胶水也是几十 KB 量级。
4. 分片懒加载（交接单实验 F）仍未评估。
