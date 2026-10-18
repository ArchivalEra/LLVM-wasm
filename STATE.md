# STATE · 活状态

正文只写「现在是什么」，**数字一律引用台账键**（或看文末机器块）。
M0 的完整记录见 `m0/RESULTS.md`；M1 见 `m1/RESULTS.md`。

## 现在是什么

- **工单 65 缺口 2（`_ZTIi`）已裁决 = A**（宿主 `027`/本仓 `011`）：宿主**接受我的"第三种情况"判定**
  并选择支持基本类型 throw；keep 生成器与容器内 keep 已补 7 条基本 typeinfo（零风险半），
  **重链留作独立批**（`ready-for-human`，产品决定）。本仓侧：缺口检查**未撤**（宿主明言
  "别提前撤"）且升格为持久回归 `driver/check-ztii-regression.mjs`
  （[[ztii_regression_pass]] PASS）——它把裁决时间表钉进验收：**重链前**点名 `_ZTIi`
  （编译期提示），**重链后**自然打出 "ruling A has landed"，与宿主
  `probe-toolchain-gap` 的翻绿互为旁证。
- **一处口径教训**（内容仓 `mail/010` 抓的，对）：`mail/009` 手抄了台账旧值
  （3,592/10,246），同批提交里全量重扫落账 4,084/11,663 ⇒ 信里数字当场过期。
  **信里引台账数字写键名，不写数值**（与正文同一条纪律，散文体是它的盲区）。

- **接缝线已收**（`mail/005`/`006` → `mail/007`）。宿主三答落定：`license` 保持自由字符串
  （**不改形状**，但 tar 内已带三份许可，`see …` 指得到）、**13 条合法**（"普通"= 不特殊，
  非"只能一条"）、**表已被宿主 `--upstream` 复跑并入并 `ok`**。我另从**生产者侧**结了三个
  "本批不实现"的悬案：`pin` 改 `release:` 前缀，且**真去核存在性**
  （tag/远端/release 三查；故意破坏验过会红）、`license_files` 的路已铺（包内确有许可原文）、
  无前缀 pin 会**打 NOTE**（合法但无类型）。

- **接缝记录已过宿主的校验器**（`mail/003` 报了两处必修，都已修，见 `mail/004`）：
  `content: []`（能力层按宿主裁决留空）、`producer.id` 小写、新增 `upstream_url`
  （指向**可重取的 bundle**，不是逐文件的假 URL）。v0.1.2 已发布 ⇒ pin 指向真实发布。
  **最重要的更正**：我的自检只查"记录有没有写错自己"，**看不见宿主 `content` 词表的存在** ——
  同一条记录我自检 26 项全绿、宿主校验器 19 条 PROBLEM。现在 `check-content-list.mjs`
  **直接跑宿主那份校验器**（两模式；不在本机时明说 SKIP，不 vendor 副本）。

- **接了「额外内容」接缝的报送**（`mail/001` → `mail/002`）：本仓的 13 个资产已按 schema 2
  出一条 content-list（[[content_list_entries]] 条），**由 `make-content-list.mjs` 从 manifest
  派生**（一处产地，两个输出），记录在 `release/content-list.json`（git 追踪）。
  自洽性检查 [[content_list_check_pass]] PASS —— **不是**宿主校验器（它尚未落地），
  只是"记录没写错自己"。同时抓到并修掉一个真合规缺口：sysroot tar 里 442/1578 个文件
  不带许可声明 ⇒ tar 内已补 `LICENSE-LLVM.txt` / `LICENSE-EMSCRIPTEN.txt` / `NOTICE`，
  tar 因此变为 [[sysroot_wasm32_tar]] B（sha256 已更新）。

- **issue #1 已修**（分支 `fix/issue-1-wasm64-sysroot-in-release`）：发布包此前只装 wasm32 档
  sysroot 却在 manifest 里声称支持两档，导致 `compile({target:'wasm64'})` **返回 ok:true**
  但产物缺 `_emscripten_tls_init`，下游 dlopen 才炸。现在：**两档 sysroot 都进发布包**
  （[[release_assets]] 个资产），驱动按 target 自选；**缺档时明确拒绝**（不再静默降级）；
  并补了从发布包到真宿主的 wasm64 闭环验收（[[wasm64_release_e2e_pass]] PASS，
  产物 [[wasm64_release_e2e_bytes]] B）。已记翻案 R-010。

