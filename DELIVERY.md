# 交付说明（下游怎么用这个仓）

> 对应 SPEC §2 交付物表与 §12 与下游的接口。数字全部来自 `FACTS.json`；
> 本文件不手抄，引用写 `[[键名]]`。

---

## 1. 这个仓交付了什么

| SPEC §2 要求 | 在哪 |
|---|---|
| `clang.wasm` + 胶水 | `release/out/clang.wasm` + `clang.js` |
| `lld.wasm` | `release/out/lld-wasm-only.wasm` + `lld-wasm-only.js` |
| `sysroot-headers.tar`（只含头文件） | `release/out/sysroot-headers.tar`（wasm32） |
| 同上、wasm64 档 | `release/out/sysroot-headers.wasm64.tar` |
| 驱动 API/脚本 | `release/out/driver/toolchain.mjs`（`compile()`，SPEC §7.4） |
| `manifest.json`（名字+字节+sha256+**许可证**+版本串） | `release/out/manifest.json` |
| `LICENSE` | `release/out/LICENSE`（AGPL-3.0，本仓胶水与脚本） |
| `LICENSE-LLVM.txt` | `release/out/LICENSE-LLVM.txt`（Apache-2.0 WITH LLVM-exception） |

外加 `LICENSE-EMSCRIPTEN.txt`（MIT/NCSA）——**胶水层是 emscripten 的产物**，
SPEC §2 只点了两份许可，这份是实测需要补的第三份。

### 许可分档（SPEC §2 的红线）

`manifest.json` 里逐资产标了 `license`，实测校验过：

- `clang.wasm` / `lld-wasm-only.wasm` / `sysroot-headers.tar` → **Apache-2.0 WITH LLVM-exception**
- `clang.js` / `lld-wasm-only.js` → **MIT OR NCSA**（emscripten）
- 驱动脚本 / LICENSE → **AGPL-3.0-or-later**（本仓）

**别把 AGPL 套在 wasm 上**（会给下游"提供完整对应源码"的义务，而那份源码不是你们的）。
`release/check-release.mjs` 有一条断言专门守这件事。

## 2. 怎么接（SPEC §12）

```sh
# 1. pin 本仓的一个 commit（submodule 或 fetch 都行）
git submodule add <this repo> vendor/llvm-wasm && cd vendor/llvm-wasm && git checkout <commit>

# 2. 读 manifest，按需拉资产
#    manifest.first_load.assets 列出首拉需要的三件；lld 是首次链接才拉的懒加载分片。
#    逐资产的 sha256 必须校验后才使用（fail-closed，SPEC §9.10）。

# 3. 调 compile()
```

```js
import { Toolchain } from '<bundle>/driver/toolchain.mjs';

const tc = new Toolchain({
  clangBin: '<bundle>', clangJs: 'clang.js',
  lldBin:   '<bundle>', lldJs: 'lld-wasm-only.js',
  bundle: { tarPath: '<bundle>/sysroot-headers.tar',
            manifestPath: '<bundle>/manifest.json' },   // ← sha256 在这里校验
  sysroot: undefined,                                    // bundle 模式下不需要
});

const r = await tc.compile({
  source,                       // 或 files: {name: text}
  target: 'wasm32',             // 'wasm64' 也支持（同一个工具链）
  abi: { exceptions: 'wasm-legacy', pthread: true, memory64: false },
  hostWasm,                     // ← 宿主 .wasm 的字节；给了就做 §5.4 缺口检查
});
// r = { ok, moduleBytes, diagnostics, symbolGap: {
//         missingFunctions, missingTags, sideSelfExported, hostChecked } }
```

**浏览器**里用 `browser/worker.mjs`（同一份 ABI 拼装，见下）。它已经做了：
sysroot 的 sha256 校验（`crypto.subtle`）、内存 FS 装载、编译。

## 3. ABI 契约（SPEC §4.5 / §8）

三个轴由**调用方**传，工具链不内置表：

```
exceptions: 'none' | 'emscripten' | 'wasm-legacy' | 'wasm-standard'
pthread:    bool
memory64:   bool
```

**必须与宿主一致**，否则装上也不对。本仓 `manifest.host_baseline` 记录了打包时已知的宿主契约：

```json
{ "exceptions": "wasm-legacy", "pthread": true, "memory64": false, "main_module": 2 }
```

⚠️ 判据是**契约相等**，不是版本号相等（SPEC §8）。
工具链跑在 emsdk **[[emcc_version]]**；下游宿主自 2026-10-11 起同为 6.0.12（同版本，
端到端见 `release/check-wasm64-e2e.sh`）。历史注：6.0.12 产物曾在 5.0.7 宿主上验证通过
（M0/M1 期），该轴已随下游全面切 6.0.12 退役。

