# clang-wasm 工具链：M0 实测后发现的问题与待决事项

**Purpose:** M0（原生手工命令跑通 SPEC §4 全链）已做完并全绿。过程中实测出**四处与 SPEC 不符**和**两处需要你拍板的边界**。这份问卷要把这些不确定项一次性问清，然后才能开工 M1（把 clang+lld 编成 wasm）。

**From:** ArchivalEra（工具链侧执行） **To:** SPEC-clang-wasm.md 的委托人
**How your answers will be used:** 直接决定 M1 的编译矩阵、符号契约的实现方式、以及 manifest 里要钉的版本串。

---

## Context

**已完成**：按 SPEC §10 的 M0，用手工命令（裸 `clang` + `wasm-ld`，side module 全程不经 emcc）编出 side module，被 emscripten 主模块 `dlopen` 并调用成功。wasm32 与 wasm64 两档都过：符号解析、回调宿主符号、异常双向穿越 dlopen 边界、`std::map` + `std::ostringstream` 模板实例化全部正确。

**复跑**（全部 PASS 行都是它打出来的）：

```sh
cd LLVM-wasm && sh m0/run-m0.sh            # wasm32
ARCH=wasm64 sh m0/run-m0.sh                # wasm64
sh m0/run-counterexamples.sh               # §9.5 反例 + §9.6 模板缺口
```

完整记录见 `m0/RESULTS.md`。**工具链侧的环境是 emsdk 6.0.12 / clang 24.0.0git / LLD 24.0.0**（按你的指示装的 6.x；下游宿主容器是 `emscripten/emsdk:5.0.7`）。

**M0 全绿的含义**：SPEC §4 记录的 ABI 侧五处"缺一不可"全部复现，**没有未知的 ABI 障碍**。下面的问题都不是"能不能做"，而是"做成哪一种"。

---

## How to answer

不着急，但 M1 卡在 A 组。**分条答复即可，不确定就写"不确定"**——比跳过有用，我会按"不确定"处理（要么补实验，要么标记为悬案）。每条下面留了空行，直接写。

---

## A. 版本与异常模型（阻塞 M1，最优先）

### A1. 工具链用 6.x、宿主用 5.0.7——这个偏差是有意的吗？

SPEC §8 要求「`crtbegin-mt.o`、`-L <SR>/lib/<target>-emscripten/pic`、libc++ 头、`__config_site` **必须与宿主主模块的 emscripten 版本完全一致**，不一致 fail-closed」。你指示我装 6.x，但下游宿主实测是 5.0.7（`upstream/emsdk` submodule 钉在 `41190c21`）。

_Why this matters: 如果宿主会升到 6.x，则无冲突；如果不升，SPEC §8 的 fail-closed 会**主动拒绝**这套 6.0.12 的 sysroot。我按哪个版本做 M1 的编译矩阵，取决于这条。_

```
```

### A2. 如果两边版本必须一致，宿主的升级是这条线的任务吗？

5.0.7 → 6.x 会牵动下游整棵树（NOTES-upstream.md 记着"全部车道依赖 farm 重编，单独立项"）。

```
```

### A3. 异常模型其实是**四档**，SPEC §4.5 只列了三档——第四档（legacy vs standard wasm EH）怎么归？

SPEC §4.5 说「异常模型 / pthread / memory64 三项必须与宿主一致」。实测 emcc 6.x 里 `-fwasm-exceptions` 是**两档**：`WASM_LEGACY_EXCEPTIONS` 默认 `true`（`src/settings.js:803`），此时系统库选 `libc++-mt-legacyexcept.a`；加 `-sWASM_LEGACY_EXCEPTIONS=0` 才走标准 wasm EH（选 `-wasmexcept` 变体）。裸 clang 24 默认是标准 EH。两档产出的 tag 形态不同，混用装不上（装得上也跑不对）。

_Why this matters: 这不是 flag 拼装细节，而是 §7 那个 `compile({ abi: { exceptions: 'wasm'|'emscripten'|'none' }})` 的**接口要不要多一个字段**（wasm EH 的 legacy/standard 档）。两边各猜一次 ⇒ 必然漂移，正是 §4.5 要防的。另外我先确认：下游宿主 5.0.7 构建时走的是哪一档？（这决定 6.x 工具链该默认产哪一档。）_

