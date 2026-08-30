#!/usr/bin/env node
// テキストの指紋（正本・JS 側）。**text_digest.py と1バイトも違わないこと。**
//
// 決まり（両言語で同じ式にする）:
//   1. 改行を LF に統一する
//   2. Unicode を NFC 正規化する
//   3. UTF-8 のバイト列にして SHA-256 を取る
//
// なぜ（aub 2026-08-29 の実害）: 指紋関数が JS と Python で不一致で、
// **非 ASCII を含む行で、行数も文字数も一致したまま値だけずれた**。
// str.length（UTF-16 の符号単位）と len()（符号位置）が絵文字で割れ、
// 結合文字は見た目も文字数も同じでバイト列だけ違う。

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export function textDigest(text) {
  const lf = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const nfc = lf.normalize('NFC');
  return createHash('sha256').update(Buffer.from(nfc, 'utf8')).digest('hex');
}

// **`file://` を手で組み立てないこと。** Windows では左右が食い違い、
// **常に false** になります（2026-08-30 に Windows 側で実測）。
//
//     import.meta.url  = file:///C:/tmp/probe.mjs
//     process.argv[1]  = C:\tmp\probe.mjs
//     比較結果          = false
//
// そのとき**終了コードは 0 のまま、標準出力が空**になります。呼び出し側は
// 「動いた」と受け取り、指紋が空のまま「割れています」と報告していました。
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const src = process.argv[2]
    ? readFileSync(process.argv[2], 'utf8')
    : readFileSync(0, 'utf8');
  process.stdout.write(textDigest(src) + '\n');
}
