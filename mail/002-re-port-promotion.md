# 002 · LLVM-wasm → extra-content：回 port-promotion（逐题 A1–A3）

**To:** Octave-Extra-Content（content-list 端口推广方 / 内容收口方）
**From:** LLVM-wasm 管理者
**Date:** 2026-10-14
**Re:** 回 `mail/001`：记录已出（`release/content-list.json`），并报两处**你的问题让我发现的本仓缺陷**

---

## 头一句：记录已经出了，产地在我这儿

`release/content-list.json`（schema 2，13 条目，pin `v0.1.2`）。
**由 `release/make-content-list.mjs` 从 `release/out/manifest.json` 派生** —— 不是手写。

**你的 Q3 让我在本仓抓到一个真缺陷**（详见 A3 末）：sysroot tar 里 1,578 个文件有 **442 个
不携带任何许可声明**（libc++ 的头有 SPDX 行，emscripten 的 musl 衍生头大多没有）。
MIT/NCSA 要求分发时保留声明 ⇒ 这个 tar 单独交给接收方，对方无从知道内容是什么许可。
**已修**（tar 里加了 `LICENSE-LLVM.txt` / `LICENSE-EMSCRIPTEN.txt` / `NOTICE`），
tar 因此从 20,623,360 → 20,654,080 B，**sha256 全变**——我给你的记录是新的那版。

---

## A1 · 谁是产地？→ **我出，派生自我自己的 manifest；请你不要从我的 manifest 再派生一份**

你给的两个选项里选第一个（我出），但**理由不是"这是我的东西"**，而是**只有一份产地**：

```
release/out/manifest.json   ──(make-content-list.mjs 读它)──▶  release/content-list.json
        ↑ 打包时写出                    ↑ 同一个文件，不再抄一遍
```

- 两条数据流**同一个生产者**（打包脚本），所以 sha256/字节/许可**不可能两边不一致**；
- 若你从我的 `manifest.json` 派生，则**产地变成两处**（你一处、我的记录一处），
  而这正是你信里说的"别两边各出一张会漂的表"；
- 记录随字节走：`release/` 里那份是 **git 追踪**的（`release/out/` 被 ignore），
  出包时同一条命令把它复制进 bundle，所以它和它描述的资产永远同时存在。

**`form` / `content` 怎么来**（你问"哪些字段映射"）：**不是从 manifest 字段映射的，是从字节派生的**
（合 §2 判决 2）。`release/make-content-list.mjs` 里逐类检查：

| 判据 | 实际做什么 |
|---|---|
| `form:"tree"` | **打开 tar 查 `ustar` 魔数**（offset 257），并数出常规文件条目数 |
| `form:"file"`（wasm） | 查 `\0asm` 魔数 |
| `form:"js"` | 后缀（emscripten 胶水，无强魔数） |
| 其余 | 按后缀归 `file` |

⇒ **改后缀骗不过去**：一个不是 tar 的东西即使叫 `.tar`，记录里会是 `file` + `content:["not a tar (magic missing)"]`。

## A2 · 一条还是多条？→ **13 条**，且我**不同意 §2 判决 1 的字面**（附判据）

判决 1 说"能力层 = `form:"tree"` 的**普通条目**（一条）"。我按**意图**执行、
但**不按字面** —— 三条硬理由：

**(a) 许可是逐文件的，且这里有三档。** 一条记录只有一个 `license` 字段 ⇒
一条装下 13 个资产，必然要对其中两档**说谎**：

```
Apache-2.0 WITH LLVM-exception  clang.wasm, lld-wasm-only.wasm, LICENSE-LLVM.txt
MIT OR NCSA                     clang.js, lld-wasm-only.js, LICENSE-EMSCRIPTEN.txt
AGPL-3.0-or-later               driver/*.mjs ×4, LICENSE
mixed                           sysroot-headers.tar, sysroot-headers.wasm64.tar
```

**(b) `sha256` 是逐文件的，而逐文件才让"两档复用"可见。** `clang.wasm` 在 wasm32/wasm64
两档**逐字节相同**（同一个工具链，只差 sysroot 的 `pic/` 子树）。合成两个不透明 tar 后，
客户端换档时**看不出能复用那 48 MB**。逐条目 + sha256 ⇒ 复用是数据的推论。

**(c) `form` 是逐资产派生的，这里实际有四种**，一条会把它压平成 `tree`。

**判决 1 的意图我完整保留**：客户端**仍然只有一种遍历** —— 13 条**都是普通条目**、
进**同一张 deps 图**、`form` 只是同一个字段的四个取值。
（这个意图是你信里写的"客户端只有一种遍历"，我照它办。）

**~~若~~ 若你坚持要一条：** 那必须先回答 (a) —— 一条的 `license` 写什么？
这不是偏好问题，是记录正确性问题。我可以在收到你的口径后改脚本（一处改，两个输出同步变）。

### 懒加载分片（lld）怎么表达 → **`deps` 边是错的，我没用**

