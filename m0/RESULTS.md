# M0 结果：原生手工命令跑通 §4 全链

> 状态：**绿**。测于 emsdk **6.0.12** / clang **24.0.0git** / LLD **24.0.0**（wasm32 与 wasm64 两档）。
> 所有判定都有复跑命令。**本文的「现在如此」只写实测；与 SPEC 的出入单列 §5。**

复跑方式（每条 PASS 都是它打出来的）：

```sh
sh run-m0.sh                 # wasm32：编 side → 手链 → 编宿主 → dlopen → 调 → 查缺口
ARCH=wasm64 sh run-m0.sh     # 同一套，wasm64 档
sh run-counterexamples.sh    # §9.5 反例 + §9.6 模板缺口（需先跑过 run-m0.sh）
```

---

## 1. 结论：M0 通过

SPEC §10 的 M0 门槛是「原生手工命令跑通 §4 全链，产出 side module 并被宿主 dlopen 调通，
再跑 §9.5/9.6」。**全部达成**，且两档（wasm32/wasm64）都过。

手搓的 side module（**side module 全程不进 emcc**，只用裸 `clang` + `wasm-ld`）
被 emscripten 主模块 `dlopen` 成功并调用：

```
PASS dlopen
PASS minifn(7): got=10 want=10
PASS miniprobe([2,3;1,4]): got=5 want=5      ← 回调宿主符号（跨模块解析）
PASS minithrow(1): got=1 want=1              ← side 自己 throw 自己 catch
PASS minithrow(2): got=1 want=1              ← 宿主 throw，side catch
PASS ministl(42): got=42:2 want=42:2         ← std::map + std::ostringstream
=== ALL PASS ===
```

⇒ **ABI 侧无未知**。M1（把 clang+lld 编成 wasm）可以开工。

---

## 2. SPEC §4「五处缺一不可」的实测复核

| # | SPEC 说缺了会怎样 | 实测（6.0.12） |
|---|---|---|
| 1 | 缺 `--sysroot` ⇒ `'cinttypes' file not found` | ✅ 成立 |
| 2 | 缺 `-isystem <SR>/include/compat` ⇒ `'xlocale.h' file not found` | ✅ 成立 |
| 3 | 缺 `-pthread`+`--shared-memory` ⇒ `mismatch in shared state of memory` | ✅ 成立 |
| 4 | 缺 `crtbegin-mt.o`+`--export=_emscripten_tls_init` ⇒ `tlsInitFunc is not a function` | ✅ 成立 |
| 5 | 缺 `--export-dynamic` ⇒ 产物被 GC 成极小、导出全没 | ✅ 成立（无它时极小；有它时 [[m0_wasm32_side_bytes]] B 量级） |

五条全部复现。**但 SPEC §4.2 的命令行本身要改**，见 §5。

---

## 3. 体积与结构（实测）

| 量 | wasm32 | wasm64 | 复跑 |
|---|---|---|---|
| side module（`minifn.so`） | **[[m0_wasm32_side_bytes]] B** | **[[m0_wasm64_side_bytes]] B** | `stat -c%s build-*/minifn.so` |
| 其中 gzip -9 | 见下方复跑命令（一次性测量，**未入台账**） | — | `gzip -9 -c build-wasm32/minifn.so \| wc -c` |
| side 的 exports | [[m0_wasm32_side_exports]] | [[m0_wasm64_side_exports]] | `node -e '…Module.exports…'` |
| side 的 env 导入 | 见复跑命令（一次性测量，**未入台账**） | 同 | 同上 |
| 宿主导出（`MAIN_MODULE=1` + wasm EH） | **[[m0_wasm32_host_exports]]** | **[[m0_wasm64_host_exports]]** | `node -e '…host.wasm…'` |

宿主体积是 **MAIN_MODULE=1 的代价**（1.41 MB / 1.45 MB）——它不做 DCE，把所有符号都导出去。
这是 §5.3「宿主补导出」那条路的最宽松形态。

