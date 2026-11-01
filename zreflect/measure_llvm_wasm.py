#!/usr/bin/env python3
"""LLVM-wasm — **本仓的数据层**（Einfacht 机制层之上的"你的部分"）。

Einfacht 的 `zreflect/facts.py` 只提供机制（守卫 / 渲染 / 收尾），
`measure_example()` 是占位。这里放本仓真正要量的东西：M0/M1/M2 的验收
PASS 数、产物字节、见证指纹……每条带复跑命令 + 出处。

为什么是独立模块而不是 fork `facts.py`（Einfacht issue #15 A1/C3）：
上游的 `_measure()` 按旋钮 `REFLECT_MEASURE_MODULE` 分派，未配 / 导入失败
会**响亮回落**占位。于是"同步上游"从"改 facts.py"降级为"拷文件"——
下次上游再改机制层，本仓只拷，数据层不动（否则就是第二份修过的副本，
必然漂）。

⚠️ 本模块**自包含**：不 import build/ 下的 gate.py（命名会撞）。
"""
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate import GATE_REPO, module_meta, repo   # noqa: E402
from ledger import fact                         # noqa: E402

# C5：本仓数据层也必须在平台名册里声明自己，否则 registry 报 undeclared。
# selftest=False：它是**数据**（量什么、怎么量），机制的自证在上游那批。
MODULE = module_meta("本仓数据层", "量本仓的产物/验收/见证（数据 vs 机制分离）",
                     selftest=False)

EMSDK = repo("toolchain/emsdk")
EMCC = os.path.join(EMSDK, "upstream/emscripten/emcc")
CLANG = os.path.join(EMSDK, "upstream/bin/clang")
WASM_LD = os.path.join(EMSDK, "upstream/bin/wasm-ld")
EV = repo("m0/evidence")
EV1 = repo("m1/evidence")   # M1 的证据日志（同一套 ARTIFACT 约定）


def _run(cmd, cwd=None):
    """跑一条命令，返回去空白的 stdout；失败返回 None（量不到就明说）。"""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=60, cwd=cwd or GATE_REPO)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


BUILD_INPUTS = ("m0/side.cc", "m0/host.cc", "m0/run-m0.sh",
                "m0/run-mm2-keeplist.sh", "m0/check-symbol-gap.mjs")
BUILD_INPUTS_CMD = "cat m0/side.cc m0/host.cc m0/run-*.sh m0/check-symbol-gap.mjs | sha256sum | cut -c1-16"


def build_inputs_fingerprint():
    """产出 M0 产物的那套输入（源 + 脚本）的指纹 —— 贵事实的**便宜见证**。

    值（产物字节数）不重跑；但「产出它的输入还是我以为的那个」每次提交真跑。
    输入一动，指纹就变，见证立刻红 —— 而那时产物数字也确实该重测了。
    """
    return _hash_globs(["m0/side.cc", "m0/host.cc", "m0/run-*.sh", "m0/check-symbol-gap.mjs"])


M1_INPUTS = ("m1/build-clang-wasm.sh", "m1/acceptance.mjs")


def m1_inputs_cmd():
    return "cat m1/build-clang-wasm.sh m1/acceptance*.mjs | sha256sum | cut -c1-16"


def m1_inputs_fingerprint():
    """产出 m1 产物/结论的那套输入的指纹 —— 贵事实的便宜见证。"""
    return _hash_globs(["m1/build-clang-wasm.sh", "m1/acceptance*.mjs"])


# No hand-written tuple: the witness cmd globs (cat m1/exp-*.sh m1/patch-*.sh)
# and the fingerprint must hash THE SAME SET. Hashing a different list than the
# cmd expands is two producers of one set -- the exact drift this repo's issue
# to Einfacht (#18) is about. Derive both from disk.


def m1_opt_inputs_cmd():
    return "cat m1/exp-*.sh m1/patch-lld-wasm-only.sh | sha256sum | cut -c1-16"


def m1_opt_inputs_fingerprint():
    """产出优化实验数字的那套脚本的指纹 —— 与 witness cmd 同一组 glob。"""
    return _hash_globs(["m1/exp-*.sh", "m1/patch-lld-wasm-only.sh"])


# Discovered, not listed. A hand-written tuple here is the drift shape this repo
# keeps hitting: the seam refactor added compile-core.mjs and this witness kept
# hashing the old set, so a change to the new module was invisible to it. The
# same mistake, one layer over, is what made the release bundle ship a
# toolchain.mjs importing a file it did not contain.

