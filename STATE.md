# STATE · 活状态

正文只写「现在是什么」，**数字一律引用台账键**（或看文末机器块）。
M0 的完整记录见 `m0/RESULTS.md`；M1 见 `m1/RESULTS.md`。

## 现在是什么

- **GitRoll 扫描（issue #2）的归属已实测，且已整改**（2026-10-31）：告警的**绝大多数**
  落在 `zreflect/`（vendored Einfacht），本仓自有代码只占一小撮（明细见 issue #2 正文，
  这里不手抄数字）。上游 Einfacht 已就同类扫描整改到 **Security A / 0 defects**
  （其 issue #22，commit `6e4e6e8`）。
  ⇒ 处置（issue #3 规格）= **vendored 层整体同步上游 HEAD**（不重写修复，避免两份
  修的副本漂移）+ **自有代码告警清零**。
  **✅ 同步已完成**（同日）：`zreflect/` 与 `reflect-hooks/` 除 `Einfacht.env` 外
  **与 `6e4e6e8` 逐字节一致**；本仓数据层搬成独立模块
  `zreflect/measure_llvm_wasm.py`（`measure()`，[[measure_module_lines]] 行），
  `facts.py` 恢复上游原样，靠 `REFLECT_MEASURE_MODULE` 指名（issue #15 A1/C3）——
  **下次同步只是拷文件**。判据：台账**一条不掉**（掉条守卫拦）、闸门全绿。
  **✅ 自有代码也已清零**（同日第二批）：未用导入 / 假数组取巧 / 恒真条件 /
  嵌套三元 / 可选链 / 无比较器 `sort` / 认知复杂度 —— 逐条处置记在
  `gitroll-dispositions.json`（**两条 accept**：`m0/host.cc` 的 C 风格转换是
  C ABI 必需；CJK 多行字符串拼接是误报）。
  **本地判据**：`python3 -m ruff check`（配置 `ruff.toml`，复杂度阈值取 15
  **对齐扫描器**而非 ruff 默认 10）⇒ 全绿，不必等下一次外部扫描才知道有没有反弹。
  **两个遗留**：`.pyc` 曾被误追踪（白名单漏排 `__pycache__`，已修）；
  `m0/host.cc` 的 C 风格转换判定为**不改**（C ABI 必需，见台账）。
  **由此产生的发布动作见下一条（已完成）。**

- **✅ v0.1.4 已发布，反读全绿**：第二批整改动了 `driver/abi.mjs`
  与 `driver/toolchain.mjs`（`symbolGap` 拆成 neededFrom/selfExported、清死导入），
  而这两个文件**在已发布的 v0.1.3 包里** ⇒ 反读判据当场报红：
  `--tar …v0.1.3.tar.gz --freshness` ⇒ `stale (abi.mjs, toolchain.mjs)`。
  **这正是该判据存在的理由**（"包内自洽"抓不到"整体落后"，见翻案 R-012）——
  它把"改了包里有的文件"从"没人知道"变成"提交前后随时可问"。
  处置 = 重打 bundle + 发 **v0.1.4**，发布后反读：
  `node release/check-published.mjs --tag v0.1.4` ⇒ [[published_check_pass]] PASS
  （含 pin 指向本 tag、driver 与 HEAD 逐字节一致、imports 闭合）。
  消费方验收照旧在同一次里跑过：`check-release.mjs` 27 PASS、
  `check-wasm64-e2e.sh` 12 PASS。
  **踩到的一处**：`make-content-list.mjs --pin` 收**裸 tag**（脚本自己加
  `release:` 前缀），传 `release:v0.1.4` 会得到 `release:release:v0.1.4`；
  且 `make-release.sh` 缺省用 `git describe` 作 pin ⇒ 工作树出的包 pin 是
  `v0.1.3-7-g…`。发布前必须显式 `--pin v0.1.4` 重生成再打 tar。
  `release/content-list.json`（git 追踪）现在描述 v0.1.4 的字节。

