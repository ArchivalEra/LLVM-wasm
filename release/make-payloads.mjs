#!/usr/bin/env node
// 从 release/out/manifest.json 派生**载荷身份清单**（release/payloads.json）。
//
// 为什么需要它（用户 2026-11-01：发 release 必须走 workflow）：
//   CI 上没有 `release/out/` —— 那是构建产物，122 MB，不入库。但 CI 必须知道
//   「这次要发的载荷是哪些、每个的 sha256 是多少」，否则它无从判断取回来的
//   字节对不对。这份清单就是那个答案，且它是**从构建产物派生**的（一处产地），
//   不是手写。
//
// 它不是第二份 manifest：`release/out/manifest.json` 每次构建都变（含时间戳、
// brotli 体积、宿主基线），而这份只保留**身份三要素**（name / bytes / sha256）
// ——发布判据只需要这三个。派生关系写进 `_derived_from` 字段，任何人可复算。
//
// 用法：node release/make-payloads.mjs
import { readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';

const ROOT = join(dirname(new URL(import.meta.url).pathname), '..');
const SRC = join(ROOT, 'release/out/manifest.json');
const DST = join(ROOT, 'release/payloads.json');

const man = JSON.parse(readFileSync(SRC, 'utf8'));
const payloads = man.assets.map((a) => ({
  name: a.name,
  bytes: a.bytes,
  sha256: a.sha256,
}));

// 排序：让 diff 只反映真的变化（构建顺序不稳定时不该产生噪音）
payloads.sort((x, y) => (x.name < y.name ? -1 : x.name > y.name ? 1 : 0));

const doc = {
  _why:
    '载荷身份清单：CI 发布时用它核对取回来的字节。只保留 name/bytes/sha256 —— '
    + '发布判据只需要这三样。派生于 release/out/manifest.json（构建产物，不入库），'
    + '复跑：node release/make-payloads.mjs。',
  _derived_from: 'release/out/manifest.json',
  generated: man.generated,
  counts: { payloads: payloads.length, total_bytes: payloads.reduce((n, p) => n + p.bytes, 0) },
  payloads,
};

writeFileSync(DST, JSON.stringify(doc, null, 1) + '\n');
console.log(`wrote ${DST}`);
console.log(`  ${payloads.length} payloads, ${doc.counts.total_bytes} bytes`);
for (const p of payloads) console.log(`  ${p.name.padEnd(28)} ${String(p.bytes).padStart(10)}  ${p.sha256.slice(0, 16)}`);