- **🎉 v0.1.0 已发布**：https://github.com/ArchivalEra/LLVM-wasm/releases/tag/v0.1.0
  交付包（12 资产，含逐资产许可证与 sha256）作为附件；**从附件下载回来的资产独立编译成功**
  （[[browser_module_basic_bytes]] B，与源头逐字节同尺寸）。接法见 `DELIVERY.md`。
  SPEC §2 的交付物清单已齐：clang+lld 的 wasm 与胶水、sysroot-headers.tar、驱动、
  `manifest.json`（名字+字节+sha256+**许可证**+版本串+宿主契约四轴）、
  `LICENSE`（AGPL，本仓）/ `LICENSE-LLVM.txt`（Apache-2.0 WITH LLVM-exception）
  —— 外加实测需要的第三份 `LICENSE-EMSCRIPTEN.txt`（胶水是 emscripten 的产物，MIT/NCSA）。

- **浏览器闭环已通（SPEC §9.1–9.4 全在真浏览器里）**：worker 编出 side module
  （[[loop_sidemodule_bytes]] B，M0 完整夹具），页面把它 **dlopen 进真实 emscripten 宿主**并跑宿主的全部自检 ——
  含**异常双向穿越边界**（side 抛的 side 接、宿主抛的 side 接）与 STL 模板。
  验收 [[loop_acceptance_pass]] 项 PASS。宿主 wasm [[browser_host_wasm]] B。
  复跑：`bash browser/build-host.sh && node browser/check-loop.mjs`。详见 `browser/RESULTS.md` §7。

- **浏览器验收已通（SPEC §7.3/§9.4/§9.8）**：真实 Chromium 里，Worker 加载并校验 sysroot
  （sha256 fail-closed）、实例化 lean clang + wasm-only lld、编出 ABI 正确的 side module。
  验收 [[browser_acceptance_pass]] 项 PASS。产物与 node 逐字节同尺寸
  （[[browser_module_basic_bytes]] B / node [[driver_module_bytes]] B）。
  §9.8 是**记录**不是断言：17 个请求全是同源 GET，无 POST、URL 不含源码。
  复跑：`node browser/check-browser.mjs`。详见 `browser/RESULTS.md`。
  三条"没真浏览器发现不了"的约束：主线程禁同步编译 >8MB 的 wasm（我们 48 MB）；
  pthread 需 COOP/COEP 否则无 SharedArrayBuffer；**glue 与 wasm 必须配对**
  （配错报 `Import #41 "a" "P"`，因 minimized 后的 import 字母表不同）。
  另有一个 emscripten lld 状态陷阱：同一实例连续编译两次，第二次会拒 `-mllvm`
  （argv 完全相同）⇒ 每次 compile 用新实例。

- **wasm64 已通（SPEC §4.5/§9.7）**：**不需要第二套编译器** —— 同一个 `clang.wasm`
  加 `--target=wasm64-unknown-emscripten` 就产出真 64 位对象（memory flags `0x04`，
  非静默降级），同一个 `lld.wasm` 加 `-mwasm64` 就能链。两档只差 sysroot 的 `pic/` 子树。
  验收 [[wasm64_acceptance_pass]] 项 PASS，含**反向断言**：wasm64 产物必须 memory64=true
  （wasm32 [[wasm32_module_bytes]] B / wasm64 [[wasm64_module_bytes]] B）。
  复跑：`node driver/acceptance-wasm64.mjs`。详见 `driver/RESULTS.md` §4b。