```
```

---

## B. 宿主符号契约（决定交付边界）

### B1. 宿主符号契约：`MAIN_MODULE=2` + keep-list 现状下，工具链的检查基线是什么？

实测确认（下游产物自带的 `octave.build.json`）：

```json
"declared": { "main_module": 2, ... }
"measured": { "exported_functions": 752, ... }
"inputs":   { "keep_list": { "...": "keep-w64.txt", "lines": 1304 } }
```

即宿主确实是 **MM=2 + 1304 行 keep-list**，最终导出 **752** 个函数，**且其中含 `__cpp_exception`**（tag）。我在 M0 里验证过这条路的可行性：MM=2 + 从 side module 导入生成的 50 行 keep-list ⇒ 宿主导出 76 个（含 tag），dlopen **全绿**。

_Why this matters: 这条确认了 SPEC §5.3「宿主补导出」是**可行的主路**（不是退路），也解释了为什么现状能跑。但 752 这个基线是**随 keep-list 变的**——工具链的 §5.4 检查器该拿哪一份导出面做判定？是跟着每次宿主编译的 `octave.build.json` 走（它已经写了 `measured.exported_functions`），还是要求宿主另给一份稳定的"承诺导出清单"？_

```
```

### B2. 有一个符号宿主里**根本不存在**，keep-list 救不了——这条缺口怎么办？

实测（`needlib-noa.oct`，22,910 B，与 SPEC §5.3 记载的字节数一致）对真实宿主：

| 口径 | 缺口 |
|---|---|
| SPEC §5.2 原口径（不扣 side 自导出） | 2 个 |
| 修正口径（扣掉 side 自己导出的） | **1 个**：`_ZNSt3__213basic_ostreamIcNS_11char_traitsIcEEElsEm` |

第 2 个（那个 `__tree::__emplace`）**side module 自己导出了**，emscripten 加载器从 `moduleExports` 就解析掉了 ⇒ 它不是真缺口。剩下这 1 个是**真缺**：我把整个宿主反汇编（20,754,803 行）搜过，该符号**在宿主里既无定义、也不在导出表**。

_Why this matters: SPEC §5.4 给了两条路——「宿主补导出」和「可选自包含模式」。对这个符号，**宿主补导出不可行**（没有东西可补，得先让宿主真的用到 `ostream<<unsigned long` 这个实例化）。所以问题变成：交付物要不要默认走自包含模式（把 libc++ 目标文件链进产物，20 KB → 1.1 MB 量级），还是坚持"宿主承诺可解析"+ 响亮报错？_

```
```

### B3. 「响亮报错」的检查器，口径以哪个为准？

SPEC §5.4 第 3 条要求工具链主动比对「产物的 `env` 导入」与「宿主导出」并点名缺失。M0 发现**直接比会误报**——`--export-dynamic` 让 side 既导入又导出同一符号（GOT 自引用），而 emscripten 的 `resolveSymbol` 把 `moduleExports` 当合法解析源。我已按修正口径实现（`m0/check-symbol-gap.mjs`，另把 **tag** 单列一类）。

_Why this matters: 口径差一个 `sideExports` 差集，就会在真实 `.oct` 上报出假缺口（实测 2 vs 1）。下游 `check-oct-host-symbols.mjs` 用的是未修正口径。要不要我把它一并改掉、或把这个判定收进工具链？_

```
```

### B4. 真实 `.oct` 里近一半导入异常 tag——keep-list 流程知道这件事吗？

抽样 40 个真实 `.oct`，**19 个（47.5%）导入 `env.__cpp_exception`**。好消息：下游 `gen-keep-list.sh` 用 `wasm-dis` 读 IMPORT 段、正则 `^ \(import "(env|GOT\...)" "..."`，**实测能匹配到 tag 导入行**（`(import "env" "__cpp_exception" (tag ...))`），配合 `-Wl,--export-if-defined=` 喂给主链是有效的（我验证过：MM=2 + 50 个符号的 keep-list，宿主导出 76 个含 tag，**全绿**）。

_Why this matters: 这说明 tag 缺口**只需把 tag 名放进 keep-list 就能修**，不必动 MM=1。但下游脚本目前是靠"从 .oct 扫导入"隐式拿到的——一旦某个 `.oct` 有异常但没被扫到，就会退化成 SPEC §5.1 那种"装得上、跑到才炸"。要不要把 tag 做成**显式必带项**（不依赖扫描）？_