---

## 4. 三条路的实测代价（复核 SPEC §5.3）

SPEC §5.3 列了三条路。M0 把它们都跑了：

| 做法 | 实测结果 |
|---|---|
| 不链 `.a`（本 M0 的选择） | side [[m0_wasm32_side_bytes]] B ✅ **跑通**，但依赖宿主导出面 |
| 链 libc++ `.a` | SPEC §5.3 记录：+48× 体积、约千余个仍找不到 ⇒ 错路；**M0 未重复**（有前证；引用值见 SPEC 原文） |
| 宿主补导出（`MAIN_MODULE=1`） | 宿主见 §9 表，**缺口 0** ✅ |

**关键修正**：SPEC 与下游都记 `MAIN_MODULE=2`。**该配置下 M0 根本装不上**，见 §5 F-3。

---

## 5. ⚠️ 与 SPEC 的出入（v2 需要第三次更正）

### F-1（阻塞级）SPEC §4.2 的 `-mllvm -wasm-enable-eh` 在 LLVM 24 已不存在

```
wasm-ld: Unknown command line argument '-wasm-enable-eh'.
         Did you mean '--wasm-enable-sjlj'?
```

SPEC 原文：
```
wasm-ld … -mllvm -wasm-enable-eh -mllvm -exception-model=wasm
```
**改法**：去掉 `-mllvm -wasm-enable-eh`，只留 `-mllvm -exception-model=wasm`。
（`run-m0.sh` 用的就是修正后的命令行。）

另：`--experimental-pic` 仍**接受但已忽略**——`wasm-ld --help` 原文：
`--experimental-pic  Legacy enable Experimental PIC flag; ignored`。留着无害。

### F-2 SPEC §4.2 的 sysroot 路径在 6.0.12 是**按需生成**的

`<SR>/lib/wasm32-emscripten/pic/` 与 `<SR>/lib/wasm64-emscripten/` **初始都不存在**。
`crtbegin-mt.o` 由 emcc 在第一次需要时编出来（`emcc -v` 会打
`cache:INFO: generating system asset: … crtbegin-mt.o`）。

⇒ 工具链**不能假设这两个路径预先存在**；要么先跑一次 emcc 暖缓存，
要么自己在 wasm 里生成（这正是 M1/M2 要解决的问题）。
wasm64 的整个 sysroot 目录也是同理（跑过 `--target=wasm64-unknown-emscripten` 才出现）。

### F-3（最重要）`MAIN_MODULE=2` 下**异常 tag 不导出**，side module 装不上

SPEC 与下游都写 `MAIN_MODULE=2`（DCE 版 + keep-list）。实测：

| 宿主配置 | 导出数 | tag 导出 | 结果 |
|---|---|---|---|
| `MAIN_MODULE=1` | [[m0_wasm32_host_exports]] | `__cpp_exception`, `__c_longjmp` | ✅ dlopen 成功，全绿 |
| `MAIN_MODULE=2` | 30 | **0** | ❌ `LinkError: Import #14 "env" "__cpp_exception": tag import requires a WebAssembly.Tag` |

根因：`__cpp_exception` 这个 **wasm tag** 定义在 libunwind
（`system/lib/libunwind/src/Unwind-wasm.c` 的 `.tagtype __cpp_exception i32`），
而 `MAIN_MODULE=2` 的 DCE + 导出白名单默认不会把它带上。

⇒ **`MAIN_MODULE=2` 路线必须把 tag 显式补进导出**，否则异常模型根本跨不过边界。

**⚠️ 本条的两处初判已被后续实测推翻**（本行含更正标记；更正日期见 git 历史）：

