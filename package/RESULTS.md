# M2（部分）：sysroot 打包 + manifest + fail-closed

> 状态：**绿**。SPEC §6（交付形态）、§2（manifest）、§9.10（sha256 fail-closed）三项落地。
> 数字全部来自 `FACTS.json`。

复跑：

```sh
sh package/package-sysroot.sh wasm32        # 打包（实测构成，非猜测）
sh package/package-sysroot.sh wasm64
node driver/check-fail-closed.mjs           # §9.10 篡改必须被拒
M1_BUNDLE=1 node driver/acceptance-driver.mjs   # 交付路径：只从 tar 编译
```

---

## 1. 交付物：sysroot tar 里到底装什么（实测）

SPEC §6 说「只带**实际用到的**，不要整份 `lib/`」。我按**实测**而不是猜测来确定构成：

| 来源 | 宿主大小 | 进 tar？ | 为什么 |
|---|---|---|---|
| `include/` 整棵 | 23 MB | ✅ 全部 [[sysroot_wasm32_headers]] 个头 | 不同源码读不同头：一个 6 个 include 的夹具**实测读了 680 个头**（`-MD` 依赖输出）。按某个夹具裁剪会坑下一个用户 |
| `lib/wasm32-emscripten/pic/` | 54 MB | ❌ 只取 `crtbegin-mt.o`（5,589 B） | §4.2 的链接行只点名这一个；pic/ 里其余 31 个是 `.a` 归档，side module **不链**（SPEC §5.1） |
| `lib/wasm32-emscripten/` 其余 | 582 MB | ❌ | 同上，全是 `.a` 变体（asan/debug/mt/ww 各 66 组） |

**结果**：tar = **[[sysroot_wasm32_tar]] B raw / [[sysroot_wasm32_tar_brotli]] B brotli**
（对比 SPEC §6 假设的 8.87 MB / 1.23 MB —— 真实值更大但同量级；§6 那格是 LLVM 8 时代的估计）。

### 两档 tar 的关系（一个容易误读的地方）

`sysroot-wasm32.tar` 与 `sysroot-wasm64.tar` **尺寸完全相同**（都 [[sysroot_wasm64_tar]] B），
这不是 bug：**`include/` 是架构共享的**（sysroot 里没有 `include/wasm64-emscripten` 变体）。
真正按架构不同的只有 `crtbegin-mt.o`，我验证过两个 tar 里装的是**各自架构**的那一份。
复跑（两个 md5 应当不同，且各自等于宿主对应架构的 `crtbegin-mt.o`）：

```sh
for a in wasm32 wasm64; do
  printf '%s tar: ' "$a"
  tar -xOf package/out/sysroot-$a.tar sysroot/lib/$a-emscripten/pic/crtbegin-mt.o | md5sum
  printf '%s host: ' "$a"
  md5sum toolchain/emsdk/upstream/emscripten/cache/sysroot/lib/$a-emscripten/pic/crtbegin-mt.o
done
```

## 2. 交付路径可用：驱动只从 tar 编译

`driver/toolchain.mjs` 现在接受两种 sysroot 来源：
`{sysroot: '<目录>'}`（开发）或 `{bundle: {tarPath, manifestPath}}`（交付）。

实测（`M1_BUNDLE=1`，**完全不碰宿主 sysroot 目录**）：

```
[bundle] verified sha256 <见 [[sysroot_wasm32_tar_sha256]]>, 1578 files, [[sysroot_wasm32_tar]] bytes
[bundle] installed 1578 files into the memory FS
...
ok = true, module bytes: 966, exports: __wasm_call_ctors,_emscripten_tls_init,f
```

⇒ 浏览器里要走的正是这条路：**一个 tar + 一个 sha256**，没有 emsdk 目录。

## 3. fail-closed 的六条断言（SPEC §9.10）

`driver/check-fail-closed.mjs`（[[fail_closed_pass]] 项 PASS）：

| 用例 | 期望 | 实测 |
|---|---|---|
| 诚实 bundle | 加载 | ✅ 1,578 文件 |
| 篡改 1 字节 | **拒绝** | ✅ `sha256 mismatch` |
| 截断 | **拒绝** | ✅ `sha256 mismatch` |
| 篡改（经 manifest 校验） | **拒绝** | ✅ `sha256 mismatch` |
| manifest 字节数与文件不符 | **拒绝** | ✅ `bytes=20623361 but file is 20623360` |
| manifest 文件不存在 | **拒绝** | ✅ `manifest missing` |

### ⚠️ 这条测试自己踩过"假装通过"

第一版里我改了字节却**没改文件名**，于是拒绝的原因是
`manifest has no asset for /tmp/tampered.tar`（名字不匹配），**sha256 根本没被检查到**。
测试绿了，但它证明的不是 fail-closed。

修法：每个用例都用**同一 basename** + 显式 digest，并断言**拒绝原因**里含 `sha256 mismatch`，
再加一条控制组确认诚实文件仍能加载。**只断言"被拒"是不够的——得断言"因为什么被拒"。**

## 4. manifest（SPEC §2）

`package/out/manifest-<arch>.json`，逐资产记 `bytes` + `sha256` + `brotli_bytes`，
外加 `toolchain`（emcc 版本串 / arch / LLVM target）与 `contains`（实测构成）。

`driver/sysroot-bundle.mjs` 同时校验 `sha256` **和** `bytes`（两个独立断言）——
manifest 自称的字节数若与文件不符也拒绝（实测用例见上表第 5 行）。

## 5. 还没做的

- **Worker 化**（SPEC §7.3）—— 需要真实浏览器环境。
- **wasm64 的编译路径** —— 驱动目前对 `target:'wasm64'` **明确拒绝**（不静默降级），
  因为 M1 只建了 wasm32 的 clang/lld 产物。tar 已经备好（含 wasm64 的 crtbegin）。
- **分片懒加载**（SPEC §6）—— 见问卷 C0，等委托人对预算的决定。

## 6. 文件

| 文件 | 作用 |
|---|---|
| `package/package-sysroot.sh` | 打包（实测构成 + manifest + sha256） |
| `driver/sysroot-bundle.mjs` | tar 读取 + sha256 fail-closed + 装进内存 FS |
| `driver/check-fail-closed.mjs` | §9.10 的六条断言 |
| `package/out/manifest-*.json` | 逐资产清单 |
| `package/evidence/*.log` | 打包证据（`ARTIFACT` 行 = 数字产地） |