- **发布形态改为契约单一形态（2026-11-01，用户定的判据）**：到 v0.1.4 为止发的是
  **整包 tar.gz**（14 个文件进一个 34.7 MB 的 tar）。契约 §0 一句话是
  「一个 release = 一个不可变 tag = 一份 manifest.json + N 个扁平 asset」，
  ⇒ **release 里只许有 manifest 声明的东西**。整包不在 manifest 里，就是不合规资产，
  哪怕它"有用"：它的内容**已经**由 identity 分片完整表达（Σ identity chunks == 载荷字节），
  再挂一份 tar 既冗余，又让「release 的内容 == manifest 的内容」这条可判定性破掉。
  **产出**：`release/make-split-release.sh`（调契约仓的工具，不重写生成器）⇒
  [[split_entries]] 条目 / [[split_assets]] 个扁平 asset / zstd 合计
  [[split_zstd_bytes]] B / 最大分片 [[split_max_chunk]] B（正好在契约硬限内）。
  **判据 `Release contents == manifest contents`**：盘上文件集必须**恰好等于**
  manifest 声明的集合（含 manifest.json 自身）。双证过 —— 干净时 PASS，
  故意塞进一个整包立刻 FAIL。
  **三条规矩写进脚本头**：生成器用契约仓的、**元数据不进载荷**（直接喂 `out/`
  会连 manifest/content-list 一起切成 16 条而不是 14 条，实测）、
  **载荷目录可注入**（`PAYLOAD_SRC`，CI 上不是 `release/out`）。
  **一处实测发现的契约细节**：zstd 分片**每块是独立帧**，按"单一多帧流"整串解会
  在 4 个大载荷上 sha 不符（我自己的独立校验脚本第一版就这么错的）；客户端必须
  **逐块解再拼**——正好也是契约判据 5 要求的「每块能独立解码」。
  独立复核（不走契约校验器）：gzip 14/14、zstd 14/14 逐块 sha + 拼接后整条 sha 全对。
  **整包可由 identity 分片完整重建**（14/14 逐个校验，且重建后再生成分片得到
  同一份全绿的产物）—— 所以不发整包不损失任何东西，这是它的判据。

- **发布**只能**经由 GitHub Action**（用户 2026-11-01 的硬要求：`workflow_dispatch`
  手动触发、自动出 release）。手动 `gh release create` 已废弃 —— 我在 v0.1.5 上手动发过
  一次，已**连同 tag 一起删除**重来。
  为什么要 Action：本机慢网络下 `gh release create` 超时留 **draft**（draft 对客户端
  不可见而资产看着都在，三个仓都踩过）；且分片有 [[split_assets]] 个，本地分批传要几轮。
  **CI 的载荷来源**（以前说不清，现在说清）：`clang.wasm` 等要几小时才建出、不入库 ⇒
  CI 不重建。载荷的**身份**由 `release/payloads.json`（git 追踪，2.4 KB，只含
  name/bytes/sha256，派生于 `out/manifest.json`）声明；**字节**从上一个 release 的
  identity 分片拼回（契约客户端算法第 4/5 步），拼完逐个核 sha。
  ≤v0.1.4 的 release 没有分片 ⇒ 首次过渡允许从整包取载荷，但**不把整包发出去**。
  `check-wasm64-e2e.sh` 需要 `m0/build-wasm64/host.js`（本地产物、不入库）⇒ CI 明说 SKIP。
  **✅ v0.1.5 由 Action 发出**（`workflow_dispatch`，两次：`publish=false` 先看绿、
  再一次 `publish=true`）。已发布字节反读合规：**声明的集合 == 已发布的集合**
  （[[split_assets]] 个分片 + manifest.json），**零多余资产**（无整包）。
  CI 里逐条跑过的断言：14 个载荷 sha 全对、契约校验器 [[split_entries]] 条全绿、
  [[split_assets]] 个扁平 asset 无斜杠。
  **首跑抓到一处**：反读那步漏了 `GH_TOKEN` 与 `INPUT_TAG` ⇒ `gh` 退出 4。
  症状是 job 红而**发布其实是好的** —— 「反读没跑成」不等于「反读通过」，
  这条区别写进了 README。

- **v0.1.3 已发布**（宿主 `044`/本仓 `013` 抓出 v0.1.2 缺 `compile-core.mjs` 后的重发）：
  修复提交晚于发布 8 分钟、而检查器只读工作树 ⇒ 已发布包整体落后但**内部自洽**（13/13/13，
  一致地旧——"内部一致"抓不到这种失效）。已记翻案 R-012。v0.1.3 = 14 资产、
  driver/ 与 HEAD 逐字节一致；**新增 `release/check-published.mjs` 反读对账器**
  （[[published_check_pass]] PASS，`--tag` 模式下载 GitHub 正在服务的字节核对），
  四对账：资产↔manifest、manifest↔content-list、imports 闭合、bundle↔HEAD。
  **判据双证**：对 v0.1.2 + `--freshness` 红在恰好两个真缺陷；对 v0.1.3 全绿。
  复跑：`node release/check-published.mjs --tag v0.1.3`。

