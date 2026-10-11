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
| 哪根杠杆最有效？ | **`CMAKE_BUILD_TYPE=MinSizeRel`（真 · `-Os`）**，clang brotli 16.40 → 13.30 MB（−18.9%） |
| 第二有效？ | **lld 只留 wasm 驱动**，brotli 9.66 → 8.50 MB（−12.1%） |
| 第三有效？ | **关 C++ 异常 + RTTI**（`-fno-exceptions -fno-rtti`），clang 再 −5.2% → 12.61 MB（§5.2.1） |
| 能到 15 MB 吗？ | **看口径，两个答案** —— 见下。**首拉 14.31 MB ⇒ 达标；总量 22.80 MB ⇒ 超 52%** |
| 这个组合还能跑吗？ | **能。** 整链验收 **10 PASS / 0 FAIL**，`minifn.so` 976 B 与基线一致（§4） |

### 0.1 ★ 预算口径：这是本单最要紧的一条（前几版答错了）

SPEC §6 的原文是：

> **预算目标**：brotli 后 **≤ 15 MB**（**首拉**），支持**分片懒加载** + 浏览器缓存。

**「首拉」+「分片懒加载」两个词决定了该怎么比。** 而本文前几版一直拿
**三资产总量**去比，于是得出「到不了」。**那个比较是错的**（至少是未经论证的）。

按 SPEC 自己的口径算（`bash m1/exp-firstload.sh`，产地 `m1/evidence/opt-firstload.log`）：

| 口径 | 构成 | brotli | vs 15 MB |
|---|---|---|---|
| **首拉**（第一次能**编译**） | clang.wasm 12,614,129 + clang.js 18,682 + sysroot.tar 1,675,293 | **14,308,104（14.31 MB）** | **达标 ✓ 余量 0.69 MB** |
| 首次**链接**时再拉 | lld.wasm（wasm-only） | 8,495,303（8.50 MB） | —— |
| **三资产总量** | 首拉 + lld | **22,803,407（22.80 MB）** | 超 52% |

**为什么 lld 可以不算进首拉**（不是我在抠字眼，有两处独立支撑）：
1. 驱动里 lld 本来就是**懒加载**的 —— `driver/toolchain.mjs` 的 `async lld()` 带
   `if (this._lld) return this._lld`，只有走到链接那一步才 `require`；`compile()` 里
   `await this.clang()` 在前、`await this.lld()` 在后（第 269 / 302 行）。
2. SPEC §6 自己点名「支持**分片懒加载**」，且 §6 那张表把三资产求和叫「合计」
   —— 但同一段的预算句子写的是「（**首拉**）」。

⚠️ **这条需要委托人拍板，我不替你定**：SPEC 那段话里「合计 13.07 MB」与
「≤ 15 MB（首拉）」**自相矛盾**（合计是总量口径，括号是首拉口径）。
我的判断是**括号里的「首拉」是限定词、应当优先**（它更具体，且与「分片懒加载」互相印证），
所以按首拉算**达标**。但如果原意是"三资产总量 ≤ 15 MB"，那就**超 52%**，
需要走 §5.3 的"改功能集合"路线。