- **M2（部分）已完成：sysroot 打包 + manifest + fail-closed**（SPEC §6/§2/§9.10）。
  `package/package-sysroot.sh` 按**实测**构成打包：`include/` 整棵（[[sysroot_wasm32_headers]] 个头）
  + 只有 `crtbegin-mt.o` 一个 pic 成员 —— 从宿主 582 MB 的 `lib/` 里只取 5,589 字节。
  tar = [[sysroot_wasm32_tar]] B / brotli [[sysroot_wasm32_tar_brotli]] B。
  驱动可从 tar 编译（`M1_BUNDLE=1`，完全不碰宿主 sysroot 目录）；
  sha256 fail-closed [[fail_closed_pass]] 条断言（篡改/截断/字节数不符/缺 manifest 全被拒）。
  复跑：`sh package/package-sysroot.sh wasm32 && node driver/check-fail-closed.mjs`。
  详见 `package/RESULTS.md`。**未做**：Worker 化（§7.3）、wasm64 编译路径、分片懒加载。

- **M2（部分）已完成：薄驱动**（SPEC §7.4/§7.5）。`driver/toolchain.mjs` 把「源码 → side module」
  封成一个 `compile()` 调用：拼 §4.1/4.2 命令行、经内存 FS 流转、跑 §5.4 缺口检查、
  ABI 四项由调用方传（§4.5）。验收 [[driver_acceptance_pass]] 项 PASS，
  缺口检查的反向断言 [[gap_reverse_pass]] 项 PASS（真缺口必须被点名）。
  产物 [[driver_module_bytes]] B，在**基线**与**隔壁优化版**两种构建上都能驱动。
  复跑：`node driver/acceptance-driver.mjs`。详见 `driver/RESULTS.md`。
  **未做**：Worker 化（§7.3）、sysroot 打包（§6）、manifest + sha256（§2/§9.10）。

- **M1 已完成、全绿**：`clang` 与 `lld`（wasm-ld）**各自编成 wasm 并在 wasm 里跑通了完整链路** ——
  经由内存文件系统（SPEC §7.2）编译 `hello.cc` → 链接 → 产出 **Side module ABI 正确**的
  `minifn.so`（[[m1_sidemodule_bytes]] B，导出 `minifn` / `__wasm_call_ctors` /
  `_emscripten_tls_init`，带 dylink 段）。验收 [[m1_acceptance_pass]] 项 PASS、0 FAIL。
  复跑：`node m1/acceptance-full.mjs`（需先 `bash m1/build-clang-wasm.sh both`）。

- **M1 体积实测（SPEC §6 那条悬案的答案，本单已结案）**：

  | 资产 | raw | gzip -9 | brotli -q11 |
  |---|---|---|---|
  | `clang.wasm` | [[m1_clang_wasm]] | [[m1_clang_wasm_gzip]] | [[m1_clang_wasm_brotli]] |
  | `lld.wasm` | [[m1_lld_wasm]] | [[m1_lld_wasm_gzip]] | [[m1_lld_wasm_brotli]] |

  ⇒ SPEC §6 的两处推断都要改：**raw 推低了**（它猜合计 35–60 MB，实测单 clang 就 71 MB）；
  **brotli 超预算**（它定 ≤ 15 MB，实测两个 wasm 合计 26.1 MB）。减重从"可选优化"变成"必须做"。

- **一轮减重实验已做（隔壁，2h）**：最好组合把合计从 26.06 MB 降到 **21.80 MB（−16.4%）**，
  且**两份更小的产物仍通过整链验收**（10 PASS / 0 FAIL）：
  - clang：`CMAKE_BUILD_TYPE=MinSizeRel`（真 `-Os`）⇒ brotli [[anchor_clang_wasm_brotli]]
    （基线 [[m1_clang_wasm_brotli]]）；
  - lld：只留 wasm 驱动 ⇒ brotli [[lld_wasmonly_brotli]]（基线 [[m1_lld_wasm_brotli]]）。
  - 结论见 `m1/OPT-RESULTS.md`（隔壁的报告）与 `m1/OPT-REVIEW.md`（我的独立复核）。
  - ⚠️ **仍超 SPEC §6 预算 45%**。未打通的最强杠杆（关异常+RTTI）乐观估计到 17–19 MB，
    （按**总量**口径仍超；但 SPEC §6 的口径是**首拉** —— 见下一条）。

