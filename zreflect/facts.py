#!/usr/bin/env python3
"""事实台账的 CLI：量一遍、写台账、渲染机器块，以及**两道守卫**。

用法
    python3 zreflect/facts.py                      # 量一遍并写 FACTS.json（掉条/改口会拒绝）
    python3 zreflect/facts.py --allow-drop         # 允许本次掉条（掉掉的键会打出来）
    python3 zreflect/facts.py --accept-changes     # 允许本次改口（旧值→新值会打出来）
    python3 zreflect/facts.py --accept-changes=k1,k2  # 只接受列出的键，其余改口仍拒绝（issue #3 ①）
    python3 zreflect/facts.py --render-doc [文件]  # 把机器块写进文档（默认 STATE.md）
    python3 zreflect/facts.py --check [文件]       # 文档里的块是否与台账一致
    python3 zreflect/facts.py --get 键名           # 只打印该键的值（消费方出口，issue #4 ④）
    python3 zreflect/facts.py show [键]            # 打印某条事实
    python3 zreflect/facts.py --selftest           # 自证：两道守卫必须都能红

⚠️ **量不到的项不写**（宁缺勿假）。比如「最近一次全绿回归」只在有日志的机器上量得出来；
没日志就把那条事实**留空**，而不是写 0 —— 0 是一个数字，会被人当结果引用。
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import module_meta, GATE_REPO, main_selftest_or, repo, selftest  # noqa: E402
from ledger import age_days, fact, facts_of, load, value_of  # noqa: E402
from render import BLOCK_BEGIN, BLOCK_END, body_of, prose_of, render_block  # noqa: E402
import guard                                             # noqa: E402
import registry                                          # noqa: E402

LEDGER_NAME = os.environ.get("REFLECT_FACTS", "FACTS.json")
OUT = repo(LEDGER_NAME)
DOC = os.environ.get("REFLECT_DOC", "STATE.md")


# ══ 你的部分（本仓数据层）════════════════════════════════════════════════════
# 本仓量的是「M0 验证链」的事实。三类分档（collect.py 的四条原则）：
#   · 便宜的（连表/读日志/查版本）⇒ 裸 cmd，每提交逐字复跑；
#   · 贵的（要跑编译，分钟级）⇒ replay=False + 便宜 witness 见证来源不变；
#   · 每跑必变的（sha 型）⇒ 显式 replay=False，或存一次采样 + *_stable 标记。
#
# 工具链位置：toolchain/ 不入库（见 .gitignore），所以「工具链版本」这类事实
# 在没装工具链的机器上**量不到** ⇒ 不写（宁缺勿假），而不是写 0。
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
BUILD_INPUTS_CMD = "cat %s | sha256sum | cut -c1-16" % " ".join(BUILD_INPUTS)


def build_inputs_fingerprint():
    """产出 M0 产物的那套输入（源 + 脚本）的指纹 —— 贵事实的**便宜见证**。

    值（产物字节数）不重跑；但「产出它的输入还是我以为的那个」每次提交真跑。
    输入一动，指纹就变，见证立刻红 —— 而那时产物数字也确实该重测了。
    """
    import hashlib                                          # noqa: PLC0415
    h = hashlib.sha256()
    for rel in BUILD_INPUTS:
        p = os.path.join(GATE_REPO, rel)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


M1_INPUTS = ("m1/build-clang-wasm.sh", "m1/acceptance.mjs")


def m1_inputs_cmd():
    return "cat %s | sha256sum | cut -c1-16" % " ".join(M1_INPUTS)


def m1_inputs_fingerprint():
    """产出 m1 产物/结论的那套输入的指纹 —— 贵事实的便宜见证。"""
    import hashlib                                          # noqa: PLC0415
    h = hashlib.sha256()
    for rel in M1_INPUTS:
        p = os.path.join(GATE_REPO, rel)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


M1_OPT_INPUTS = ("m1/exp-build.sh", "m1/exp-run.sh", "m1/patch-lld-wasm-only.sh")


def m1_opt_inputs_cmd():
    return "cat %s | sha256sum | cut -c1-16" % " ".join(M1_OPT_INPUTS)


def m1_opt_inputs_fingerprint():
    """产出优化实验数字的那套脚本的指纹 —— 贵事实的便宜见证。"""
    import hashlib                                          # noqa: PLC0415
    h = hashlib.sha256()
    for rel in M1_OPT_INPUTS:
        p = os.path.join(GATE_REPO, rel)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


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



def measure_facts():
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

    # ── M1 体积优化实验（隔壁一轮的产物，贵 ⇒ 挂见证）──────────────────────
    # 值来自 m1/evidence/opt-*.log 的 ARTIFACT 行。
    for key, log, label in (
            ("anchor_clang_wasm_brotli", "opt-anchor.log",
             "MinSizeRel(-Os) 下 clang.wasm 的 brotli（vs 基线 [[m1_clang_wasm_brotli]]）"),
            ("anchor_clang_wasm", "opt-anchor.log", "同上 raw"),
            ("lld_wasmonly_brotli", "opt-lld-wasm-only.log",
             "只留 wasm 驱动的 lld brotli（vs 基线 [[m1_lld_wasm_brotli]]）"),
            ("lld_wasmonly_raw", "opt-lld-wasm-only.log", "同上 raw")):
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

    # ── 闸门数（发现式名录，便宜；机制层不在就不写）────────────────────────
    if os.path.isdir(repo("zreflect")):
        facts["gates_total"] = fact(
            int(_run("python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l")),
            "python3 zreflect/registry.py --all-runnable 2>/dev/null | wc -l", "repo",
            "发现式名录（手写清单会漂）")

    return facts


# ══ 以下不用改 ════════════════════════════════════════════════════════════════
def _machine_blocks(ledger):
    """文档里要维护的两个机器块（Phase 3 起）：

      · 事实块（AUTO:FACTS）—— 台账渲染，**数字的唯一产地**；
      · 闸门名录块（AUTO:GATES）—— 发现式名录渲染，**闸门叙述的唯一产地**
        （手写的「N 道闸门」清单漂过：ab/locks/pins 并入当天清单就少了
        三道 —— 叙述从声明行派生，手写退役）。

    返回 (blocks, 错误句)。名录对账不过（缺声明 / 孤儿 / 旗标错）⇒ 拒绝渲染
    —— 判据只有一份产地：`registry.problems()`。
    """
    gs, missing = registry.gates()
    probs = registry.problems(gs, missing)
    if probs:
        return None, "名录对账不过，拒绝渲染：\n  · " + "\n  · ".join(probs)
    return ((BLOCK_BEGIN, BLOCK_END, render_block(ledger)),
            (registry.GATES_BEGIN, registry.GATES_END,
             registry.render_gates(gs))), None


def write_doc(path_rel, ledger):
    """把机器块写进文档（就地替换）。没有标记就报错，**不悄悄追加** ——
    悄悄追加会让「块过期」变成「有两份块」，那是更难查的坏法。"""
    p = path_rel if os.path.isabs(path_rel) else repo(path_rel)
    if not os.path.exists(p):
        print("FATAL: %s 不存在。先手工放一次机器块标记。" % p,
              file=sys.stderr)
        return 2
    blocks, err = _machine_blocks(ledger)
    if err:
        print("FATAL: %s" % err, file=sys.stderr)
        return 2
    text = open(p, encoding="utf-8").read()
    new = text
    for begin, end, body in blocks:
        if begin not in new or end not in new:
            print("FATAL: %s 缺 %s / %s 标记（第一次落地时要手工放一次）"
                  % (path_rel, begin, end), file=sys.stderr)
            return 2
        pre, _, rest = new.partition(begin)
        _, _, post = rest.partition(end)
        new = pre + body + post
    # 写盘前的完整性守卫：替换必须保得住**全部**块的标记。标记字面量若被
    # 写进正文（哪怕在行内代码里），首现替换会把两块之间的内容整个吞掉、
    # 让别的块消失 —— 实测踩过：bullet 里写了标记字面量，渲染一次丢掉整个
    # 事实块。歧义 ⇒ 拒绝写盘，人先修文档（块内 cmd 引用 begin 字面量是
    # 合法嵌套 —— md_lines 的 awk 判据 —— 故不做替换前的计数断言）。
    for begin, end, _ in blocks:
        if begin not in new or end not in new:
            print("FATAL: %s 的标记字面量混进了正文（%s）—— 渲染会吞块，"
                  "拒绝写盘；标记只许出现在机器块首尾"
                  % (path_rel, begin), file=sys.stderr)
            return 2
    if new != text:
        open(p, "w", encoding="utf-8").write(new)
        print("已刷新 %s 的机器块" % path_rel)
    else:
        print("%s 的机器块无变化" % path_rel)
    return 0


def check_doc(path_rel, ledger):
    p = path_rel if os.path.isabs(path_rel) else repo(path_rel)
    if not os.path.exists(p):
        print("FATAL: 文档 %s 不存在（--check 不能因为找不到文件就算通过）" % p, file=sys.stderr)
        return 2
    blocks, err = _machine_blocks(ledger)
    if err:
        print("FATAL: %s" % err, file=sys.stderr)
        return 2
    text = open(p, encoding="utf-8").read()
    for begin, end, body in blocks:
        if begin not in text or end not in text:
            print("FATAL: %s 缺 %s / %s 标记" % (path_rel, begin, end),
                  file=sys.stderr)
            return 2
        cur = text.split(begin, 1)[1].split(end, 1)[0]
        fresh = body.split(begin, 1)[1].split(end, 1)[0]
        if cur != fresh:
            print("FATAL: %s 的 %s 块与现算不一致 ⇒ 跑 --render-doc"
                  % (path_rel, begin), file=sys.stderr)
            return 1
    print("%s 的机器块与现算一致" % path_rel)
    return 0


def _age_human(entry):
    """`measured_at` 的人话（issue #3 ②）：今天 / N 天前 / 未记录。"""
    d = age_days(entry)
    if d is None:
        return "未记录测量时间"
    if d < 1:
        return "今天测的"
    return "%d 天前测的" % int(d)


