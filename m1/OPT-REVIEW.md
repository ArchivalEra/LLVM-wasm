# 复核：隔壁那份 OPT-RESULTS.md（我方独立验证）

> 复核人：LLVM-wasm 仓的上一轮 agent。**不是转述**——下面每条都是我自己跑出来的，
> 与隔壁的日志分开。数字口径：本仓台账键 + 我现场量的值。
>
> **⚠️ 2026-10-10 追记（第三方复核了这份复核）**：本文件 §1.4 给出的"确切命令"
> **是错的**，而且**方向恰好反了**。我建议加的 `-sSUPPORT_LONGJMP=wasm` 正是
> **制造**那个链接失败的旗标。§1.2 的符号表是对的、§1.1 的旗标冲突观察也是对的，
> 但我据此推出的修法错了。更正见文末 **§5**，实测证据在
> `m1/evidence/opt-lean_nosjlj.log`（末尾附失败那一次的报错原文）与 `m1/OPT-RESULTS.md` §5.2.2。

## 0. 复核结论

| 隔壁的断言 | 我的复核 | 判据 |
|---|---|---|
| 基线实际是 `-O3`（不是 `-O1`） | ✅ **成立** | `ninja -t commands` 里 `-O1` 与 `-O3` 同时在，emcc 认最后一个 |
| `anchor`（MinSizeRel）：clang brotli 16.40 → 13.30 MB | ✅ **成立** | 我复算 brotli q11 = 13,301,149（与它一致） |
| 最好组合合计 21.80 MB，超预算 45% | ✅ **成立** | 独立算：13,301,149 + 8,495,303 = 21,796,452 |
| **两份更小的产物还能编出东西** | ✅ **成立**（我独立跑的验收） | 我自己跑 `acceptance-full.mjs`：**10 PASS / 0 FAIL**，`minifn.so` 976 B |
| `-fno-exceptions` 走不通，卡 `emscripten_longjmp` | ⚠️ **现象成立，但根因诊断不完整** | 见 §1 —— 这是本轮复核最有价值的更正 |
| `wasm-opt -Oz` 无用 | ✅ 成立，且**它给出了正确解释** | 基线链接期已跑过 binaryen（`-O3`），我 handoff 那条判断的依据是错的 |

**一句话**：隔壁的交付质量高，数字可信，负结果也诚实。唯一要更正的是 §1 那条诊断——
它把"旗标冲突"误判成了"必须改 LLVM 源码"。

**但要连我的更正一起更正**：我 §1.4 给的修法也是错的（见文末 §5）。

---

## 1. 更正：`emscripten_longjmp` 失败的根因

隔壁 §5.2 写「要做成需要**改源码**」，并猜「`-sSUPPORT_LONGJMP=wasm` 是下一个最该试的命令」。
**方向对，但根因不是它说的那个。** 我从它的证据日志里读出了真实机制：

### 1.1 它的链接行里有两个互相矛盾的旗标

```
m1/evidence/opt-lean.log 的链接行（原文摘录）：
  em++ -Os -fno-exceptions -fno-rtti ... -fwasm-exceptions ... -o bin/clang.js-24
```

`-fno-exceptions` 与 `-fwasm-exceptions` **同时在场**。实测计数（同一日志）：
`-fno-exceptions` ×2、`-fno-rtti` ×2、`-fwasm-exceptions` ×1。

### 1.2 真正的机制：`-fno-exceptions` 让 emcc 换了 builtins 变体

我在 sysroot 里逐个查了符号（`llvm-nm --defined-only`）：

| builtins 变体 | 有 `emscripten_longjmp`？ |
|---|---|
| `libclang_rt.builtins.a` | **有** |
| `libclang_rt.builtins-mt.a` | **有** |
| `libclang_rt.builtins-ww.a` | **有** |
| `libclang_rt.builtins-legacysjlj.a` | **无** |
| `libclang_rt.builtins-wasmsjlj*.a` | **无** |

而隔壁那次链接，emcc 实际选的是 **`libclang_rt.builtins-legacysjlj`**（我在它日志的
链接行里 grep 到）。⇒ **符号缺，是因为选错了 builtins 变体**，不是因为 LLVM 源码需要改。