**两档 sysroot 都在包里，按 `target` 自动选**（issue #1）：
`manifest.toolchain.sysroots` 给出 `{wasm32: …, wasm64: …}` 映射；把两档一起交给驱动即可：

```js
bundle: { tars: {
  wasm32: { tarPath: '<bundle>/sysroot-headers.tar',        manifestPath: '<bundle>/manifest.json' },
  wasm64: { tarPath: '<bundle>/sysroot-headers.wasm64.tar', manifestPath: '<bundle>/manifest.json' },
}}
```

**若某个 target 的 sysroot 不在包里，`compile()` 会明确拒绝**（不是静默降级）——
缺 crt 会让产物没有 `_emscripten_tls_init`，宿主到 dlopen 才报
`TypeError: tlsInitFunc is not a function`，症状完全不指向真因。

**`-s` 旗标与 clang 旗标面不同**：`-sWASM_LEGACY_EXCEPTIONS` 那类只对链接期有效，
喂给裸 clang 会让它静默退出 1。驱动已经处理，不要自己再拼一遍。

## 4. 宿主侧必须承诺的（SPEC §5.5）

工具链**不打包 `.a`**（SPEC §6），所以宿主必须能解析 side module 的导入符号：

1. **基线 = 宿主实际导出面**（从宿主 `.wasm` 的 export 表读），把字节传给 `compile({hostWasm})`，
   驱动会把缺口**点名**返回（含 tag 单列）。
2. **tag 做成显式必带**：下游宿主 keep-list 里请无条件包含
   `__cpp_exception` 与 `__cxa_*` 系列 —— 真实 `.oct` 里 [[oct_tag_importers]] / [[oct_total]]
   个文件导入异常 tag（全量普查）。
3. **`MAIN_MODULE=2` 可行**，但 keep-list 必须显式含 tag 与 `__cxa_*`（实测：
   bare MM=2 宿主连实例化都过不去，报 `LinkError` 缺 tag；补上 keep-list 后全绿）。

## 5. 已验证到什么程度（都可复跑）

| 验收 | 命令 | 结果 |
|---|---|---|
| M0：手搓 side module 被真宿主 dlopen | `sh m0/run-m0.sh` | [[m0_pass_wasm32]] PASS（wasm32/wasm64 两档） |
| M1：clang+lld 编成 wasm | `bash m1/build-clang-wasm.sh both` | 见 `m1/RESULTS.md` |
| 薄驱动 | `node driver/acceptance-driver.mjs` | 15 PASS |
| wasm64 是真 64 位 | `node driver/acceptance-wasm64.mjs` | [[wasm64_acceptance_pass]] PASS |
| sha256 fail-closed | `node driver/check-fail-closed.mjs` | [[fail_closed_pass]] PASS |
| 浏览器 Worker 编译 | `node browser/check-browser.mjs` | [[browser_acceptance_pass]] PASS |
| **浏览器闭环**：编译 → dlopen → 异常穿越 | `bash browser/build-host.sh && node browser/check-loop.mjs` | [[loop_acceptance_pass]] PASS |
| 交付包自足 | `node release/check-release.mjs` | [[release_acceptance_pass]] PASS |

**浏览器闭环**那条是核心：在真实 Chromium 里，worker 编出 side module（[[loop_sidemodule_bytes]] B），
页面把它 dlopen 进真实 emscripten 宿主，**异常双向穿越边界**（side 抛的 side 接、宿主抛的 side 接）。

## 6. 体积（SPEC §6）

| | brotli |
|---|---|
| 首拉（clang.wasm + 胶水 + sysroot） | **[[release_first_load_brotli]]**（预算 15,000,000） |
| 含 lld（懒加载分片） | [[release_total_brotli]] |

SPEC §6 的口径是「brotli ≤ 15 MB（**首拉**），支持分片懒加载」——按首拉算达标。
三轮减重的过程与负结果在 `m1/OPT-RESULTS.md`，我的复核在 `m1/OPT-REVIEW.md`。

## 7. 本仓的事实纪律

本仓用 [Einfacht](https://github.com/ArchivalEra/Einfacht)（vendored 在 `zreflect/`）：
文档正文**不手抄数字**，一律写 `[[键名]]`；台账 `FACTS.json` 是数字的唯一产地，
每条事实旁写复跑命令并由闸门每次提交逐字执行。被推翻的断言进 `retractions.json`
（当前 [[retractions_count]] 条），推断进 `questions/` 并注明哪个实验能结案。

复跑全部闸门：`sh gates-selftest.sh`（每道闸门先证明自己会红）。