def _hash_globs(patterns):
    """Hash exactly what `cat <globs>` would concatenate (sorted per pattern).

    The single-source rule for every "files that must travel together" set in
    this repo (issue to Einfacht #18): the witness cmd globs, so the fingerprint
    must hash the same expansion -- never a hand-written list of names, which is
    a second producer and drifts (measured: the m1 tuple lacked exp-firstload.sh
    while the cmd's glob included it).
    """
    import glob as _g                                       # noqa: PLC0415
    import hashlib                                          # noqa: PLC0415
    h = hashlib.sha256()
    for pat in patterns:
        for rel in sorted(os.path.relpath(p, GATE_REPO)
                          for p in _g.glob(os.path.join(GATE_REPO, pat))):
            with open(os.path.join(GATE_REPO, rel), "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]

def _driver_inputs():
    d = repo("driver")
    if not os.path.isdir(d):
        return ()
    return tuple(sorted("driver/" + f for f in os.listdir(d) if f.endswith(".mjs")))


# Witness commands use GLOB, not enumeration (Einfacht issue #18, adopted half):
# a hand-listed set of "files that must travel together" is a second producer and
# drifts -- measured three times in one day on this repo. A glob in the witness
# cmd re-expands at every run, so adding/removing a file changes the fingerprint
# and the gate goes red. The tuples below stay only for _fingerprint() hashing,
# which derives from disk (same principle, Python side).
def _glob(pattern):
    d = repo(".")
    import glob as _g                                              # noqa: PLC0415
    hits = sorted(os.path.relpath(p, d) for p in _g.glob(os.path.join(d, pattern)))
    return tuple(hits)

DRIVER_INPUTS = _driver_inputs()


def package_inputs_cmd():
    return "cat package/package-sysroot.sh | sha256sum | cut -c1-16"


def package_inputs_fingerprint():
    """打包脚本的指纹 —— sysroot tar 体积数字的便宜见证。"""
    import hashlib                                          # noqa: PLC0415
    p = os.path.join(GATE_REPO, "package/package-sysroot.sh")
    if not os.path.exists(p):
        return "no-script"
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def driver_inputs_cmd():
    return "cat driver/*.mjs | sha256sum | cut -c1-16"


BROWSER_LOG = repo("browser/evidence/browser.log")
LOOP_LOG = repo("browser/evidence/loop.log")
RELEASE_LOG = repo("release/evidence/check-release.log")
W64_LOG = repo("release/evidence/wasm64-e2e.log")
CL_LOG = repo("release/evidence/check-content-list.log")
MAKE_LOG = repo("release/evidence/make-release.log")
SEAM_LOG = repo("driver/evidence/check-compile-seam.log")
ZTII_LOG = repo("driver/evidence/check-ztii-regression.log")
PUB_LOG = repo("release/evidence/check-published.log")
SPLIT_LOG = repo("release/evidence/make-split-release.log")

BROWSER_INPUTS = ("browser/worker.mjs", "browser/index.html", "browser/check-browser.mjs")


def browser_inputs_cmd():
    return "cat browser/*.mjs browser/*.html | sha256sum | cut -c1-16"


def browser_inputs_fingerprint():
    """浏览器 harness 的指纹 —— 浏览器验收数字的便宜见证。"""
    return _hash_globs(["browser/worker.mjs", "browser/index.html", "browser/check-*.mjs"])


def driver_inputs_fingerprint():
    """薄驱动源码的指纹 —— 驱动验收数字的便宜见证。"""
    import hashlib                                          # noqa: PLC0415
    h = hashlib.sha256()
    return _hash_globs(["driver/*.mjs"])


def oct_census_fingerprint():
    """普查证据文件（m0/evidence/oct-eh-perfile.txt）的指纹 —— 贵事实的便宜见证。

    输入（那批 .oct 的逐文件扫描结果）不变 ⇒ 普查结论仍成立；
    文件一改，见证立刻红。
    """
    import hashlib                                          # noqa: PLC0415
    p = os.path.join(GATE_REPO, "m0/evidence/oct-eh-perfile.txt")
    if not os.path.exists(p):
        return "no-census"
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def _artifact(path, name):
    """从证据日志里取 `ARTIFACT <name> <value>` 的**原文**；没有 ⇒ None（不编 0）。"""
    if not os.path.exists(path):
        return None
    prefix = "ARTIFACT %s " % name
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            if line.startswith(prefix):
                return line[len(prefix):].strip()
    except OSError:
        return None
    return None


def _artifact_int(path, name):
    """同 `_artifact`，但转成 int。

    ⚠️ 必须转 int：`check_facts` 的裸数字判据只查 `isinstance(v, int)`，
    字符串值不会被查 —— 手抄同样的数字就**拦不住**（实测踩到：
    STATE.md 正文写「19653 字节」时闸门全绿）。值型别错 = 判据静默失效。
    """
    raw = _artifact(path, name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _grep_count(pattern, path):
    """数一个文件里匹配的行数；文件不在 ⇒ None（读不到就明说，不许编 0）。"""
    if not os.path.exists(path):
        return None
    n = 0
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            if re.search(pattern, line):
                n += 1
    except OSError:
        return None
    return n



def measure():
    """量一遍本仓的事实。**量不到的键不写** —— 宁缺勿假。

    ⚠️ 前四条（py_files / md_files / py_lines / md_lines）**必须保留**：
    `gates-selftest.sh` 的跨仓库夹具文档就引用 `[[py_files]]` / `[[md_files]]`，
    删掉它们夹具会红（实测踩到：「引用不存在的键」）。这也合本仓的意：
    仓库结构事实便宜、永远可复跑，是台账的基座。
    """
    facts = {}

    # ── 便宜的：仓库结构（连表，永远可复跑；夹具依赖这四个键名）────────────
    n_py = 0
    n_md = 0
    lines_py = 0
    for root, dirs, files in os.walk(GATE_REPO):
        if "/.git" in root:
            continue
        # 第三方树不计数（toolchain/ = emsdk，自带上千个 .py）：
        # 它不入库、装不装随机器而变 ⇒ 算进去就是「会自己变的输入」
        # （collect.py 原则 2），而且复跑在新机器上必然不符。
        dirs[:] = [d for d in dirs if d not in ("toolchain", ".git")]
        for f in files:
            if f.endswith(".py"):
                n_py += 1
                try:
                    lines_py += sum(1 for _ in open(os.path.join(root, f), encoding="utf-8",
                                                    errors="replace"))
                except OSError:
                    pass                      # 数不出来的文件不计数 —— 宁缺勿假
            elif f.endswith(".md"):
                n_md += 1
    EXCL = "-not -path './.git/*' -not -path './toolchain/*'"
    facts["py_files"] = fact(n_py, "find . -name '*.py' %s | wc -l" % EXCL, "repo",
                             "不含 toolchain/（emsdk 自带大量 .py，装了才算数 ⇒ 会自己变）")
    facts["md_files"] = fact(n_md, "find . -name '*.md' %s | wc -l" % EXCL, "repo")
    facts["py_lines"] = fact(lines_py, "find . -name '*.py' %s "
                             "-exec cat {} + | wc -l" % EXCL, "repo",
                             "含 vendored 的机制层（zreflect/），不含 toolchain/")
    md_lines_cmd = ("find . -name '*.md' %s"
                    " -exec awk 'FNR==1{b=0} /<!-- AUTO:FACTS -->/{b=1} !b' {} + | wc -l" % EXCL)
    facts["md_lines"] = fact(
        int(subprocess.run(md_lines_cmd, shell=True, capture_output=True,
                           text=True, check=True, cwd=GATE_REPO).stdout.strip()),
        md_lines_cmd, "repo",
        "不含机器块：块就渲染在文档里，数进去会让渲染一遍值就过期")

    # ── 便宜的：本仓结构（路径不在就不写 —— 宁缺勿假）───────────────────────
    if os.path.isdir(repo("m0")):
        facts["m0_runner_scripts"] = fact(
            int(_run("find m0 -maxdepth 1 -name 'run-*.sh' | wc -l")),
            "find m0 -maxdepth 1 -name 'run-*.sh' | wc -l", "repo",
            "M0 的三个 runner（主链 / 反例 / MM2 证据）")

    # ── M0 验收证据（读日志，便宜）───────────────────────────────────────────
    # 值 = PASS 数。日志由 runner 生成，是「跑过」的记录；cmd 只数行，不重跑编译
    # （重跑编译是分钟级 ⇒ 那部分挂在 witness 档，见下）。
    for arch in ("wasm32", "wasm64"):
        log = os.path.join(EV, "m0-%s.log" % arch)
        n = _grep_count(r"^PASS", log)
        if n is not None:
            facts["m0_pass_%s" % arch] = fact(
                n, "grep -c '^PASS' m0/evidence/m0-%s.log" % arch, "m0/evidence",
                "SPEC §9.1–9.7 的 PASS 行数（%s 档）" % arch)

    cf = _grep_count(r"^OK", os.path.join(EV, "counterexamples.log"))
    if cf is not None:
        facts["m0_counterexample_ok"] = fact(
            cf, "grep -c '^OK' m0/evidence/counterexamples.log", "m0/evidence",
            "§9.5 反例 + §9.6 模板缺口：两条都按预期表现")

    # ── M0 产物事实（贵：要跑编译）⇒ replay=False + 便宜见证 ────────────────
    # 值的**唯一产地**是 runner 打的 `ARTIFACT <key> <value>` 行 —— 不重跑编译，
    # 只 grep 日志（便宜）；见证断言「产出它们的那套输入没变」（源/脚本指纹）。
    for key, log in (("wasm32", "m0-wasm32.log"), ("wasm64", "m0-wasm64.log")):
        path = os.path.join(EV, log)
        if not os.path.exists(path):
            continue
        for suffix in ("side_bytes", "side_exports", "host_bytes", "host_exports"):
            name = "%s_%s" % (key, suffix)
            val = _artifact_int(path, name)
            if val is not None:
                facts["m0_" + name] = fact(
                    val, "grep -m1 '^ARTIFACT %s ' m0/evidence/%s | cut -d' ' -f3"
                    % (name, log), "m0/evidence",
                    "M0 %s 档产物（SPEC §9 体积/导出面）" % key,
                    replay=False,
                    witness=BUILD_INPUTS_CMD, witness_expect=build_inputs_fingerprint())

    for name, log in (("mm2_keeplist_bytes", "mm2-keeplist.log"),
                      ("mm2_keeplist_exports", "mm2-keeplist.log"),
                      ("mm2_bare_exports", "mm2-keeplist.log"),
                      ("mm2_bare_tags", "mm2-keeplist.log"),
                      ("mm2_tagonly_exports", "mm2-keeplist.log"),
                      ("keep_list_symbols", "mm2-keeplist.log")):
        path = os.path.join(EV, log)
        val = _artifact_int(path, name)
        if val is not None:
            facts["m0_" + name] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m0/evidence/%s | cut -d' ' -f3"
                % (name, log), "m0/evidence",
                "§5.5 MM=2 主路的三步证据（bare / +tag / +keep-list）",
                replay=False,
                witness=BUILD_INPUTS_CMD, witness_expect=build_inputs_fingerprint())

    # ── M1：把 clang/lld 编成 wasm 的体积（贵 ⇒ 挂见证）────────────────────
    # 值的产地 = m1/build-clang-wasm.sh 的 ARTIFACT 行（见 m1/evidence/build-*.log）。
    # 这是 SPEC §6 那条「LLVM 8 旧数、现代 LLVM 是推断」悬案的答案。
    for key, log, label in (
            ("clang_wasm", "build-clang.log", "clang.wasm raw 字节（SPEC §6 悬案）"),
            ("clang_wasm_gzip", "build-clang.log", "clang.wasm gzip -9 字节"),
            ("clang_wasm_brotli", "build-clang.log", "clang.wasm brotli -q11 字节（SPEC §6 预算比这个）"),
            ("clang_js", "build-clang.log", "clang.js 胶水字节"),
            ("lld_wasm", "build-lld.log", "lld（wasm-ld）raw 字节"),
            ("lld_wasm_gzip", "build-lld.log", "lld gzip -9 字节"),
            ("lld_wasm_brotli", "build-lld.log", "lld brotli -q11 字节")):
        val = _artifact_int(os.path.join(EV1, log), key)
        if val is not None:
            facts["m1_" + key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m1/evidence/%s | cut -d' ' -f3" % (key, log),
                "m1/evidence", label, replay=False,
                witness=m1_inputs_cmd(), witness_expect=m1_inputs_fingerprint())

    # 验收结果：值从验收日志的 ARTIFACT 行读（与 M0 runner 同一约定）。
    # ⚠️ 不从 m1/acceptance/minifn.so 直接 stat：那是产物、不入库，
    #    换个机器量不到 ⇒ 键会掉、守卫报「掉条」（实测踩到这类形状）。
    #    日志入库 ⇒ 任何机器都能复算。
    acc = os.path.join(EV1, "m1-acceptance.log")
    for key, label in (("m1_acceptance_pass",
                        "在 wasm 里完成 编译+链接，产出 ABI 正确的 side module（PASS 数）"),
                       ("m1_sidemodule_bytes",
                        "wasm 内 clang+lld 产出的 side module 字节数")):
        val = _artifact_int(acc, key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m1/evidence/m1-acceptance.log | cut -d' ' -f3" % key,
                "m1/evidence", label, replay=False,
                witness=m1_inputs_cmd(), witness_expect=m1_inputs_fingerprint())

    # ── M2：sysroot 打包 + fail-closed（SPEC §6 / §2 / §9.10）──────────────
    PKG = repo("package/evidence")
    for key, log, label in (
            ("sysroot_wasm32_tar", "package-wasm32.log",
             "wasm32 sysroot tar 字节（SPEC §6 交付物）"),
            ("sysroot_wasm32_tar_brotli", "package-wasm32.log",
             "同上 brotli -q11（与 §6 预算同口径）"),
            ("sysroot_wasm32_headers", "package-wasm32.log",
             "tar 里的头文件数（实测构成，非猜测）"),
            ("sysroot_wasm64_tar", "package-wasm64.log",
             "wasm64 sysroot tar 字节（与 wasm32 同尺寸：include/ 是架构共享的）")):
        # sha 型事实（issue #4 ⑤）：值会随打包输入变 ⇒ 显式 replay=False + 见证。
        if key == "sysroot_wasm64_tar":
            for skey, slog in (("sysroot_wasm32_tar_sha256", "package-wasm32.log"),):
                raw = _artifact(os.path.join(PKG, slog), skey)
                if raw:
                    facts[skey] = fact(
                        raw, "grep -m1 '^ARTIFACT %s ' package/evidence/%s | cut -d' ' -f3"
                        % (skey, slog), "package/evidence",
                        "sysroot tar 的 sha256（SPEC §9.10 的校验值）", replay=False,
                        witness=package_inputs_cmd(),
                        witness_expect=package_inputs_fingerprint())
        val = _artifact_int(os.path.join(PKG, log), key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' package/evidence/%s | cut -d' ' -f3" % (key, log),
                "package/evidence", label, replay=False,
                witness=package_inputs_cmd(), witness_expect=package_inputs_fingerprint())

    # ── M2：薄驱动（SPEC §7.4/§7.5）的验收（贵 ⇒ 挂见证）────────────────────
    EVD = repo("driver/evidence")
    for key, log, label in (
            ("driver_acceptance_pass", "driver-acceptance.log",
             "薄驱动 compile() 验收 PASS 数（含带真宿主的缺口检查）"),
            ("driver_module_bytes", "driver-acceptance.log",
             "驱动经内存 FS 产出的 side module 字节数"),
            ("gap_reverse_pass", "gap-reverse.log",
             "缺口检查的反向断言（真缺口必须被点名）PASS 数"),
            ("fail_closed_pass", "fail-closed.log",
             "sha256 fail-closed 断言数（篡改/截断/字节数不符/缺 manifest 四类拒绝）"),
            ("browser_acceptance_pass", BROWSER_LOG,
             "真实浏览器（Chromium）验收 PASS 数：Worker 编译 + §9.8 纯客户端"),
            ("browser_module_basic_bytes", BROWSER_LOG,
             "浏览器里编出的 side module 字节数（对比 node 驱动 [[driver_module_bytes]]）"),
            ("browser_module_eh_bytes", BROWSER_LOG,
             "浏览器里异常夹具的字节数（§9.4 在真浏览器里复核）"),
            ("loop_acceptance_pass", LOOP_LOG,
             "浏览器**闭环**验收 PASS 数：worker 编译 → 页面 dlopen（§9.1–9.4）"),
            ("loop_sidemodule_bytes", LOOP_LOG,
             "闭环里编出的 side module 字节数（M0 完整夹具，对比 [[m0_wasm32_side_bytes]]）"),
            ("browser_host_wasm", LOOP_LOG,
             "浏览器宿主主模块的 wasm 字节数（dlopen 那半的宿主）"),
            ("release_acceptance_pass", RELEASE_LOG,
             "交付包验收 PASS 数（自足性 / 许可证分档 / §8 版本串 / §6 预算）"),
            ("release_assets", RELEASE_LOG,
             "交付包资产数（manifest.json 的 assets 条目）"),
            ("release_first_load_brotli", RELEASE_LOG,
             "首拉 brotli（SPEC §6 预算口径，≤ 15,000,000）"),
            ("release_total_brotli", RELEASE_LOG,
             "含 lld 的 brotli 总量（lld 是懒加载分片）"),
            ("wasm64_release_e2e_bytes", W64_LOG,
             "从发布包编出的 wasm64 产物字节数（issue #1 的闭环）"),
            ("wasm64_release_e2e_pass", W64_LOG,
             "同一产物在真 wasm64 宿主里的 dlopen 验收 PASS 数"),
            ("content_list_entries", MAKE_LOG,
             "content-list（接缝 schema 2）条目数 —— 给内容收口方的记录"),
            # 分片静态分发（契约 schema 2；额外内容仓 mail/016 = 本仓 016）。
            # 产地 = release/evidence/make-split-release.log 的 ARTIFACT 行，
            # 由 release/make-split-release.sh 打（它调的是契约仓的工具，
            # 本仓不重写生成器）。
            ("split_entries", SPLIT_LOG,
             "分片 release 的条目数（== 载荷数；元数据不进载荷）"),
            ("split_assets", SPLIT_LOG,
             "分片 release 的 asset 总数（三编码合计；每个 ≤ 5 MiB）"),
            ("split_zstd_bytes", SPLIT_LOG,
             "zstd 编码合计字节（与整包 tar.gz 对比 = 首拉省多少）"),
            ("split_max_chunk", SPLIT_LOG,
             "最大分片字节（契约硬限 5242880；超了客户端就不合规）"),
            ("published_check_pass", PUB_LOG,
             "发布件反读对账 PASS 数（--tag：从 GitHub 下载的已发布字节）"),
            ("ztii_regression_pass", ZTII_LOG,
             "_ZTIi 回归 PASS 数（裁决 A 时间表：重链前点名 / 重链后翻绿）"),
            ("compile_seam_check_pass", SEAM_LOG,
             "编译流水线 seam 守卫 PASS 数（两个 adapter 必须走同一个 core）"),
            ("content_list_check_pass", CL_LOG,
             "记录验收 PASS 数（含宿主校验器两模式 —— 见 mail/004）"),
            ("browser_acceptance_pass", "../browser/evidence/browser.log",
             "真实浏览器（Chromium）验收 PASS 数：Worker 编译 + §9.8 纯客户端"),
            ("browser_module_basic_bytes", "../browser/evidence/browser.log",
             "浏览器里编出的 side module 字节数（对比 node 驱动 [[driver_module_bytes]]）"),
            ("browser_module_eh_bytes", "../browser/evidence/browser.log",
             "浏览器里异常夹具的字节数（§9.4 在真浏览器里复核）"),
            ("wasm64_acceptance_pass", "wasm64-acceptance.log",
             "wasm64 验收 PASS 数（含「必须是真 64 位」的反向断言）"),
            ("wasm64_module_bytes", "wasm64-acceptance.log",
             "wasm64 side module 字节数（对比 wasm32 [[m0_wasm32_side_bytes]] 量级）"),
            ("wasm32_module_bytes", "wasm64-acceptance.log",
             "同一夹具 wasm32 的字节数（两档对照）")):
        path = log if os.path.isabs(log) else os.path.join(EVD, log)
        rel_log = os.path.relpath(path, GATE_REPO)
        val = _artifact_int(path, key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' %s | cut -d' ' -f3" % (key, rel_log),
                "driver/evidence", label, replay=False,
                witness=driver_inputs_cmd(), witness_expect=driver_inputs_fingerprint())

    # ── M3：首拉体积（SPEC §6 的预算口径 —— 不是三资产总量，见 R-008）────────
    for key, log, label in (
            ("firstload_brotli", "opt-firstload.log",
             "首拉 brotli 合计（clang.wasm+胶水+sysroot；SPEC §6 预算口径）"),
            ("firstload_plus_lld_brotli", "opt-firstload.log",
             "三资产总量（lld 懒加载不计入首拉）"),
            ("firstload_clang_wasm_brotli", "opt-firstload.log",
             "lean（关异常+RTTI）clang.wasm 的 brotli")):
        val = _artifact_int(os.path.join(EV1, log), key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m1/evidence/%s | cut -d' ' -f3" % (key, log),
                "m1/evidence", label, replay=False,
                witness=m1_opt_inputs_cmd(), witness_expect=m1_opt_inputs_fingerprint())
        path = log if os.path.isabs(log) else os.path.join(EVD, log)
        rel_log = os.path.relpath(path, GATE_REPO)
        val = _artifact_int(path, key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' %s | cut -d' ' -f3" % (key, rel_log),
                "driver/evidence", label, replay=False,
                witness=driver_inputs_cmd(), witness_expect=driver_inputs_fingerprint())

    # ── M1 体积优化实验（隔壁一轮的产物，贵 ⇒ 挂见证）──────────────────────
    # 值来自 m1/evidence/opt-*.log 的 ARTIFACT 行。
    for key, log, label in (
            ("anchor_clang_wasm_brotli", "opt-anchor.log",
             "MinSizeRel(-Os) 下 clang.wasm 的 brotli（vs 基线 [[m1_clang_wasm_brotli]]）"),
            ("anchor_clang_wasm", "opt-anchor.log", "同上 raw"),
            ("lld_wasmonly_brotli", "opt-lld-wasm-only.log",
             "只留 wasm 驱动的 lld brotli（vs 基线 [[m1_lld_wasm_brotli]]）"),
            ("lld_wasmonly_raw", "opt-lld-wasm-only.log", "同上 raw"),
            # ── 关异常+RTTI 这根杠杆（第三轮打通；见 OPT-RESULTS.md §5.2）──────
            # 数字产地 = m1/evidence/opt-lean_nosjlj.log，由
            # `EXP_JOBS=22 bash m1/exp-run.sh lean_nosjlj` 产出 —— **ninja 一把过**，
            # 不是手工重链。这一点很重要：值必须来自别人也能复跑的那条命令。
            # 该日志末尾附了**失败的那一次**（带 -sSUPPORT_LONGJMP=wasm）—— 那是
            # 翻案 R-008 的证据，不能丢，否则"为什么要去掉那个旗标"就没有产地，
            # 下一个 agent 会再踩一次。
            ("lean_nosjlj_clang_wasm_brotli", "opt-lean_nosjlj.log",
             "关 C++ 异常 + RTTI 后 clang.wasm 的 brotli（三轮里最好的 clang）"),
            ("lean_nosjlj_clang_wasm", "opt-lean_nosjlj.log", "同上 raw"),
            ("lean_nosjlj_clang_wasm_gzip", "opt-lean_nosjlj.log",
             "同上 gzip（`-n` 口径：不含文件名/时间戳，见 exp-build.sh 的说明）"),
            ("lean_nosjlj_acceptance_pass", "opt-lean_nosjlj-acceptance.log",
             "关异常后的 clang 仍能编出 side module（验收 PASS 数）"),
            # ── 首拉分解（SPEC §6 的预算口径是「≤ 15 MB（**首拉**）」）──────────
            # 这一组是**结论性**的：前几版 OPT-RESULTS 一直在比**总量**，
            # 得到「到不了」；而 SPEC 的字面口径是**首拉**（且点名支持分片懒加载），
            # 按首拉算是**达标**的。两个口径都给数字，谁对由委托人裁。
            # 产地 = m1/evidence/opt-firstload.log（bash m1/exp-firstload.sh）。
            ("firstload_brotli", "opt-firstload.log",
             "首拉 brotli：clang.wasm + clang.js + sysroot tar（不含 lld —— 它是懒加载）"),
            ("firstload_plus_lld_brotli", "opt-firstload.log",
             "三资产总量 brotli：首拉 + lld.wasm（即 SPEC §6 那张表的「合计」口径）"),
            ("firstload_sysroot_tar_brotli", "opt-firstload.log",
             "sysroot-wasm32.tar 的 brotli（首拉的一部分）")):
        val = _artifact_int(os.path.join(EV1, log), key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m1/evidence/%s | cut -d' ' -f3" % (key, log),
                "m1/evidence", label, replay=False,
                witness=m1_opt_inputs_cmd(), witness_expect=m1_opt_inputs_fingerprint())

    # ── 下游 .oct 的异常符号依赖面（全量普查，贵 ⇒ 挂见证）─────────────────
    # 值来自一次全量扫描（10,246 个 .oct，wasm-dis 读 IMPORT 段），记在
    # m0/evidence/oct-eh-census.txt。见证 = 那批 .oct 的清单指纹（文件集合没变）。
    census = os.path.join(EV, "oct-eh-census.txt")
    for key, label in (("oct_total", "下游 .oct 全量数"),
                       ("oct_tag_importers", "导入 __cpp_exception 的文件数"),
                       ("oct_throw_importers", "导入 __cxa_throw 的文件数")):
        val = _artifact_int(census, key)
        if val is not None:
            facts[key] = fact(
                val, "grep -m1 '^ARTIFACT %s ' m0/evidence/oct-eh-census.txt | cut -d' ' -f3"
                % key, "m0/evidence", label, replay=False,
                witness="sha256sum m0/evidence/oct-eh-perfile.txt | cut -c1-16",
                witness_expect=oct_census_fingerprint())

    # ── 工具链版本（要 toolchain/ 在；不在就量不到）──────────────────────────
    # cmd 里不拼 sed 转义：直接打整行再在闸门侧用 grep 取值不可判，
    # 所以 cmd 就写成「打版本号那一行」，值取同一行 —— 裸值契约仍然成立。
    if os.path.exists(EMCC):
        line = _run("%s --version 2>/dev/null | head -1" % EMCC)
        if line:
            ver = re.search(r"\b(\d+\.\d+\.\d+)\b", line)
            if ver:
                facts["emcc_version"] = fact(
                    ver.group(1),
                    "toolchain/emsdk/upstream/emscripten/emcc --version "
                    "2>/dev/null | head -1 | grep -oE '[0-9]+[.][0-9]+[.][0-9]+' | head -1",
                    "toolchain", "工具链侧 emcc 版本（SPEC §8 只记档不拦）")
        # 见证：断言「量的是本仓 toolchain/ 的 emcc，不是系统 PATH 里那个」。
        facts["emcc_from_repo_toolchain"] = fact(
            "yes", "test -x toolchain/emsdk/upstream/emscripten/emcc && echo yes",
            "toolchain", "量的是本仓 toolchain/ 的 emcc，不是系统 PATH 里那个")

    for name, path, vers in (
            ("clang_major", CLANG, "clang version"),
            ("lld_major", WASM_LD, "LLD")):
        if not os.path.exists(path):
            continue
        line = _run("%s --version 2>/dev/null | head -1" % path)
        if not line:
            continue
        mv = re.search(r"(?:%s)\s*(\d+)" % re.escape(vers), line)
        if mv:
            facts[name] = fact(
                int(mv.group(1)),
                "toolchain/emsdk/upstream/bin/%s --version 2>/dev/null | head -1 "
                "| grep -oE '%s [0-9]+' | head -1 | grep -oE '[0-9]+$'"
                % ("clang" if name == "clang_major" else "wasm-ld", vers),
                "toolchain", "SPEC §4.2 的旗标随这个版本漂")

    # ── 翻案台账条数（便宜：数 JSON）────────────────────────────────────────
    rp = repo("retractions.json")
    if os.path.exists(rp):
        try:
            import json as _json                               # noqa: PLC0415
            n = len(_json.load(open(rp, encoding="utf-8")).get("retractions", []))
            facts["retractions_count"] = fact(
                n, "python3 -c \"import json;print(len(json.load(open('retractions.json'))['retractions']))\"",
                "repo", "翻案台账条数（被推翻的断言不许悄悄回来）")
        except Exception:
            pass                                               # 读不到就不写（宁缺勿假）

    # ── 闸门数（发现式名录，便宜；机制层不在就不写）────────────────────────
    if os.path.isdir(repo("zreflect")):
        facts["gates_total"] = fact(
            int(_run("python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l")),
            "python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l", "repo",
            "发现式名录（手写清单会漂）")

    # ── 数据层自身的形状（便宜：数本文件行数）──────────────────────────────
    # STATE.md 用 [[measure_module_lines]] 说「数据层有多大」—— 同步上游之后
    # 这个数字会随本仓测量逻辑长，所以它必须进台账，不许手抄。
    # （台账**条数**刻意不设键：它数的是自己写盘后的结果，量的时候还没写盘
    #   ⇒ 值必然差一。掉条判据本来就在守卫里，不是一条能复跑的裸值。）
    me = os.path.join(GATE_REPO, "zreflect/measure_llvm_wasm.py")
    if os.path.exists(me):
        facts["measure_module_lines"] = fact(
            int(_run("wc -l < zreflect/measure_llvm_wasm.py")),
            "wc -l < zreflect/measure_llvm_wasm.py", "facts",
            "本仓数据层行数（数据 vs 机制分离的度量：机制层大小由上游决定）")

    return facts