- **工单 65 缺口 2（`_ZTIi`）已裁决 = A**（宿主 `027`/本仓 `011`）：宿主**接受我的"第三种情况"判定**
  并选择支持基本类型 throw；keep 生成器与容器内 keep 已补 7 条基本 typeinfo（零风险半），
  **重链留作独立批**（`ready-for-human`，产品决定）。本仓侧：缺口检查**未撤**（宿主明言
  "别提前撤"）且升格为持久回归 `driver/check-ztii-regression.mjs`
  （[[ztii_regression_pass]] PASS）——它把裁决时间表钉进验收：**重链前**点名 `_ZTIi`
  （编译期提示），**重链后**自然打出 "ruling A has landed"，与宿主
  `probe-toolchain-gap` 的翻绿互为旁证。
  **⇒ 时间表已走到第二格**（2026-10-31 实测）：对真宿主的缺口检查现在报
  "`_ZTIi` is provided by the host — ruling A has landed"，`missingFunctions: []`。
  同一支脚本的 PASS 数因此由 4 变 [[ztii_regression_pass]] —— **这是断言按设计换了一侧，
  不是回归**（脚本第 9 行写的就是「两个断言，裁决时间表各一侧」）。缺口检查本身仍未撤。
- **一处口径教训**（内容仓 `mail/010` 抓的，对）：`mail/009` 手抄了台账旧值
  （`oct_total` 与 `oct_tag_importers` 的旧数），同批提交里全量重扫落账 [[oct_total]]
  / [[oct_tag_importers]] ⇒ 信里数字当场过期。
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
  + 只有 `crtbegin-mt.o` 一个 pic 成员（从宿主庞大的 `lib/` 里只取这一个）——
  pic 成员字节数记在 `package/evidence/` 的 ARTIFACT 行里，不在这里手抄。
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
  复跑全部闸门自证：`python3 zreflect/harness.py`（或老入口 `sh gates-selftest.sh`
  —— 它现在只是 harness 的一行兼容壳）。

## 本仓专属的坑（写给下一个 agent）

- **vendored 层已整层换成新 Einfacht（2026-11-08，用户点令「vendor 全新版本」）**：
  pin 从 `6e4e6e8` 跳到 **`351dc7b4`**（旧新版**不兼容**，不是同步而是换装）。
  新套件的关键差异，都踩过一遍：
  · **入口换了**：`reflect-hooks/gate.py commit <repo>` 是给外部钩子系统（宿主桥）调的
    唯一入口；`pre-commit`/`pre-push` 薄壳仅供老 `core.hooksPath` 装法，逻辑全在 gate.py。
  · **自证换了**：`gates-selftest.sh` 变成 `zreflect/harness.py` 的一行兼容壳。
  · **i18n 纪律**：套件核心零语言（输出走 `M()` + 语言包），扫描器 `check_i18n` 会咬
    中文常量 —— 本仓自有文件靠 `PINNED:` 声明豁免（数据/单语仓文案），**不是**改上游。
  · **快照闸门**（check_snapshots）禁止 import 时刻复制 `gate.GATE_REPO` 进模块常量
    ⇒ 数据层从 `__file__` 自算仓库根（REPO），闸门用 `import gate` + `gate.GATE_REPO`。
  · **闸门声明**：源码会走 `off()` 的闸门必须在 `GATE = meta(…, off_reason=…)` 里写明理由。
  · **encoding 判据**：`open()`/`subprocess.run` 文本模式必须显式 `encoding=`。
  · **copied_value 判据**：台账整数（≥ 默认阈值）出现在文档正文而同一行
    没有 `[[键名]]` ⇒ 拦（本次抓出多处手抄的 [[browser_module_basic_bytes]]，已换成引用）。
  · **vendored 同步闸门判据只比 pin 里的文件**：上游新文件（check_i18n/check_lint/
    harness/…）不在旧 pin 里，所以旧装法看不见缺它们 —— 换装后 18 道闸门。
- **集合的产地只有一个：盘**（Einfacht issue #18 采纳半落地，2026-10-19）：
  全部见证 cmd 与全部指纹函数统一走 **glob**（`_hash_globs` 帮手，指纹哈希与
  witness cmd **相同的展开**）——手写元组与 glob 共存时是两个产地（实测：
  `M1_OPT_INPUTS` 元组漏 3 个文件而 cmd 的 glob 含 7 个，当场对不上）。
  判据双证：往 `driver/` 丢新文件 ⇒ 24 条见证红；删除 ⇒ 复绿。
  **当年事故 2（新文件进集合、见证沉默）从此被闸门必拦。**