### 1.3 独立验证：单独用 `emscripten_longjmp` 并不必然失败

```sh
printf 'extern "C" void emscripten_longjmp(int);\nextern "C" int f(void){ emscripten_longjmp(1); return 0; }\n' > probe.cc
em++ -Os -fno-exceptions probe.cc -o p.js            # rc=0，只有 warning: function signature mismatch
em++ -Os -fno-exceptions -sSUPPORT_LONGJMP=wasm probe.cc -o p2.js   # rc=0，连 warning 都没了
```

⇒ 光 `-fno-exceptions` **能链接**（只是签名警告）。**加 `-sSUPPORT_LONGJMP=wasm` 警告也消失。**

### 1.4 所以下一轮该试的**确切**命令

不是"改源码"，而是：**去掉那个矛盾的 `-fwasm-exceptions`，并显式给 `SUPPORT_LONGJMP`**。
`m1/exp-build.sh` 里对应的改法是 `lean` 配置的 flag 只留：

```
-Os -fno-exceptions -fno-rtti -sSUPPORT_LONGJMP=wasm
```

（`-fno-unwind-tables` / `-fno-asynchronous-unwind-tables` 可留，它们只是省表。）

**但要诚实说**：即使这条通了，隔壁 §5.2 的收益预估（10–20%，即约 17–19 MB）
**仍然达不到 15 MB**。所以本条的**主要价值**是"把一条被误判为'要改源码'的路，降级为'改一个旗标'"，
而不是"能达标"。

---

## 2. 我这边要更正的（我 handoff 里的错）

隔壁抓到我一个真错误：我写「基线 `-O1`」是错的。

`m1/build-clang-wasm.sh` 里写 `-DCMAKE_C_FLAGS="-O1"`，但 `CMAKE_BUILD_TYPE=Release`
会在后面追加 `-O3 -DNDEBUG`，emcc 认最后一个 ⇒ **实际 `-O3`**。

这条错误导致我 handoff 里那句「`wasm-opt -Oz` 只省 36 KB ⇒ 体积不在可消冗余里」的
**论证依据是错的**（真实原因是 binaryen 已经跑过一遍了）。结论碰巧对，理由是错的——
按本仓纪律，这种要写进翻案台账。

⇒ 已记 `retractions.json` 的 R-007（见下一条提交）。

---

## 3. 对 SPEC 的影响（需要委托人拍板，不是我能定的）

综合两轮实测：

- SPEC §6 的 brotli 预算 **≤ 15 MB**，两轮最好组合 **21.80 MB**（超 45%）。
- 未打通的最强杠杆（关异常+RTTI）乐观估计到 **17–19 MB**，**仍超**。
- 已探明的其余方向（裁 driver、分片懒加载）按隔壁 §5.3 判断都是 <1.5 MB 量级。

⇒ **15 MB 这个目标按现在的功能集合大概不成立**。三个可能的方向（我只列，不选）：

1. **改预算**（把 15 MB 抬到 ~22 MB），接受现状 + 已得的 16.4% 减重；
2. **改功能集合**——比如只支持 C（不带 C++ 前端/异常/RTTI）、或只支持编译不支持链接；
3. **改交付形态**——分片懒加载（首拉只带常用部分），让"首拉 ≤15 MB"成立而总量更大。

这条要问 SPEC 的委托人。我已把问题写进 `to-questionnaire-clang-wasm-m1.md` 的 C 组。

---

## 4. 我复核时用的命令（可复跑）

