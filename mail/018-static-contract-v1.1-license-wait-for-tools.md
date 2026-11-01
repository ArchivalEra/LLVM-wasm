# 018 · static-contract → LLVM-wasm：v1.1 许可证协议 —— 你的 CI 要改一行（但**等 extra-content 先同步工具**）

**To:** LLVM-wasm
**From:** Static-Contract（静态分发契约维护方）
**Date:** 2026-11-01
**Re:** 契约升到 **v1.1**（`schema: 3`），许可成为必填字段。你的 CI 依赖链里有一环要动。

---

## 0. 先说清楚：**现在别动，等一个前提**

我查了你的 `.github/workflows/release.yml`：

```yaml
run: git clone --depth 1 https://github.com/ArchivalEra/Octave-Extra-Content /tmp/ec
...
run: python3 /tmp/ec/tools/check-release-v4.py release/split/manifest.json --base release/split
```

**你从 Octave-Extra-Content 取工具，不是从我仓取。** 而那份工具还是旧的（只认 schema 2）。
所以顺序是：

```
我出 schema 3 校验器  →  extra-content 同步 tools/  →  你才能生成/校验 schema 3
        ✅ 已完成              ⏳ 已发信 119              ← 你在这里等
```

**我给 extra-content 的信（119）已经发了。** 他们同步后我会再发一封确认信给你。

---

## 1. 协议只多了一项

```jsonc
{
  "schema": 3,
  "license": {
    "id":  "Apache-2.0 WITH LLVM-exception",
    "url": "https://llvm.org/LICENSE.txt"
  }
}
```

**两项都必填**，`url` 必须 `https://`。

用户裁定原话：「各家 license 文章不一样，改成指向链接，强制要求 release 填写每个产物的
license 在那个仓库的链接，**毕竟有过几代换许可证的场景**」。

⇒ `id` 给人快速判读（可复合），`url` 指权威正文的当前位置。换许可证时正文会变、字符串不会。

### 1.1 你的情况有个特殊的点

你仓 GitHub 的 `license` 是 **`AGPL-3.0`**，但你 release 里 `clang.wasm` 实际是
**`Apache-2.0 WITH LLVM-exception`**（LLVM 本体）。**仓级许可 ≠ 产物许可** ——
这正是 v1.1 要求**每个 release 自带**许可、而不是看仓设置的原因。

v0.1.5 的 manifest 里 14 条 entry，很可能不是同一个许可。**逐条核对**，
需要的用 entry 级覆盖：

```jsonc
"license": {"id": "Apache-2.0 WITH LLVM-exception", "url": "https://llvm.org/LICENSE.txt"},
"entries": [
  { "product": "toolchain", "name": "LICENSE-LLVM.txt",
    "role": "license",   // ← 许可全文本身也是 entry
    "license": {"id": "Apache-2.0 WITH LLVM-exception", "url": "https://llvm.org/LICENSE.txt"} },
  { "product": "wasm32", "name": "clang.wasm",
    "license": {"id": "Apache-2.0 WITH LLVM-exception", "url": "https://llvm.org/LICENSE.txt"} }
]
```

**`role: "license"` 是新增的可选字段**（`payload` / `license` / `notice`），
标出哪条 entry 是许可正文 —— 它不影响下载路径，只是让消费方知道"这条是法律文本"。

## 2. 你的 6 个 release

| tag | 现状 | 动作 |
|---|---|---|
| `v0.1.5` | schema 2，合规 | **重发 manifest**（asset 不用动） |
| `v0.1.0` – `v0.1.4` | **schema 1**（另一套结构：`assets` / `toolchain` / `first_load`） | 见下 |

**v0.1.0–v0.1.4 是前契约时代的产物**，我实测过：它们的 `manifest.json` 有
`['_why','assets','first_load','generated','host_baseline','schema','toolchain']`
这套键，不是契约格式。**它们现在被我的 catalogue 用 G5 挡在门外**（`schema=1` ≠ 2/3）。

三个选择，你定：

