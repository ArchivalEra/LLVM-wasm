#!/usr/bin/env python3
"""按静态库/源文件把 clang.wasm 的 CODE 段体积归因（用于回答「砍掉某个功能能省多少」）。

为什么要这个：OPT-RESULTS.md §5.3 要回答「只支持 C 能省多少」。那是个**派生量**
（哪些 .o 属于"C++ 专属"），手算是没人能复跑的猜测 —— 我先前正是拍脑袋写错了
（把 clangSema/clangAST 当成"C++ 前端"，其实它们 C/C++ 共用）。

做法：用 `-Wl,--Map=` 重链一次，读 lld 的 map 文件。map 里每个符号一行，
`In` 列是它来自哪个 `.o`（在 `.a` 里的话形如 `lib/libclangSema.a(Foo.cpp.o)`）。

⚠️ 两个坑（都踩过）：
  · map 的 Size 列是**十六进制**（`int(size, 16)`，别用 int() 直接转）；
  · 同一个符号在 map 里可能出现两次（主符号行 + demangled 副本行），
    只取带 `:(` 的**主符号行**，否则总量会翻倍（实测 111 MB vs 55 MB）。

用法:
  # 1) 先重链一次拿 map（把 <map> 换成你要的路径）
  #    python3 m1/exp-map-attrib.py --make-map /tmp/mapbuild/clang.map \\
  #        --build m1/build-exp-lean_nosjlj
  # 2) 再分析
  python3 m1/exp-map-attrib.py --map /tmp/mapbuild/clang.map
"""
import argparse
import collections
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEC_RE = re.compile(r'^\s*-\s+([\da-f]+)\s+([\da-f]+)\s+'
                    r'(CODE|DATA|ELEM|TABLE|GLOBAL|EXPORT|IMPORT|TYPE|FUNCTION)\s*$')
# 主符号行：Addr(可 `-`) Off Size <src>:(<mangled>)
SYM_RE = re.compile(r'^\s*(?:-|[\da-f]+)\s+([\da-f]+)\s+([\da-f]+)\s+(\S.*?):\(')

# 「非 C 语言特性」的判定：按源文件名。这是**下界**（共用文件里也有这些特性的代码，
# 比如 SemaDecl.cpp 里有 383 处 CXX），所以算出来的省量是**乐观上限**。
FAMILIES = {
    'C++(模板/概念/协程/Lambda)': r'CXX|Cxx|Template|Concept|Lambda|Coroutine',
    'OpenMP': r'OMP|OpenMP',
    'ObjC/ARC': r'ObjC|ARC',
    'HLSL/DXIL': r'HLSL|Hlsl|DXIL|Dxil',
    'CUDA/HIP/SYCL': r'CUDA|Cuda|\bHIP\b|Hip|SYCL|Sycl',
}


def make_map(build, out_map, tool='clang'):
    """用 ninja 的链接行重链一次，附加 -Wl,--Map=<out_map>。"""
    r = subprocess.run(['ninja', '-t', 'commands', f'bin/{tool}.js'],
                       cwd=os.path.join(ROOT, build), capture_output=True, text=True)
    pat = re.compile(r'em\+\+ .*-o bin/%s\.js([- ]|$)' % re.escape(tool))
    cands = [l for l in r.stdout.splitlines() if pat.search(l)]
    if not cands:
        sys.exit(f'FATAL: no link command for bin/{tool}.js in {build}')
    argv = shlex.split(cands[-1])
    while argv and argv[0] in (':', '&&'):
        argv = argv[1:]
    if '&&' in argv:
        argv = argv[:argv.index('&&')]
    i = argv.index('-o')
    argv[i + 1] = os.path.join('/tmp', 'mapbuild', f'{tool}.js')
    argv += [f'-Wl,--Map={out_map}']
    os.makedirs(os.path.dirname(out_map), exist_ok=True)
    os.makedirs('/tmp/mapbuild', exist_ok=True)
    env = dict(os.environ)
    env.setdefault('EM_CACHE', os.path.join(
        os.environ.get('EMSDK', os.path.join(ROOT, 'toolchain/emsdk')),
        'upstream/emscripten/cache'))
    print(f'== relinking {tool} with --Map -> {out_map} (this takes minutes)')
    subprocess.run(argv, cwd=os.path.join(ROOT, build), env=env, check=True)


def analyse(map_path, brotli_now):
    sec = None
    total = 0
    by_archive = collections.Counter()
    by_file = collections.Counter()
    declared = None
    for raw in open(map_path, encoding='utf-8', errors='replace'):
        s = SEC_RE.match(raw)
        if s:
            sec = s.group(3)
            if sec == 'CODE':
                declared = int(s.group(2), 16)
            continue
        if sec != 'CODE':
            continue
        m = SYM_RE.match(raw)
        if not m:
            continue
        _off, size, src = m.groups()
        try:
            sz = int(size, 16)          # ← 十六进制
        except ValueError:
            continue
        total += sz
        am = re.search(r'(lib[A-Za-z0-9_]+\.a)\(([^)]+)\)', src)
        if am:
            by_archive[am.group(1)] += sz
            by_file[(am.group(1), am.group(2))] += sz
        else:
            by_archive['(direct .o)'] += sz
            by_file[('(direct .o)', os.path.basename(src))] += sz

    print(f'CODE 段声明 {declared:,} B / 主符号行合计 {total:,} B '
          f'（覆盖率 {total/declared*100:.1f}%）' if declared else f'合计 {total:,} B')
    print('\n=== 按静态库（前 15）===')
    for k, v in by_archive.most_common(15):
        print(f'  {v:>11,}  {v/total*100:5.2f}%  {k}')

    fam = collections.Counter()
    for (_lib, f), v in by_file.items():
        for name, rx in FAMILIES.items():
            if re.search(rx, f):
                fam[name] += v
                break
    print('\n=== 「非 C 语言特性」占用（按文件名判定 = 乐观上限）===')
    for k, v in fam.most_common():
        print(f'  {v:>11,}  {v/total*100:5.2f}%  {k}')
    s = sum(fam.values())
    print(f'  {s:>11,}  {s/total*100:5.2f}%  合计')
    if brotli_now:
        opt = int(brotli_now * (1 - s / total))
        print(f'\n乐观外推：clang brotli {brotli_now:,} -> 约 {opt:,} '
              f'({opt/1e6:.2f} MB)')
        print(f'  + lld 8,495,303 => 约 {(opt+8495303)/1e6:.2f} MB'
              f'（15 MB 预算 {"达标" if opt+8495303 <= 15e6 else "仍超"}）')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', help='已有的 map 文件，直接分析')
    ap.add_argument('--make-map', help='先生成 map（重链一次）')
    ap.add_argument('--build', default='m1/build-exp-lean_nosjlj')
    ap.add_argument('--brotli-now', type=int, default=12_614_129,
                    help='当前 clang brotli 字节（用于外推）')
    a = ap.parse_args()
    if a.make_map:
        make_map(a.build, a.make_map)
        analyse(a.make_map, a.brotli_now)
    elif a.map:
        analyse(a.map, a.brotli_now)
    else:
        ap.error('需要 --map 或 --make-map 之一')


if __name__ == '__main__':
    main()
