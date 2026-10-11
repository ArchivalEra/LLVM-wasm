// tar 读取 —— **纯 JS，无 node 依赖**（浏览器 worker 与 node 驱动共用这一份）。
// 只处理 `tar -cf` 实际会产出的形态：常规文件 / 目录 / GNU 长名 / PAX 头。
// 自己带一个 60 行的解析器，不值得为此往浏览器 bundle 里塞一整个 tar 库。

/**
 * Read an (uncompressed) tar into Map<path, Uint8Array>.
 */
export function readTar(buf) {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  const out = new Map();
  let off = 0;
  let pendingLongName = null;
  const dec = new TextDecoder();
  // 读**当前 header** 的 [s, s+n) —— 注意是相对 header，不是相对整个文件
  // （实测踩过：闭包里写成了绝对偏移，解析出 1 个垃圾条目，静默装不上）。
  const str = (header, s, n) =>
    dec.decode(header.subarray(s, s + n)).replace(/\0.*$/, '');
  while (off + 512 <= b.length) {
    const header = b.subarray(off, off + 512);
    if (header.every((x) => x === 0)) break;               // end-of-archive
    const name = str(header, 0, 100);
    const size = parseInt(str(header, 124, 12).trim(), 8) || 0;
    const type = String.fromCharCode(header[156] || 48);
    const prefix = str(header, 345, 155);
    let full = prefix ? `${prefix}/${name}` : name;
    off += 512;
    const data = b.subarray(off, off + size);
    off += Math.ceil(size / 512) * 512;

    if (type === 'L') { pendingLongName = dec.decode(data).replace(/\0.*$/, ''); continue; }
    if (type === 'x' || type === 'g') continue;              // PAX headers
    if (type === '5') continue;                              // directory
    if (pendingLongName) { full = pendingLongName; pendingLongName = null; }
    out.set(full.replace(/^\.\//, ''), data.slice());
  }
  return out;
}
