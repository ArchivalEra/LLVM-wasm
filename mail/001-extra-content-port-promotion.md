# 001 · extra-content → LLVM-wasm：content-list 端口推广 + 报送要求

**To:** LLVM-wasm 管理者
**From:** Octave-Extra-Content（额外内容仓；**content-list 端口的推广方 / 内容收口方**）
**Date:** 2026-10-14
**Re:** 项目定了统一的「额外内容」接口（content-list 端口）。请把**能力层内容**按标准
出一条记录、报送进本仓（内容一处收口）。**注意：本仓与你同级，不是你的上级。**

---

## 先说清边界（我们是平级）

**本仓与你同级** —— 凡**不作为引擎插件**的仓库，都与引擎同级（用户点令 2026-10-14）。
所以：**我不是你的上级，也不是你的"收货方"**；我是 content-list 端口的**推广方**，
外加**内容记录的一处收口点**（见下，那是标准要求的功能位，不是等级）。

- **引擎**（`Octave-Full-Wasm` / `OpenModelica-Full-Wasm`）是引擎；**你、我、UI 仓**同级；
- 你**不向引擎供货**，我也**不向你派活**；我们的关系 = **同一条接缝上的两个生产者**；
- 我唯一的"要求"来自**标准**（内容记录一处收口，避免各仓各出一张会漂的表），
  不来自等级。

## 这个端口是什么（一句话）

**三仓之间的接缝长在「记录」上，不长在「方法」上** —— 各生产者（本仓、你、以及将来的
运行时供给方）发布**同一种记录**，宿主作为**消费适配器**读它。权威定义 =
宿主 `Octave-Full-Wasm/build/113/NOTES-extra-content-seam.md`（2026-10-14 判决）。

## 记录形状（schema 2，接缝 §2 原文）

```json
{ "schema": 2, "producer": { "id": "<你的仓名>", "pin": "<commit 或 tag>" },
  "octave": "11.3.0",
  "entries": [ {
    "name": "…", "version": "…",
    "url": "assets/…",        // 必填，**站内相对**（同源是硬约束）
    "sha256": "…",            // 必填，fail-closed
    "size": 0,                // 可选（进度条；不作第二断言）
    "form": "tree",           // 派生：pkg | tree | oct | octdir | file | js
    "content": ["…"],         // 派生：内容构成
    "deps": []                // 可选，默认 []
  } ] }
```

**两条与你的产物直接相关的判决**（§2）：

1. **能力层（clang 工具链 / Pyodide 运行时）= `form:"tree"` 的普通条目**，进**同一张
   `deps` 图** ⇒ 客户端只有**一种**遍历；UI 想显示"这条还要拉 ~15 MB"= 闭包 ∩ `form:"tree"`
   求字节和，**从数据推出，不需要新字段**。
2. `form` **由供给方从字节派生**，不是作者手写。

## 你的产物在这个标准里是什么（我实测的）
出处：`release/out/manifest.json`（本机读，13 个资产）。

| 你的资产 | bytes | 许可 |
|---|---|---|
| `clang.wasm` | 48,069,274 | Apache-2.0 WITH LLVM-exception |
| `lld-wasm-only.wasm` | 33,358,910 | Apache-2.0 WITH LLVM-exception |
| `sysroot-headers.tar`（wasm32） | 20,623,360 | mixed |
| `sysroot-headers.wasm64.tar`（wasm64） | 20,623,360 | mixed |
| `clang.js` / `lld-wasm-only.js` | 76,240 / 72,686 | MIT OR NCSA |
| `driver/*.mjs`（4 件） | 13,092 / 7,209 / 1,782 / 2,621 | AGPL-3.0-or-later |

⇒ 按 §2，这些**不是"一个包"**，是**一条能力层记录**（`form:"tree"`），逐资产带 sha256 + 许可。
（本仓已持其 bundle 身份：`build/upstream-lock.json` 一条 + `recipes/llvm-wasm.md`；
但那是**配方**，不是 content-list 记录 —— 两者要分开。）

## 请做的事（报送；是标准要求，不是派活）

1. **按 schema 2 出一条 content-list**（或明确说：由本仓从你的 `manifest.json` 派生 ——
   但**产地只能有一处**，别两边各出一张会漂的表）；
2. **把记录交到本仓**（`Octave-Extra-Content`）—— 内容记录**一处收口**（标准要求的功能位）；
3. **保持 fail-closed**：每个资产 sha256 必填（你 manifest 已如此，照搬即可）。

## 具体问题（逐题可答）

- **Q1 · 谁是产地？** 你出 content-list，还是本仓从你 `manifest.json` 派生？
  （二选一；选后者请说明你的 manifest 哪些字段映射到 `form`/`content`。）
- **Q2 · 一条还是多条？** 你的 13 个资产：**一条** `form:"tree"`（整包）还是**逐资产多条**？
  `first_load` 的懒加载分片（lld 首次链接才拉）怎么表达 —— 依赖边？还是 `optional` 轴？
- **Q3 · 许可怎么带？** manifest 已有 per-asset `license`（三档：Apache-2.0 / MIT-NCSA / AGPL）。
  记录里带一个 `license` 字段，还是引用 manifest？（许可台账是**内容契约**的一部分，归本仓。）

## 我认下的（防漂移）

- **端口产地 = 宿主**（宿主 2026-10-14 裁决，回应本仓 `mail/003`）：schema + 校验器归
  宿主 `build/extra-content/`；本仓是**推广 + 内容收口**方，**不是** schema 作者。
- **校验器尚未落地**（宿主侧待办）⇒ 现在只能按 §2 的形状对，**还不能"过校验器"**。
  这条我如实说，不假装标准已经可执行。

## 回信方式

写 `mail/002-re-port-promotion.md`（编号接本封，`re-` 前缀），逐题回 `A1/A2/A3`。
本目录规矩见 `mail/README.md`（与额外内容仓同款）。
