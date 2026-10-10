# STATE · 活状态

正文只写「现在是什么」，**数字一律引用台账键**（或看文末机器块）。
硬规矩见 `AGENTS.md`（vendored）；本次 M0 的完整记录见 `m0/RESULTS.md`。

## 现在是什么

- **M0 已完成、全绿**：用裸 `clang` + `wasm-ld` 手工编出的 side module（全程不经 emcc）
  被 emscripten 主模块 `dlopen` 并调用成功；wasm32 档 [[m0_pass_wasm32]] 项 PASS、
  wasm64 档 [[m0_pass_wasm64]] 项 PASS，两档 FAIL 均为 0。
  复跑：`sh m0/run-m0.sh`（wasm32）/ `ARCH=wasm64 sh m0/run-m0.sh`。

- **工具链就位**：emsdk **[[emcc_version]]**（clang [[clang_major]] / lld [[lld_major]]），
  装在 `toolchain/`（**不入库**，见 `.gitignore`）。
  按委托人指示装 6.x；下游宿主是 5.0.7 —— 按 SPEC §8「契约而非版本号」判定，
  两者**不冲突**（契约四项一致即可，版本号只记档）。

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

- **反例按预期表现**：[[m0_counterexample_ok]] 条（§9.5 去掉 `-fwasm-exceptions` ⇒
  **装得上、跑到第一次 throw 才炸**；§9.6 模板缺口被点名而非静默 stub）。
  复跑：`sh m0/run-counterexamples.sh`。

- **闸门在线**：[[gates_total]] 道（清单见文末机器块；叙述从声明行派生，不手写）。
  贵事实（产物尺寸/导出数）挂**便宜见证**：值不重跑，但「产出它们的输入没变」
  每次提交真跑 —— 实测篡改 `m0/side.cc` 一个字节 ⇒ 见证全红。

- **本仓的事实纪律**：文档正文**不手抄数字**，一律写 `[[键名]]`；
  台账 `FACTS.json` 是数字的唯一产地；推断写进 `questions/`，翻案进 `retractions.json`。

## 本仓专属的坑（写给下一个 agent）

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
| `clang_major` | **24** | 2026-10-10T19:19:02+0800 | `toolchain/emsdk/upstream/bin/clang --version 2>/dev/null | head -1 | grep -oE 'clang version [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `emcc_from_repo_toolchain` | **yes** | 2026-10-10T19:19:02+0800 | `test -x toolchain/emsdk/upstream/emscripten/emcc && echo yes` |
| `emcc_version` | **6.0.12** | 2026-10-10T19:19:02+0800 | `toolchain/emsdk/upstream/emscripten/emcc --version 2>/dev/null | head -1 | grep -oE '[0-9]+[.][0-9]+[.][0-9]+' | head -1` |
| `gates_total` | **14** | 2026-10-10T19:19:02+0800 | `python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l` |
| `lld_major` | **24** | 2026-10-10T19:19:02+0800 | `toolchain/emsdk/upstream/bin/wasm-ld --version 2>/dev/null | head -1 | grep -oE 'LLD [0-9]+' | head -1 | grep -oE '[0-9]+$'` |
| `m0_counterexample_ok` | **2** | 2026-10-10T19:19:02+0800 | `grep -c '^OK' m0/evidence/counterexamples.log` |
| `m0_keep_list_symbols` | **50** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT keep_list_symbols ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_exports` | **30** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT mm2_bare_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_bare_tags` | **0** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT mm2_bare_tags ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_bytes` | **163130** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_bytes ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_keeplist_exports` | **76** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT mm2_keeplist_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_mm2_tagonly_exports` | **32** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT mm2_tagonly_exports ' m0/evidence/mm2-keeplist.log | cut -d' ' -f3` |
| `m0_pass_wasm32` | **12** | 2026-10-10T19:19:02+0800 | `grep -c '^PASS' m0/evidence/m0-wasm32.log` |
| `m0_pass_wasm64` | **12** | 2026-10-10T19:19:02+0800 | `grep -c '^PASS' m0/evidence/m0-wasm64.log` |
| `m0_runner_scripts` | **3** | 2026-10-10T19:19:02+0800 | `find m0 -maxdepth 1 -name 'run-*.sh' | wc -l` |
| `m0_wasm32_host_bytes` | **1413116** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm32_host_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_host_exports` | **5790** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm32_host_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_bytes` | **19653** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm32_side_bytes ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm32_side_exports` | **9** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm32_side_exports ' m0/evidence/m0-wasm32.log | cut -d' ' -f3` |
| `m0_wasm64_host_bytes` | **1448809** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm64_host_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_host_exports` | **5796** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm64_host_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_bytes` | **20041** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm64_side_bytes ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `m0_wasm64_side_exports` | **9** | 2026-10-10T19:19:02+0800 | `grep -m1 '^ARTIFACT wasm64_side_exports ' m0/evidence/m0-wasm64.log | cut -d' ' -f3` |
| `md_files` | **7** | 2026-10-10T19:19:02+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `md_lines` | **643** | 2026-10-10T19:19:02+0800 | `find . -name '*.md' -not -path './.git/*' -not -path './toolchain/*' -exec awk 'FNR==1{b=0} /<!-- AUTO:FACTS -->/{b=1} !b' {} + | wc -l` |
| `py_files` | **25** | 2026-10-10T19:19:02+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' | wc -l` |
| `py_lines` | **5485** | 2026-10-10T19:19:02+0800 | `find . -name '*.py' -not -path './.git/*' -not -path './toolchain/*' -exec cat {} + | wc -l` |

27 条事实。
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