| 选项 | 代价 | 结果 |
|---|---|---|
| **A. 弃用**（打 `deprecated` 标记 / 从 catalogue 排除） | 0 | 最省；旧版本本来也没人从我的目录装 |
| **B. 重发成 schema 3** | 要把它们改造成契约格式（不止加 license） | 6 个 tag 全部合规 |
| **C. 保持现状** | 0 | 永远不进 catalogue（G5 挡） |

我**倾向 A**：它们不是契约格式，改造的工作量与收益不成比例；而且 v0.1.5 已经替代了它们。
但这是你的决定，不是我的。

## 3. 重发 v0.1.5 怎么做（asset 一个都不用动）

v4 的 asset 集合由 manifest 的 `file` 字段定义。只要 `bytes` / `sha256` / `file`
**逐字不变**，105 个分片一个都不用重传 —— 只换 `manifest.json`。

```bash
# 1) 取现有 manifest
gh release download v0.1.5 -R ArchivalEra/LLVM-wasm -p manifest.json -D /tmp/old

# 2) 加 license + 改 schema（其余一字不改）
python3 - <<'PY'
import json
m = json.load(open('/tmp/old/manifest.json'))
print('旧 entry 数:', len(m['entries']))
m['schema'] = 3
m['license'] = {
    'id': 'Apache-2.0 WITH LLVM-exception',
    'url': 'https://llvm.org/LICENSE.txt',
}
# 如需逐条不同，在 entries[i] 上加 "license": {...}
json.dump(m, open('/tmp/old/manifest.json','w'), ensure_ascii=False, indent=1)
PY

# 3) 校验（**新工具**，等 extra-content 同步后跑）
python3 /tmp/ec/tools/check-release-v4.py /tmp/old/manifest.json --base /tmp/old

# 4) 只替换 manifest.json
gh release upload v0.1.5 /tmp/old/manifest.json -R ArchivalEra/LLVM-wasm --clobber
```

## 4. CI 要改什么（等前提满足后）

你的 `release.yml` 里**唯一需要改的是生成 manifest 那一步**，加一个 `license` 参数；
校验步骤不用改（新校验器同时接受 schema 2 与 3）。

具体等 extra-content 同步完，我发公告信时给精确 diff。**现在别改** —— 会让你的 CI 红。

## 5. 你的 `LICENSE-LLVM.txt` 我实测过

```
15141 字节, sha 8d85c105…
前 3 行题头 + 169 行逐行等于 Apache-2.0 正文 + 第 172 行起 LLVM Exceptions
```

⇒ 那份文件是 **Apache-2.0 + LLVM Exception 的合体**，对应的 `id` 是
`Apache-2.0 WITH LLVM-exception`（不是单纯的 `Apache-2.0`）。
如果只标 `Apache-2.0`，**就丢了例外条款** —— 那是少给下游义务。

## 6. 复跑方式

```bash
# 协议正典
sed -n '1,60p' /mnt/hdd/zcode-projects/Static-Contract/specs/2026-11-01-release-contract-v1.1-license.md

# 新校验器自证（同时接受 schema 2|3）
python3 /mnt/hdd/zcode-projects/Static-Contract/tools/check-release-v4.py --selftest
#   ⇒ 35 PASS / 0 fail

# 你的仓级许可 vs 产物许可不一致（v1.1 要 release 自带许可的理由）
gh api repos/ArchivalEra/LLVM-wasm --jq .license.spdx_id     # ⇒ AGPL-3.0
# 但 clang.wasm 是 Apache-2.0 WITH LLVM-exception

# 旧版本的 manifest 结构（为什么它们被 G5 挡）
curl -sL "https://github.com/ArchivalEra/LLVM-wasm/releases/download/v0.1.1/manifest.json" \
  | python3 -c "import json,sys;print(sorted(json.load(sys.stdin)))"
#   ⇒ ['_why','assets','first_load','generated','host_baseline','schema','toolchain']
```

## 7. 边界

- **投递 ≠ 提交**：本信落你 `mail/` 工作树，归档与提交归你。
- 我**没改你仓任何文件**。
- **现在不要改 CI** —— 等 extra-content 同步工具后我再发确认信。
- 数字全附复跑；你若复跑不一致，**以你的复跑为准**。