def measure(argv):
    """量一遍并写台账。**必须接 `argv`** —— 两道守卫都要读它。

    ⚠️ 这里踩过：`measure()` 曾经没有 `argv` 参数，而守卫里写着 `not in argv`。
    因为 `and` 短路，**只在真的掉条时**才走到那句 ⇒ 报的不是「掉了哪几条」而是一段
    NameError traceback；`--allow-drop` 从未生效过。写盘被拦住只是**顺带**（异常早于写盘），
    那不叫守卫，那叫故障。所以本文件把 argv 显式传进来；守卫的**决策**在
    `zreflect/guard.py`（decide()，接线有自证），本函数只执行它。
    """
    facts = measure_facts()

    old = facts_of(load(OUT)) if os.path.exists(OUT) else {}

    verdict, problems, notes = guard.decide(old, facts,
                                            accepted=guard.accepted_keys(argv),
                                            allow_drop="--allow-drop" in argv)
    for x in notes["err"]:
        print(x, file=sys.stderr)
    for x in notes["out"]:
        print(x)
    if verdict == "refuse":
        for x in problems:
            print("FATAL: %s" % x, file=sys.stderr)
        return 2

    # 仪器生命周期（issue #6 ①）：值没变的键沿用旧 first_seen
    # （换值 / 新键的 first_seen 已由 ledger.fact() 盖今天）——
    # 恒常检测（可插拔闸门 check_instruments.py）靠它。
    for k, entry in facts.items():
        o = old.get(k)
        fs = o.get("first_seen") if isinstance(o, dict) else None
        if fs and value_of(o) == value_of(entry):
            entry["first_seen"] = fs

    import json                                         # noqa: PLC0415
    import time                                         # noqa: PLC0415
    doc = {"schema": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "_why": "事实台账：每条 = 一个**测出来**的值 + 复跑命令 + 出处。"
                   "别手改，跑 zreflect/facts.py。",
           "facts": facts}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("已写出 %s（%d 条事实）" % (os.path.relpath(OUT, GATE_REPO), len(facts)))
    for k, v in sorted(facts.items()):
        print("  %-20s %s（%s）" % (k, v["value"], _age_human(v)))
    return 0


