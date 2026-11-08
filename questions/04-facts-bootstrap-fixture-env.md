# 04: harness 的 facts bootstrap 夹具在 vendored 形态下 2 例结构性必红（上游 issue #34）

**What to build:** 等上游 Einfacht 修 `facts.py _copy_suite_into()`（把宿主
`reflect-hooks/Einfacht.env` 排除出夹具拷贝面，upstream issue #34 的「最小」方案），
同步后 `python3 zreflect/harness.py` 全绿。

**Blocked by:** 上游 Einfacht（`ArchivalEra/Einfacht`）修复并发布含修复的 commit。

**Status:** ready-for-human
（等上游 Einfacht #34 修复后同步重验；理由写在下一行。）

**Settling:** `mv reflect-hooks/Einfacht.env /tmp/hold && python3 zreflect/facts.py --selftest && mv /tmp/hold reflect-hooks/Einfacht.env` —— 挪走宿主 env 载体后 16 PASS / 0 FAIL、
挪回后恢复 14 PASS / 2 FAIL（2026-11-08 实测，与上游 #34 §4 的隔离变量一致）。
上游修复后（vendored 同步到含修复的 commit），**不挪** env 直接 `python3 zreflect/harness.py`
rc=0 ⇒ 本案结案；仍红 ⇒ 修法与 #34 不同，回上游再报。

**实测结论（2026-11-08，351dc7b）**：

- `python3 zreflect/facts.py --selftest` ⇒ **14 PASS / 2 FAIL**：
  `facts.fresh_repo_bootstraps_green` / `facts.real_repo_shaped_bootstraps`；
- 同一份代码、挪走宿主 `reflect-hooks/Einfacht.env` ⇒ **16 PASS / 0 FAIL**；
- 纯上游仓（无 env 载体）⇒ 16 PASS / 0 FAIL（上游同日自测）。
- 根因（上游 #34 §3）：`_copy_suite_into()` 把宿主整个 `reflect-hooks/`（含带宿主
  旋钮的 `Einfacht.env`）拷进「全新仓」夹具，宿主 env 按加载优先级**遮蔽**夹具
  `--init` 自己生成的 env ⇒ `check_facts`/`check_readme_sync` 按宿主旋钮跑夹具，必红。
- **生产判据不受影响**：`registry --run commit` 11 ran / 0 failed / 6 off 全绿
  （off 的 6 道是未启用，不是失败）；两例夹具红如实留账，不造假占位文件绕过。

**结算步骤**：

- [ ] 上游 #34 修复落地，vendored 层同步到含修复的 commit
- [ ] `python3 zreflect/harness.py` rc=0（不挪 env），`Status:` 改 `resolved`