> **⚠️ 本文另有一处错误的根因诊断，已更正**：§5.2 第一版把"关异常失败"归因于
> 「需要改 LLVM 源码」。**错。** 真实原因是旗标选择问题，而且**两轮 agent 都猜反了
> 修法** —— 复核者建议的 `-sSUPPORT_LONGJMP=wasm` 恰恰是**制造**故障的那个旗标。
> 完整机制与实测对照见 §5.2.2。这是本单最值得读的一节。

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
| 1 | **`lean_nosjlj`：`-Os` + 关异常 + 关 RTTI** | **48,069,274** | **12,614,129** | **10 PASS** | `EXP_JOBS=22 bash m1/exp-run.sh lean_nosjlj` |
| 2 | `anchor`：`MinSizeRel`(`-Os`)，带异常 | 51,580,817 | 13,301,149 | **10 PASS** | `bash m1/exp-run.sh anchor` |
| 3 | `anchor_oz`：锚点对象 + 链接 `-Oz` | 50,748,892 | 13,307,575 | 未单测² | `python3 m1/exp-relink.py --tool clang --name anchor_oz --build m1/build-exp-anchor --emcc="-Oz"` |
| 4 | `baseline`：`Release`(实际 `-O3`) | 71,055,261 | 16,400,451 | **10 PASS** | `bash m1/build-clang-wasm.sh clang` |
| 5 | `baseline` + `wasm-opt -Oz --converge`（26 分钟） | 69,913,426 | — | 未测 | 见 §2 |

² `anchor_oz` 与 `anchor` 只差链接旗标（对象文件完全相同），验收结论由 #2 覆盖；
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
| `anchor` + `wasmonly` | 13,301,149 | 8,495,303 | **21,796,452**（20.79 MiB） | **+45%** |
| **本轮最好（`lean_nosjlj` + `wasmonly`）** | **12,614,129** | **8,495,303** | **21,109,432**（20.13 MiB） | **+41%** |

⇒ **省下 4,951,205 B（−19.0%）**，距离达标还差 **6,109,432 B**。

这个组合整链跑过验收（**10 PASS / 0 FAIL**，日志 `m1/evidence/opt-lean_nosjlj-acceptance.log`）：

```sh
M1_TAG=lean_nosjlj M1_CLANG_BIN=m1/build-exp-lean_nosjlj/bin M1_LLD_BIN=m1/build-lld/bin \
  M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs
```

（`M1_TAG` 把这次验收的 `ARTIFACT` 键和基线那次分开，两趟的数字不会互相覆盖 ——
见该脚本的注释。）

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

## 3. 试过但**没用**的路（省下你重试的时间）

| # | 做法 | 结果 | 为什么 |
|---|---|---|---|
| 1 | `wasm-opt -Oz`（交接单已做） | raw −1.13 MB，brotli **−36 KB（0.2%）** | binaryen 已经跑过（见 §0）；再跑一遍只是把已消化的冗余再扫一次 |
| 2 | `wasm-opt -Oz --converge`（跑到不动点，26 分钟） | raw **69,913,426**（−1.14 MB，−1.6%） | 同上；brotli 层面收益只会更小 |
| 3 | 链接期 `-Oz`（不动对象，只换链接旗标） | clang raw −0.8 MB 但 brotli **+6 KB**；lld raw −1.0 MB / brotli **−24 KB（−0.25%）** | emcc 链接默认已按 `-O3` 跑 binaryen，`-Oz` 只是把同一批 pass 换个挡 |
| 4 | 把 `-DCMAKE_C_FLAGS="-O1"` 改成 `-Os`（照交接单字面做） | **实测无效**：`Release` 在后面追加 `-O3 -DNDEBUG`，emcc 认最后一个 `-O` ⇒ 只改 `-O1` 那一处等于没改 | 必须改 `CMAKE_BUILD_TYPE` 才真正换挡；这正是 §0 的发现，也是**本单唯一的大杠杆**（−18.9%） |
| 5 | `-fno-exceptions -fno-rtti`（配置名 `lean`，**第一次**） | **链接失败** | 链接行里同时有 `-fno-exceptions` 与 `-fwasm-exceptions`，emcc 选了不带 `emscripten_longjmp` 的 builtins 变体。**这是旗标问题，不是源码问题** —— 根因与正解见 §5.2.2（后来打通了：−5.2%，配置名 `lean_nosjlj`） |
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
| **本轮最好组合**：clang `lean_nosjlj` + lld `wasmonly` | `M1_CLANG_BIN=m1/build-exp-lean_nosjlj/bin M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs` | **10 PASS / 0 FAIL**，`minifn.so` = 976 B（与基线同尺寸） |
| `anchor` + `wasmonly` | 同上，`M1_CLANG_BIN=m1/build-exp-anchor/bin` | **10 PASS / 0 FAIL** |
| lld `wasmonly`（单查） | `M1_LLD_BIN=m1/build-lld/bin M1_LLD_JS=lld-wasm-only.js node m1/acceptance-lld-only.mjs` | **8 PASS / 0 FAIL** |
| lld `baseline`（对照） | `node m1/acceptance-lld-only.mjs` | 8 PASS / 0 FAIL |
| clang `anchor_oz` | 未单测（对象与 `anchor` 相同，只差链接旗标） | — |