- **预算判定（已更正，R-008）**：SPEC §6 是「brotli ≤ 15 MB（**首拉**），支持分片懒加载」。
  按首拉口径（clang.wasm + 胶水 + sysroot tar，lld 懒加载）：**14.31 MB，达标**。
  我曾按总量口径错判"超 45%、预算不成立"——**已翻案**。

- **复核发现一条更正（已入翻案台账 R-007）**：交接单曾写「基线是 `-O1`」，**错** ——
  `CMAKE_BUILD_TYPE=Release` 会在 `-O1` 后追加 `-O3`，emcc 认最后一个 ⇒ 基线实际是 `-O3`。
  这解释了「`wasm-opt -Oz` 几乎无效」的真实原因（binaryen 早就按 `-O3` 跑过了），
  而不是交接单原先给的理由。由隔壁抓出。

- **M0 已完成、全绿**：用裸 `clang` + `wasm-ld` 手工编出的 side module（全程不经 emcc）
  被 emscripten 主模块 `dlopen` 并调用成功；wasm32 档 [[m0_pass_wasm32]] 项 PASS、
  wasm64 档 [[m0_pass_wasm64]] 项 PASS，两档 FAIL 均为 0。
  复跑：`sh m0/run-m0.sh`（wasm32）/ `ARCH=wasm64 sh m0/run-m0.sh`。

- **工具链就位**：emsdk **[[emcc_version]]**（clang [[clang_major]] / lld [[lld_major]]），
  装在 `toolchain/`（**不入库**，见 `.gitignore`）。
  下游已于 2026-10-11 **三线全面切到 6.0.12 并发运** ⇒ 工具链与宿主**同版本**。
  （历史：曾按「契约而非版本号」判定 6.x 工具链对 5.0.7 宿主不冲突——那个判定当时靠
  单向实测支撑，现在被同版本现实覆盖；5.0.7 轴已退役，见 `questions/02` 的 wontfix。）

- **§4.3 五处「缺一不可」全部复现**，且 §4.2 的命令行按 LLVM 24 修正（见「已翻案」节）。
  产物尺寸：side module wasm32 [[m0_wasm32_side_bytes]] B / wasm64 [[m0_wasm64_side_bytes]] B，
  各导出 [[m0_wasm32_side_exports]] 个符号。

- **宿主符号契约的三条路已量化**（SPEC §5.5）：
  - 纯 `MAIN_MODULE=2`：导出 [[m0_mm2_bare_exports]] 个、tag **[[m0_mm2_bare_tags]] 个**
    ⇒ side module 连实例化都过不去（`LinkError`）；
  - 只补 tag 导出：[[m0_mm2_tagonly_exports]] 个 ⇒ 仍缺其余符号；
  - `MM=2` + 从 side 导入生成的 keep-list（[[m0_keep_list_symbols]] 个符号）：
    导出 [[m0_mm2_keeplist_exports]] 个、**含 tag**、dlopen 全绿 ⇒ **这是主路**。
  - 对照：`MAIN_MODULE=1` 导出 [[m0_wasm32_host_exports]] 个，宿主
    [[m0_wasm32_host_bytes]] B —— 是 keep-list 版的 8.7 倍体积。
  复跑：`sh m0/run-mm2-keeplist.sh`。

- **下游 `.oct` 的异常依赖面（全量普查）**：[[oct_total]] 个文件里
  [[oct_tag_importers]] 个导入 `__cpp_exception`、[[oct_throw_importers]] 个导入 `__cxa_throw`
  ⇒ 支持 SPEC §5.5「tag 显式必带」。
  复跑：`python3 zreflect/facts.py --get oct_tag_importers`（值来自 `m0/evidence/oct-eh-census.txt`）。

- **反例按预期表现**：[[m0_counterexample_ok]] 条（§9.5 去掉 `-fwasm-exceptions` ⇒
  **装得上、跑到第一次 throw 才炸**；§9.6 模板缺口被点名而非静默 stub）。
  复跑：`sh m0/run-counterexamples.sh`。

- **闸门在线**：[[gates_total]] 道（清单见文末机器块；叙述从声明行派生，不手写）。
  贵事实（产物尺寸/导出数）挂**便宜见证**：值不重跑，但「产出它们的输入没变」
  每次提交真跑 —— 实测篡改 `m0/side.cc` 一个字节 ⇒ 见证全红。

