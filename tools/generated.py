#!/usr/bin/env python3
"""**そのファイルは生成物か**を1か所で決める（2026-09-06 新設・issue #78）。

`machine_scope.py`（担当の判定）と `generated_check.py`（機体固有の文字列の検査）が
同じ判断を使うために、ここに1本だけ置く。**2か所で別々に判定すると必ずずれる。**

## なぜ要るか

**決定論的な生成物は担当で縛りません**（2026-09-06 ユーザー確定・DESIGN.md）。
`design/` を1つの機体の担当にすると、その下の生成物も自動的にその機体のものになり、
**生成器を直した機体が、その直しを適用できない**という倒錯が起きるためです。

実害（aub-familywalk・2026-09-06）: Mac mini が `gen_notcaptured.py` の移植性を直したのに、
生成し直すと「担当外を変えた」で落ち、生成し直さないと「生成し直していない」で落ちる、
**どちらを選んでも1段落ちる行き止まり**に入りました。

## 判定（**一覧を手で書かない。生成器が書いた印から導く**）

| 形 | 印 |
|---|---|
| JSON | ルートに `$手で書き換えない` がある |
| JSON | `$meta.source` が `GENERATED` で始まる |
| コード | **最初の5行以内**に `自動生成。手で編集しない`（`gen_io.write` が書く形） |

**「先頭」を厳しく見ます。** ファイル内のどこかに印があればよい、にすると
**生成器そのものを拾います**（`gen_io.write` は同じ文字列を書き出すので、
生成器のソースにも文字列として現れる）。2026-09-06 に aub の `design/catalog_build.py`
を実際に誤検出しました。生成物の見出しは必ずファイルの先頭に来ます。

**印はすべて生成器が自分で書いたものです。** 内容からの推測はしません
（「生成」という語がコメントに出てくるだけのファイルを拾わないため）。

## 捕まえないもの

- 生成物が**本当に決定論的か**。それは「生成物のべき等」の段（`gen_verify.py`）と、
  機体固有の文字列を見る `generated_check.py` が担当する
- 印を**書き忘れた**生成物。書いていない印は機械には見えない
  （**だから生成器は必ず印を書く**。`gen_io.write` は自動で書く）
- 確かめた方法: `--self-test`（3つの印それぞれを拾うこと・紛らわしい非生成物を拾わないこと）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない
from _submodules import is_inside, submodule_paths

#: コード生成物の見出し（`gen_io.write` が書く形）
CODE_MARK = "自動生成。手で編集しない"

#: JSON のルートに置かれる印
JSON_ROOT_MARK = "$手で書き換えない"

#: `$meta.source` がこれで始まれば生成物
JSON_SOURCE_PREFIX = "GENERATED"

#: 先頭だけ読む（大きな生成物を全部読まない）
HEAD_BYTES = 4096

#: コードの見出しを認める行数。**ここを緩めると生成器そのものを拾う**
#: （`gen_io.write` は同じ文字列を書き出すので、生成器のソースにも現れる。
#: 2026-09-06 に aub の `design/catalog_build.py` を誤検出した）
CODE_MARK_LINES = 5


#: `$手で書き換えない` の値がこれで始まるなら、**生成物ではない**という宣言として読む
#: （キーの存在だけで判定すると、否定を書いたファイルまで生成物になる）
DENIALS = ("いいえ", "no", "false", "手で書", "ちがい", "違い")


def is_generated(path) -> tuple[bool, str]:
    """生成物か。**理由も返す**（報告でどの印を見たか示すため）。

    読めないファイル（消えた・壊れている）は「生成物ではない」に倒す。
    担当の判定に使うので、**分からないものを共有にしない**のが安全側。
    """
    p = Path(path)
    try:
        head = p.read_text(encoding="utf-8", errors="replace")[:HEAD_BYTES]
    except OSError:
        return False, "読めない"

    if any(CODE_MARK in ln for ln in head.splitlines()[:CODE_MARK_LINES]):
        return True, f"最初の {CODE_MARK_LINES} 行に「{CODE_MARK}」"

    if p.suffix == ".json":
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "JSON として読めない"
        if isinstance(d, dict):
            if JSON_ROOT_MARK in d:
                # **値まで読む。** キーがあるだけで生成物にすると、「これは手で書く定義です」と
                # 否定を書いたファイルまで拾う（2026-09-06 実測: build/inventory-schema.json）
                val = str(d[JSON_ROOT_MARK]).strip()
                if any(val.lower().startswith(x) for x in DENIALS):
                    return False, f"`{JSON_ROOT_MARK}` の値が否定（{val[:20]}…）"
                return True, f"ルートに `{JSON_ROOT_MARK}`"
            meta = d.get("$meta")
            if isinstance(meta, dict):
                src = str(meta.get("source", ""))
                if src.startswith(JSON_SOURCE_PREFIX):
                    return True, f"`$meta.source` が `{JSON_SOURCE_PREFIX}` で始まる"
    return False, "印が無い"


def list_generated(root, subdirs=None) -> list[tuple[Path, str]]:
    """`root` の下から生成物を**導出**する（一覧を宣言しない）。

    `subdirs` は歩く場所。既定は `["design"]`（案件の形）。**`"."` を渡すとリポジトリ全体**を
    歩く。ハーネス自身のように `design/` を持たないリポジトリでは、既定のままだと
    **必ず 0 件になり、検査が空振りの緑になります**（2026-09-06 実測: design-harness で
    `生成物 0 件。機体固有の文字列はありません（共有して安全）` と出ていたが、
    `gate/conditions.json` は生成物だった）。

    `design/harness`（submodule）と `__pycache__` と `.git` は見ない。
    """
    root = Path(root)
    _subs, _how = submodule_paths(root)
    out, seen = [], set()
    for sub in (subdirs or ["design"]):
        base = root if sub == "." else root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel_ = p.relative_to(root)
            parts = set(rel_.parts)
            if "__pycache__" in parts or ".git" in parts:
                continue
            # **submodule は git から導いて外します**（#97）。
            # `"harness" in parts` で外していたため、ハーネス一式を
            # `site/design/harness/` に置いている案件では**案件の生成物まで
            # 全部外れて 0 件**になっていた（2026-09-09・qnd-database で実測）。
            # **分からないときは外しません**（外しすぎた 0 件は「綺麗」と読み違える）。
            if _subs and is_inside(rel_, _subs):
                continue
            rel = p.relative_to(root)
            if rel in seen:
                continue
            ok, why = is_generated(p)
            if ok:
                seen.add(rel)
                out.append((rel, why))
    return sorted(out)


def self_test() -> int:
    import tempfile
    ok = True
    CASES = [
        ("拾う: コードの見出し", "a.dart",
         "// 自動生成。手で編集しない。\n// 生成元: x\nclass A {}\n", True),
        ("拾う: JSON ルートの印", "a.json",
         '{"$手で書き換えない": "gen.py が生成します", "x": 1}', True),
        ("拾う: $meta.source が GENERATED", "b.json",
         '{"$meta": {"source": "GENERATED — gen_x.py が作る"}, "x": 1}', True),
        ("拾わない: 手書きの JSON", "c.json",
         '{"$meta": {"source": "2026-08-19 の実測"}, "x": 1}', False),
        ("拾わない: 本文に「生成」と書いてあるだけ", "d.json",
         '{"$meta": {"note": "生成器が読む一覧。手で書く"}, "x": 1}', False),
        ("拾わない: コードだが印が無い", "e.dart", "class B {}\n", False),
        # **生成器そのものを拾わない**（gen_io.write が同じ文字列を書き出すので、
        # 生成器のソースにも文字列として現れる。2026-09-06 に実際に誤検出した）
        ("拾わない: 生成器（印はずっと下の行）", "h.py",
         '"""カタログを作る。"""\nimport x\n\n\n\n\ndef w():\n'
         "    head = '// 自動生成。手で編集しない。\\n'\n", False),
        ("拾わない: 壊れた JSON", "f.json", "{壊れている", False),
        ("拾わない: source が GENERATED で始まらない", "g.json",
         '{"$meta": {"source": "手書き。GENERATED ではない"}, "x": 1}', False),
        # **キーの存在だけで判定しない。** 値が否定なら生成物ではない
        # （2026-09-06 実測: build/inventory-schema.json が誤判定されていた）
        ("拾わない: 印の値が否定", "i.json",
         '{"$手で書き換えない": "いいえ。これは手で書く定義です", "x": 1}', False),
        ("拾う: 印の値が生成器の名前", "j.json",
         '{"$手で書き換えない": "tools/gen_gate.py が生成します", "x": 1}', True),
    ]
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for name, fn, body, want in CASES:
            f = d / fn
            f.write_text(body, encoding="utf-8")
            got, why = is_generated(f)
            if got != want:
                print(f"self-test NG: {name} → {got}（期待 {want}・理由 {why}）")
                ok = False

        # **歩く場所を変えられる。** `design/` を持たないリポジトリで既定のまま回すと
        # 必ず0件になり、検査が空振りの緑になる（2026-09-06 に design-harness で実測）
        (d / "gate").mkdir(exist_ok=True)
        (d / "gate" / "conditions.json").write_text(
            '{"$手で書き換えない": "gen_gate.py が生成します"}', encoding="utf-8")
        if list_generated(d):
            print("self-test NG: design/ の外を既定で歩いた"); ok = False
        if len(list_generated(d, ["."])) < 1:
            print("self-test NG: `.` を渡してもリポジトリ全体を歩かない"); ok = False
        if len(list_generated(d, ["gate"])) != 1:
            print("self-test NG: 場所を指定して歩けない"); ok = False
        # 同じファイルを2つの場所から拾っても1件（重複しない）
        if len(list_generated(d, [".", "gate"])) != len(list_generated(d, ["."])):
            print("self-test NG: 場所を重ねると同じファイルを二重に数える"); ok = False

        # 消えたファイルは「生成物ではない」に倒す（分からないものを共有にしない）
        got, _ = is_generated(d / "no-such.json")
        if got:
            print("self-test NG: 存在しないファイルを生成物と判定した"); ok = False

        # 導出が submodule と __pycache__ を避けるか
        #
        # **submodule は名前ではなく `.gitmodules` から導きます**（#97）。
        # `"harness" in parts` で外していたため、ハーネス一式を
        # `site/design/harness/` に置いている案件では**案件の生成物まで
        # 全部外れて 0 件**になっていました（2026-09-09・qnd-database で実測）。
        (d / "design" / "harness" / "tools").mkdir(parents=True)
        (d / "design" / "harness" / "tools" / "x.json").write_text(
            '{"$手で書き換えない": "y"}', encoding="utf-8")
        (d / "design" / "figma").mkdir(parents=True)
        (d / "design" / "figma" / "y.json").write_text(
            '{"$手で書き換えない": "y"}', encoding="utf-8")

        # (1) 宣言が無ければ**外しません**。**多く見えるほうに倒します**——
        #     外しすぎた `0 件` は「綺麗」と読み違えるからです
        found = sorted(str(p) for p, _ in list_generated(d))
        if found != ["design/figma/y.json", "design/harness/tools/x.json"]:
            print(f"self-test NG: **宣言が無いのに外した**: {found}"); ok = False

        # (2) `.gitmodules` に書いてあれば外す
        (d / ".gitmodules").write_text(
            '[submodule "design/harness"]\n\tpath = design/harness\n'
            '\turl = https://example.invalid/h.git\n', encoding="utf-8")
        found = sorted(str(p) for p, _ in list_generated(d))
        if found != ["design/figma/y.json"]:
            print(f"self-test NG: submodule を外していない: {found}"); ok = False

        # (3) **名前が似ているだけの置き場は外さない**（`harness2`）。
        #     名前で外していたときは、ここも巻き添えになっていました
        (d / "design" / "harness2").mkdir(parents=True)
        (d / "design" / "harness2" / "z.json").write_text(
            '{"$手で書き換えない": "y"}', encoding="utf-8")
        found = sorted(str(p) for p, _ in list_generated(d))
        if found != ["design/figma/y.json", "design/harness2/z.json"]:
            print(f"self-test NG: **名前が似ているだけの置き場を外した**: {found}"); ok = False
        (d / "design" / "harness2" / "z.json").unlink()
        (d / ".gitmodules").unlink()

    if ok:
        print("self-test: OK")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    found = list_generated(args.root)
    print(f"生成物 {len(found)} 件（印から導出。一覧は宣言していません）")
    for p, why in found:
        print(f"  {p}  ← {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