```
```

---

## C. 交付与许可

### C1. 交付物的 LICENSE 到底写哪个？仓库现在是 AGPL-3.0，SPEC §2 写的是 LLVM 的 Apache-2.0-with-LLVM-exception。

SPEC §2 交付物表最后一行：「`LICENSE` | LLVM（Apache-2.0 with LLVM exceptions）+ 胶水」。但**当前仓库根的 LICENSE 是 AGPL-3.0**（544 行，与下游 Octave 仓的 AGPL 文本仅差一个换行）。

_Why this matters: 两者不兼容的方向正好相反——AGPL 会"传染"到下游（下游整体已是 AGPL-3.0-or-later），而 LLVM 的 Apache-2.0-with-exception 不会。这个仓库要作为 submodule 被下游钉住，选哪个直接决定下游的分发义务。_

```
```

### C2. 我去找委托人前需要知道：这个仓是**独立公开**的吗？

`ArchivalEra/LLVM-wasm` 当前公开、只有 LICENSE 一个文件（加我这次提交的三样）。

```
```

### C3. wasm64 的 sysroot 是**按需生成**的，交付物里要不要预生成？

实测 6.0.12：`<SR>/lib/wasm32-emscripten/pic/` 与整个 `<SR>/lib/wasm64-emscripten/` **初始都不存在**，要跑一次对应 target 的编译才生成（`crtbegin-mt.o` 由 emcc 在需要时编出，`emcc -v` 会打 `cache:INFO: generating system asset: ...`）。SPEC §5.1 的 §6 体积预算把 sysroot 算成一份 tar。

_Why this matters: 浏览器里没有 emcc 可以"按需生成"这些。工具链得决定：sysroot tar 里**预置** pic/crtbegin 与 wasm64 全套（体积涨），还是自己在 wasm 内生成（M2 的工程量涨）。_

```
```

---

## D. 验收口径的两处更正（需要你确认，不是问答题）

### D1. §9.5「去掉 `-fwasm-exceptions` ⇒ 必须装不上」——实测是**装得上，跑到第一次 throw 才炸**。

SPEC §9.5 与 §4.4 反例都写「去掉 ⇒ 装不上（`LinkError: Incompatible version`）」。我实测（6.0.12 + LLVM 24）：那样编出的 side **`PASS dlopen`、通过 9 项检查**，直到第一次 C++ throw 才抛未捕获 `WebAssembly.Exception`。

_Why this matters: 这跟 SPEC §5.1「装得上 ≠ 跑得对」是同一类失效，但**更隐蔽**——加载器不拦，只有真跑到异常路径才暴露。所以第 5 条的验收必须**跑到运行期**，"链接期报错"这个预期本身要改。你同意改措辞吗？_

```
```

### D2. §4.2 的链接命令行在 LLVM 24 上有一处**已失效**。

`-mllvm -wasm-enable-eh` 在 LLVM 24 已不存在，`wasm-ld` 直接报 `Unknown command line argument '-wasm-enable-eh'`（提示 `Did you mean '--wasm-enable-sjlj'?`）。去掉它、只留 `-mllvm -exception-model=wasm` 即可。另外 `--experimental-pic` 现在是 no-op（help 原文：`Legacy enable Experimental PIC flag; ignored`），留着无害。

_Why this matters: 这直接印证 SPEC §4.5「不要内置旗标表」的正确性——现在连 `-mllvm` 选项也得按版本参数化。确认一下我按"去掉 `-wasm-enable-eh`"修 SPEC §4.2，还是你想保留原文另加版本注记？_

```
```

---

## Anything else?

- M0 绿了，**M1 我按你的答复开工**。若 A 组暂时答不了，我可以先把 M1 的"能跑不优化"部分做起来（用 6.0.12，把版本一致性当已知偏差记着）。
- SPEC §6 那张体积表（LLVM 8 的 57.22 MB raw / 13.07 MB brotli）你标了"**你的第一件事就是把它量成实测**"。M0 不涉及它；M1 编出 wasm 后我会补一版**现代 LLVM 24 的实测表**替换它。
- 还有什么我没问到、但会影响工具链形态的事？

```
```
