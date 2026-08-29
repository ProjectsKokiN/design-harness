#!/usr/bin/env python3
"""テキストの指紋（正本・Python 側）。**mjs 版と1バイトも違わないこと。**

## 決まり（両言語で同じ式にする）

1. 改行を **LF に統一**する（CRLF / CR → LF）
2. Unicode を **NFC 正規化**する（結合文字の並びを1つに決める）
3. **UTF-8 のバイト列**にして SHA-256 を取る

## なぜこの3つか（aub 2026-08-29 の実害）

> 指紋関数が JS と Python で不一致。**非 ASCII を含む行で、行数も文字数も
> 一致したまま値だけずれる**

- JS の `str.length` は UTF-16 の符号単位、Python の `len()` は符号位置。
  **絵文字（サロゲートペア）で数え方が割れる**
- 「が」は U+304C（合成済み）とも U+304B+U+3099（結合）とも書ける。
  **見た目も文字数も同じで、バイト列だけ違う**
- CRLF と LF は、書き出し器が動く OS で変わる

**行数も文字数も一致したまま値だけずれる**ので、いちばん気づきにくい種類の食い違い。
"""

import hashlib
import sys
import unicodedata


def text_digest(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    src = (open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1
           else sys.stdin.read())
    print(text_digest(src))