| 初判（错） | 实测（对） |
|---|---|
| 「keep-list 从 IMPORT 段生成，**收不到 tag 这类非函数项**」 | ❌ 错。`wasm-dis` 把 tag 导入打成 `(import "env" "__cpp_exception" (tag …))`，`gen-keep-list.sh` 的正则 `^ \(import "(env\|GOT\..*)" "…"` **能匹配到**（实测：对 M0 side 跑同一套管道，`__cpp_exception` 在输出里） |
| 「这一步下游**今天没做**」 | ❌ 错。下游产物自带的 `octave.build.json` 写着 `main_module: 2`、`measured.exported_functions` 为一个三位数（**该数字出自下游产物，非本仓测量；见该文件**），而那批导出里**含 `__cpp_exception`** ⇒ 下游**已经做到了** |

**修正后的结论**：tag 缺口是真的（纯 MM=2、无 keep-list 时 dlopen 直接 `LinkError`），
但**修法是现成的**——把 tag 名纳入 keep-list 即可。实测验证：MM=2 + 从 side 导入
生成的 50 行 keep-list ⇒ 宿主导出 76 个（含 tag），dlopen **全绿**
（`m0/tagtest/`，`host3.js`）。

⇒ 对工具链的意义不变（§5.4 检查器**必须把 tag 单列一类**，因为它不是函数、
不在下游现有的函数型扫描里显式覆盖），但对下游现状的判断要更正：
**不是"没做"，而是"靠扫描隐式做到了，缺一个显式必带项"。**

### F-4 符号缺口检查器必须扣掉 side **自己导出**的符号

SPEC §5.4 让工具链比对「产物的 env 导入」与「宿主导出」。
**但 side module 会同时导入并导出同一符号**（GOT 自引用：`--export-dynamic` 下
`_ZNSt3__219piecewise_constructE` 等既在 imports 又在 exports）。
emscripten 的 `resolveSymbol` 查 `wasmImports → localScope → moduleExports`，
**side 自己的导出是合法解析源**。

不扣掉 ⇒ 假报警（实测：误报 3 个，实际缺口 0）。
`check-symbol-gap.mjs` 已修正（扣掉 `sideExports`），修正后 0 缺口与运行期一致。

### F-5 SPEC §9.5「去掉 `-fwasm-exceptions` ⇒ **装不上**」的失效模式更晚

SPEC §9.5 与 §4.4 反例都写「去掉 ⇒ **装不上**（`LinkError: Incompatible version`）」。
实测（6.0.12 + LLVM 24）**装得上**：

```
no-EH side: tag imports = 0     (EH side: 1)
→ PASS dlopen，通过 9 项检查，走到第一次 C++ throw 才炸
   UnhandledPromiseRejection: #<Exception>
```

⇒ 失效**不是**在加载期，而是**运行期首次 throw**。
这和 SPEC §5.1「装得上 ≠ 跑得对」是同一类，**比 SPEC 描述的更隐蔽**
（加载器不会拦，只有真跑到异常路径才暴露）。
验收第 5 条因此要改成「必须**在运行期**暴露」，不能只查链接期。

---

## 6. SPEC §9 验收标准逐条（本次可证的）

| # | 标准 | 结果 |
|---|---|---|
| 1 | 能编：最小 C++ → side module | ✅ `minifn`，[[m0_wasm32_side_bytes]] B |
| 2 | 能装：被主模块 dlopen | ✅ `PASS dlopen` |
| 3 | 能调 + 回调宿主 | ✅ `miniprobe` 返回 5 / -2 |
| 4 | 异常双向穿越 | ✅ `minithrow(1)` / `minithrow(2)` |
| 5 | 反例：异常模型改错**必须暴露** | ✅ 暴露，但是**运行期**（见 F-5），非链接期 |
| 6 | 模板：跑对 或 响亮点名缺符号 | ✅ 本例两档都跑对，缺口 0（F-4 修正后） |
| 7 | 两档 wasm32 + wasm64 | ✅ 都过 1–6 |
| 8 | 纯客户端 | ⬜ 不适用 M0（M1 起才在浏览器里） |
| 9 | 体积 | ⬜ M3 的事；M0 只记 side/宿主的原始字节 |
| 10 | 可校验 sha256 | ⬜ M3 |