**`lean_nosjlj` 的验收值得一提**：它不仅"能启动"，还**真的编出了带 STL 的 C++ 对象**
（`std::string` 那支夹具），并被 `wasmonly` 链成 ABI 正确的 side module。
⇒ 「关掉异常」关掉的是**编译器自身**的异常，不影响它**编译别人的代码**。

`m1/acceptance-lld-only.mjs` 是本轮新增的：只跑"链接"那一半，输入固定为
`m1/acceptance/hello.o`，所以 lld 是唯一变量（`acceptance-full.mjs` 会先编译，慢一个数量级）。
`m1/acceptance-full.mjs` 也顺手参数化了（`M1_CLANG_BIN` / `M1_LLD_BIN` / `M1_LLD_JS`），
下一轮复核整体组合时不用再改脚本。

---

## 5. 进一步减重的路径（与 §0.1 的口径结论配套读）

> **先看 §0.1**：按 SPEC 字面的**首拉**口径，15 MB **已经达标**（14.31 MB）。
> 本节讨论的是**另一个问题** —— 如果委托人裁定预算管的是**总量**（22.80 MB，超 52%），
> 还能往哪儿压。两条路都不轻松，所以结论是"按总量口径，现有功能集合下不成立"。

### 5.1 为什么"总量到不了 15 MB"不是因为没试够

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

> **⚠️ 本节第一版把根因写错了，已更正（2026-10-10 复核）。**
> 原文说"要做成需要改源码"——**不对**。真实原因是我方旗标自相矛盾：
> 编译期给了 `-fno-exceptions`，而链接行里还留着 `-fwasm-exceptions`，
> emcc 因此选中 `libclang_rt.builtins-legacysjlj`（该变体**不提供**
> `emscripten_longjmp`），于是链接期缺符号。
> 复核与独立验证见 `m1/OPT-REVIEW.md` §1；逐条判据见本节末尾。

**真实机制**（`toolchain/emsdk/.../sysroot/lib/wasm32-emscripten/` 下逐档 `llvm-nm` 实测）：

| builtins 变体 | 有 `emscripten_longjmp`？ |
|---|---|
| `libclang_rt.builtins.a` / `-mt` / `-ww` | **有** |
| `libclang_rt.builtins-legacysjlj*.a` | **无** |
| `libclang_rt.builtins-wasmsjlj*.a` | **无** |

第一次 `lean` 的链接行里同时有 `-fno-exceptions`（×2）与 `-fwasm-exceptions`（×1）
⇒ emcc 走 legacy-SJLJ 那一支 ⇒ 拿到没有 `emscripten_longjmp` 的 builtins ⇒ 缺符号。

**正解不是改源码，是改旗标**：

```
-Os -fno-exceptions -fno-rtti -sSUPPORT_LONGJMP=wasm      # 链接期不要带 -fwasm-exceptions
```

对应的实验配置是 `m1/exp-run.sh` 的 `lean_nosjlj`。**实测结果见 §5.2.1。**

