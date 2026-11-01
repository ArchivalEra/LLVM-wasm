# LLVM-wasm

浏览器内的 C/C++ → Emscripten side module 编译工具链。

> **v0.1.3 已发布**：[releases/tag/v0.1.3](https://github.com/ArchivalEra/LLVM-wasm/releases/tag/v0.1.3)
> —— v0.1.2 曾缺 `compile-core.mjs`（宿主抓出，R-012）；v0.1.3 修复并带反读对账器
> `release/check-published.mjs`（`--tag` 从已发布字节核对）。历史：v0.1.2 / v0.1.1 / v0.1.0
> —— 交付包 + `manifest.json` + `content-list.json`（接缝记录）都在附件里；
> 下游接法见 [`DELIVERY.md`](DELIVERY.md)。
> v0.1.2：记录**通过宿主的内容校验器**（`--producer` / `--site` 两模式），
> 且 sysroot tar 内补了三份许可（442/1578 个文件原本不带声明）。
> v0.1.1 修 issue #1：发布包只装 wasm32 档 sysroot 却声称支持两档 ⇒ wasm64 产物缺 TLS 入口。
> 版本：工具链与下游宿主同为 emsdk 6.0.12（下游 2026-10-11 三线发运；5.0.7 轴已退役，悬案 02 wontfix）。独立仓库，被下游以
submodule 钉住（pin = commit，字节 = sha256）。需求书是**唯一一份**，在
下游仓：`Octave-Full-Wasm/build/113/SPEC-clang-wasm.md`（本仓不另存副本）。

**现在到哪了**：**M0 与 M1 都已完成、全绿。**

- **M0**：裸 `clang` + `wasm-ld` 手工编出的 side module 被 emscripten 主模块 dlopen 并调通
  （wasm32 / wasm64 两档）。
- **M1**：`clang` 与 `lld` 已各自编成 wasm，并在 wasm 内部跑通完整链路 ——
  经内存 FS 编译 → 链接 → 产出 Side module ABI 正确的 `.so`。

**体积**：三轮减重已做，三根杠杆按收益排 ——
`MinSizeRel`（真 `-Os`）−18.9%、lld 只留 wasm 驱动 −12.1%、关 C++ 异常/RTTI −5.2%；
三资产总量 brotli 26.06 → **22.80 MB**，产物仍通过整链验收。

**按 SPEC §6 的字面口径（「≤ 15 MB（首拉）」），首拉 = 14.31 MB ⇒ 达标**
（clang.wasm + clang.js + sysroot.tar；lld 是懒加载的，首次链接才拉）。
但 SPEC 同段的表格把三资产求和叫「合计」，与「首拉」**自相矛盾** ——
两个口径差 8.5 MB、结论相反，已升到 `to-questionnaire-clang-wasm-m1.md` 的 C0
请委托人裁决**这一件事**。
报告：[`m1/OPT-RESULTS.md`](m1/OPT-RESULTS.md)（实验，§0.1 是口径那节）·
[`m1/OPT-REVIEW.md`](m1/OPT-REVIEW.md)（独立复核）。
首拉分解可复跑：`bash m1/exp-firstload.sh`。

**下一步不是继续减重**：按链接器 map 的逐符号归因（§5.3），
把所有非 C 语言特性（模板/OpenMP/ObjC/HLSL/CUDA）**全砍光的乐观上限**
也只到 19.59 MB、仍超 15 MB，而且上游没有"只编 C"的开关 ——
**"只支持 C"这条我先前推荐过，实测是错的**。等 C0 的口径裁决即可。

**M2 进行中**。已完成：

- **薄驱动**（SPEC §7.4/§7.5 的 `compile()` 接口 + §5.4 缺口检查）—— [`driver/RESULTS.md`](driver/RESULTS.md)
- **sysroot 打包 + manifest + sha256 fail-closed**（§6/§2/§9.10）—— [`package/RESULTS.md`](package/RESULTS.md)
- **wasm64**（§4.5/§9.7）—— 同一个 clang/lld 加 target 旗标即可，不需要第二套产物
- **体积达标**（§6）：三轮减重后（`-Os` + lld 裁 wasm-only + 关异常/RTTI），**首拉 brotli 14.31 MB ≤ 15 MB**
  —— SPEC §6 的口径是**首拉**（lld 是懒加载分片）。lean 编译器（`-fno-exceptions`）
  产出的模块**异常往返正常**（§9.4 已验）。报告：[`m1/OPT-RESULTS.md`](m1/OPT-RESULTS.md)

还剩 **Worker 化**（§7.3，需真实浏览器）；分片懒加载（§6）**其实已经在驱动里实现了**
（lld 懒加载），只等 C0 的口径裁决。

> ⚠️ 三处反直觉的坑，复跑前值得先看：`-O1` 会被 `Release` 追加的 `-O3` 覆盖
> （交接单据此判断错过一次）；`-sSUPPORT_LONGJMP=wasm` 是**制造**
> `emscripten_longjmp` 链接失败的开关、不是修法；`gzip -9 -c` 会把文件名写进头
> （同一份字节流换路径就换值）。三条都记在
> [`retractions.json`](retractions.json) 的 R-007 / R-008 / R-009。

## 数字住在哪

**本仓正文不手抄数字。** 所有「测出来的值」在 `FACTS.json`（事实台账）里生产，
文档里引用写 `[[键名]]`，复跑命令写在每条事实旁边并由闸门每次提交逐字执行。
活状态在 [`STATE.md`](STATE.md)，本次 M0 的完整记录在 [`m0/RESULTS.md`](m0/RESULTS.md)。

```sh
python3 zreflect/facts.py --get m0_pass_wasm32    # 取一条事实的裸值
python3 zreflect/facts.py --render-doc STATE.md   # 重渲染机器块
sh gates-selftest.sh                              # 每道闸门先证明自己会红
```

## 怎么复现

```sh
# M1：把 clang / lld 编成 wasm，然后在 wasm 里编+链（约 20–30 分钟，24 核）
bash m1/build-clang-wasm.sh both
node m1/acceptance-full.mjs

# M2：薄驱动（源码字符串 → side module 字节 + 缺口报告）
node driver/acceptance-driver.mjs
node driver/check-gap-reverse.mjs
node driver/check-fail-closed.mjs             # §9.10 篡改必须被拒
node driver/acceptance-wasm64.mjs             # §9.7 两档都过，且 wasm64 是真 64 位

# M2：真实浏览器（Chromium + COOP/COEP 服务器）
node browser/check-browser.mjs

# M2：浏览器闭环（编译 → dlopen，§9.1–9.4）
bash browser/build-host.sh
node browser/check-loop.mjs

# 交付包：生成 + 以消费方身份验收（§2 交付物 / §9.10 / §6 预算）
bash release/make-release.sh
node release/check-release.mjs
M1_BUNDLE=1 node driver/acceptance-driver.mjs  # 交付路径：只从 tar 编译

# M2：打包 sysroot（实测构成 + manifest + sha256）
sh package/package-sysroot.sh wasm32

# M0：手搓 side module 并让真宿主 dlopen 它
sh m0/run-m0.sh               # wasm32：编 side → 手链 → 编宿主 → dlopen → 查缺口
ARCH=wasm64 sh m0/run-m0.sh   # 同一套，wasm64 档
sh m0/run-counterexamples.sh  # §9.5 反例 + §9.6 模板缺口
sh m0/run-mm2-keeplist.sh     # 宿主符号契约的三条路（bare / +tag / +keep-list）

# 体积优化实验（见 m1/OPT-RESULTS.md；ccache 走 CMAKE_*_COMPILER_LAUNCHER）
EXP_JOBS=20 bash m1/exp-run.sh anchor          # MinSizeRel（-Os）那根杠杆
bash m1/patch-lld-wasm-only.sh                 # lld 只留 wasm 驱动
cd m1/build-lld && ninja lld-wasm-only && cd ../..
# 量体积（q11 = 与 SPEC §6 预算同口径；一次要 1–10 分钟）
python3 -c "import brotli,sys;print(len(brotli.compress(open(sys.argv[1],'rb').read(),quality=11)))" \
  m1/build-exp-anchor/bin/clang.wasm
```

结果记录在 [`m1/RESULTS.md`](m1/RESULTS.md) 与 [`m0/RESULTS.md`](m0/RESULTS.md)；
两个阶段的**数字**都在 `FACTS.json` 里（`m1_clang_wasm` 等键），文档只引用不手抄。

工具链（emsdk）**不入库**，需要先装：

```sh
python3 toolchain/emsdk/emsdk.py install <版本> && python3 toolchain/emsdk/emsdk.py activate <版本>
```

## 一条从 issue #1 学到的规则

**验收必须打开发布件本身。** 原先的 `driver/acceptance-*.mjs` 读 `package/out/`
（那里两档 sysroot 恒在），所以**永远抓不到「发布时挑错了档」**——缺陷出现在交付面，
而验收只覆盖了生产侧的中间产物。凡与交付相关的断言，都按 `manifest` 里的名字
去开**实际发布出去的那个文件**。

同一条教训的另一半：`hasCrt=false` 曾经静默（`compile()` 仍返回 `ok:true`），
现在**先拒绝**再说。声称支持 + 静默降级 + 自检全绿，是本仓立身要消灭的形状。

## 一条已机制化的纪律

**集合的产地只有一个：盘。** 全部见证 cmd 与指纹函数走同一组 glob（`_hash_globs`），
不手写文件清单——手写元组与 glob 共存即双产地（实测对不上过）。判据双证：
往 `driver/` 丢新文件 ⇒ 24 条见证红。见 `zreflect/measure_llvm_wasm.py` 的 `_hash_globs`。

## 断电之后：`.git` 坏了怎么读

本机经历过两次断电，第二次打坏了 git 的内部状态。症状看着像三个独立故障，
其实是同一个事件（关机时 git 正在写盘）。**先只读诊断，别急着修**：

```sh
ls -la .git/index                    # 0 字节 ⇒ 索引没了（可重建，不丢数据）
cat .git/refs/heads/main             # 打出 "refs/heads/main" 而非 sha ⇒ ref 写坏
find .git/objects -type f -size 0    # 空对象 = 写了一半的那次提交
tail .git/logs/HEAD                  # reflog 一般完好，给出最后一个真提交的 sha
```

修复四步：用 reflog 的好 sha 重写 ref（**带结尾换行**）、`rm .git/index && git reset`、
删掉空对象、`git fsck`（应只剩悬空对象，无害）。

**唯一重要的判断**：坏的是没推送的那次提交、而工作树与旧对象都在 ⇒ **重做提交**。
`git reset --hard` 或重新 clone 才是真正会丢东西的动作。

## 发版走 GitHub Action，不手动 `gh release`

```sh
# 仓库页 → Actions → release → Run workflow
#   tag:        v0.1.5
#   source_tag: v0.1.4      ← 承载载荷的来源 bundle
#   split:      true        ← 同时发 5 MiB 分片形态
#   publish:    false       ← ★ 先用 false 跑一遍，绿了再 true
```

**为什么**：三个仓都踩过同一个坑 —— 慢网络下 `gh release create` 超时，留下 **draft**；
而 draft 对客户端不可见，本地却看着"资产都在"。v0.1.5 还有 105 个分片要分批传。

**CI 的边界，说清楚**：CI **不重建工具链**（`make-release.sh` 要 300 MB emsdk 和数小时
建出的 clang.wasm/lld.wasm，都不入库）。所以 Action 走
`release/assemble-from-bundle.sh`：**搬运**上一个已发布 bundle 的 14 个资产，重打 + 换
tag/pin。**载荷真变了**（重编 clang、换 sysroot）必须在有工具链的机器上跑
`make-release.sh`，然后手动发 —— 那条路 CI 做不了，Action 会失败而不是发一个旧载荷的新 tag。

`check-wasm64-e2e.sh` 需要本地 M0 产物（不入库），CI 里**明说 SKIP**：少一条验收必须被看见。

## 两种分发形态，同时存在

一个 tag 下同时挂两套东西，**不是替换关系**：

| 形态 | 是什么 | 谁在读 |
|---|---|---|
| `llvm-wasm-bundle-vX.Y.Z.tar.gz` | 整包（34.7 MB），**内含**构建清单 `manifest.json`（schema 1） | 宿主 provision（它硬编码 `$WORK/manifest.json`） |
| 分片 + 顶层 `manifest.json` | 契约 schema 2：每个载荷切 ≤5 MiB、三编码，**105 个扁平 asset** | 静态分发的客户端 |

**为什么两份都叫 `manifest.json` 却不冲突**：层级不同。我那份在 tar **里面**，
契约那份在 release **顶层**；没有任何客户端会在同一层看到两个。

⚠️ 发的时候别传反了：v0.1.5 第一次就把构建清单传到了顶层，靠对比文件大小才发现
（构建清单几 KB，契约那份二十多 KB）。名字一样，唯一能分辨的是内容。

```sh
sh release/make-split-release.sh v0.1.5     # ⇒ release/split/
```

分片形态把首拉从 34.7 MB 降到 26.68 MB（zstd，−23%），实测依据是 EdgeOne 在
10–20 MB 之间降速。**客户端注意**：zstd 分片**每块是独立帧**，必须
**逐块解码再拼接**；把整串当单一多帧流解会在多块载荷上静默出错（单块载荷全绿，
把问题藏住）。

## 发版的三个必读陷阱

`release/README.md` 有完整步骤，这里只记**踩过才知道**的三条：

1. **`--pin` 收裸 tag**：`make-content-list.mjs --pin v0.1.4`（脚本自己加 `release:` 前缀）。
   传 `release:v0.1.4` 会得到 `release:release:v0.1.4`。
2. **缺省 pin 是 `git describe`**：直接从工作树出的包 pin 会是 `v0.1.3-7-g2c3bc09` ——
   指向一个不是 tag 的东西。发布前必须显式传 tag **并重打 tar**（manifest 里没有
   content-list，所以只重打 tar 就够）。
3. **`gh release create` 不是原子的**：带资产的那次调用可能只上去一部分
   （实测两次都落在 draft + 只有 `manifest.json`）。发布后必须
   `gh release view --json assets` 核数，缺了就 `gh release upload --clobber`。

这三条的共同形状：**生成器不能自己检查自己**。唯一能发现它们的是反读 ——
`node release/check-published.mjs --tag vX.Y.Z`（从 GitHub 下载正在服务的字节，
对账 manifest / content-list / imports / HEAD 四处）。

## 事实系统的分层（同步上游时唯一要懂的一件事）

机制层是上游的，数据层是本仓的，两者在**不同的文件**里：

| 层 | 在哪 | 归属 | 同步上游时 |
|---|---|---|---|
| 机制层 | `zreflect/*.py`、`reflect-hooks/*`（除 `Einfacht.env`） | [Einfacht](https://github.com/ArchivalEra/Einfacht) | **整体覆盖**（逐字节等于 `zreflect/VENDORED.json` 的 pin） |
| 数据层 | `zreflect/measure_llvm_wasm.py` | 本仓 | **不动**（`REFLECT_MEASURE_MODULE` 指名它） |
| 本仓配置 | `reflect-hooks/Einfacht.env`、`FACTS.json`、`STATE.md`、`retractions.json`、`questions/` | 本仓 | 不动 |

这一分层是上游 `REFLECT_MEASURE_MODULE`（其 issue #15 A1/C3）带来的：`facts.py` 不再
被 fork，「本仓量什么」只是一个独立模块。于是同步上游 = 拷文件 + 改一行 pin，不需要
merge。**判据**：`node release/check-vendored-sync.mjs`（闸门 `check_vendored_sync.py`
每次提交自动跑）——从远端重拉 pin 那个 commit，逐字节比；本仓自有文件在
`VENDORED.json` 的 `local` 里显式列出，它们不同**不是**漂移。

## 代码质量：本地判据，不等外部扫描

```sh
python3 -m ruff check      # ⇒ All checks passed
```

配置在 `ruff.toml`：只选 GitRoll 能机械判定的那几族（`F`/`E9`/`B`/`C901`/`SIM`），
复杂度阈值**取 15 对齐扫描器**而不是 ruff 默认的 10 —— 否则修的是 ruff 的偏好，
不是被报的缺陷。`zreflect/*.py` 整层豁免：那是上游的字节，改了会让 vendored 同步闸门红。

每条历史告警的处置（`fix` / `accept` + 理由）记在
[`gitroll-dispositions.json`](gitroll-dispositions.json)。**故意不接进闸门** ——
台账本身也会腐烂，接进去只会多一个要维护的判据。判据只有一条：`ruff check` 绿。

## 纪律

本仓用 [Einfacht](https://github.com/ArchivalEra/Einfacht)（vendored 在 `zreflect/`）：
**每句「现在如此」都要能复跑证明**。三条最常撞上的：

- 活状态文档里**只写实测**；推断写进 [`questions/`](questions/) 并注明哪个实验能结案；
- 被推翻的断言进 [`retractions.json`](retractions.json)，不许悄悄回来当现状；
- 改了产出数字的东西（如 `m0/run-*.sh`）⇒ 重跑它刷新证据日志，再 `facts.py` 重测。

## 许可

本仓的 `LICENSE` 是 AGPL-3.0（与下游一致）。
**交付物里的 LLVM 派生部分（clang.wasm / lld.wasm）另按上游条款**
（Apache-2.0 WITH LLVM-exception）—— 见 SPEC §2，交付时拆成两份 LICENSE。

## 目录

| 路径 | 是什么 |
|---|---|
| `m0/` | M0 验证链：夹具、runner、证据日志、RESULTS.md |
| `m1/` | M1 构建与验收：把 clang/lld 编成 wasm，wasm 内全链验收 |
| `driver/` | M2 薄驱动：`compile()` 接口 + §5.4 缺口检查 + §9.10 fail-closed；**流水线在 `compile-core.mjs`（两个 adapter 共用）** |
| `browser/` | M2 浏览器验收：Worker 编译 + 闭环 dlopen（§7.3/§9.1–9.4/§9.8） |
| `release/` | 交付包：manifest + 许可证分档 + 消费方验收（§2/§8/§9.10）；出包与 release notes 规范见 `release/README.md`（**发布说明用英文**） |
| `package/` | M2 交付打包：sysroot tar + manifest |
| `zreflect/` | Einfacht 机制层（vendored）：闸门 / 台账 / 渲染；**本仓数据层 `measure_llvm_wasm.py` 也在这**（见「事实系统的分层」） |
| `reflect-hooks/` | git 钩子与旋钮载体 `Einfacht.env`（含 `REFLECT_MEASURE_MODULE`） |
| `toolchain/` | emsdk（**不入库**） |
| `questions/` | 悬案：每条挂一个能结案的实验 |
| `STATE.md` | 活状态（正文 + 文末机器块） |
| `FACTS.json` | 事实台账：数字的唯一产地 |
| `retractions.json` | 翻案台账 |
| `DELIVERY.md` | 交付说明：下游怎么 pin、怎么接、宿主须承诺什么 |
| `mail/` | 跨 agent 通信收件箱（只追加）：其他仓（额外内容仓 / 宿主）的问与答，规矩见 `mail/README.md`；接缝记录：必修见 `mail/003`，复核见 `mail/005`，收线见 `mail/007`（**已收**）；工单 65 缺口 2（`_ZTIi` 归属）已裁决 = A：答复见 `mail/009`，宿主裁决见 `mail/011`，回执在宿主仓 mail/028；回归守卫 `driver/check-ztii-regression.mjs`；跨仓催办（宿主工单 65 缺口 2 归属）见 `mail/008`，归属已确认（宿主 ABI 决策）见 `mail/009`/`010` |
| `release/content-list.json` | 接缝记录（schema 2）：给内容收口方的资产清单 |