def get_value(ledger, key):
    """按键取台账值 —— 跨语言消费方的**官方只读出口**（issue #4 ④）。

    消费方（CI、其它语言的测试进程）一律走 `facts.py --get KEY`，
    **不要自己解析 FACTS.json**：手写 parser 的经典坑是 substring 找
    `"value"` 再取引号内 —— 同一文件里到处都是 `"value": …`，会取到
    **别的键**上的值。这里把值取完整。
    键不存在 ⇒ (False, 错误句)；存在 ⇒ (True, 值)。
    """
    f = facts_of(ledger)
    if key not in f:
        return False, "台账里没有键 `%s`（现有：%s）" % (
            key, ", ".join(sorted(f)) or "空")
    return True, value_of(f[key])


def _load_or_die():
    """读台账；**没有就给出可操作的提示**而不是原始 traceback。
    为什么单列：新仓库第一次用时台账还不存在，而这个脚本今天会直接抛
    FileNotFoundError —— 那是"为本仓写死"的味道（我们那边永远有 FACTS.json）。
    语义仍是 fail-loud（空台账照样拒绝渲染），只是**把下一步写在错误里**。"""
    if not os.path.exists(OUT):
        print("FATAL: 还没有台账 %s\n"
              "       先在仓库根跑一遍量测：python3 zreflect/facts.py\n"
              "       然后再 --render-doc 把机器块写进文档。" % os.path.basename(OUT),
              file=sys.stderr)
        raise SystemExit(2)
    return load(OUT)


