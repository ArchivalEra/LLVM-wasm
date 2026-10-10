# M2（部分）：薄驱动 —— SPEC §7.4/§7.5 的 `compile()` 接口

> 状态：**绿**。`driver/toolchain.mjs` 实现了 §7.4 的接口，验收
> [[driver_acceptance_pass]] 项 PASS / 0 FAIL，缺口检查的反向断言 [[gap_reverse_pass]] 项 PASS。
> 数字全部来自 `FACTS.json`。

复跑：

```sh
node driver/acceptance-driver.mjs                                   # 全链 + 反向断言
node driver/acceptance-driver.mjs --host <宿主.wasm>                 # 带真宿主做 §5.4 缺口检查
node driver/check-gap-reverse.mjs                                   # 缺口检查必须点名真缺口
```

---

## 1. 做了什么

SPEC §7.5 说：**自己写薄驱动**，按 §4.1/4.2 拼命令行，**不要**移植 clang driver / `emcc.py`
（它们的价值是"猜旗标 + spawn 子进程"，浏览器里都不需要/不可用）。

`driver/toolchain.mjs` 就是那个薄驱动，它owns四件事：

| 职责 | 对应 SPEC |
|---|---|
| 拼 §4.1 编译行 + §4.2 链接行（已去掉 LLVM 24 移除的旗标） | §4.1 / §4.2 |
| 内存文件系统：源码 / sysroot / 产物都在 wasm 内流转 | §7.2 |
| §5.4 缺口检查（扣 side 自导出、tag 单列） | §5.4 / §5.5 |
| ABI 四项**由调用方传**，工具链不内置旗标表 | §4.5 |

它**不**负责：拉资产、sha256 校验、Worker 边界（§7.3）、打包。那些留给调用方。

接口（SPEC §7.4 原文的形状）：

```js
const r = await tc.compile({
  source,                    // 或 files: {name: text}
  target: 'wasm32',          // 'wasm64' 未建 ⇒ 明确拒绝，不静默降级
  abi: { exceptions: 'wasm-legacy'|'wasm-standard'|'emscripten'|'none',
         pthread: bool, memory64: bool },
  hostWasm,                  // 宿主 .wasm ⇒ 做 §5.4 缺口检查
  flags, define, include,
});
// r = { ok, moduleBytes, diagnostics, symbolGap: {missingFunctions, missingTags, sideSelfExported} }
```

## 2. 验收覆盖（每条都是实测）

| 组 | 断言 |
|---|---|
| 正向 | `compile()` 返回 ok、产出 [[driver_module_bytes]] B 的 side module |
| 产物 | 导出 `minifn` / `__wasm_call_ctors` / `_emscripten_tls_init`；导入 `env.memory`；可重定位（`__memory_base`） |
| §5.4 | 缺口报告含三个具名字段；**没给宿主时 `hostChecked=false`**（不谎报"无缺口"） |
| §4.5 反例 | 未知 `abi.exceptions` **被拒**；`target:'wasm64'` **被拒**（不静默当 wasm32）；空输入**被拒** |
| 缺口反例 | 一个**真有缺口**的夹具 ⇒ 两个缺失符号都被点名（含 SPEC §5.2 记录的那个真缺口） |

最后一行最重要：**一个永远回答"无缺口"的检查器能通过正向用例**，只有反向用例能抓住它。
`driver/check-gap-reverse.mjs` 就是这个反向用例，它在一个真宿主上验证：

```
MISSING _ZNSt3__213basic_ostreamIcNS_11char_traitsIcEEElsEm   ← SPEC §5.2 记录的真缺口
MISSING host_symbol_that_does_not_exist                       ← 测试埋的（不依赖某个宿主的 STL 实例化）
```

## 3. 过程中的一个坑（M1 报告的同类）

**`-s` 设置不能进裸 clang 的编译行。** 我最初把 `-sWASM_LEGACY_EXCEPTIONS=1` 写进
`compileFlagsFor()`，clang **退出 1 且不给有用的诊断**（安静地失败）。
`-s` 是 emcc 的设置，不是 clang 的。

修法：编译行只放 **codegen 选择**（`-fwasm-exceptions` 或 `-fno-exceptions`），
`-sWASM_LEGACY_EXCEPTIONS` 那类**链接期**设置归 `linkFlagsFor()`。
这与 M1 踩的"`-s` 旗标放编译期被静默丢弃"是同一个家族：**emcc 与 clang 的旗标面不同，
混用会安静地坏**。

## 4. 与隔壁产物的兼容

驱动不绑死某个构建：实测**基线**（`m1/build-clang` + `lld.js`）与**优化版**
（`m1/build-exp-anchor` + `lld-wasm-only.js`）**都能驱动**，产物尺寸分别
966 B / 976 B（差异来自优化档，都通过 ABI 检查）。

⇒ 隔壁的体积线一有更好的产物，驱动**换路径即可用**，不需要改代码。

## 5. 还没做的（M2 的其余部分）

SPEC §7 还要求三件，都不在本轮：

1. **Worker 化**（§7.3）—— 现在是在 node 里跑；浏览器里要进 Web Worker，
   且要避开主线程 >8 MB 同步编译的限制。这需要真实浏览器环境。
2. **sysroot 打包**（§6）—— 现在是从宿主目录喂进 FS；交付物要变成 tar
   （`pic/crtbegin-mt.o`、wasm64 那套要**预生成**）。
3. **manifest + sha256 校验**（§2 / §9.10）—— 资产清单与 fail-closed 校验。

## 6. 文件

| 文件 | 作用 |
|---|---|
| `driver/toolchain.mjs` | 薄驱动：`compile()` + `symbolGap()` |
| `driver/acceptance-driver.mjs` | 验收（正向 + §4.5 反例 + §5.4 报告） |
| `driver/check-gap-reverse.mjs` | 缺口检查的反向断言 |
| `driver/evidence/*.log` | 证据（含 `ARTIFACT` 行 = 数字产地） |