- **本仓的事实纪律**：文档正文**不手抄数字**，一律写 `[[键名]]`；
  台账 `FACTS.json` 是数字的唯一产地；推断写进 `questions/`，翻案进 `retractions.json`。

## 本仓专属的坑（写给下一个 agent）

- **同一件事有两份实现 ⇒ 必然漂移，而且漂在"只修了一处"**（codebase-design 的 seam 教训，
  2026-10-15）：`compile()` 有两个 adapter（node 的 `driver/toolchain.mjs`、浏览器
  `browser/worker.mjs`），此前只共享旗标拼装（`abi.mjs`），**编排各写一份**。
  issue #1 的 precheck（缺 sysroot 时拒绝）进了 node、**没进浏览器** ⇒ 同一个失效
  （产物缺 `_emscripten_tls_init`）在修好并验证过的 node 路径之外**原地复发**。
  ⇒ 编排抽进 `driver/compile-core.mjs`（`compileWith(runtime, req)`，runtime 注入
  `targetsAvailable/clang/lld/log`），两个 adapter 只剩"sysroot 从哪来、实例怎么拿"。
  守卫 `driver/check-compile-seam.mjs`（[[compile_seam_check_pass]] PASS）**按结构断言**：
  core 是唯一拼 argv 的地方、两个 adapter 都不自己拼、precheck 不在 adapter 里重复。
  ⚠️ 该守卫**必须匹配代码而不是注释**——第一版匹配原文，浏览器 adapter 已停止调用 core
  却因注释里还有 `compileWith` 而**照绿**（实测）。已改成剥注释后再匹配。
- **`hasCrt: false` 这条分支不该存在**：core 里 precheck 通过后链接固定传 `hasCrt: true`
  —— "静默丢 crt"那条路被**结构性地删掉**了，而不是靠记得检查。


- **验收必须打开发布件本身**（issue #1 的教训）：`driver/acceptance-*.mjs` 读的是
  `package/out/`（那里两档恒在），所以**永远抓不到「发布时挑错了档」**。
  凡是"发布/交付"相关的断言，都要按 `manifest` 里的名字去开**实际发布出去的那个文件**
  （`release/check-release.mjs` 就是这么做的，并且断言每档 tar 含**自己架构**的 crt）。
  更一般的形状：**验收的输入面必须覆盖缺陷能出现的面**——只在生产侧的中间产物上验，
  等于没验交付。
- **`hasCrt=false` 曾经静默**：`compile()` 现在会**先拒绝**再做任何工作。
  这条比选哪种打包口径更重要——"声称支持 + 静默降级 + 自检全绿"是本仓立身要消灭的形状。
- **lld 实例不可复用**：同一个 lld 模块连续编译两次，第二次会拒 `-mllvm`（argv 相同），
  因为 emscripten 的 lld 首次解析时 latch 了 feature 集。每次 compile 都要新实例。


- **`toolchain/` 不入库**：`toolchain/emsdk` 约 300 MB，按 `.gitignore` 排除。
  因此「工具链版本」类事实在没装工具链的机器上**量不到** —— `measure_facts()`
  的做法是不写该键（宁缺勿假），不是写 0。
- **M0 产物也不入库**：`m0/build-*/`、`m0/*.so`、`m0/*.wasm` 全部忽略。
  能让它们入库的只有 `m0/evidence/*.log`（ARTIFACT 行 = 数字产地）。
- **事实的产地是 runner，不是文档**：改动 `m0/run-*.sh` 的测量逻辑后，
  必须重跑 runner 刷新 `m0/evidence/*.log`，再 `python3 zreflect/facts.py`。
  忘了刷新 ⇒ 见证会红（因为脚本指纹进了见证）。
- **异常 tag 是 ABI 的一部分**：side module 依赖 `env.__cpp_exception`。
  纯 MM=2 宿主不导出它 ⇒ 装不上。「靠扫 `.oct` 导入拿到 tag」能work但脆，
  SPEC §5.5 要求做成**显式必带**。

