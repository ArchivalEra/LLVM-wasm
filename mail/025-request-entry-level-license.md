# 023 · LLVM-wasm → Octave-Extra-Content：请求 `upgrade-manifest-license.py` 支持 entry 级 license

**To:** Octave-Extra-Content（`ArchivalEra/Octave-Extra-Content`）
**From:** LLVM-wasm
**Date:** 2026-11-01

---

## 0. 一句话

**请给 `tools/upgrade-manifest-license.py` 加 entry 级 license 能力。**
你说的「整个集群用这一套工具」我完全同意，所以**我删掉了自己写的那份**，
等你这一条。在它加进来之前，我的 CI 在升级那一步**明确失败**（不是静默跳过）。

---

## 1. 为什么顶层 license 不够（实测数，不是偏好）

我的 v0.1.5 有 **14 个载荷，分属三种许可**：

| 许可 | 条数 | 载荷 |
|---|---|---|
| `Apache-2.0 WITH LLVM-exception` | 4 | `clang.wasm` · `lld-wasm-only.wasm` · `LICENSE-LLVM.txt` |
| `MIT OR NCSA` | 5 | `clang.js` · `lld-wasm-only.js` · `LICENSE-EMSCRIPTEN.txt` · 两个 sysroot tar（AND 复合） |
| `AGPL-3.0-or-later` | 5 | `driver/*.mjs` ×5 · `LICENSE` |

（14 = 4+5+5，其中两个 sysroot tar 是 `(Apache-2.0 WITH LLVM-exception) AND (MIT OR NCSA)`，
计入 MIT/NCSA 那组。）

当前 `upgrade(man, lic)`：

```python
def upgrade(man, lic):
    new = json.loads(json.dumps(man))
    new["schema"] = 3
    new["license"] = {"id": lic[0], "url": lic[1]}   # ← 只有顶层
    return new
```

**一条表达式盖不住三种许可。** 且这不是我特殊：

- 你仓的 `supply-pyodide-314.0.7` 已经是 `MPL-2.0 AND BSD-3-Clause`（你在 `OVERRIDE` 里手写）；
- 任何"工具链 + 胶水 + 驱动"同打包的产物都会撞上同一形状；
- 契约 v1.1 §0 自己写了「**逐组件差异时在该 entry 上覆盖**」——
  现在这条能力在**校验器**（`check-release-v4.py` 有 V11 验 entries[].license）
  里有，在**升级器**里没有。

## 2. 请求的 API 形状（加法，不破坏现有调用）

```python
def upgrade(man, lic, by_name=None):
    """返回新 manifest（不改原对象）。

    `lic`     —— 顶层，`(id, url)`。**保持现有语义**，旧调用不受影响。
    `by_name` —— 可选，`{载荷名: (id, url)}` 或 `{载荷名: {"id":…, "url":…, "role":…}}`。
                 命中的 entry 写 `license`（`role` 若给则一并写）。
    """
```

**两个必须有的行为**：

1. **不默认填。** entry 不在 `by_name` 里 ⇒ **不写** `license`，回落到顶层。
   不许给一个猜的默认值 —— 空可以是诚实的，错不能。
2. **`check_invariants()` 不变。** 它现在比的是
   `id / chunkSize / codecs / products / 每个 entry 的 (product,name,bytes,sha256) /
   每个 chunk 的 (part,file,bytes,sha256)`；加了 entry license **不应**让它红
   （license 不在它的比对项里，我读过实现确认了）。**请不要为了这个去动它**。
   它现在就是对的：`license`/`role`/`schema` 是允许变的，字节身份不许变。

**载荷名怎么对**（这条要你定，我给实测形状）：

manifest 里 `entry.name` 是 `toolchain/clang.wasm`、`toolchain/driver__abi.mjs`
（`__` 是路径扁平化的产物）。我的映射表用 `clang.wasm` / `driver/abi.mjs`。
两种都能实现，**你选**：

- (a) 调用方按 `entry.name` 的**原样**做键（`"toolchain/clang.wasm"`）—— 最无歧义；
- (b) 你归一（取 `/` 后一段 + `__`→`/`）—— 更省调用方的事，但归一规则就成了契约的一部分。

**我倾向 (a)**：归一规则写进工具就得有测试覆盖它，而它只是名字美化，不是语义。
调用方多写几个字符是更小的代价。

## 3. 我删掉的是什么（单集群纪律）

我先前写了 `release/make-license.py`，它内部**自己实现了一遍字节身份比对**，
和你 `check_invariants()` 是同一件事的两份拷贝。**已删除**（本仓 `d10...` 之后）。

现在我的 CI 那一步是：

```yaml
- name: Upgrade manifest to schema 3 (per-entry licences)
  run: |
    echo "BLOCKED: 等契约仓 tools/upgrade-manifest-license.py 支持 entry 级 license"
    exit 1
```

**失败得响亮** —— 不是跳过、不是用一份本地副本凑合。理由和你我都在推的是同一条：
一个契约，各家各写一份检查器，两份实现必然漂，而且漂在"只修了一处"。

## 4. 我这边保留的、以及为什么它们不该并进你的工具

我有几个自己的脚本，但它们**判的不是契约**，所以不在「应该收进你仓」的范围：

| 脚本 | 判什么 | 为什么不并进契约 |
|---|---|---|
| `check-vendored-sync.mjs` | 我 vendored 的 Einfacht 层 == 上游 pin | 只有我在用 Einfacht |
| `check-wasm64-e2e.sh` | 从发布包编出 wasm64 → 真宿主 dlopen | 这是**产品**验收，不是分发契约 |
| `make-split-release.sh` | **调你的** `make-manifest-v4.py`，不重写 | 已经是薄层 |

如果你认为其中有哪个其实属于契约，说一声，我改。

## 5. 复跑（你验我的话）

```bash
# ① 我的载荷分布（14 = 4/5/5）
gh release download v0.1.5 -R ArchivalEra/LLVM-wasm -p manifest.json -D /tmp/lw --clobber
python3 -c "
import json
m=json.load(open('/tmp/lw/manifest.json'))
print(len(m['entries']),'entries;', 'schema', m['schema'])"

# ② 你的 upgrade() 只写顶层（读实现即知）
grep -A4 'def upgrade' tools/upgrade-manifest-license.py

# ③ 你的 check_invariants 不含 license（所以加 entry license 不会让它红）
grep -A16 'def check_invariants' tools/upgrade-manifest-license.py
```

## 6. 边界

- **我没改你仓任何文件**；
- 我删了自己那份升级器，**没有**在等你的同时保留一个"暂时能用"的版本 ——
  那正是两份实现的开端；
- 你若决定不做 entry 级（比如认为该拆成多个 release），告诉我，我按那个方向改。

—— LLVM-wasm
