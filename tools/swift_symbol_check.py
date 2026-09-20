#!/usr/bin/env python3
"""**実装が引いている名前が、実際に在るか**を見る（2026-09-20 新設）。

## これは型検査ではありません

見られるのは「`X.y` の `X` と `y` が在るか」だけです。
関数の戻り値の型・ジェネリクス・`some View` の中の食い違いは**捕まりません**。
**「0 件だから通る」とは言えません。**出力にもそう書きます。

## なぜ要るか

実害（2026-09-20・PlantTalk）: Mac mini のビルドが **2 回とも「存在しない型・
存在しないメンバ」で止まりました**。

    1 回目  MBTIGroup がどこにも無い / ColorBrand という型も無い（生成物は Brand）
    2 回目  Space.chipGap / chipPadV / chipPadH が無い

**`design_check.py` は禁止パターンしか見ないので、存在しない名前を書いても緑です。**
そのため「機械で確かめた」と報告した画面が、**そもそもビルドできない**状態でした。

**Swift は最初に落ちたところで止まります。**1 回のビルドで全部は出ません。
Xcode の無い機体で書いていると、**この往復がビルドの回数だけ続きます。**

## なぜ `swiftc -typecheck` でないのか

**iOS の SDK がこの機体にありません**（Command Line Tools は macOS SDK だけ。
`xcrun --sdk iphoneos --show-sdk-path` が落ちるのを実測）。
iOS 専用の API を使うファイルは macOS SDK では通らないので、**全部の型検査は
できません。**通るなら、そちらのほうが強いので、そちらを使ってください。

## 何を見るか

1. `X.y` の `X` が案件で宣言されている型なら、**`y` がその型に在るか**
2. `X` が案件の外の型なら、**`外の型` に宣言されているか**

**コメントと文字列は潰してから数えます。**潰さないと、コメントの中の
`DESIGN.md` や `DECISIONS.md` が型の参照に見えます（実測: 13 件 → 5 件）。

## 終了コード

    0 … 確かめて合格
    1 … 確かめて違反（在らない名前を引いている）
    2 … **確かめられなかった**（設定が無い・走査対象が 0 件）

## 設定（案件の design/swift-symbols.json）

    {
      "sources": ["Sources"],
      "外の型": {"Font": "SwiftUI", "UIScreen": "UIKit"},
      "見ない名前": {"Self": "文脈で決まるので追えません"}
    }
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

DECL_RX = re.compile(
    r'^[ \t]*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+)?'
    r'(?:final\s+)?(?:enum|struct|class|protocol|actor)\s+(\w+)', re.M)
EXT_RX = re.compile(r'^[ \t]*extension\s+([\w.]+)', re.M)
# **行頭に固定しない。**`enum X { static let m = 1 }` のように 1 行で書くと
# 行頭に来ません（2026-09-20 に自分の試験で踏みました）。`{` や `;` の後ろも見ます
MEMBER_RX = re.compile(
    r'(?:^|[{;])[ \t]*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+)?'
    r'(?:static\s+|class\s+)(?:let|var|func)\s+(\w+)', re.M)
CASE_RX = re.compile(r'(?:^|[{;])[ \t]*case\s+([\w, ]+)', re.M)
REF_RX = re.compile(r'(?<![\w.])([A-Z]\w*)\.([a-z_]\w*)')


def strip_code(src: str) -> str:
    """コメントと文字列を空白に潰す。**中の字を数えないため。**

    潰さないと、コメントの中の `DESIGN.md` や `DECISIONS.md` が型の参照に
    見えます（PlantTalk で実測: 外の型が 13 件 → 5 件）。
    行数と桁は保つので、行番号がずれません。
    """
    out, i, n, depth = [], 0, len(src), 0
    while i < n:
        c = src[i]
        if depth:
            if src.startswith("/*", i):
                depth += 1; out.append("  "); i += 2; continue
            if src.startswith("*/", i):
                depth -= 1; out.append("  "); i += 2; continue
            out.append("\n" if c == "\n" else " "); i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            out.append(" " * (j - i)); i = j; continue
        if src.startswith("/*", i):
            depth = 1; out.append("  "); i += 2; continue
        if c == '"':
            if src.startswith('"""', i):
                j = src.find('"""', i + 3); j = n if j < 0 else j + 3
            else:
                j = i + 1
                while j < n and src[j] != '"':
                    if src[j] == "\\":
                        j += 1
                    j += 1
                j = min(j + 1, n)
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j]))
            i = j; continue
        out.append(c); i += 1
    return "".join(out)


