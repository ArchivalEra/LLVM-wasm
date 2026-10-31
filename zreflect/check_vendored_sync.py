#!/usr/bin/env python3
"""vendored 同步闸门：`zreflect/` 必须仍是上游 Einfacht 的字节。

它守的不是「有没有同步过」，而是**「同步的那份之后没被偷偷改过」**：
本仓 vendored 的机制层 + 钩子，逐字节必须等于 `zreflect/VENDORED.json`
记的那个 commit 的对应文件。本仓自己的东西（数据层 `measure_llvm_wasm.py`、
本闸门自己、本仓 `Einfacht.env`）在 `local` 里显式列出 —— 它们与上游不同
**不是漂移**。

为什么单列成闸门而不是只留 `release/check-vendored-sync.mjs`：
「我们落后上游了吗」此前只能靠人重跑 diff（issue #3 用户故事 19），没有闸门
时它的答案会随时间腐烂。判据本体是 node 那支（远端 shallow fetch + 逐字节
比），这里只做 rc 转译与声明 —— **不复制逻辑**（两份实现必然漂）。

**边界（不藏）**：它只证明「本仓副本 == pin 那个 commit」，不证明「pin 是
最新上游」。追求最新是同步动作的事（`node release/check-vendored-sync.mjs`
对不上时重跑拷贝），闸门不联网查 releases。

用法：python3 zreflect/check_vendored_sync.py [--selftest]
退出码：0=绿 / 1=漂移或上游不可达 / 2=pin 或判据文件缺失（配置坏）。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate import GATE_REPO, fatal, finish, main_selftest_or, meta, off  # noqa: E402

PIN_NAME = "zreflect/VENDORED.json"
CHECKER_NAME = "release/check-vendored-sync.mjs"


def problems(pin_name=PIN_NAME, checker_name=CHECKER_NAME, root=None):
    """跑 node 判据，返回问题清单（空 = 绿 / ["OFF"] = 本仓不适用）。

    文件缺失分两类，这个分别是被跨仓库夹具逼出来的：
      · **没有 pin**（`zreflect/VENDORED.json` 不在）⇒ 这不是配置坏，是
        「本闸门在这个仓不适用」—— 夹具仓、只消费 Einfacht 的仓都没有随
        机制分发的 VENDORED.json。由 main() 翻成 **off() 并明说**，不是红：
        否则每个下游仓都得先写一份 pin 才能过换名自证（实测：夹具里它红，
        被误判成「闸门把名字写死在代码里」）。
      · **pin 在、判据脚本不在** ⇒ 真配置坏（我们自己弄丢了解析器）。
    pin 在而远端对账失败 ⇒ 真问题（副本漂了）。
    """
    root = root or GATE_REPO
    pin = os.path.join(root, pin_name)
    checker = os.path.join(root, checker_name)
    if not os.path.exists(pin):
        return ["OFF"]
    if not os.path.exists(checker):
        return ["FATAL: %s 不存在 —— 判据本身丢了" % checker_name]
    try:
        r = subprocess.run(["node", checker], capture_output=True, text=True,
                           cwd=root, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        return ["FATAL: 跑不了 node 判据（%r）" % (e,)]
    if r.returncode == 0:
        return []
    fails = [ln.strip() for ln in r.stdout.splitlines() if ln.startswith("FAIL")]
    if fails:
        return fails
    tail = (r.stderr or r.stdout).strip().splitlines()
    return ["远端拉取失败或判据崩溃：%s" % (tail[-1] if tail else "无输出")]


def main(argv):
    probs = problems()
    if probs == ["OFF"]:
        return off("本仓没有 %s（不是 vendored 本仓）—— 未查，不是通过" % PIN_NAME)
    if any(p.startswith("FATAL:") for p in probs):
        return fatal(probs[0][len("FATAL: "):])
    return finish("vendored 同步闸门", probs, "zreflect/ 与上游 pin 逐字节一致")


def _cases():
    """该红的会红 —— 一条 OFF 明说、一条配置坏、一条空输入不是通过。

    远端对账不塞进自证（网络 + 分钟级）；它的判据在 node 侧双证过
    （改动一个文件 ⇒ FAIL，恢复 ⇒ ALL PASS，见 commit 记录）。
    """
    return [
        ("OFF：没有 pin ⇒ 明说不适用（不是红，也不是静默绿）",
         lambda: problems(pin_name="nope.json") == ["OFF"]),
        ("★ pin 在而判据脚本缺失 ⇒ 报配置坏（判据丢了不许算绿）",
         lambda: any(x.startswith("FATAL:") for x in
                     problems(checker_name="nope.mjs"))),
        ("绿：两个文件都在且远端一致 ⇒ 空问题清单",
         lambda: problems() == []),
    ]


GATE = meta("vendored 同步闸门",
            "zreflect/ 必须仍是上游 Einfacht 的字节（VENDORED.json 的 pin）",
            knobs=())

if __name__ == "__main__":
    sys.exit(main_selftest_or(sys.argv[1:], "check_vendored_sync（vendored 同步）",
                              _cases, main))
