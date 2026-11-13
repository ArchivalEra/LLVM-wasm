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
#   tag:        v0.1.6
#   source_tag: v0.1.5      ← 承载载荷的来源 release
#   split:      true        ← 同时发 5 MiB 分片形态
#   publish:    false       ← ★ 先用 false 跑一遍，绿了再 true
```

**为什么**：三个仓都踩过同一个坑 —— 慢网络下 `gh release create` 超时，留下 **draft**；
而 draft 对客户端不可见，本地却看着"资产都在"。分片有上百个，要分批传。

**CI 的边界，说清楚**：CI **不重建工具链**（`make-release.sh` 要 300 MB emsdk 和数小时
建出的 clang.wasm/lld.wasm，都不入库）。所以 Action 走
`release/assemble-from-bundle.sh`：**搬运**上一个已发布 bundle 的 14 个资产，重打 + 换
tag/pin。**载荷真变了**（重编 clang、换 sysroot）必须在有工具链的机器上跑
`make-release.sh`，然后手动发 —— 那条路 CI 做不了，Action 会失败而不是发一个旧载荷的新 tag。

`check-wasm64-e2e.sh` 需要本地 M0 产物（不入库），CI 里**明说 SKIP**：少一条验收必须被看见。

## 一个 release 只有 manifest 声明的东西
### 客户端两条必读

1. **zstd 分片每块是独立帧**，必须**逐块解码再拼接**。把整串当单一多帧流解会在
   多块载荷上静默出错，而单块载荷全绿会把问题藏住（实测：10 个单块的都过了，
   4 个多块的炸了）。
2. **下载回来的分片必须逐块核 sha 再用**。慢网络下 `gh release download` 会**静默截断**
   （文件残留在盘上、命令仍返回 0）。实测有块读出来是 409600/1454141 这种半截长度 ——
   不核 sha 就会把"我下坏了"误诊成"发布坏了"，而后者才是值得上报的事。


契约（`ArchivalEra/Static-Contract`，v4 §0）一句话：

> 一个 release = 一个不可变 tag = 一份 `manifest.json` + N 个扁平 asset

**「+ N 个扁平 asset」是封闭集合**：release 里多一个资产就是不合规，哪怕它有用。
整包 tar.gz 因此不再发布 —— 它的内容已由 identity 分片完整表达：

```sh
# 契约形态的 release 里只有 manifest + 分片；整包按下面这条路径拼回
# 从分片拼回整包（契约客户端算法第 4/5 步）
#   逐块 GET → 校验 bytes+sha256 → 解码 → 拼接 → 校验 entry.sha256
# 14 个载荷全部可重建，且重建后再切分得到逐字节相同的分片
```

**唯一的合规产物**：`manifest.json` + 105 个分片（14 载荷 × 三编码，每块 ≤5 MiB）。
判据是机器判的，不是我说的 —— workflow 里那条
`Release contents == manifest contents` 断言盘上文件集**恰好等于** manifest 声明的集合。

## 发版的四个必读陷阱

发版只走 `.github/workflows/release.yml`（手动触发），下面这些仍会咬人：

1. **release 里只许有 manifest 声明的东西** —— 多挂一个整包 tar.gz 就是不合规。
   判据由 workflow 断死（`Release contents == manifest contents`），双证过：
   干净 PASS，塞进 tar 立刻 FAIL。
2. **顶层 `manifest.json` 是契约那份**（schema 2，描述发布字节），不是构建清单。
   两个同名、只能靠大小/内容分辨（构建清单几 KB，契约那份二十多 KB）。
3. **`--pin` 收裸 tag**：`make-content-list.mjs --pin v0.1.5`（脚本自己加 `release:` 前缀）。
   传 `release:v0.1.5` 会得到 `release:release:v0.1.5`。
4. **`gh release create` 不是原子的**：可能只上去一部分并落在 draft
   （draft 对客户端不可见而资产看着都在）。所以发布后必须**反读**：
   `node release/check-published.mjs --tag vX.Y.Z` + 下载回来逐条核。

共同形状：**生成器不能自己检查自己**。唯一能发现这些的是反读正在服务的字节。
5. **workflow 里每个调 `gh` 的步骤都要自己的 `GH_TOKEN`** —— 漏一个，那步退出 4，
   job 红而发布其实是好的：**反读没跑成 ≠ 反读通过**（v0.1.5 首跑实测）。

## 每个载荷有自己的许可

路由契约 v1.1（schema 3）：release 声明许可，**逐条可覆盖**。本仓的产物不是一种许可：

| 载荷 | 许可 | 为什么 |
|---|---|---|
| `clang.wasm` / `lld-wasm-only.wasm` / `LICENSE-LLVM.txt` | `Apache-2.0 WITH LLVM-exception` | 实测 `LICENSE-LLVM.txt` = Apache 正文 **+** LLVM Exceptions 段；只写 `Apache-2.0` 会丢掉例外条款 |
| `clang.js` / `lld-wasm-only.js` / `LICENSE-EMSCRIPTEN.txt` | `MIT OR NCSA` | 实测其首段写明是 MIT 与 NCSA 双许可，**不是** BSD-3-Clause |
| `sysroot-headers*.tar` | `(Apache-2.0 WITH LLVM-exception) AND (MIT OR NCSA)` | 一个 tar 里两种：libc++ 头是 LLVM 派生，emscripten 的 compat 头是 MIT/NCSA |
| `driver/*.mjs` / `LICENSE` | `AGPL-3.0-or-later` | 本仓自己的代码 |

首次真发 schema 3 是 **v0.1.6**（2026-11-02，由 Action 发出，反读通过）：
载荷与 v0.1.5 **逐个 (name,bytes,sha256) 相同**（从两份 manifest 对读确认），
只有 manifest 换了 schema —— 纯契约升级。客户端规则一行：
`entry.license ?? manifest.license.id`。

跨 release 的对读（`v0.1.5` vs `v0.1.6` 的 `(name,bytes,sha256)`）已核：**零差异**。
发布说明里「No payload changed」这类话必须对着两份 manifest 核，不能凭印象写。

每个 id 都核过官方 SPDX 列表（来源与行号记在 `release/licenses.json` 的 `_spdx_verified`）——
协议不验词表，所以"这个 id 拼对了没有"这件事只能靠外部权威或人。

契约 v1.1 当前**只查形状不查语义**（合法 SPDX + https url），所以上面这张表的值是我逐条核产物、而不是抄建议得来的。

**工具只在契约仓**：升级与校验都用 `Octave-Extra-Content/tools/`，本仓不留第二份实现。
契约的 `upgrade-manifest-license.py` 已支持 entry 级（`by_name`，键 = `entry.name` 原样）；
本仓只拥有**数据**（`release/licenses.json`），升级与校验逻辑一行都不在本仓。

**键是 `entry.name` 的原样字面串**（`clang.wasm`、`driver__abi.mjs`）——不做任何归一。
这条有教训，而且**两个方向都犯过**：

- 在 `licenses.json` 里把 `driver__abi.mjs` 改写成「更整齐」的 `driver/abi.mjs`；
- 在信里给裸名 `clang.wasm` **加上**一个 `toolchain/` 前缀。

方向相反，病同一个：**以为知道自己该长什么样，而不是抄盘上那一串**。
一般形式：**凡是参与匹配的字符串，只能来自被匹配的那一侧。**

映射在 `release/licenses.json`（数据），`release/make-license.py` 施加，并**断言字节身份未变**
——只许改 `schema`/`license`/`role`；分片名、字节数、sha256 必须逐字相同，否则拒绝写盘。
那是「换 manifest 不用重传 asset」这句话的机器判据。

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

配置在 `ruff.toml`（vendored 自上游 Einfacht）：判据只有 `C901`（阈值 8）/ `F` /
`E9` / `B` / `SIM` / `I` 等真 bug 族；**并且现在真的接进闸门了** —— 新套件的
`check_lint` 每次提交真跑它（ruff 不在时明说 OFF，不是静默绿）。本仓自有的
`zreflect/measure_llvm_wasm.py` / `check_vendored_sync.py` / `mail-read.py`
已照新判据清理并登记 `PINNED:` 豁免（中文是台账数据与单语仓文案，不是用户消息）。

每条历史告警的处置（`fix` / `accept` + 理由）记在
[`gitroll-dispositions.json`](gitroll-dispositions.json)。
判据两条：`ruff check` 绿 + `registry --run commit` 全绿。

**CI 等价评估**（[`.github/workflows/quality-assessment.yml`](.github/workflows/quality-assessment.yml)）：
GitHub Code Quality 在个人账号不可用 ⇒ 用本仓**已有**的检查在 CI 里产出可比摘要
（Einfacht commit 相位闸门 / harness 自证 / ruff 0.17.3 / facts replay；
PR + 每周一 + 手动触发）。**不新增 lint 规则、失败如实报 rc**。
重验收套件（M0/M1/driver/browser）需要 wasm 构建，CI 不可复现 ⇒ 不进这个
workflow，不伪装（`release.yml` 里本就明说 SKIP 的那批）。

**shellcheck 跑批**（2026-11-12，v0.10.0，外部验证轮，不进闸门）：21 个 .sh 全扫
12 findings ⇒ 修 1（`m0/run-counterexamples.sh` 的 `cd` 无守卫，runner 重跑后证据
PASS 数逐项不变）+ 11 条有意/误报逐条留痕（`CDPATH= cd` 空赋值即目的、emcc
`-sKEY=v1,v2` 单 token、诊断用 ls、printf 模板不展开、非固定 source 即插件机制）。
处置全文在 [`gitroll-dispositions.json`](gitroll-dispositions.json) 的 shellcheck 条目。

## 纪律

本仓用 [Einfacht](https://github.com/ArchivalEra/Einfacht)（vendored 在 `zreflect/`）：
**每句「现在如此」都要能复跑证明**。三条最常撞上的：

- 活状态文档里**只写实测**；推断写进 [`questions/`](questions/) 并注明哪个实验能结案；
- 被推翻的断言进 [`retractions.json`](retractions.json)，不许悄悄回来当现状；
- 改了产出数字的东西（如 `m0/run-*.sh`）⇒ 重跑它刷新证据日志，再 `facts.py` 重测。

vendored 层的同步钉在 `zreflect/VENDORED.json` 的 pin（2026-11-12 起 =
`0040c7ee`，上游 facts bootstrap 修复落地、questions/04 随之结案）。本仓
README 是单语仓的单条目 `REFLECT_READMES` ⇒ push 闸门要求**每次推送同批更新
本文件**（该判据的完整语义见 Einfacht `check_readme_sync.py` 的
`problems_push`：单条目无「同批」可言，判据就是「必须在场」）。

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