- **契约 v1.1（schema 3）：许可逐条声明**（2026-11-01，Static-Contract `018`/`021`
  + extra-content `019`/`020`）：manifest 加 `license: {id, url}`，`schema` → 3，
  校验器加 V11。**M2 迁移期 catalogue 仍收 schema 2**（v0.1.5 不会被下架），
  M3 只收 3 且时机由用户定。
  **本仓的许可不是一条表达式**：clang/lld 与 `LICENSE-LLVM.txt` 是
  `Apache-2.0 WITH LLVM-exception`（实测该文件 = Apache 正文 + LLVM Exceptions 段，
  标成纯 `Apache-2.0` 会丢例外条款）；`clang.js`/`lld.js`/`LICENSE-EMSCRIPTEN.txt`
  与两个 sysroot tar 是 `MIT OR NCSA`（实测其首段，**不是** BSD-3-Clause）；
  `driver/*` 与 `LICENSE` 是 `AGPL-3.0-or-later`。
  ⇒ 映射写成数据文件 `release/licenses.json`，`release/make-license.py` 施加并
  **断言字节身份未变**（只许改 schema/license/role；id/chunkSize/codecs/products/
  每条 entry 与 chunk 的 (name,bytes,sha256) 必须逐字相同）—— 那是「换 manifest
  不用重传 asset」这个前提的机器判据。
  **顺序**（`021` §1 指定）：内容判据 → 升级 → **再跑一次校验器**（新 schema 下）。
  实测：本地全流程 [[split_assets]] 分片 + schema 3 ⇒ 697 PASS / 0 FAIL
  （基础判据 + V11 的逐条许可判据）。
  **已发布字节上的独立验证**（2026-11-01，不依赖任何校验器）：从 v0.1.5 下载
  gzip/zstd 分片回本地，**逐块核 bytes+sha256 → 逐块解码 → 拼接 → 核 entry.sha256**，
  21 个变体 **0 bad**，其中 6 个是**多块**载荷（`lld-wasm-only.wasm` 7 块、
  三个 sysroot tar 各 4 块）—— 正是"整串当单一多帧流解"会炸的那类。
  **过程中的一个教训**：慢网络下 `gh release download` 会**静默截断**（文件残留在盘上、
  命令 rc=0）。先后有 4 个块读出来是 409600/1454141、65983/700795 这种半截长度。
  ⇒ 下载回来**必须逐块核 sha 再用于任何判断**，否则会把"我下坏了"误诊成"发布坏了"。
  **⚠️ v0.1.5 已撤除（2026-11-02，含 tag）**：它的许可声明**不完整**，不是「合法的未声明」。
  schema 2 的正当用途是「**载荷本身无法声明许可**（如上游只有一个版权声明文件、
  或无元数据的外部包）也能随契约发布」；v0.1.5 **不属此列** —— 14 个载荷分属三种
  **已核实**的许可，而且包里就有 `LICENSE` / `LICENSE-LLVM.txt` /
  `LICENSE-EMSCRIPTEN.txt` 三份正文，manifest 却**一条都没声明**
  （14/14 entry 无 license 字段，顶层也没有）。
  ⇒ 「许可就在包里但元数据不指出来」= 不完整声明，比"不知道"更糟：
  **空可以是诚实的，错不能；而"明明有却不写"两者都不是。**
  撤回不损失字节：v0.1.6 含全部同一批载荷（已对读确认零差异）。
  `notes-v0.1.6` 已改写，不再指向那个已不存在的 tag。

  **✅ v0.1.6 已发出 —— 这是第一次真 schema 3**（2026-11-02，**由 Action 发**，
  `publish=false` 先跑绿再 `publish=true`，19 步全过含反读）。
  它是**纯契约升级**：载荷身份与 v0.1.5 **逐个 (name,bytes,sha256) 相同**
  （从已发布 manifest 对读确认），只有 manifest 换了 schema。
  已发布字节上独立核过：`schema == 3`、14/14 条 entry 各有 license、
  **63 条 V11 判据全过**（用契约仓的校验器）、
  **release 内容 == manifest 声明的集合**（零多余零缺失）。
  ⇒ 本仓「能力具备」到此变成「在生产里跑过」。
  **v0.1.0–v0.1.4 处置 = A（弃用）**：schema 1 前契约格式（`assets`/`toolchain`/
  `first_load` 那套键），catalogue 的 G5 已挡在门外；改造工作量与收益不成比例，
  且 v0.1.5 已替代。**release 历史不重写**，只标注。
## 本仓专属的坑（写给下一个 agent）

