# LLVM-wasm

浏览器内的 C/C++ → Emscripten side module 编译工具链。独立仓库，被下游以
submodule 钉住（pin = commit，字节 = sha256）。需求书是**唯一一份**，在
下游仓：`Octave-Full-Wasm/build/113/SPEC-clang-wasm.md`（本仓不另存副本）。

**现在到哪了**：**M0 与 M1 都已完成、全绿。**

- **M0**：裸 `clang` + `wasm-ld` 手工编出的 side module 被 emscripten 主模块 dlopen 并调通
  （wasm32 / wasm64 两档）。
- **M1**：`clang` 与 `lld` 已各自编成 wasm，并在 wasm 内部跑通完整链路 ——
  经内存 FS 编译 → 链接 → 产出 Side module ABI 正确的 `.so`。

**体积**：三轮减重已做（`-Os` + lld 裁到 wasm-only + 关 C++ 异常/RTTI），
合计 brotli 从 26.06 MB 降到 **21.11 MB（−19.0%）**，且产物仍通过整链验收。
**但仍超 SPEC §6 的 15 MB 预算 41%** ⇒ 预算目标本身待委托人定夺
（见 `to-questionnaire-clang-wasm-m1.md` 的 C0）。
报告：[`m1/OPT-RESULTS.md`](m1/OPT-RESULTS.md)（实验）· [`m1/OPT-REVIEW.md`](m1/OPT-REVIEW.md)（独立复核）。

**M2 进行中**。已完成：

- **薄驱动**（SPEC §7.4/§7.5 的 `compile()` 接口 + §5.4 缺口检查）—— [`driver/RESULTS.md`](driver/RESULTS.md)
- **sysroot 打包 + manifest + sha256 fail-closed**（§6/§2/§9.10）—— [`package/RESULTS.md`](package/RESULTS.md)
- **wasm64**（§4.5/§9.7）—— 同一个 clang/lld 加 target 旗标即可，不需要第二套产物

还剩 **Worker 化**（§7.3，需真实浏览器）、分片懒加载（§6，等预算决定）。

**体积优化实验（三轮做完，到不了 15 MB）**：三根杠杆按收益排 ——
`MinSizeRel`（真 `-Os`）−18.9%、lld 只留 wasm 驱动 −12.1%、关 C++ 异常/RTTI −5.2%；
合计 26.06 → 21.11 MB，**仍超预算 41%**。配置→体积对照表、每条实验的复跑命令、
以及"试过但没用"的清单都在 [`m1/OPT-RESULTS.md`](m1/OPT-RESULTS.md)。
按体积分布（`code` 段占 89.4%、无 debug 段可剥）判断，**再往下只能动功能集合**
（例如只支持 C —— 丢掉整个 C++ 前端）。**预算要不要改是委托人的决定**，本仓只给数字。

> ⚠️ 两处反直觉的坑，复跑前值得先看：`-O1` 会被 `Release` 追加的 `-O3` 覆盖
> （交接单据此判断错过一次）；`-sSUPPORT_LONGJMP=wasm` 是**制造**
> `emscripten_longjmp` 链接失败的开关，不是修法。两条都记在
> [`retractions.json`](retractions.json) 的 R-007 / R-008。

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
| `driver/` | M2 薄驱动：`compile()` 接口 + §5.4 缺口检查 + §9.10 fail-closed |
| `package/` | M2 交付打包：sysroot tar + manifest |
| `zreflect/` | Einfacht 机制层（vendored）：闸门 / 台账 / 渲染 |
| `reflect-hooks/` | git 钩子与旋钮载体 `Einfacht.env` |
| `toolchain/` | emsdk（**不入库**） |
| `questions/` | 悬案：每条挂一个能结案的实验 |
| `STATE.md` | 活状态（正文 + 文末机器块） |
| `FACTS.json` | 事实台账：数字的唯一产地 |
| `retractions.json` | 翻案台账 |
