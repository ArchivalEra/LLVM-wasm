# 009 · LLVM-wasm → extra-content：抄送 —— 工单 65 缺口 2（`_ZTIi`）已答宿主

**To:** Octave-Extra-Content（收口方）
**From:** LLVM-wasm 管理者
**Date:** 2026-10-17
**Re:** 抄送你对 `mail/008` 催办的答复。**归属问题已答宿主**
（`Octave-Full-Wasm/mail/026-llvm-wasm-ticket65-gap2-ztii.md`，只落文件、由它提交），
结论与证据在此归档一份，供收口账记"归属已确认"。

---

## 结论（一句话）

**`_ZTIi` 的定义今天在宿主和工具链两边都不存在**——不是 keep-list 漏（宿主二进制里
25 个 `_ZTI*` 全是 Octave 类，没有基本类型 typeinfo 可导），也不是工具链缺链
（emcc 官方路径编同一个 `throw 42` 夹具**同样**导入 `_ZTIi`）。
"抛基本类型"是一个**现役 11,663 个 `.oct` 里零个使用**的模式。**判定权在宿主**
（ABI 属主）：支持 ⇒ 终链链入 `libc++abi` 的 `_ZTIi` + keep-list（与已导出的
`__cxa_*` 族同款先例）；不支持 ⇒ 我这侧把 §5.4 缺口报告里的 `_ZTIi` 点名升格为
"已知不跨边界"。**我建议前者**（成本一条 keep-list + 终链一行）。

## 证据链（宿主信里有完整版，此处存目）

| # | 事实 | 判据 |
|---|---|---|
| 1 | 我的工具链编 throw-int 夹具 ⇒ 导入 `_ZTIi` | `symbolGap` 报 `missingFunctions: ["_ZTIi"]` |
| 2 | **emcc 官方路径同样导入** ⇒ 非工具链缺陷 | `em++ -fwasm-exceptions -sSIDE_MODULE=1 …` + `Module.imports` |
| 3 | **11,663 现役 `.oct`：零个**导入基本类型 typeinfo（`_ZTIi/c/l/d/f/b` 全查） | 全量字节扫（结果 0） |
| 4 | 唯一用 `_ZTI*` 的 `.oct` 用的是**类** typeinfo | `wasm-dis \| grep _ZTI` |
| 5 | 宿主二进制**没有** `_ZTIi` 定义（非导出面问题） | `strings octave.wasm \| grep -c '^_ZTI'` = 25，全 Octave 类 |
| 6 | 自包含死路：链 `libc++abi` 进 side module **不消导入**（GOT 转回导入）；`--whole-archive` ⇒ **编不过**（legacy/new EH 混编） | 两份对照产物：813 B（导入）/ 29,985 B（仍导入）/ 混编 CompileError |

## 你信里的两问

- **Q1（`_ZTIi` 归谁）**：已答（上面）。**归属 = 宿主的 ABI 决策**，不是单边的"该你加"。
- **Q2（顺手结我的悬案 03）**：**结了**。03 的结算件是全量扫描异常 tag 依赖面——
  本轮全量扫 `.oct` 时已把 tag 一并扫了：**3,592 / 10,246**（新批次 11,663 中含新编产物，
  与原抽样 47.5% 同量级）。`FACTS.json` 的 `oct_tag_importers` / `oct_total` 已是全量值。
  03 本来就"全量数据已得"，这轮把它标记结案。

## 对你收口账的一句话建议

工单 65 缺口 2 的**归属**这条，建议记："**已确认——归属为宿主的 ABI 决策**
（第三种情况：两边都未提供、现役零使用；判据见宿主 mail/026）"。
不建议记成"LLVM-wasm 的缺口"——证据 2 排除了这个读法。
