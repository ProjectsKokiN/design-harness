#!/usr/bin/env python3
"""指紋が JS と Python で同じ値になるかを見る（aub 提案7・2026-08-29）。

## 実害

> 指紋関数が JS と Python で不一致。**非 ASCII を含む行で、行数も文字数も
> 一致したまま値だけずれる**（aub-familywalk 2026-08-29）

**いちばん気づきにくい種類の食い違い**。行数も文字数も合うので、目でも
`wc` でも分からない。書き出し器（Figma プラグイン = JS）と検査（Python）で
指紋が割れると、**鮮度の検査が毎回「変わった」と言い続けるか、逆に
変わったのに黙る**。

## 直し方（この道具の前提）

**各案件が自前の指紋関数を書かない。** `fingerprint/text_digest.{py,mjs}` を使う。
両方に同じ3つの決まりが書いてある:

1. 改行を LF に統一する
2. Unicode を NFC 正規化する
3. UTF-8 のバイト列にして SHA-256 を取る

この検査は、その2本が**固定具に対して同じ値を出すこと**と、
**その値が記録した値から動いていないこと**を見る。

## この検査が捕まえないもの

- 案件が独自の指紋関数を書いてしまった場合。それは「使っているか」の話で、
  `gen_input_check` / コードレビューの領域
- 指紋に**何を入れるか**の設計（`figma_freshness.py` の DIGEST_FIELDS）
- 確かめた方法: --self-test（NFC を省いた実装が固定具で割れることを示す）

## 使い方

    python3 <harness>/tools/fingerprint_parity.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FP = HERE.parent / "fingerprint"


def run(cmd, path):
    try:
        r = subprocess.run(cmd + [str(path)], capture_output=True, text=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{cmd[0]} を実行できません: {e}"
    if r.returncode != 0:
        return None, f"{cmd[0]} が失敗しました: {r.stderr.strip()[:200]}"
    return r.stdout.strip(), None


def main(argv=None):
    ap = argparse.ArgumentParser(description="指紋が JS と Python で一致するか")
    ap.add_argument("--fixture", type=Path, default=FP / "fixture.txt")
    ap.add_argument("--expected", type=Path, default=FP / "expected.txt")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.fixture.exists():
        print(f"固定具がありません: {args.fixture}", file=sys.stderr)
        return 2

    py, err1 = run([sys.executable, str(FP / "text_digest.py")], args.fixture)
    js, err2 = run(["node", str(FP / "text_digest.mjs")], args.fixture)

    if err2 and "node" in str(err2):
        print(f"注意: node が無いので JS 側を確かめられません（{err2}）。\n"
              f"  **確かめていないので、確かめた顔をしません。**"
              f"書き出し器を動かすマシンでは node を入れてください。",
              file=sys.stderr)
        return 2
    for e in (err1, err2):
        if e:
            print(e, file=sys.stderr)
            return 2

    if py != js:
        print(f"指紋が JS と Python で割れています。\n"
              f"  Python: {py}\n  JS    : {js}\n"
              f"  改行の統一 / NFC 正規化 / UTF-8 バイト列 のどれかが"
              f"片側で抜けています。", file=sys.stderr)
        return 1

    if args.expected.exists():
        want = args.expected.read_text(encoding="utf-8").strip()
        if py != want:
            print(f"指紋の式が変わりました（両側そろって動いています）。\n"
                  f"  記録: {want}\n  いま: {py}\n"
                  f"  意図した変更なら {args.expected} を更新してください"
                  f"（差分が git に残ります）。**下流の指紋が全部ずれます。**",
                  file=sys.stderr)
            return 1

    print(f"OK: 指紋は JS と Python で一致し、記録とも同じです（{py[:16]}…）。")
    return 0


def self_test():
    """固定具が本当に違いを暴けるかを示す（通ることの確認では何も証明できない）。"""
    import hashlib, tempfile, unicodedata
    ok = True
    # **バイトで読んで自前で復号する。** Path.read_text は Python の
    # universal newlines で CRLF を LF に直してしまい、「改行を統一しない」
    # 変種が固定具で割れなくなる（2026-08-29 に実際に踏んだ）。
    # なお本番の text_digest.py も open(encoding=...) で読むため Python 側では
    # CRLF が消えるが、JS の readFileSync は消さない。**だから両方に
    # 明示の LF 統一が要る**——片方で省くと、そこで割れる。
    text = (FP / "fixture.txt").read_bytes().decode("utf-8")

    def canonical(s):
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        return hashlib.sha256(unicodedata.normalize("NFC", s)
                              .encode("utf-8")).hexdigest()

    variants = {
        "NFC を省く": lambda s: hashlib.sha256(
            s.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest(),
        "改行を統一しない": lambda s: hashlib.sha256(
            unicodedata.normalize("NFC", s).encode("utf-8")).hexdigest(),
        "UTF-16 で符号化する（JS の素朴な実装）": lambda s: hashlib.sha256(
            unicodedata.normalize("NFC", s.replace("\r\n", "\n"))
            .encode("utf-16-le")).hexdigest(),
    }
    base = canonical(text)
    for label, fn in variants.items():
        if fn(text) == base:
            print(f"self-test NG: 固定具が「{label}」を暴けていません。"
                  f"**この固定具では割れを検出できません。**")
            ok = False

    # 実際の2本が一致すること
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "f.txt"
        f.write_text(text, encoding="utf-8")
        py, e1 = run([sys.executable, str(FP / "text_digest.py")], f)
        js, e2 = run(["node", str(FP / "text_digest.mjs")], f)
        if e2:
            print(f"self-test: node が無いので JS 側は未確認（{e2}）")
        elif py != js:
            print(f"self-test NG: 2本が割れています\n  py={py}\n  js={js}"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