**另一条 cmake 侧的硬约束**（本轮实测撞到两次）：`LLVM_ENABLE_RTTI=OFF` 只有在
`LLVM_ENABLE_EH=OFF` 时才被允许（`HandleLLVMOptions.cmake:1244` 反过来也拦）。
所以正确姿势是 `-DLLVM_ENABLE_EH=OFF`，RTTI 在**编译器层**用 `-fno-rtti` 关。

#### 5.2.1 实测：`lean_nosjlj` —— **这根杠杆真的打通了，而且是新的最优**

**结论：关掉 C++ 异常 + RTTI 是有效的，clang brotli 13.30 → 12.61 MB。**

| clang 配置 | raw | brotli q11 | 验收 |
|---|---|---|---|
| `anchor`（`-Os`，带异常） | 51,580,817 | 13,301,149 | 10 PASS |
| **`lean_nosjlj`（`-Os` + 关异常 + 关 RTTI）** | **48,069,274** | **12,614,129** | **10 PASS** |
| 相对 `anchor` | **−6.8%** | **−5.2%** | 产物 976 B 同尺寸 |

⇒ 异常 + RTTI 的代价是 **687 KB brotli**（约 5.2%）。
比我原来的乐观预估（10–20%）小得多 —— 这也是一条**该被记下来的负结果**：
"关异常"对 LLVM 这种以 C++ 为主但异常使用密度不高的代码库，收益是**个位数百分比**。

**新的最好组合**：

| | clang | lld | 合计（**总量**口径） | vs 15 MB |
|---|---|---|---|---|
| 基线 | 16,400,451 | 9,660,186 | 26,060,637 | +74% |
| `anchor` + `wasmonly` | 13,301,149 | 8,495,303 | 21,796,452 | +45% |
| **`lean_nosjlj` + `wasmonly`** | **12,614,129** | **8,495,303** | **21,109,432** | **+41%** |

⚠️ 这张表是**总量**口径。按 §0.1 论证的 SPEC 字面口径（**首拉**），
真正的数字是 **14.31 MB ⇒ 达标**（lld 懒加载、不计入首拉）。**两个口径都在这里，别只看一张。**

#### 5.2.2 真正的根因（两轮 agent 都猜反了，以实测为准）

复核者（`m1/OPT-REVIEW.md` §1）指出"不是要改源码，是旗标冲突"，**方向对**；
但它给的确切修法（`-sSUPPORT_LONGJMP=wasm`）**是把情况弄坏，不是修好**。实测：

| 链接旗标 | emcc 选中的 builtins 变体 | 该变体有 `emscripten_longjmp`？ | 结果 |
|---|---|---|---|
| 带 `-sSUPPORT_LONGJMP=wasm`（默认 `WASM_LEGACY_EXCEPTIONS=true`） | `libclang_rt.builtins-legacysjlj` | **无** | **链接失败** |
| **不设** `SUPPORT_LONGJMP` | `libclang_rt.builtins` | **有** | **链接成功** |

机制在 emscripten 自己的源码里（`tools/system_libs.py:898` 的
`get_default_variation`）：

```python
if settings.SUPPORT_LONGJMP == 'wasm':
    if settings.WASM_LEGACY_EXCEPTIONS:      # 默认 true（settings.js:803）
        eh_mode = Exceptions.WASM_LEGACY      # -> 名字后缀 '-legacysjlj'
    else:
        eh_mode = Exceptions.WASM              # -> '-wasmsjlj'
else:
    eh_mode = Exceptions.EMSCRIPTEN            # -> 无后缀，即 builtins.a
```

`-fno-exceptions` 下 `CrashRecoveryContext.cpp` 的 `setjmp/longjmp` 正好展开成
`emscripten_longjmp`，而 `-legacysjlj` / `-wasmsjlj` 两个变体都**不含**这个符号
（`llvm-nm --defined-only` 逐档验过，见 `m1/OPT-REVIEW.md` §1.2 的表 —— 那张表是对的）。

⇒ **正解 = 不设 `SUPPORT_LONGJMP`，让 emcc 留在 `Exceptions.EMSCRIPTEN`。**