<!-- AUTO:FACTS -->
> 本区块由 `zreflect/facts.py --render-doc` 从 `FACTS.json` 渲染，**不要手改**（pre-commit 会重算并 `git add`）。
> 正文里的「测出来的数字」只在这里生产：要引用就写 `[[键名]]`，不要手抄数字。

| 键 | 值 | 测于 | 复跑命令 |
|---|---|---|---|
| `anchor_clang_wasm` | **51580817** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT anchor_clang_wasm ' m1/evidence/opt-anchor.log | cut -d' ' -f3` |
| `anchor_clang_wasm_brotli` | **13301149** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT anchor_clang_wasm_brotli ' m1/evidence/opt-anchor.log | cut -d' ' -f3` |
| `browser_acceptance_pass` | **14** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT browser_acceptance_pass ' browser/evidence/browser.log | cut -d' ' -f3` |
| `browser_host_wasm` | **1413116** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT browser_host_wasm ' browser/evidence/loop.log | cut -d' ' -f3` |
| `browser_module_basic_bytes` | **976** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT browser_module_basic_bytes ' browser/evidence/browser.log | cut -d' ' -f3` |
| `browser_module_eh_bytes` | **2117** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT browser_module_eh_bytes ' browser/evidence/browser.log | cut -d' ' -f3` |
| `clang_major` | **24** | 2026-10-18T15:30:23+0800 | `toolchain/emsdk/upstream/bin/clang --version 2>/dev/null | head -1 | grep -oE 'clang version [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `compile_seam_check_pass` | **18** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT compile_seam_check_pass ' driver/evidence/check-compile-seam.log | cut -d' ' -f3` |
| `content_list_check_pass` | **32** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT content_list_check_pass ' release/evidence/check-content-list.log | cut -d' ' -f3` |
| `content_list_entries` | **14** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT content_list_entries ' release/evidence/make-release.log | cut -d' ' -f3` |
| `driver_acceptance_pass` | **14** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT driver_acceptance_pass ' driver/evidence/driver-acceptance.log | cut -d' ' -f3` |
| `driver_module_bytes` | **976** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT driver_module_bytes ' driver/evidence/driver-acceptance.log | cut -d' ' -f3` |
| `emcc_from_repo_toolchain` | **yes** | 2026-10-18T15:30:23+0800 | `test -x toolchain/emsdk/upstream/emscripten/emcc && echo yes` |
| `emcc_version` | **6.0.12** | 2026-10-18T15:30:23+0800 | `toolchain/emsdk/upstream/emscripten/emcc --version 2>/dev/null | head -1 | grep -oE '[0-9]+[.][0-9]+[.][0-9]+' | head -1` |
| `fail_closed_pass` | **6** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT fail_closed_pass ' driver/evidence/fail-closed.log | cut -d' ' -f3` |
| `firstload_brotli` | **14308104** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT firstload_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_clang_wasm_brotli` | **12614129** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT firstload_clang_wasm_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_plus_lld_brotli` | **22803407** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT firstload_plus_lld_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_sysroot_tar_brotli` | **1675293** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT firstload_sysroot_tar_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `gap_reverse_pass` | **5** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT gap_reverse_pass ' driver/evidence/gap-reverse.log | cut -d' ' -f3` |
| `gates_total` | **14** | 2026-10-18T15:30:23+0800 | `python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l` |
| `lean_nosjlj_acceptance_pass` | **10** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_acceptance_pass ' m1/evidence/opt-lean_nosjlj-acceptance.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm` | **48069274** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm_brotli` | **12614129** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm_brotli ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm_gzip` | **17317077** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm_gzip ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lld_major` | **24** | 2026-10-18T15:30:23+0800 | `toolchain/emsdk/upstream/bin/wasm-ld --version 2>/dev/null | head -1 | grep -oE 'LLD [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `lld_wasmonly_brotli` | **8495303** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lld_wasmonly_brotli ' m1/evidence/opt-lld-wasm-only.log | cut -d' ' -f3` |
| `lld_wasmonly_raw` | **33358910** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lld_wasmonly_raw ' m1/evidence/opt-lld-wasm-only.log | cut -d' ' -f3` |
| `loop_acceptance_pass` | **13** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT loop_acceptance_pass ' browser/evidence/loop.log | cut -d' ' -f3` |
| `loop_sidemodule_bytes` | **19602** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT loop_sidemodule_bytes ' browser/evidence/loop.log | cut -d' ' -f3` |
| `m0_counterexample_ok` | **2** | 2026-10-18T15:30:22+0800 | `grep -c '^OK' m0/evidence/counterexamples.log` |
| `m0_keep_list_symbols` | **50** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT keep_list_symbols ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_exports` | **30** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT mm2_bare_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_tags` | **0** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT mm2_bare_tags ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_bytes` | **163130** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_bytes ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_exports` | **76** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_tagonly_exports` | **32** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT mm2_tagonly_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_pass_wasm32` | **12** | 2026-10-18T15:30:22+0800 | `grep -c '^PASS' m0/evidence/m0-wasm32.log` |
| `m0_pass_wasm64` | **12** | 2026-10-18T15:30:22+0800 | `grep -c '^PASS' m0/evidence/m0-wasm64.log` |
| `m0_runner_scripts` | **3** | 2026-10-18T15:30:22+0800 | `find m0 -maxdepth 1 -name 'run-*.sh' | wc -l` |
| `m0_wasm32_host_bytes` | **1413116** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm32_host_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_host_exports` | **5790** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm32_host_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_bytes` | **19653** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm32_side_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_exports` | **9** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm32_side_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm64_host_bytes` | **1448809** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_host_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_host_exports` | **5796** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_host_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_bytes` | **20041** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_side_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_exports` | **9** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_side_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m1_acceptance_pass` | **10** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT m1_acceptance_pass ' m1/evidence/m1-acceptance.log | cut -d' ' -f3` |
| `m1_clang_js` | **75866** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT clang_js ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm` | **71055261** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT clang_wasm ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm_brotli` | **16400451** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT clang_wasm_brotli ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm_gzip` | **23299801** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT clang_wasm_gzip ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_lld_wasm` | **38912004** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lld_wasm ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_lld_wasm_brotli` | **9660186** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lld_wasm_brotli ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_lld_wasm_gzip` | **13601263** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT lld_wasm_gzip ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_sidemodule_bytes` | **976** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT m1_sidemodule_bytes ' m1/evidence/m1-acceptance.log | cut -d' ' -f3` |
| `md_files` | **49** | 2026-10-18T15:30:22+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `md_lines` | **6766** | 2026-10-18T15:30:22+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' -exec awk 'FNR==1{b=0} /<!-- AUTO:FACTS -->/{b=1} !b' {} + | wc -l` |
| `oct_tag_importers` | **4084** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT oct_tag_importers ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `oct_throw_importers` | **7402** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT oct_throw_importers ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `oct_total` | **11663** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT oct_total ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `py_files` | **27** | 2026-10-18T15:30:22+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `py_lines` | **6109** | 2026-10-18T15:30:22+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' -exec cat {} + | wc -l` |
| `release_acceptance_pass` | **27** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT release_acceptance_pass ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_assets` | **14** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT release_assets ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_first_load_brotli` | **14371044** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT release_first_load_brotli ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_total_brotli` | **22866347** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT release_total_brotli ' release/evidence/check-release.log | cut -d' ' -f3` |
| `retractions_count` | **14** | 2026-10-18T15:30:23+0800 | `python3 -c "import json;print(len(json.load(open('retractions.json'))['retractions']))"` |
| `sysroot_wasm32_headers` | **1577** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_headers ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar` | **20654080** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar_brotli` | **1680675** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar_brotli ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar_sha256` | `5b9a8d2cd528f3f6…` | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar_sha256 ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm64_tar` | **20654080** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT sysroot_wasm64_tar ' package/evidence/package-wasm64.log | cut -d' ' -f3` |
| `wasm32_module_bytes` | **976** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm32_module_bytes ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_acceptance_pass` | **10** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_acceptance_pass ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_module_bytes` | **994** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_module_bytes ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_release_e2e_bytes` | **20041** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_release_e2e_bytes ' release/evidence/wasm64-e2e.log | cut -d' ' -f3` |
| `wasm64_release_e2e_pass` | **12** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT wasm64_release_e2e_pass ' release/evidence/wasm64-e2e.log | cut -d' ' -f3` |
| `ztii_regression_pass` | **4** | 2026-10-18T15:30:22+0800 | `grep -m1 '^ARTIFACT ztii_regression_pass ' driver/evidence/check-ztii-regression.log | cut -d' ' -f3` |

80 条事实。
<!-- /AUTO:FACTS -->

<!-- AUTO:GATES -->
> 本区块由 `zreflect/facts.py --render-doc` 从发现式名录（zreflect/registry.py 的声明行）渲染，**不要手改**。
> 执行面（hooks / CI）读 `registry --run <相位>` —— 相位是声明字段（`runs_at`），不是文件名。

| 闸门 | 相位 | 它挡住什么 | 消费的旋钮 |
|---|---|---|---|
| `check_ab.py`（A/B 闸门） | commit | A/B 同旗标不变式（非 allow 轴差异 = 混淆变量，A/B 作废） | `REFLECT_AB` |
| `check_envfile.py`（env 文件闸门） | commit | 守钩子的 REFLECT_* 载体（旋钮 typo / 指向缺失 / 空值） | `REFLECT_ENV_FILE` |
| `check_facts.py`（事实闸门） | commit | 块一致性 / 裸数字 / 坏引用 | `REFLECT_FACTS`, `REFLECT_DOC`, `REFLECT_NAKED_MIN` |
| `check_facts_replay.py`（复跑闸门） | commit | 台账 cmd 逐字复跑（裸值契约：stdout 必须等于值） | `REFLECT_FACTS`, `REFLECT_REPLAY`, `REFLECT_REPLAY_TIMEOUT` |
| `check_instruments.py`（仪器生命周期闸门） | commit | 恒常检测（first_seen）+ 被证伪量法登记 | `REFLECT_INSTRUMENTS`, `REFLECT_INSTRUMENT_DAYS`, `REFLECT_FACTS` |
| `check_invariants.py`（不变量闸门） | commit | 声明式不变量：仓库文件必须/不得含某片段（grep 级） | `REFLECT_INVARIANTS` |
| `check_locks.py`（锁定源闸门） | commit | 锁定源清单（URL + 文件 + sha256 的内容指纹） | — |
| `check_pins.py`（pin 闸门） | commit | 派生树 pin 一致性（stamp commit / dirty / 版本串对读） | `REFLECT_PINS` |
| `check_questions.py`（悬案闸门） | commit | 未结案的问题必须挂一个能跑的结算件 | `REFLECT_QUESTIONS` |
| `check_readme_sync.py`（三语 README 闸门） | commit | 语言版本是同一条断言的三份拷贝：结构互链 + 每次推送同批 | `REFLECT_READMES` |
| `check_retractions.py`（翻案重现检测） | commit | 被推翻的断言不许悄悄回来当现状 | `REFLECT_RETRACTIONS`, `REFLECT_DOCS`, `REFLECT_HISTORY_SECS` |
| `check_stale.py`（陈旧断言检测） | commit | sha 出处 / 退役名 / 测龄 | `REFLECT_DOCS`, `REFLECT_FACTS`, `REFLECT_HISTORY_SECS`, `REFLECT_RETIRED`, `REFLECT_STALE_DAYS` |
| `check_world.py`（world 闸门） | commit | 声明式验证对象：多线仓库共享验证环境的世界对账 | `REFLECT_WORLD`, `REFLECT_WORLD_LINE` |
| `doctor.py`（开工预检 doctor） | start-of-work | 进程 / 端口活性（查会死的东西 ⇒ runs_at=start-of-work，不进 pre-commit） | `REFLECT_DOCTOR`, `REFLECT_DOCTOR_TIMEOUT` |

14 道闸门（发现式名录派生 —— 手写清单会漂，加闸门 = 落一个声明行，这里自动长出来）。
<!-- /AUTO:GATES -->