def main(argv):
    if argv and argv[0] == "--render":
        sys.stdout.write(render_block(_load_or_die()) + "\n")
        return 0
    if argv and argv[0] == "--render-doc":
        return write_doc(argv[1] if len(argv) > 1 else DOC, _load_or_die())
    if argv and argv[0] == "--check":
        return check_doc(argv[1] if len(argv) > 1 else DOC, _load_or_die())
    if argv and argv[0] == "--get":
        if len(argv) < 2:
            print("FATAL: --get 需要一个键名：--get KEY", file=sys.stderr)
            return 2
        ok, v = get_value(_load_or_die(), argv[1])
        if not ok:
            print("FATAL: %s" % v, file=sys.stderr)
            return 2
        print(v)                       # 只打印值本身：不解释、不带前缀
        return 0
    if argv and argv[0] == "show":
        led = _load_or_die()
        f = facts_of(led)
        keys = [argv[1]] if len(argv) > 1 else sorted(f)
        rc = 0
        for k in keys:
            if k not in f:
                print("没有这条事实：%s（现有：%s）" % (k, ", ".join(sorted(f))), file=sys.stderr)
                rc = 1
                continue
            e = f[k] if isinstance(f[k], dict) else {"value": f[k]}
            print("%-20s %s" % (k, e.get("value")))
            print("    出处  %s" % e.get("source", "?"))
            print("    复跑  %s" % e.get("cmd", "?"))
            if e.get("note"):
                print("    备注  %s" % e["note"])
        return rc
    return measure(argv)


def _tmp_doc(content, name="doc.md"):
    """自证用的临时文档（tempfile + atexit 清理 —— 此前写固定的 /tmp
    路径，非 pid 唯一，并行跑两份自证会互相踩）。"""
    import atexit                                        # noqa: PLC0415
    import shutil                                        # noqa: PLC0415
    import tempfile                                      # noqa: PLC0415
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    p = os.path.join(d, name)
    open(p, "w").write(content)
    return p


CASES = [
    # ③ 空输入必须报（守卫的决策接线在 zreflect/guard.py 的自证里；
    #    掉条 / 改口的纯函数在 ledger.py 的自证里 —— 各归各）
    ("★ 空文档（没有块标记）⇒ check_doc 必须报，不许算通过",
     lambda: check_doc(_tmp_doc("空空如也\n"), {"facts": {"a": 1}}) == 2),
    ("★ 文档文件不存在 ⇒ check_doc 必须报（不许因为找不到就算通过）",
     lambda: check_doc(os.path.join(_tmp_doc("", "x.md"), "..",
                                    "no_such_%d.md" % os.getpid()),
                       {"facts": {"a": 1}}) == 2),
    # ② 测龄人话（issue #3 ②）
    ("年龄：缺失 measured_at ⇒ 明说未记录",
     lambda: _age_human({"value": 1}) == "未记录测量时间"),
    ("年龄：刚刚测的 ⇒ 今天",
     lambda: _age_human({"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) == "今天测的"),
    # ④ 官方只读出口（issue #4 ④）
    ("--get：键存在（字典形状）⇒ (True, 裸值)",
     lambda: get_value({"facts": {"n": {"value": 12, "cmd": "c"}}}, "n") == (True, 12)),
    ("--get：键存在（裸值形状）⇒ (True, 值)",
     lambda: get_value({"facts": {"n": 7}}, "n") == (True, 7)),
    ("★ --get：键不存在 ⇒ (False, 错误句)（空输入不是通过）",
     lambda: get_value({"facts": {"n": 1}}, "zzz")[0] is False),
]


MODULE = module_meta("台账 CLI", "量一遍 / 渲染 / --get / 两道守卫", selftest=True)


if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "facts.py（两道守卫 + 文档一致性）",
                              CASES, main))