**完整可复跑的 flag（这就是新基线）**：

```
# cmake
-DCMAKE_BUILD_TYPE=MinSizeRel
-DLLVM_ENABLE_EH=OFF                    # RTTI 必须留 ON（见下）
-DCMAKE_C_FLAGS="-Os -fno-exceptions -fno-rtti -fno-unwind-tables -fno-asynchronous-unwind-tables"
-DCMAKE_CXX_FLAGS=<同上>
-DCMAKE_EXE_LINKER_FLAGS="-sWASM=1 -sALLOW_MEMORY_GROWTH=1 -sSTACK_SIZE=5242880 \
  -sEXIT_RUNTIME=0 -sINITIAL_MEMORY=268435456 -sFORCE_FILESYSTEM=1 -sMODULARIZE=1 \
  -sEXPORT_NAME=createToolChain \
  -sEXPORTED_RUNTIME_METHODS=FS,callMain,ccall,cwrap,getValue,setValue"
  #                                  ^^^ 注意：**没有** -fwasm-exceptions，**没有** SUPPORT_LONGJMP
```

⚠️ **`-DLLVM_ENABLE_RTTI=OFF` 不能给**：`HandleLLVMOptions.cmake:1244` 有硬判据
「`LLVM_ENABLE_EH=ON` 时 RTTI 必须 ON」（反过来 `EH=OFF` 配 `RTTI=OFF` 本轮也撞到了
一次 FATAL）。RTTI 改在**编译器层**用 `-fno-rtti` 关 —— 那才是进代码生成的那个开关。

⚠️ **执行诚实交代（已解决）**：`ninja` 第一次跑这个配置时，链接行里带的是
`-sSUPPORT_LONGJMP=wasm` ⇒ 失败。把该旗标去掉后**重跑 `m1/exp-run.sh lean_nosjlj`，
ninja 一把过**，上表数字即来自那一趟（`m1/evidence/opt-lean_nosjlj.log`，
配置已改对，别人复跑得到同样的值）。**失败那一次**的报错原文附在同一份日志末尾 ——
它是翻案 R-008 的证据，故意留着。

⚠️ **一个顺手修掉的量测缺陷**：`gzip -9 -c <file>` 会把**文件名**写进 gzip 头，
于是"同一份字节流"在两条路径下量出的 gzip 值不同（实测 17,317,088 vs 17,317,077）。
`m1/exp-build.sh` 现在用 `gzip -9 -nc`（`--no-name`），量的是内容本身。

同一族还有第二个坑：**Python 的 `gzip.compress` 与 GNU `gzip -9` 也不同值**
（同一份 48,069,274 B 实测：python 17,308,255 / GNU `-n` 17,170,777）。
两者都"对"，但**混用就是两个口径**。本表的 gzip 一律以 `m1/exp-build.sh` 的
GNU `-9 -nc` 为准。

`m1/build-clang-wasm.sh` 里基线那两行仍是 `gzip -9 -c`（**未改** —— 交接单要求
基线脚本行为不动）。它量的是固定 basename，所以**复跑仍一致**，但与本表口径不统一：
拿它和 `[[anchor_clang_wasm_gzip]]` 直接相减会**多算**几个字节。要比 gzip 就都用 `-nc`。



### 5.3 「只支持 C」这条路的实测上限（**我先前是拍脑袋的，这里补实测**）

我在 §8 与问卷 C0 里写过"唯一可能达标的方向是只支持 C（丢掉整个 C++ 前端）"。
**那句话没有实测支撑，而且按实测是错的。** 用链接器 map 文件按库归因
（`python3 m1/exp-map-attrib.py --make-map …`，逐符号把 CODE 段归属到 `.a`；
口径与坑都写在脚本注释里）：