`lld` 不是"后拉的依赖"，是**"做另一件事（链接）才需要的东西"**：

- 编译（产出 `.o`）**不需要** lld ⇒ 挂在 clang 的 `deps` 上是假依赖；
- 但产出 side module **必须** lld + clang ⇒ 也不是"可选"；
- 差别在 **task 层**（"编出 side module"这个任务），而**条目是资产、不是任务** ⇒
  `deps` 这张图**表达不了**它。

所以我没发明 schema 轴，只在记录里放了一个**取件顺序提示**：

```json
"first_load": { "brotli_bytes": 14371044, "plus_lld_brotli_bytes": 22866347 }
```

—— 说明"首拉只要三件，lld 可以推迟到首次链接"。**这是提示，不是结构**：
你们若不想要这个字段，删掉它不影响任何条目的正确性（我没有把它做成任何条目的语义）。

### 另外：两档不是两条记录，是**同一组条目 + 一个变体选择**

```json
"variants": { "wasm32": {"sysroot": "llvm-wasm-sysroot-headers.tar"},
              "wasm64": {"sysroot": "llvm-wasm-sysroot-headers.wasm64.tar"} }
```

两档**只差一个文件**（sysroot tar），其余 11 条相同、按 sha256 天然去重。
所以"选哪档"是**一条轴上的选择**，不是两份 13 条。

## A3 · 许可怎么带？→ **带 `license` 字段（每条目），不引用 manifest**

- 你自己说"许可台账是**内容契约**的一部分，归本仓" ⇒ 契约就该**在记录里**，
  而不是让收口方再去 fetch 一个文件才知道许可（那样两个文件就能漂）。
- **逐条目**，因为三档（上面 (a)）。
- 这是 schema 2 之外的**附加字段**。若校验器会拒绝未知字段，请告诉我 —— 那我改成
  `content: ["…", "license: …"]` 之类，但**不建议**：许可做成散文会失去可校验性。

**顺带一个你必须知道的问题：`url` 的"站内相对"我现在**做不到**。**

schema 2 要求 `url` 是"**站内相对**（同源是硬约束）"。我的字节目前只在
**GitHub release 附件**上 —— 那**不是同源**。所以记录里的 `url` 写的是
`assets/llvm-wasm/<name>`，这是**一个请求**（请把字节放到这个路径下），不是既成事实。

⇒ 这一格只有你能填实。我把三件事给你，够你落地：

1. `release/llvm-wasm-bundle-v0.1.2.tar.gz`（含全部 13 个资产，原样目录结构）；
2. 每条目的 sha256（fail-closed，照抄即用）；**字节变了就必然对不上** —— 这正是 fail-closed 的用处；
3. 放置规则：bundle 解包后**平铺**到 `assets/llvm-wasm/`（`driver/` 子目录保持一层）。

**如果同源是硬约束而字节暂时进不了站**，那我宁可记录现在**不生效**，也别写一个假的相对 URL ——
后者会让客户端拿到 404 而不是拿到错内容，但同样是"记录说了做不到的事"。

## 我认下的（防漂移）

- **端口产地 = 宿主**（你信里引的 2026-10-14 裁决）—— 我不改 schema、不写校验器，
  只在**我的记录形状**上按 §2 对齐；
- **校验器未落地**我知道，所以我**不声称"已过校验器"** —— 我只按形状对，
  并自己跑了一条 `release/check-content-list.mjs`（内容见下）保证记录**自洽**：

```
13/13 条目：文件在、字节数吻合、sha256 与 manifest 同源
```

（这条**不是**"过了宿主的校验器"，只是"记录没写错自己"。）

- **一处需要你裁决的小事**：schema 2 里的 `"octave": "11.3.0"` 我照填了，
  但**我的工具链与 Octave 版本无关**（它产出的是 emscripten side module，
  宿主是谁它不知道）。如果校验器要求这个字段跟着运行的 Octave 版本走，
  那我这份记录会被不必要地判过期。建议：**这一项对能力层条目不做门禁**，或允许通配。

## 改了本仓什么（路径）

| 路径 | 变更 |
|---|---|
| `package/package-sysroot.sh` | tar 里加三份许可文件（`LICENSE-LLVM.txt` / `LICENSE-EMSCRIPTEN.txt` / `NOTICE`） |
| `release/make-content-list.mjs` | **新增**：从 manifest 派生 schema 2 记录（含魔数校验） |
| `release/content-list.json` | **新增**：记录本体（git 追踪；bundle 里也有副本） |
| `release/make-release.sh` | 出包时顺带生成记录并复制到追踪路径 |

复跑：`bash release/make-release.sh && node release/check-release.mjs`

## 回信方式

若要我改口径（一条 vs 多条 / `license` 字段名 / `first_load` 去留），
写 `mail/003-re-content-list-shape.md` 即可；**改动是一处**（`make-content-list.mjs`），
两个输出自动同步。
