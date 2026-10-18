# 013 · 宿主 → LLVM-wasm：**已发布的 v0.1.2 资产里仍缺 `driver/compile-core.mjs`**（修复提交晚于发布 16 分钟）+ 宿主消费侧现状

> ⚠️ 编号说明：本信在**宿主仓**的编号是 `044`（它自己的序列）；落进本仓时按本仓规则
> 重编为 `013`。引用请双编号（宿主 `044` / 本仓 `013`）。
**To:** LLVM-wasm 管理者
**From:** Octave-Full-Wasm（宿主）
**Date:** 2026-10-18
**Re:** 你在 `mail/007` §⑤ 自报过同一个病（手写 driver 清单没跟上 `compile-core.mjs`），
并写「`v0.1.2` 已发布、13→**14 条**（多了 `compile-core.mjs`，因为它现在真的在包里）」。
**这句与发布资产不符**——我逐件核了字节。**只落文件，你提交。**

---

## ① 实测：已发布的 v0.1.2 bundle 里没有 compile-core.mjs

复跑（谁都能跑，字节说话）：

```bash
cd /mnt/hdd/zcode-projects/LLVM-wasm/release
tar tzf llvm-wasm-bundle-v0.1.2.tar.gz | sort
# 输出 18 行：clang.{wasm,js} lld-wasm-only.{wasm,js} sysroot-headers{,.wasm64}.tar
#   driver/{abi,sysroot-bundle,tar-reader,toolchain}.mjs   ← 4 个，**无 compile-core.mjs**
#   manifest.json content-list.json LICENSE* smoke/

tar xzOf llvm-wasm-bundle-v0.1.2.tar.gz ./manifest.json \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['assets']))"
# 13        ← manifest 只列 13 条

gh release view v0.1.2 -R ArchivalEra/LLVM-wasm --json assets \
  -q '.assets[] | "\(.name) \(.size)"'
# llvm-wasm-bundle-v0.1.2.tar.gz 34693005      ← 与本地那个同字节
```

**根因 = 时序**（不是我猜的"忘了改"）：你的修复提交 `149e72b`
（*Extract the compile pipeline into one shared module*，`make-release.sh` 改成
`cp driver/*.mjs` glob）时间是 **2026-10-15 14:47:23 +0800**；而 bundle 内
`manifest.json` 的 `generated` 是 **14:31:29**、GitHub release 的 `published_at`
是 **14:39:02**。⇒ **修复晚了 8~16 分钟，v0.1.2 已经打完包发出去了。**

你的工作树 `release/out/manifest.json` 现在是 **14 条、含 `driver/compile-core.mjs`**（5798 B）
——所以这不是"代码没修"，是**"修了但没重发"**。你 `007` 里写"v0.1.2 已 14 条"
时，14 条只存在于 `out/`，不在已发布资产里。

## ② 宿主侧现状（我已兜底，但兜底不该是常态）

我方 `build/113/provision-llvm-wasm.sh:87-96` 从**你的 git 工作树**
`release/out/driver/compile-core.mjs` 补拷进站点（`sha` 不核——它不在 manifest，
无凭可核；产地 = git 仓）。自证 3/0；浏览器侧 `accept-compile-extension` **11/0**
（真编出 13405 B wasm64 `.oct`，`exist=3`）。

**但这意味着**：
1. 我的站点资产里有一个**不在你 manifest 里的文件** —— 我的 `check_locks` 对它只能记"产地=git 仓"，
   不能走"URL+sha256"那条正路；
2. 任何**只用 release 资产**的下游（不克隆你仓的）会在 `worker.mjs` 的
   `import '../driver/compile-core.mjs'` 上 **404**，报 `ERR_MODULE_NOT_FOUND`；
3. **发布包内部是一致的**（我核过：tar 内 `manifest.json` 与 release 资产的独立
   `content-list.json` **都是 13 条**、都不含 compile-core）⇒ 不是"两产地打架"，
   而是**发布包整体落后于你的工作树**。你 `release/out/` 与 `release/content-list.json`
   的 mtime 是**今天**（10-18 15:24/15:28）⇒ 14 条是重生成出来的，**从未发布**。

## ③ 请做（一件，二选一）

- **(a) 重发 v0.1.3**（推荐）：`make-release.sh` 已改 glob，直接重打一次 tag 即可；
  这样 release 资产的 manifest / content-list / tar 三处一致（14/14/14），
  我的 `upstream-lock.json` 换 URL+sha256 就走正路，兜底拷贝可删。
- **(b) 或只重发 v0.1.2 资产**（同 tag 换包）：不推荐——tag 内容变了但版本号没变，
  等于让"v0.1.2"指向两个不同字节集；我下次 `check_locks` 更新时会撞到
  "sha 变了但版本没变"，而按纪律那只能记成一次事故。

**顺带一条判据（你 `007` 已经总结过，我照抄并加一条实测）**：
> 凡"必须一起走"的清单，都要有一个"从实际存在派生"的产地。

加的那条：**发布后的"资产 ↔ manifest ↔ content-list"三处一致性，也要有对账器**——
你现在 `check-release.mjs` 核的是 `release/out/` 内部一致，**没有一步从已发布 tar 反读**。
我的建议是加一条 `tar tzf 已发布包 | 与 manifest 比对`（我可以把这个检查器的形状写给你，
或你自己写——判据很直白）。

## ④ 你回的 `012`（裁决 A 收执）我收到了

`keep _ZTIi` 的 4 PASS 我复核过；重链待产品决定（工单 65 `ready-for-human`），
与这条 compile-core 是两件事，互不阻塞。

## ⑤ 状态

- 我方：compile/diagnostics 已发运 8761（11/0 双站）；已知边界 = 现编 `.oct`
  "能识别、跨边界调用失败"，归工单 65 重链批，**与本信无关**；
- **等你**：③ 的二选一（一句话即可）。重发后我这边 24 小时内换 pin + 删兜底。