| 库 | CODE 占用 | 占比 |
|---|---|---|
| `libclangSema.a` | 7,822,306 | 14.02% |
| `libclangAST.a` | 6,255,091 | 11.21% |
| 其余（CodeGen / LLVM 后端与优化 / Basic / Driver / …） | 41,719,571 | 74.77% |

**关键更正**：`clangSema` + `clangAST` 是**C 与 C++ 共用**的（词法/语法/语义/常量求值
对 C 一样要跑），**不是"C++ 前端"**。按文件名把"非 C 语言特性"挑出来：

| 族 | CODE 占用 | 占 CODE 段 |
|---|---|---|
| C++ 模板/概念/协程 | 2,964,289 | 5.31% |
| OpenMP | 2,242,287 | 4.02% |
| ObjC/ARC | 665,972 | 1.19% |
| HLSL/DXIL | 567,053 | 1.02% |
| CUDA/HIP/SYCL | 286,447 | 0.51% |
| **合计** | **6,726,048** | **12.05%** |

⇒ **把所有非 C 语言特性全砍光（乐观上限，现实里做不到 —— 它们散在共用文件里，
见 `SemaDecl.cpp` 里 383 处 `CXX`），brotli 也只到约 11.09 MB；加 lld 8.50 MB = 19.59 MB，
仍超 15 MB。** 而且上游**没有**"只编 C"的构建开关（`grep CLANG_ENABLE_C_ONLY` 为空），
要做只能改源码。

**结论**：**"只支持 C"救不了总量口径**。这条我先前的判断是错的，以本表为准。

### 5.4 其它还没试、但按 §5.1 的量级判断收益有限的

- 裁 `clang/lib/Driver`：交接单点名过。`libclangDriver.a` 进 CODE 段约 1.70 MB（2.7%），
  而且要保住 `-cc1` 就不能丢 `cc1_main.cpp` + `FrontendTool`。
  **判断：收益在 0.3–0.8 MB brotli 量级，不是决定性杠杆。**
- 分片懒加载（交接单实验 F）：**这条现在最重要** —— 它正是 §0.1 里"首拉达标"的
  机制本身（lld 懒加载）。**已由驱动实现**（`driver/toolchain.mjs` 的 `async lld()`），
  本轮把它量成了首拉分解（`m1/exp-firstload.sh`）。

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

1. **★ 预算口径要委托人拍板**（唯一真正卡住的事，见 §0.1）：
   SPEC §6 写「brotli ≤ 15 MB（**首拉**）」但同段那张表把三资产求和叫「合计」。
   **首拉口径 14.31 MB ⇒ 已达标；总量口径 22.80 MB ⇒ 超 52%。**
   在这一点定下来之前，不需要再花时间减重。
2. **让 `lean_nosjlj` 由 ninja 一把跑通** —— **已完成**（重跑 `m1/exp-run.sh
   lean_nosjlj`，ninja 一把过，值不变）。剩下的是把 `m1/build-clang-wasm.sh`
   的 gzip 也换成 `-nc`，统一口径（那是基线脚本，改动要经委托人同意）。
3. **「只支持 C」这条已实测证伪**（§5.3）：把所有非 C 语言特性全砍光的**乐观上限**
   也只到 19.59 MB，仍超 15 MB；且上游没有对应构建开关。**别再往这个方向花时间。**
4. **若委托人裁定是总量口径**，剩下的路只剩两条，且都不在编译配置里：
   - 真正动源码做功能裁剪（§5.3 的 12.05% 是乐观上限，实际能拿到的远小于此）；
   - 或改交付形态（更激进的懒加载分层：例如把 CodeGen 也拆出去按需拉）。
5. `clang.js` 胶水（brotli 18,682 B）没优化；量级可忽略，别再花时间。
6. **首拉分解已经是可复跑的量测件**（`m1/exp-firstload.sh`，产地
   `m1/evidence/opt-firstload.log`）—— 以后任何改动都可以拿它验首拉有没有回退。