---

## 7. 对工具链的硬要求（M0 逼出来的）

1. **异常 tag 是资产的一部分**：side module 依赖 `env.__cpp_exception`（wasm32/wasm64 都是 i32/i64 tag），
   宿主必须提供。工具链在 §5.4 的缺口检查里**必须把 tag 单列**（`missing tags` 计数），
   否则 F-3 会静默重演。
2. **sysroot 路径不可假设**：`pic/`、`wasm64-emscripten/` 都可能不存在（F-2）。
3. **命令行随 LLVM 版本漂**：`-mllvm -wasm-enable-eh` 的消失说明 SPEC §4 那种
   "逐字复现的命令行"必须**按版本参数化**，不能硬编码（呼应 SPEC §4.5 的旗标参数化要求，
   现在连 mllvm 选项也要参数化）。
4. **验收必须跑到运行期**：F-5 证明链接期全绿不代表异常模型对。
5. **tag 要进 keep-list**：F-3 更正后，下游 `gen-keep-list.sh` 的管道**能**扫到 tag，
   但那是"靠扫描隐式拿到"。工具链应把 tag 做成**显式必带项**（不依赖某个 `.oct`
   恰好被扫到），并把 `missing tags` 单列进 §5.4 的报错。
6. **MM=2 主路可行**：`run-mm2-keeplist.sh` 三步证据证明
   「MM=2 + 从 side 导入生成的 keep-list」可以 dlopen 全绿 ⇒ **不必为了异常
   退回 MM=1**（MM=1 的宿主体积代价见 §9 表）。

---

## 8. 文件清单

| 文件 | 作用 |
|---|---|
| `run-m0.sh` | 主 runner（wasm32/wasm64），编→链→宿主→dlopen→缺口 |
| `run-counterexamples.sh` | §9.5 反例 + §9.6 模板缺口 |
| `run-mm2-keeplist.sh` | F-3 证据：MM=2 bare / +tag / +keep-list 三步对比 |
| `side.cc` | side 夹具（minifn/miniprobe/minithrow/ministl） |
| `host.cc` | 宿主夹具（host_det2/host_error + 断言） |
| `landmine.cc` | STL 模板缺口夹具（`gen-landmine.sh` 生成） |
| `check-symbol-gap.mjs` | §5.4 缺口检查器（已修 F-4，tag 单列） |
| `toolchain/emsdk` | emsdk 6.0.12（**未入库**，见 `.gitignore`） |

---

## 9. 宿主配置的实测代价（F-3 更正后的三条路）

| 宿主配置 | 导出数 | tag | 体积 | 结果 |
|---|---|---|---|---|
| `MAIN_MODULE=2` bare | [[m0_mm2_bare_exports]] | 无（[[m0_mm2_bare_tags]] 个） | — | ❌ `LinkError`：缺 tag |
| `MAIN_MODULE=2` + 只导 tag | [[m0_mm2_tagonly_exports]] | 有 | — | ❌ 仍缺其余符号 |
| `MAIN_MODULE=2` + [[m0_keep_list_symbols]] 行 keep-list | [[m0_mm2_keeplist_exports]] | 有 | **[[m0_mm2_keeplist_bytes]] B** | ✅ 全绿 |
| `MAIN_MODULE=1`（无 DCE） | [[m0_wasm32_host_exports]] | 有 | **[[m0_wasm32_host_bytes]] B** | ✅ 全绿 |

复跑：`sh run-mm2-keeplist.sh`（三行一组依次验证）。
⇒ **MM=2 + keep-list 是正确的主路**；MM=1 是把 8.7× 的体积当"省事"来买。
下游当前用的正是 MM=2 + keep-list（行数见下游 `octave.build.json` 的 `inputs.keep_list.lines`，**非本仓测量**）。
