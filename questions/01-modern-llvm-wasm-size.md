# 01: 现代 LLVM 编译器的实际体积（SPEC §6 那张表是 LLVM 8 的旧数）

**What to build:** 把 clang / lld 编成 wasm，量出 **LLVM 24（本仓工具链）**的真实体积，
替换 SPEC §6 那张表 —— 那张是 LLVM 8（一个很老、WASI 向的实现）的实测，SPEC 自己
标了「**这一格是推断**，你的第一件事就是把它量成实测」，raw 估计 35–60 MB。

**Blocked by:** M1（把 clang+lld 编成 wasm）。

**Status:** resolved

**Settling:** ✅ **已结案**（M1 完成时）⇒ `python3 zreflect/facts.py --get m1_clang_wasm_brotli` —— rc=0 ⇒ 已量得现代 LLVM 的真实体积（本单结案）；rc=2 ⇒ 键不存在，M1 产物或台账丢了，回到 blocked。

**实测结论（LLVM 24 / emsdk 6.0.12，`-O1`、只开 WebAssembly 后端）**：

| 资产 | raw | gzip -9 | brotli -q11 |
|---|---|---|---|
| `clang.wasm` | [[m1_clang_wasm]] | [[m1_clang_wasm_gzip]] | [[m1_clang_wasm_brotli]] |
| `lld.wasm`（wasm-ld） | [[m1_lld_wasm]] | [[m1_lld_wasm_gzip]] | [[m1_lld_wasm_brotli]] |

**两条与 SPEC §6 的出入**：

1. **raw 推断偏低**：SPEC 猜「现代 LLVM raw 35–60 MB（合计量级）」；
   实测**单 `clang.wasm` 就 71 MB**，两个加起来 110 MB。推断区间要改。
2. **brotli 明显超预算**：SPEC §6 的预算是「brotli 后 ≤ 15 MB（首拉）」。
   实测两个 wasm 的 brotli **合计 26.1 MB** —— 超预算约 74%。
   ⇒ §6 的减重方向（`-Os`/MinSizeRel、`wasm-opt -Oz`、只带 `-cc1` 不带完整 driver）
   **从"进一步优化"升级为"必须做"**，否则 §6 的预算目标不成立。

## 为什么留着不删

第一稿的 SPEC §6 表里，`clang` 29.77 MB / `lld` 18.59 MB / 合计 brotli 13.07 MB 这组数
是 **LLVM 8** 的。本仓工具链是 LLVM 24，两者差 16 个大版本，体积必然不同。
「推断 35–60 MB」写不出复跑命令，按本仓纪律**不许留在活状态**（见 `AGENTS.md` 纪律 5）。

## 复跑方式（M1 完成前跑不了 —— 这正是它 Blocked 的原因）

```sh
# M1 产出后：
stat -c%s build/clang.wasm build/lld.wasm
gzip -9 -c build/clang.wasm | wc -c
brotli -q 11 -c build/clang.wasm | wc -c     # 若装了 brotli
```

结案时把上面三条改成台账键的 `cmd`（裸值契约：只打印数字）。

**Type:** task

- [ ] M1 产出 clang.wasm / lld.wasm
- [ ] 量 raw / gzip / brotli 三档，写进台账
- [ ] 用 `[[键名]]` 替换 SPEC §6 表里的推断值
- [ ] 结论回填，`Status:` 改 `resolved`，**别删这个文件**