def blocks(src: str):
    """`型名 → その中身` を返す。**波括弧を数えて切ります**（行数で切らない）。

    `extension X { … }` も同じ型に足します。**別のファイルで足した static も
    拾うため**です。
    """
    found = {}
    for rx, grp in ((DECL_RX, 1), (EXT_RX, 1)):
        for m in rx.finditer(src):
            name = m.group(grp).split(".")[0]
            j = src.find("{", m.end())
            if j < 0:
                continue
            depth, k = 0, j
            while k < len(src):
                if src[k] == "{":
                    depth += 1
                elif src[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            found.setdefault(name, []).append(src[j:k])
    return found


def members_of(bodies):
    out = set()
    for b in bodies:
        out |= set(MEMBER_RX.findall(b))
        for cs in CASE_RX.findall(b):
            for c in cs.split(","):
                c = c.strip()
                if c and re.fullmatch(r"\w+", c):
                    out.add(c)
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in argv or "--selftest" in argv:
        return self_test()
    if "--config" not in argv:
        print("--config <案件>/design/swift-symbols.json を渡してください", file=sys.stderr)
        return 2
    cfg_path = Path(argv[argv.index("--config") + 1])
    if not cfg_path.exists():
        print(f"設定がありません: {cfg_path}", file=sys.stderr)
        print("  **置いていないことと、対象 0 件は別です。**", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else cfg_path.resolve().parent.parent

    files = []
    for d in (cfg.get("sources") or []):
        p = root / d
        files += sorted(p.rglob("*.swift")) if p.is_dir() else ([p] if p.is_file() else [])
    if not files:
        print(f"Swift のファイルが 1 件もありません: {cfg.get('sources')}", file=sys.stderr)
        print("  **0 件は『綺麗』ではなく『見ていない』です。**", file=sys.stderr)
        return 2

    stripped = {f: strip_code(f.read_text(encoding="utf-8", errors="replace")) for f in files}
    types = {}
    for src in stripped.values():
        for name, bodies in blocks(src).items():
            types.setdefault(name, []).extend(bodies)
    known = {n: members_of(b) for n, b in types.items()}
    outside = cfg.get("外の型") or {}
    ignore = cfg.get("見ない名前") or {}

    bad_member, bad_type = [], []
    refs = 0
    for f, src in stripped.items():
        for m in REF_RX.finditer(src):
            cont, mem = m.group(1), m.group(2)
            if cont in ignore:
                continue
            refs += 1
            line = src.count("\n", 0, m.start()) + 1
            if cont in known:
                if mem not in known[cont]:
                    bad_member.append((f, line, cont, mem))
            elif cont not in outside:
                bad_type.append((f, line, cont, mem))

    print(f"名前の照合: 案件の型 {len(known)} 件 / 参照 {refs} 件 "
          f"（外の型 {len(outside)} 件 / 見ない名前 {len(ignore)} 件）")
    print("  **これは型検査ではありません。**戻り値の型・ジェネリクス・"
          "`some View` の中の食い違いは見ていません。**0 件でも通るとは限りません。**")
    if bad_type:
        print("\n**どこにも宣言されていない型を引いています:**", file=sys.stderr)
        for f, line, c, mem in bad_type[:12]:
            print(f"  - {f}:{line}  {c}.{mem}", file=sys.stderr)
        print("  案件の外の型なら、`外の型` に「どこの型か」を書いてください。", file=sys.stderr)
    if bad_member:
        print("\n**その型に無いメンバを引いています:**", file=sys.stderr)
        for f, line, c, mem in bad_member[:12]:
            near = sorted(known[c])[:6]
            print(f"  - {f}:{line}  {c}.{mem} — {c} が持つのは "
                  f"{', '.join(near)}{' ほか' if len(known[c]) > 6 else ''}", file=sys.stderr)
    if bad_type or bad_member:
        print(f"\n  合計 {len(bad_type) + len(bad_member)} 件。"
              f"**Swift は最初の 1 件で止まるので、ビルドでは 1 件ずつしか出ません。**",
              file=sys.stderr)
        return 1
    return 0


def self_test() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "design").mkdir(); (root / "src").mkdir()
        cfgp = root / "design" / "swift-symbols.json"
        cfg = {"sources": ["src"], "外の型": {"Font": "SwiftUI"}, "見ない名前": {"Self": "文脈"}}

        def write(code, c=None):
            (root / "src" / "A.swift").write_text(code, encoding="utf-8")
            cfgp.write_text(json.dumps(c or cfg, ensure_ascii=False), encoding="utf-8")

        def run():
            return main(["--config", str(cfgp), "--root", str(root)])

        write("enum Space { static let m = 16.0 }\nlet a = Space.m\n")
        if run() != 0:
            print("self-test NG: 在るメンバで落ちました"); ok = False

        write("enum Space { static let m = 16.0 }\nlet a = Space.chipGap\n")
        if run() != 1:
            print("self-test NG: **無いメンバを通しました**"); ok = False

        write("let a = ColorBrand.accent\n")
        if run() != 1:
            print("self-test NG: **宣言されていない型を通しました**"); ok = False

        write("let a = Font.body\n")
        if run() != 0:
            print("self-test NG: 外の型として宣言したのに落ちました"); ok = False

        # **コメントと文字列を数えない**（これが無いと DESIGN.md が型に見える）
        write('enum Space { static let m = 16.0 }\n// 正は DESIGN.md です\n'
              'let s = "DECISIONS.md を読む"\nlet a = Space.m\n')
        if run() != 0:
            print("self-test NG: **コメントや文字列の中を数えました**"); ok = False

        # **extension で足した static も拾う**
        write("enum Space { }\nextension Space { static let m = 16.0 }\nlet a = Space.m\n")
        if run() != 0:
            print("self-test NG: **extension の static を拾えていません**"); ok = False

        # **enum の case も拾う**
        write("enum Tone { case neutral, accent }\nlet a = Tone.neutral\n")
        if run() != 0:
            print("self-test NG: **enum の case を拾えていません**"); ok = False

        # **見ない名前は数えない**
        write("enum Space { static let m = 16.0 }\nlet a = Self.anything\n")
        if run() != 0:
            print("self-test NG: 見ない名前を数えました"); ok = False

        # **走査対象 0 件は 2**
        (root / "src" / "A.swift").unlink()
        if run() != 2:
            print("self-test NG: **0 件を通しました**（見ていないのに緑）"); ok = False

        cfgp.unlink()
        if run() != 2:
            print("self-test NG: 設定が無いのに 2 を返しませんでした"); ok = False

    print("self-test: " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
