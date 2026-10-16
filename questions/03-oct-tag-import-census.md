# 03: 真实 `.oct` 的异常 tag 依赖面有多宽（抽样 47.5%，未全量）

**What to build:** 全量统计下游 `.oct` 资产里导入 `env.__cpp_exception` 的比例，
替换目前的**抽样**数字（40 个样本里 19 个 = 47.5%）。

**Blocked by:** 下游资产树（`/mnt/hdd/octave-wasm-build`，一万余个 `.oct`）。
本仓不拥有那份资产，但它在本机可读。

**Status:** resolved

**Settling:** ✅ **已结案**（2026-10-17，工单 65 缺口 2 催办顺手触发）⇒ `python3 zreflect/facts.py --get oct_tag_importers` —— rc=0 即全量已量得。**全量结果：4084 / 11663（35.0%）**。与抽样 47.5% 的差异 ⇒ 走"结案但更正口径"分支：抽样偏高（40 个里 19 个），全量 **35%** 仍远高于"边角情况" ⇒ **SPEC §5.5「tag 显式必带」的论证加强而非削弱**——三分之一强的现役 `.oct` 依赖异常 tag，keep-list 不显式包含它就是在赌运气。STATE.md 的「近一半」口径已更正为 [[oct_tag_importers]]/[[oct_total]]。

## 为什么留着不删

SPEC §5.5 要求「tag 做成显式必带，不依赖扫 `.oct` 导入」，理由是「靠扫描反推 ⇒ 漏扫一个
`.oct` 就退化成装得上、跑到才炸」。这条**设计决策**建立在一个抽样数字上（47.5%）。
抽样不是全量，且样本是自己挑的 —— 按本仓纪律，抽样数字不能当活状态结论的支点，
要么补成全量，要么明说是抽样（现在 STATE.md 只写了「近一半」，就是抽样口径）。

## 复跑方式（全量，约一万个文件）

```sh
# 上游扫描脚本的等价物（下游 gen-keep-list.sh 用的是同一套 wasm-dis 管道）
BIN=toolchain/emsdk/upstream/bin
find /mnt/hdd/octave-wasm-build -name '*.oct' -print0 \
  | xargs -0 -P 8 -I{} sh -c "$BIN/wasm-dis '{}' 2>/dev/null | grep -q '\"__cpp_exception\"' && echo 1" \
  | wc -l
```
（分母是 `find … -name '*.oct' | wc -l`；两者一起写进台账。）

**Type:** task

- [ ] 全量扫一遍，得出分子/分母
- [ ] 写进台账，替换 STATE.md 的抽样口径
- [ ] 若比例与抽样差异大，检查 SPEC §5.5 的论证是否需要调整
- [x] 结论回填，`Status:` 改 `resolved`，**别删这个文件**（2026-10-17）
