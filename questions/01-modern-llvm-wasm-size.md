# 01: 现代 LLVM 编译器的实际体积（SPEC §6 那张表是 LLVM 8 的旧数）

**What to build:** 把 clang / lld 编成 wasm，量出 **LLVM 24（本仓工具链）**的真实体积，
替换 SPEC §6 那张表 —— 那张是 LLVM 8（一个很老、WASI 向的实现）的实测，SPEC 自己
标了「**这一格是推断**，你的第一件事就是把它量成实测」，raw 估计 35–60 MB。

**Blocked by:** M1（把 clang+lld 编成 wasm）。

**Status:** ready-for-agent

**Settling:** 三个数都从真实产物量出来，写成本仓台账的新键 ⇒ 可结案。判据两种结论：
`python3 zreflect/facts.py --get clang_wasm_brotli_bytes` —— rc=0 ⇒ 已量得现代 LLVM 的真实体积，
结案；rc=2（键不存在）⇒ M1 还没产出 clang.wasm，本单仍 blocked。
若量出的 raw 体积落在 SPEC 推断的 35–60 MB 之外 ⇒ 结案但须同时更正 SPEC §6 的推断区间。

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
