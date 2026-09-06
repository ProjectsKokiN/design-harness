#!/usr/bin/env python3
"""共有層の道具が **`~/.claude` を実行時に読んでいないか**を見る（2026-09-06 新設）。

## なぜ要るか

**`~/.claude` は作者の手元の3台にしかありません。** CI にも、他人のクローンにも
ありません。ところが共有層の道具がそこを読みにいくと、次の2つが起きます。

| 形 | 実害（2026-09-06 に実測） |
|---|---|
| **落ちる** | 案件の pre-push 関門が `gen_notcaptured.py` を回す。一覧が `~/.claude` にあったため、
`env HOME=<空>` で `プロパティの一覧がありません` の **exit 2**。`~/.claude` を持たない
実行主体は push 前検査を通せない |
| **黙って緑** | 公開 CI（`.github/workflows/attack.yml`）が `gen_gate.py --check` を回す。
正本が `~/.claude` にあったため「**鮮度は見ていません**」と出して **exit 0**。
関門6条件の鮮度検査が GitHub Actions 上でずっと空振りの緑だった |

**後者が重い。** 「検査は回っているのに中身が空」で、`hollow_check.py` が潰すために
作られた形そのものです。しかも劣化して緑を返す実装は、**欠落を永久に隠します**。

どちらも 2026-09-06 に正本を repo の中へ移して直しました
（`gate/production-gate.md` / `vocab/figma-properties.json`）。
**この道具は、同じ形が戻ってこないようにするためのものです。**

## 何を見るか

    python3 tools/reachability_check.py            # tools/ engine/ shims/ build/ を見る
    python3 tools/reachability_check.py --self-test

**実行時に読む参照だけを落とします。** 案内文（「`source ~/.claude/.env` を実行して
ください」のような手順の説明）は落としません。区別は次のとおりです。

| 落とす | 落とさない |
|---|---|
| `Path.home() / ".claude"` を**パスとして組む** | 文字列リテラルの中の `~/.claude/...`（案内文・コメント） |
| `str(Path.home())` を `replace` の引数にする | `Path.home()` を単独で使う（HOME そのものが目的の場合） |

どうしても要る所は、**その行に `# reachability-ok: 理由` を書く**（理由の無い印は落とす。
`swallow_check.py` の `swallow-ok` と同じ書式）。正しい使い方は
「**リポジトリ相対を先に試し、外にあるものだけホームを `~` に畳む**」フォールバックです
（`gen_gate.py` の `_repo_rel` が例）。この形はホームが違う機体でも同じ文字列になります。

2つ目は、**生成物に機体固有の絶対パスを残す**書き方です。2026-09-06 に
`gen_notcaptured.py` と `gen_gate.py` の2本で実際に起きました。ホームが違う機体
（機体ごとにホームの名前が違うため）では置換が起きず、
**中身が同じでも `--check` が必ず食い違います。**

## 捕まえないもの

- `~/.claude` の**存在を前提にしてよい道具**。`issue_scan.py` は Claude のセッション記録
  （`~/.claude/projects`）を読むのが目的そのものなので、`ALLOW` に理由つきで宣言する
- 参照先の中身が正しいか。ここは「repo の外を実行時に読んでいないか」だけ
- 確かめた方法: `--self-test`（4つの形それぞれが仕込みで落ちること・案内文で落ちないこと）
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない

ROOT = Path(__file__).resolve().parent.parent

#: `~/.claude` を読むのが目的そのものの道具。**理由を書く。**
ALLOW = {
    "issue_scan.py": "Claude のセッション記録（~/.claude/projects）を読むのが目的そのもの。"
                     "この道具は案件の関門からは呼ばれず、/harness-issues だけが使う",
}


def _is_home_call(node: ast.AST) -> bool:
    """`Path.home()` の呼び出しか。"""
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "home"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "Path")


def _joins_claude(node: ast.AST) -> bool:
    """`Path.home() / ".claude"` のように、HOME からパスを組んでいるか。"""
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return False
    # 左辺を辿って Path.home() に行き着くか
    left = node.left
    while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
        left = left.left
    if not _is_home_call(left):
        return False
    # 右辺のどこかに ".claude" があるか
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == ".claude":
            return True
    return False


def _home_in_replace(node: ast.AST) -> bool:
    """`.replace(str(Path.home()), ...)` のように HOME を文字列置換に使っているか。"""
    if not (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "replace"):
        return False
    for arg in node.args:
        for sub in ast.walk(arg):
            if _is_home_call(sub):
                return True
    return False


def scan_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError) as e:
        return [f"{path.name}: 読めません（{e}）"]
    lines = text.splitlines()

    def allowed(lineno: int) -> bool:
        """その行に `# reachability-ok: 理由` があるか。**理由の無い印は認めない。**"""
        if not (1 <= lineno <= len(lines)):
            return False
        line = lines[lineno - 1]
        if "reachability-ok:" not in line:
            return False
        return bool(line.split("reachability-ok:", 1)[1].strip())

    out = []
    for node in ast.walk(tree):
        if allowed(getattr(node, "lineno", 0)):
            continue
        if _joins_claude(node):
            out.append(f"{path.name}:{node.lineno} `~/.claude` を実行時に組んでいる"
                       f"（CI と他人のクローンには無い）")
        elif _home_in_replace(node):
            out.append(f"{path.name}:{node.lineno} HOME を文字列置換に使っている"
                       f"（ホームが違う機体で置換が起きず、生成物に絶対パスが残る）")
    return out


#: 歩く場所。**共有層は tools/ だけではない**（2026-09-06 に build/ が増えた）。
#: 階層を作ったら網も広げる——広げないと、新しい道具はこの検査の外で緑になる
SCAN_DIRS = ("tools", "engine", "shims")


def scan(root: Path) -> tuple[list[str], int]:
    """戻り: (見つけた問題, 見たファイル数)。**0件は「見ていない」と区別する。**"""
    problems, n = [], 0
    for d in SCAN_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.glob("*.py")):
            if p.name in ("reachability_check.py",):
                continue
            n += 1
            found = scan_file(p)
            if found and p.name in ALLOW:
                continue
            problems.extend(found)
    return problems, n


def self_test() -> int:
    import tempfile
    ok = True
    CASES = [
        ("落とす: HOME からパスを組む",
         'from pathlib import Path\nX = Path.home() / ".claude" / "skills" / "a.json"\n', True),
        ("落とす: 深い入れ子でも見つける",
         'from pathlib import Path\nX = (Path.home() / ".claude" / "s" / "r" / "a.md")\n', True),
        ("落とす: HOME を文字列置換に使う",
         'from pathlib import Path\ns = str(p).replace(str(Path.home()), "~")\n', True),
        ("落とさない: 案内文の中の ~/.claude",
         'MSG = "source ~/.claude/.env を実行してください"\n', False),
        ("落とさない: HOME を単独で使う",
         'from pathlib import Path\nX = Path.home() / "dev" / "design-harness"\n', False),
        ("落とさない: replace に HOME を渡さない",
         's = str(p).replace("\\\\", "/")\n', False),
        ("落とさない: 理由つきの印がある",
         'from pathlib import Path\n'
         's = str(p).replace(str(Path.home()), "~")  # reachability-ok: repo 相対の後のフォールバック\n', False),
        ("落とす: 印はあるが理由が無い",
         'from pathlib import Path\n'
         's = str(p).replace(str(Path.home()), "~")  # reachability-ok:\n', True),
    ]
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "tools"
        d.mkdir(parents=True)
        for name, src, want in CASES:
            f = d / "x.py"
            f.write_text(src, encoding="utf-8")
            got = bool(scan_file(f))
            if got != want:
                print(f"self-test NG: {name} → 検出 {got}（期待 {want}）")
                ok = False

        # **違反したときに 1 で落ちるか**を、main() ごと通して確かめる。
        # 検出できても終了コードが 0 なら、段としては何も止めない
        # （変異試験がこの経路の未試験を指摘した。2026-09-06）
        import contextlib, io
        f = d / "x.py"
        f.write_text('from pathlib import Path\nX = Path.home() / ".claude" / "a"\n',
                     encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            rc = main(["--root", str(Path(td))])
        if rc != 1:
            print(f"self-test NG: 違反があるのに exit {rc}（期待 1）"); ok = False
        if "~/.claude" not in buf.getvalue():
            print("self-test NG: どこが悪いかを出していない"); ok = False

        # 違反が無ければ 0 で通る
        f.write_text('X = 1\n', encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(["--root", str(Path(td))])
        if rc != 0:
            print(f"self-test NG: 違反が無いのに exit {rc}（期待 0）"); ok = False
    if ok:
        print("self-test: OK")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    problems, seen = scan(args.root)
    if seen == 0:
        print(f"道具が1本も見つかりません（{args.root} の "
              f"{' / '.join(SCAN_DIRS)}）。**0件は「読んでいない」ではなく「見ていない」です。**",
              file=sys.stderr)
        return 2
    if problems:
        print("共有層の道具が `~/.claude` を実行時に読んでいます。", file=sys.stderr)
        print("**CI と他人のクローンには無いので、落ちるか、黙って緑になります。**",
              file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\n  正本を repo の中へ移し、skills 側にはポインタだけ置いてください"
              "（2026-09-06 の gate/production-gate.md・vocab/figma-properties.json が例）。\n"
              "  読むのが目的そのものなら ALLOW に理由つきで宣言してください。",
              file=sys.stderr)
        return 1
    print(f"到達性: 道具 {seen} 本（{' / '.join(SCAN_DIRS)}）。"
          f"`~/.claude` を実行時に読むものはありません（宣言つきの例外 {len(ALLOW)} 本）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
