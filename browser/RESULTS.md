# M2（浏览器部分）：真实 Chromium 里的 Worker 编译

> 状态：**绿**。SPEC §7.3（Worker 化）、§9.4（异常）、§9.8（纯客户端）在**真实浏览器**里验证。
> 验收 [[browser_acceptance_pass]] 项 PASS / 0 FAIL。数字全部来自 `FACTS.json`。

复跑：

```sh
node browser/check-browser.mjs        # 起 Chromium（playwright-core）+ 带 COOP/COEP 的静态服务器
```

---

## 1. 结论

**整条编译链在真实 Chromium 里跑通**，产物与 node 逐字节同尺寸：

| 夹具 | 浏览器 | node 对照 |
|---|---|---|
| §9.1 最小 C++（`minifn`） | [[browser_module_basic_bytes]] B | [[driver_module_bytes]] B |
| §9.4 异常夹具（`minithrow`） | [[browser_module_eh_bytes]] B | 2117 B（`/tmp/ehrepro.mjs`） |

复跑方式与 node 驱动**共用同一份 ABI 拼装**（`driver/abi.mjs`）——这是刻意的：
SPEC §4.5 说「两边各存一份表 ⇒ 必然漂移」，所以旗标与缺口判定只有一个产地。

## 2. 三个"没有真浏览器就发现不了"的约束

### 2.1 主线程禁止同步编译 >8MB 的 wasm

```
RangeError: WebAssembly.Compile is disallowed on the main thread,
  if the buffer size is larger than 8MB.
```

我们的 `clang.wasm` 是 **48 MB**（lean 档）——**这条把 §7.3「放 Web Worker」从建议变成了硬约束**。
诊断也因此只能在 worker 里跑。

### 2.2 pthread 需要跨源隔离

`crossOriginIsolated === false` 时 `SharedArrayBuffer` 未定义，pthread 模块起不来。
服务器必须发：

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

### 2.3 glue 与 wasm 必须**配对**

`lld-wasm-only.js` 只能配 `lld-wasm-only.wasm`。配错（用 `lld.wasm`）会报：

```
LinkError: Import #41 "a" "P": function import requires a callable
```

因为 minimized 后的 import 字母表在两个构建间**不同**，glue 的 `wasmImports` 名字对不上。
这条在 node 下也会中，但 node 驱动恰好一直用配对的组合，所以从没暴露。

## 3. 三个 glue 适配问题（都有实测支撑）

1. **UMD 在 `import()` 下没有导出**：glue 尾部三个 UMD 分支都不命中 ⇒ `factory is not a function`。
   worker 追加一行 `export default createToolChain` 解决。
2. **`instantiateAsync` 忽略传给它的 `binary`**，转而 fetch `locateFile('clang.wasm')`；
   从 blob URL 导入时没有 scriptDirectory ⇒ fetch 到 404 空响应 ⇒
   `BufferSource argument is empty`。传 `locateFile` 修正。
3. **我们接管实例化**（`instantiateWasm` 钩子）：glue 自己的路径在浏览器里报
   `Import #41 "a" "P"`，而**同一个 import 对象**直接 `WebAssembly.instantiate(wasm, info)`
   连续两次都成功（实测）。钩子回调要的是**instance**，不是 `{module, instance}` ——
   传错会让 glue 的 `wasmExports` 变 undefined，随后报
   `Cannot read properties of undefined (reading '_')`。

## 4. 一个 emscripten lld 的状态陷阱

**同一 lld 实例不能连续编译两次。** 第二次会报：

```
wasm-ld (LLVM option parsing): Unknown command line argument '-exception-model=wasm'
```

即使 argv **完全相同**（日志逐字对过）。emscripten 的 lld 在首次解析 `-mllvm` 时
latch 了一批 feature，之后同一参数被拒。

⇒ **每次 compile 用新实例**（worker 现在这么做，并给新实例重装 sysroot —— 新实例的 FS 是空的）。

## 5. §9.8 纯客户端的证据

不是断言，是**记录每一次网络请求**：

```
17 requests, all GETs
4 are in-page blob: glue（同源，页面自己拼的内存模块）
no URL carries source payloads
```

源码通过 `postMessage` 进 worker，**从不进 URL、从不 POST**。

## 6. 文件

| 文件 | 作用 |
|---|---|
| `browser/worker.mjs` | Worker：加载/校验/解包 sysroot、实例化 clang+lld、编译（§7.3） |
| `browser/index.html` | 主线程 harness：只与 worker 通信 |
| `browser/check-browser.mjs` | 验收：Chromium + COOP/COEP 服务器 + §9.8 请求记录 |
| `browser/server.mjs` | 开发用静态服务器（带 COOP/COEP） |
| `browser/evidence/browser.log` | 证据（`ARTIFACT` 行 = 数字产地） |

## 7. 还没做的

- **分片懒加载**（§6）—— 首拉预算已达标（14.31 MB），懒加载是架构手段，未实施。
- **浏览器里真正 dlopen** —— 本轮的浏览器验收到「产出 ABI 正确的 side module」为止；
  dlopen 那半在 M0 用 node 宿主验过（异常往返也是）。要在浏览器里也走一遍，
  需要一个 emscripten 主模块宿主页。
