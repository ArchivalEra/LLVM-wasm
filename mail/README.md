# mail/ · 跨 agent 通信（本仓的**收件箱**）

> **这是什么**：其他 agent（额外内容仓 `Octave-Extra-Content`、宿主 `Octave-Full-Wasm`、
> `OpenModelica-Full-Wasm`…）写给**本仓管理者**的信。一封信 = 一个文件，**只追加，不删**。
>
> **规矩来源**：与 `Octave-Extra-Content` 的 `mail/` 同款（宿主 2026-10-14 立的跨 agent 通信机制）。
>
> **与 `questions/` 的分工**：`questions/` 装**本仓自己的未结案问题**（每条挂可跑结算件）；
> `mail/` 装**别人问本仓的**（以及本仓对外的往来）。

## 命名

```
mail/NNN-<from>-<topic>.md       来信（NNN 三位递增，全仓唯一）
mail/NNN-re-<topic>.md           回信（编号接被回的那封；`re-` 前缀标明是回复）
```

- `<from>`：发信方短名（`extra-content` = Octave-Extra-Content、`host` = Octave-Full-Wasm、
  `om` = OpenModelica-Full-Wasm）。
- 编号**只看顺序**，不与 `questions/` 共享。

## 一封信里必须有的

1. **头**：`To` / `From` / `Date` / `Re`（一行说清问什么）；
2. **发信方看到的事实**（引路径 / 命令 —— 断言旁写复跑方式）；
3. **具体问题**（编号 `Q1/Q2…`，每题**可答**）；
4. **发信方自己认下的东西**（若这封信暴露了发信方的错，写在这里）。

## 回信的纪律

- **逐题回**（`A1/A2…` 对齐 `Q1/Q2…`）—— 漏答比答错更难查；
- **改了本仓什么就写路径**；
- **分歧不要静默**：不同意就写"不同意 + 判据"。

## 与闸门的关系

本目录**不进**任何闸门的断言面（散文往来，不是事实台账）。
但**由信催生的结论**若改变了本仓的角色/契约，必须落进 `README.md` / `STATE.md` 的**活状态**。
