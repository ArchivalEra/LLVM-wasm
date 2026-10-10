# M1 结果：把 clang 与 lld 编成 wasm，并在 wasm 里跑通「源码 → side module」

> 状态：**绿**。测于 emsdk [[emcc_version]]（clang [[clang_major]] / lld [[lld_major]]），
> LLVM 源码 = emsdk 钉的 commit `55ea1f4e`，`-O1`、只开 WebAssembly 后端，**未做体积优化**。
> 数字全部来自 `FACTS.json`（本文不手抄；`[[键名]]` 由闸门对账）。

复跑：

```sh
bash m1/build-clang-wasm.sh both    # 编 clang + lld（约 20–30 分钟，24 核）
node m1/acceptance-full.mjs         # 在 wasm 里编 + 链，产出 side module 并查 ABI
```

---

## 1. 结论：M1 通过

SPEC §10 M1 的目标是「clang+lld 编成 wasm（先求能跑，不优化体积），浏览器里编出 §9.1 的产物」。
**达成**，且是在 wasm 内部完成全链：

```
clang.wasm  --(内存 FS)-->  hello.o
lld.wasm    --(内存 FS)-->  minifn.so     ← Side module ABI 正确
```

验收 [[m1_acceptance_pass]] 项 PASS / 0 FAIL：编译器与链接器都以 0 退出，产物
[[m1_sidemodule_bytes]] B，导出 `minifn` / `__wasm_call_ctors` / `_emscripten_tls_init`，
导入 `env.memory` / `__memory_base` / `__table_base`，二进制带 `dylink` 段。

**与 M0 的关系**：M0 证明了「手搓的 side module 能被真宿主装」；M1 证明了
「这份 side module 能在浏览器里被造出来」。两段合起来，SPEC 的核心链路成立。

---

## 2. 体积实测（SPEC §6 那条悬案的答案）

| 资产 | raw | gzip -9 | brotli -q11 |
|---|---|---|---|
| `clang.wasm` | [[m1_clang_wasm]] | [[m1_clang_wasm_gzip]] | [[m1_clang_wasm_brotli]] |
| `lld.wasm`（wasm-ld） | [[m1_lld_wasm]] | [[m1_lld_wasm_gzip]] | [[m1_lld_wasm_brotli]] |
| `clang.js` 胶水 | [[m1_clang_js]] | — | — |

**两处与 SPEC §6 的出入**（§6 的表是 LLVM 8 的，它自己标了"推断"）：

| | SPEC §6 说 | 实测（LLVM 24） |
|---|---|---|
| raw 量级 | 推断 35–60 MB | **单 clang.wasm 就 71 MB**，两个合计 110 MB ⇒ 推断偏低 |
| brotli 预算 | ≤ 15 MB（首拉） | **两个 wasm 合计 26.1 MB** ⇒ 超预算约 74% |

⇒ §6 列的减重手段（`-Os`/MinSizeRel、`wasm-opt -Oz`、只带 `-cc1` 不带完整 driver）
**从"进一步优化"升级为"必须做"**，否则 §6 的预算目标不成立。这条已写进 `questions/01`（已结案）。

---

## 3. 过程中踩到的四个坑（都有报错原文，M2 会再遇到）

### 坑 1：`-s` 旗标放编译期 = 静默失效

`em++ -sFORCE_FILESYSTEM=1 -sNODERAWFS=1 ... -c foo.cc` 会打
`em++: warning: linker setting ignored during compilation: 'FORCE_FILESYSTEM'`，
**旗标被丢弃**。后果：编出的 clang **看不见任何文件系统**，连 `clang -c t.c` 都报
`no such file or directory`。⇒ 所有 `-s` 旗标必须走 `CMAKE_EXE_LINKER_FLAGS`，不能进 `CMAKE_CXX_FLAGS`。

### 坑 2：不开 `MODULARIZE` 就没有进程内入口

默认产物在加载时直接跑 `main()` 并**不导出任何东西**（实测 `grep -c module.exports` = 0），
宿主没法"调用编译器"——而那是 SPEC §7.1 的全部意义。
⇒ 必须 `-sMODULARIZE=1 -sEXPORT_NAME=createToolChain -sEXPORTED_RUNTIME_METHODS=FS,callMain,...`。

### 坑 3：lld 是**通用驱动**，按 `argv[0]` 分派

直接 `createLld()` + `callMain(['-mwasm32', ...])` 会得到：

```
lld is a generic driver.
Invoke ld.lld (Unix), ld64.lld (macOS), lld-link (Windows), wasm-ld (WebAssembly) instead
```

**一行修法**：`createLld({ thisProgram: 'wasm-ld' })`（emscripten 胶水读 `Module.thisProgram`
当 `argv[0]`）。`bin/wasm-ld.js` 只是个指向 `lld.js` 的符号链接——链接本身不带信息。

### 坑 4：每个模块有自己的 FS

clang 与 lld 是两个独立实例，**不共享内存 FS**。往 lld 写 `hello.o` 前必须先
`lld.FS.mkdirTree('/src')`，否则 `writeFile` 抛 `ErrnoError errno=44`。
M2 若把两者合成一个模块（SPEC §2 允许），这个坑自然消失。

---

## 4. 本次的编译配置（M2/M3 的起点）

```sh
emcmake cmake -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_PROJECTS="clang;lld" \
  -DLLVM_TARGETS_TO_BUILD=WebAssembly \
  -DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DCLANG_ENABLE_STATIC_ANALYZER=OFF -DCLANG_ENABLE_OBJC_ARC=OFF -DCLANG_ENABLE_FORMAT=OFF \
  ... 详见 m1/build-clang-wasm.sh
```

- 只开 WebAssembly 后端（SPEC §6 的减重方向之一）已生效，体积仍 71 MB ⇒
  **光靠"只留一个后端"不够**，下一步要动 `-Os` / `wasm-opt -Oz` / 裁 driver。
- `-O1` 是刻意的：M1 只求能跑。M3 再谈 `-Os`。

---

## 5. 与下游的衔接（M2 要做的事）

M1 的产物**还不能直接给下游用**，缺的是 SPEC §7 的其余部分：

1. **Worker 化**（§7.3）—— 现在是在 node 里跑，浏览器里要进 Web Worker。
2. **薄驱动**（§7.5）—— 现在验收脚本是手拼 §4.1/4.2 的 argv；要封成
   `compile({source, target, abi, hostExports, ...})`（§7.4）的接口。
3. **§5.4 缺口检查**接进驱动 —— `m0/check-symbol-gap.mjs` 已有实现，要搬进工具链。
4. **sysroot 打包**（§6）—— 现在是从宿主 sysroot 目录喂进 FS；
   交付物要变成 tar（且 `pic/crtbegin-mt.o`、wasm64 那套要**预生成**）。

---

## 6. 文件

| 文件 | 作用 |
|---|---|
| `build-clang-wasm.sh` | 编 clang / lld 成 wasm（`clang` / `lld` / `both`） |
| `acceptance-full.mjs` | 全链验收：wasm 内 编译+链接，查 side-module ABI |
| `acceptance.mjs` | 只到编译那一步（更快的冒烟） |
| `evidence/build-*.log` | 构建日志（含 `ARTIFACT` 行 = 体积数字的产地） |
| `evidence/m1-acceptance.log` | 验收日志（含 `ARTIFACT` 行） |