- **删 release / 删 tag 之前，先发信**（2026-11-08 立；来源：extra-content `033`
  抓的现行，本仓 `034` 认账并采纳）：v0.1.5 撤除时没有先告诉对账方，对方下载时
  撞上 Not Found 才知道 —— 「同一个 tag 永远是同一份字节」这条地基死掉的方式，比违反本身更伤
  对账可信度的是**沉默**。**规矩**：任何删/覆盖 release、删 tag、强推发布分支之前，
  先发一封信（收件人 = 受影响的对账方），写明**删什么、为什么、谁受影响、
  替代锚点在哪**，然后才动手。
  **v0.1.5 的替代锚点**（本次补交，完整链路见 `mail/034` §2）：`release/payloads.json`
  （唯一提交 `d6822d8`，早于 v0.1.5 的发布 CI）声明 14 条载荷身份，两次发布 run 里
  workflow 逐 sha 对账后才发；且 v0.1.6 已发布 manifest 的 (sha256, bytes) 身份集合
  与该锚相等（2026-11-08 实测，比对用 sha 别用 name —— 键形差见 `mail/022`/`023`）。
  ⇒ 「v0.1.5 与 v0.1.6 载荷逐字节同源」仍可由第三方独立推出；拿 v0.1.5 原件对读
  则永远做不成了，这是删除的不可逆代价。
- **断电会打坏 `.git`，而且症状是三条互不相干的报错**（2026-10-31 夜 → 11-01 盘点）：
  第二天开机后 `git log` 报「分支似乎已损坏」、`git status` 报「索引文件比预期的小」、
  `git cat-file c7e8207` 报「对象文件为空」。三处是同一个事件：关机时 git 正在写盘。
  **诊断顺序**（都是只读，先摸清再动手）：
  1. `ls -la .git/index` —— 0 字节 ⇒ 索引没了（**可重建，不丢数据**）；
  2. `cat .git/refs/heads/main` —— 若打出字面文本 `refs/heads/main` 而非 sha，
     说明 ref 被写坏（本次实测）；
  3. `find .git/objects -type f -size 0` —— 空对象文件 = 写了一半的**那一次提交**；
  4. `tail .git/logs/HEAD` —— reflog 通常是完整的，能给出最后一个真提交的 sha。
  **修复**：用 reflog 里的好 sha 重写 ref（**带结尾换行**，否则 fsck 报
  `refMissingNewline`）→ `rm .git/index && git reset`（从 HEAD 重建）→
  `find .git/objects -type f -size 0 -delete` → `git fsck` 应当只剩悬空对象（无害）。
  **关键判断**：坏的是**未推送的那一次提交**，工作树与 `.git` 里的旧对象都完好 ⇒
  重做提交即可。**不要** `git reset --hard`、不要重新 clone —— 那会真的丢东西。
  判据：（本次）20 个改动文件与提交前一模一样，ruff 全绿、5 个 driver 验收全 PASS，
  重做后 `git push` 成功。

- **新写的 `.py` 必须以换行结尾，否则 `py_lines` 会差一**（第二次踩，2026-11-01）：
  `measure()` 用 `sum(1 for _ in open(f))` 数行（最后半行也算一行），而台账的复跑命令是
  `cat | wc -l`（只数换行符）。文件末尾缺 `\n` ⇒ 两者差 1 ⇒ **复跑闸门红**。
  症状很像"测量逻辑坏了"，实际只是一次 `printf '\n' >>`。
  第一次是 `check_vendored_sync.py`，这次是 `make-license.py` 与 `make-payloads.mjs`。
  **判据**：新文件落地后立刻 `[ -n "$(tail -c1 FILE)" ] && echo NO-EOL`。

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


- **`toolchain/` 不入库**：`toolchain/emsdk` 体积很大（数百 MB 级），按 `.gitignore` 排除。
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
> This block is rendered by `zreflect/facts.py --render-doc` from `FACTS.json`; **do not edit by hand** (pre-commit recomputes and `git add`s it).
> 'Measured numbers' in the prose are produced only here: to cite one, write `[[key]]`; never copy the number by hand.