```sh
cd /mnt/hdd/zcode-projects/LLVM-wasm

# 1) 基线其实是 -O3
ninja -C m1/build-clang -t commands tools/clang/lib/Basic/CMakeFiles/obj.clangBasic.dir/Version.cpp.o | grep -oE '\-O[0-9s]+'

# 2) 两份更小的产物真的还能编（我独立跑的，不是它的日志）
M1_CLANG_BIN=m1/build-exp-anchor/bin M1_LLD_BIN=m1/build-lld/bin \
  M1_LLD_JS=lld-wasm-only.js node m1/acceptance-full.mjs

# 3) 复算 brotli（口径：q11）
python3 -c "import brotli,sys;print(len(brotli.compress(open(sys.argv[1],'rb').read(),quality=11)))" \
  m1/build-exp-anchor/bin/clang.wasm

# 4) builtins 变体谁有 emscripten_longjmp
for a in toolchain/emsdk/upstream/emscripten/cache/sysroot/lib/wasm32-emscripten/libclang_rt.builtins*.a; do
  printf '%-48s %s\n' "$(basename $a)" \
    "$(toolchain/emsdk/upstream/bin/llvm-nm --defined-only $a 2>/dev/null | grep -c emscripten_longjmp)"
done
```

---

## 5. 追记：我 §1.4 给的那条命令是错的（方向反了）

**实测推翻了它。** 我建议的

```
-Os -fno-exceptions -fno-rtti -sSUPPORT_LONGJMP=wasm
```

跑出来的结果**仍然是同一个链接失败**（`emscripten_longjmp` undefined）。
去掉 `-sSUPPORT_LONGJMP=wasm` 之后**才通过**：

| 链接旗标 | emcc 选中的 builtins 变体 | 有 `emscripten_longjmp`？ | 结果 |
|---|---|---|---|
| 带 `-sSUPPORT_LONGJMP=wasm` | `libclang_rt.builtins-legacysjlj` | **无** | **失败** |
| **不设** `SUPPORT_LONGJMP` | `libclang_rt.builtins` | **有** | **成功（48,069,274 B raw）** |

### 5.1 我错在哪

我在 §1.2 正确地测出"只有 `builtins` / `-mt` / `-ww` 三个变体有那个符号"，
也正确地看到"那次链接选的是 `-legacysjlj`"。**但我把因果搞反了**：
我以为 `-legacysjlj` 是"`-fno-exceptions` 带来的默认"，于是想用
`SUPPORT_LONGJMP=wasm` 把它"掰"到 wasm-sjlj 那一支（`-wasmsjlj`）——
而**那一支同样没有这个符号**（我自己的 §1.2 表里就写着"无"，我读漏了）。

更根本的是：`-sSUPPORT_LONGJMP=wasm` 正是 emcc 用来**进入** legacy/wasm-SJLJ
分支的开关（`settings.WASM_LEGACY_EXCEPTIONS` 默认 `true` ⇒ 落到 `-legacysjlj`）。
**不设它**时走的是 `Exceptions.EMSCRIPTEN` 默认支，才拿到有符号的 `builtins.a`。

机制原文（`tools/system_libs.py:898` `get_default_variation`）：

```python
if settings.SUPPORT_LONGJMP == 'wasm':
    if settings.WASM_LEGACY_EXCEPTIONS:   # 默认 true
        eh_mode = Exceptions.WASM_LEGACY   # -> '-legacysjlj'（无 emscripten_longjmp）
    else:
        eh_mode = Exceptions.WASM          # -> '-wasmsjlj'（也无）
else:
    eh_mode = Exceptions.EMSCRIPTEN        # -> 'builtins.a'（有）
```

### 5.2 教训（写给下一个 agent）

我 §1.3 那个"独立验证"是**假阳性**：我拿一个只调用 `emscripten_longjmp` 声明的
最小夹具去试，它能过，我就以为找到了正解。但那个夹具**没有 LLVM 的
`CrashRecoveryContext`**，走的 builtins 选择路径和真链接不一样 ——
**夹具过了不等于真目标过了**。这正是本仓最恨的「仪器量的不是想量的」家族：
我用一个不能代表目标的探针，给真目标开了一条错药方。

**判据**：任何"根因诊断"要成立，必须在**真目标**上复现修复前后两种结果，
而不是在最小夹具上。我这次做到了前半（真目标的失败），没做到后半（真目标的成功）。

### 5.3 结果

打通后的收益是 **−5.2%**（clang brotli 13,301,149 → 12,614,129），
比隔壁原本的乐观预估（10–20%）小。**新最好组合 21.11 MB，仍超 15 MB 预算 41%。**
完整数字与 flag 见 `m1/OPT-RESULTS.md` §5.2.1 / §5.2.2。