| key | value | measured at | replay cmd |
|---|---|---|---|
| `anchor_clang_wasm` | **51580817** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT anchor_clang_wasm ' m1/evidence/opt-anchor.log | cut -d' ' -f3` |
| `anchor_clang_wasm_brotli` | **13301149** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT anchor_clang_wasm_brotli ' m1/evidence/opt-anchor.log | cut -d' ' -f3` |
| `browser_acceptance_pass` | **14** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT browser_acceptance_pass ' browser/evidence/browser.log | cut -d' ' -f3` |
| `browser_host_wasm` | **1413116** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT browser_host_wasm ' browser/evidence/loop.log | cut -d' ' -f3` |
| `browser_module_basic_bytes` | **976** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT browser_module_basic_bytes ' browser/evidence/browser.log | cut -d' ' -f3` |
| `browser_module_eh_bytes` | **2117** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT browser_module_eh_bytes ' browser/evidence/browser.log | cut -d' ' -f3` |
| `clang_major` | **24** | 2026-11-12T08:11:46+0800 | `toolchain/emsdk/upstream/bin/clang --version 2>/dev/null | head -1 | grep -oE 'clang version [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `compile_seam_check_pass` | **18** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT compile_seam_check_pass ' driver/evidence/check-compile-seam.log | cut -d' ' -f3` |
| `content_list_check_pass` | **31** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT content_list_check_pass ' release/evidence/check-content-list.log | cut -d' ' -f3` |
| `content_list_entries` | **14** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT content_list_entries ' release/evidence/make-release.log | cut -d' ' -f3` |
| `driver_acceptance_pass` | **17** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT driver_acceptance_pass ' driver/evidence/driver-acceptance.log | cut -d' ' -f3` |
| `driver_module_bytes` | **976** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT driver_module_bytes ' driver/evidence/driver-acceptance.log | cut -d' ' -f3` |
| `emcc_from_repo_toolchain` | **yes** | 2026-11-12T08:11:46+0800 | `test -x toolchain/emsdk/upstream/emscripten/emcc && echo yes` |
| `emcc_version` | **6.0.12** | 2026-11-12T08:11:46+0800 | `toolchain/emsdk/upstream/emscripten/emcc --version 2>/dev/null | head -1 | grep -oE '[0-9]+[.][0-9]+[.][0-9]+' | head -1` |
| `fail_closed_pass` | **6** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT fail_closed_pass ' driver/evidence/fail-closed.log | cut -d' ' -f3` |
| `firstload_brotli` | **14308104** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT firstload_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_clang_wasm_brotli` | **12614129** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT firstload_clang_wasm_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_plus_lld_brotli` | **22803407** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT firstload_plus_lld_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `firstload_sysroot_tar_brotli` | **1675293** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT firstload_sysroot_tar_brotli ' m1/evidence/opt-firstload.log | cut -d' ' -f3` |
| `gap_reverse_pass` | **5** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT gap_reverse_pass ' driver/evidence/gap-reverse.log | cut -d' ' -f3` |
| `gates_total` | **18** | 2026-11-12T08:11:46+0800 | `python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l` |
| `lean_nosjlj_acceptance_pass` | **10** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_acceptance_pass ' m1/evidence/opt-lean_nosjlj-acceptance.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm` | **48069274** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm_brotli` | **12614129** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm_brotli ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lean_nosjlj_clang_wasm_gzip` | **17317077** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lean_nosjlj_clang_wasm_gzip ' m1/evidence/opt-lean_nosjlj.log | cut -d' ' -f3` |
| `lld_major` | **24** | 2026-11-12T08:11:46+0800 | `toolchain/emsdk/upstream/bin/wasm-ld --version 2>/dev/null | head -1 | grep -oE 'LLD [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `lld_wasmonly_brotli` | **8495303** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lld_wasmonly_brotli ' m1/evidence/opt-lld-wasm-only.log | cut -d' ' -f3` |
| `lld_wasmonly_raw` | **33358910** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lld_wasmonly_raw ' m1/evidence/opt-lld-wasm-only.log | cut -d' ' -f3` |
| `loop_acceptance_pass` | **13** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT loop_acceptance_pass ' browser/evidence/loop.log | cut -d' ' -f3` |
| `loop_sidemodule_bytes` | **19602** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT loop_sidemodule_bytes ' browser/evidence/loop.log | cut -d' ' -f3` |
| `m0_counterexample_ok` | **2** | 2026-11-12T08:11:46+0800 | `grep -c '^OK' m0/evidence/counterexamples.log` |
| `m0_keep_list_symbols` | **50** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT keep_list_symbols ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_exports` | **30** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT mm2_bare_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_tags` | **0** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT mm2_bare_tags ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_bytes` | **163130** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_bytes ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_exports` | **76** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_tagonly_exports` | **32** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT mm2_tagonly_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_pass_wasm32` | **12** | 2026-11-12T08:11:46+0800 | `grep -c '^PASS' m0/evidence/m0-wasm32.log` |
| `m0_pass_wasm64` | **12** | 2026-11-12T08:11:46+0800 | `grep -c '^PASS' m0/evidence/m0-wasm64.log` |
| `m0_runner_scripts` | **3** | 2026-11-12T08:11:46+0800 | `find m0 -maxdepth 1 -name 'run-*.sh' | wc -l` |
| `m0_wasm32_host_bytes` | **1413116** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm32_host_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_host_exports` | **5790** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm32_host_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_bytes` | **19653** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm32_side_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_exports` | **9** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm32_side_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm64_host_bytes` | **1448809** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_host_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_host_exports` | **5796** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_host_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_bytes` | **20041** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_side_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_exports` | **9** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_side_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m1_acceptance_pass` | **10** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT m1_acceptance_pass ' m1/evidence/m1-acceptance.log | cut -d' ' -f3` |
| `m1_clang_js` | **75866** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT clang_js ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm` | **71055261** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT clang_wasm ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm_brotli` | **16400451** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT clang_wasm_brotli ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_clang_wasm_gzip` | **23299801** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT clang_wasm_gzip ' m1/evidence/build-clang.log | cut -d' ' -f3` |
| `m1_lld_wasm` | **38912004** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lld_wasm ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_lld_wasm_brotli` | **9660186** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lld_wasm_brotli ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_lld_wasm_gzip` | **13601263** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT lld_wasm_gzip ' m1/evidence/build-lld.log | cut -d' ' -f3` |
| `m1_sidemodule_bytes` | **976** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT m1_sidemodule_bytes ' m1/evidence/m1-acceptance.log | cut -d' ' -f3` |
| `md_files` | **76** | 2026-11-12T08:11:45+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `md_lines` | **10148** | 2026-11-12T08:11:46+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' -exec awk 'FNR==1{b=0} /<!-- AUTO:FACTS -->/{b=1} !b' {} + | wc -l` |
| `measure_module_lines` | **729** | 2026-11-12T08:11:46+0800 | `wc -l < zreflect/measure_llvm_wasm.py` |
| `oct_tag_importers` | **4084** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT oct_tag_importers ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `oct_throw_importers` | **7402** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT oct_throw_importers ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `oct_total` | **11663** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT oct_total ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3` |
| `published_check_pass` | **21** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT published_check_pass ' release/evidence/check-published.log | cut -d' ' -f3` |
| `py_files` | **40** | 2026-11-12T08:11:45+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `py_lines` | **20315** | 2026-11-12T08:11:45+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' -exec cat {} + | wc -l` |
| `release_acceptance_pass` | **27** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT release_acceptance_pass ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_assets` | **14** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT release_assets ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_first_load_brotli` | **14371044** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT release_first_load_brotli ' release/evidence/check-release.log | cut -d' ' -f3` |
| `release_total_brotli` | **22866347** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT release_total_brotli ' release/evidence/check-release.log | cut -d' ' -f3` |
| `retractions_count` | **16** | 2026-11-12T08:11:46+0800 | `python3 -c "import json;print(len(json.load(open('retractions.json'))['retractions']))"` |
| `split_assets` | **105** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT split_assets ' release/evidence/make-split-release.log | cut -d' ' -f3` |
| `split_entries` | **14** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT split_entries ' release/evidence/make-split-release.log | cut -d' ' -f3` |
| `split_max_chunk` | **5242880** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT split_max_chunk ' release/evidence/make-split-release.log | cut -d' ' -f3` |
| `split_zstd_bytes` | **26683734** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT split_zstd_bytes ' release/evidence/make-split-release.log | cut -d' ' -f3` |
| `sysroot_wasm32_headers` | **1577** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_headers ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar` | **20654080** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar_brotli` | **1680675** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar_brotli ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm32_tar_sha256` | `5b9a8d2cd528f3f6…` | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT sysroot_wasm32_tar_sha256 ' package/evidence/package-wasm32.log | cut -d' ' -f3` |
| `sysroot_wasm64_tar` | **20654080** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT sysroot_wasm64_tar ' package/evidence/package-wasm64.log | cut -d' ' -f3` |
| `wasm32_module_bytes` | **976** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm32_module_bytes ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_acceptance_pass` | **10** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_acceptance_pass ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_module_bytes` | **994** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_module_bytes ' driver/evidence/wasm64-acceptance.log | cut -d' ' -f3` |
| `wasm64_release_e2e_bytes` | **20041** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_release_e2e_bytes ' release/evidence/wasm64-e2e.log | cut -d' ' -f3` |
| `wasm64_release_e2e_pass` | **12** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT wasm64_release_e2e_pass ' release/evidence/wasm64-e2e.log | cut -d' ' -f3` |
| `ztii_regression_pass` | **3** | 2026-11-12T08:11:46+0800 | `grep -m1 '^ARTIFACT ztii_regression_pass ' driver/evidence/check-ztii-regression.log | cut -d' ' -f3` |

86 facts.
<!-- /AUTO:FACTS -->

<!-- AUTO:GATES -->
> This block is rendered by `zreflect/facts.py --render-doc` from the discovered roster (declaration lines in zreflect/registry.py); **do not hand-edit**.
> The execution plane (hooks / CI) reads `registry --run <phase>` — the phase is a declared field (`runs_at`), not a file name.

| Gate | Phase | What it guards | Knobs consumed | Why it may be off |
|---|---|---|---|---|
| `check_ab.py`（A/B gate） | commit | A/B same-flags invariant (a difference outside the allow axis = confounding variable, A/B void) | `REFLECT_AB` | repos that run no A/B experiments do not need it: spec unset => explicitly not enabled |
| `check_envfile.py`（env-file gate） | commit | guards the hooks' REFLECT_* carrier (knob typos / dangling targets / empty values) | `REFLECT_ENV_FILE` | a repo without an env carrier (all knobs at their defaults) does not need it: spec not configured ⇒ state it is off |
| `check_facts.py`（Facts gate） | commit | block agreement / bare numbers / bad citations | `REFLECT_FACTS`, `REFLECT_DOC`, `REFLECT_NAKED_MIN` | — |
| `check_facts_replay.py`（Replay gate） | commit | ledger cmds re-run verbatim (bare-value contract: stdout must equal the value) | `REFLECT_FACTS`, `REFLECT_REPLAY`, `REFLECT_REPLAY_TIMEOUT` | the whole gate closes only when REFLECT_REPLAY=off is set explicitly (this is the repo-wide exit; unset it still runs) |
| `check_i18n.py`（language coverage gate） | commit | the core is zero-language: user-visible text must go through M(code); language packs are optional | `REFLECT_I18N_ROOT` | — |
| `check_instruments.py`（Instrument lifecycle gate） | commit | constancy detection (first_seen) + falsified-method registry | `REFLECT_INSTRUMENTS`, `REFLECT_INSTRUMENT_DAYS`, `REFLECT_FACTS` | both knobs unset => the specialized mechanism is not enabled (pluggable; this repo turns it on when needed) |
| `check_invariants.py`（Invariants gate） | commit | declarative invariants: repo files must / must not contain a snippet (grep level) | `REFLECT_INVARIANTS` | repos that write no declarative invariants do not need it: spec unset => explicitly not enabled (pluggable) |
| `check_lint.py`（Static machine check） | commit | ruff's C901/F/E9/B, criteria in ruff.toml -- the 'all clear' must be re-established by every commit, not handwritten into the ledger from a single manual run (R-004) | — | ruff not installed on this machine (external tool, not a repo dependency) => explicitly not enabled; CI pip-installs it, and there the gate really runs |
| `check_locks.py`（Locked-sources gate） | commit | locked-sources list (content fingerprints of URL + file + sha256) | `REFLECT_LOCKS` | repos that do not pin upstream bytes do not need it: spec unset => explicitly not enabled |
| `check_pins.py`（pin gate） | commit | derived-tree pin consistency (stamp commit / dirty / version string cross-read) | `REFLECT_PINS` | repos without a derived tree do not need it: spec unset => explicitly not enabled |
| `check_questions.py`（Question ledger gate） | commit | an unresolved question must carry a runnable settler | `REFLECT_QUESTIONS` | — |
| `check_readme_sync.py`（Trilingual README gate） | commit | language versions are three copies of one assertion: structural cross-links + same-batch on every push | `REFLECT_READMES` | — |
| `check_retractions.py`（Retraction-resurfacing check） | commit | a retracted assertion may not quietly return as the current state | `REFLECT_RETRACTIONS`, `REFLECT_DOCS`, `REFLECT_HISTORY_SECS` | — |
| `check_snapshots.py`（module-level snapshot gate） | commit | a mutable global imported across modules is a value copy (stale snapshot): switch to importing the module and reading the attribute | `REFLECT_SNAPSHOT_ROOT` | — |
| `check_stale.py`（Stale-assertion gate） | commit | sha provenance / retired names / age check | `REFLECT_DOCS`, `REFLECT_FACTS`, `REFLECT_HISTORY_SECS`, `REFLECT_RETIRED`, `REFLECT_STALE_DAYS` | — |
| `check_vendored_sync.py`（vendored 同步闸门） | commit | zreflect/ 必须仍是上游 Einfacht 的字节（VENDORED.json 的 pin） | — | repos that are not a vendored Einfacht copy have no pin: VENDORED.json absent => explicitly not applicable |
| `check_world.py`（world gate） | commit | declarative validation target: world reconciliation of a multi-line repo's shared validation environment | `REFLECT_WORLD`, `REFLECT_WORLD_LINE` | a single-line repo does not need it: spec not configured ⇒ state it is off |
| `doctor.py`（start-of-work doctor） | start-of-work | process / port liveness (probes things that can die ⇒ runs_at=start-of-work, not in pre-commit) | `REFLECT_DOCTOR`, `REFLECT_DOCTOR_TIMEOUT` | this repo has no doctor.json spec: no process/port liveness is checked ⇒ state it is off |

18 gates (derived from the discovered roster — a hand-written list drifts; adding a gate = landing one declaration line, and it grows here automatically); 11 of them **may be disabled** (the last column is a **declared** justification, not runtime state — who is off right now is seen via `registry --run <phase>`).
<!-- /AUTO:GATES -->
