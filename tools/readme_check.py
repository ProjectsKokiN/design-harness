#!/usr/bin/env python3
"""README の道具の一覧が、ディスクと合っているかを見る（2026-09-02 新設）。

## なぜ要るか

**README は人が読む地図です。** 古くなると「その道具は無い」と誤解されます。

実測（2026-09-02）: 道具27本のうち **5本が README の表に無かった**
（`check_render_gaps` / `ci_path_check` / `impl_coverage_check` /
`page_scope_check` / `pin_check`）。

これはこのリポジトリが繰り返し潰してきた**「手で保守する一覧が古くなる」**の、
ハーネス自身での再発です。同じ日に、CI の self-test の一覧も5本のまま
道具が22本に増えており、**17本が一度も走っていませんでした。**

| 一覧 | 直した日 |
|---|---|
| 生成器の一覧（3か所に散っていた） | 2026-08-29（`generators.json` が唯一の正） |
| ルールの段の値（正規表現に手写し） | 2026-08-30（`gen_rules.py` が生成） |
| **CI の self-test の一覧** | **2026-09-02**（`tools/*.py` を回す） |
| **README の道具の一覧** | **2026-09-02**（この検査） |

## この検査が捕まえないもの

- **説明が正しいか**（名前が載っているかしか見ない）
- 道具以外の記述の古さ
- 確かめた方法: --self-test（載っていない道具があれば落ちること）

## 使い方

    python3 tools/readme_check.py [--readme README.md] [--tools tools]
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent

#: 一覧に載せなくてよいもの（入口・共有の部品）。理由を書く。
SKIP = {
    "__init__.py": "パッケージの印",
}


#: 発火ログを書いている場所
LOG_WRITER = "note"


def log_keys(engine_path):
    """`note()` が書くキーを、実装から読み取る（2026-09-04・#39）。

    **表を手で書き写す層にしない。** 書式は実装の中にしかなく、読むたびに
    キーを当てて外していた（`rule_id` を想定して None が返る、など）。
    """
    import ast
    try:
        tree = ast.parse(engine_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == LOG_WRITER:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    keys = [k.value for k in sub.keys
                            if isinstance(k, ast.Constant)
                            and isinstance(k.value, str)]
                    if len(keys) >= 3:
                        return keys
    return None


def check_log_schema(readme, engine_path):
    """発火ログの項目表が、実装の書くキーを全部載せているか。"""
    keys = log_keys(engine_path)
    if keys is None:
        print(f"発火ログを書いている場所が読めません: {engine_path}",
              file=sys.stderr)
        return 2
    text = readme.read_text(encoding="utf-8")
    if "発火ログ" not in text:
        print("README に発火ログの項目表がありません。\n"
              "  **書式が実装の中にしか無い状態です。**", file=sys.stderr)
        return 1
    missing = [k for k in keys if f"`{k}`" not in text]
    if missing:
        print(f"発火ログの項目表に載っていないキーがあります: {missing}\n"
              f"  {engine_path} の {LOG_WRITER}() は {keys} を書きます。\n"
              f"  **表が古いと、読む人はキーを当てて外します。**", file=sys.stderr)
        return 1
    print(f"発火ログの項目表: {len(keys)} キーすべてが載っています。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="README の一覧がディスクと合っているか")
    ap.add_argument("--readme", type=Path, default=HERE.parent / "README.md")
    ap.add_argument("--tools", type=Path, default=HERE)
    ap.add_argument("--log-schema", action="store_true",
                    help="発火ログの項目表が実装と合っているかを見る")
    ap.add_argument("--engine", type=Path,
                    default=Path(__file__).resolve().parent.parent
                    / "engine" / "design_check.py")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.log_schema:
        return check_log_schema(args.readme, args.engine)

    if not args.readme.exists():
        print(f"README がありません: {args.readme}", file=sys.stderr)
        return 2

    text = args.readme.read_text(encoding="utf-8")
    on_disk = {p.name for p in sorted(args.tools.glob("*.py"))
               if p.name not in SKIP}
    if not on_disk:
        print(f"道具が1本もありません: {args.tools}\n"
              f"  **『全部載っている』は『何も見ていない』という意味になります。**",
              file=sys.stderr)
        return 2

    # `tools/x.py` でも **`tools/x.py`** でも拾う
    # 名前に数字が入る道具（`_utf8.py`）を拾えるようにする。
    # `[a-z_]+` だけだと**載せても永久に「未掲載」と出る**（2026-09-04 実測）
    listed = set(re.findall(r"(?:tools|engine|shims)/([a-z_][a-z0-9_]*\.py)", text))
    missing = sorted(on_disk - listed)
    ghosts = sorted(n for n in listed - on_disk
                    if not (args.tools.parent / "engine" / n).exists()
                    and not (args.tools.parent / "shims" / n).exists())

    print(f"README の一覧: ディスク {len(on_disk)}本 / 載っている {len(on_disk & listed)}本")
    rc = 0
    if missing:
        print(f"\n**README に載っていない道具が {len(missing)} 本あります:**",
              file=sys.stderr)
        for n in missing:
            print(f"  - {n}", file=sys.stderr)
        print("  README は人が読む地図です。載っていないと「その道具は無い」と"
              "誤解されます。", file=sys.stderr)
        rc = 1
    if ghosts:
        print(f"\n**README にあるのに実在しない道具が {len(ghosts)} 本あります:**",
              file=sys.stderr)
        for n in ghosts:
            print(f"  - {n}", file=sys.stderr)
        rc = 1
    if rc == 0:
        print("  OK: 一覧とディスクが合っています。")
    return rc


def self_test():
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        tools = base / "tools"
        tools.mkdir()
        (tools / "a.py").write_text("", encoding="utf-8")
        (tools / "b.py").write_text("", encoding="utf-8")
        rm = base / "README.md"
        argv = ["--readme", str(rm), "--tools", str(tools)]

        rm.write_text("`tools/a.py` と `tools/b.py`", encoding="utf-8")
        check(main(argv) == 0, "全部載っているのに落ちた")

        # **載っていない道具があれば落ちる**（この検査の本題）
        rm.write_text("`tools/a.py` だけ", encoding="utf-8")
        check(main(argv) == 1, "載っていない道具があるのに通した")

        # **名前に数字が入る道具**（`_utf8.py`）を載せたら通ること。
        # 拾えないと、載せても永久に「未掲載」と出て**直しようがない**
        (tools / "_utf8.py").write_text("", encoding="utf-8")
        rm.write_text("`tools/a.py` `tools/b.py` `tools/_utf8.py`", encoding="utf-8")
        check(main(argv) == 0, "数字の入る名前を載せても未掲載と出た")
        (tools / "_utf8.py").unlink()

        # 実在しない道具が載っていれば落ちる
        rm.write_text("`tools/a.py` `tools/b.py` `tools/ghost.py`", encoding="utf-8")
        check(main(argv) == 1, "実在しない道具を通した")

        # 道具が0本＝空振り
        for f in tools.glob("*.py"):
            f.unlink()
        rm.write_text("なにもない", encoding="utf-8")
        check(main(argv) == 2, "道具0本なのに通した")

        # README が無い
        rm.unlink()
        check(main(argv) == 2, "README が無いのに通した")

    # ─── #39: 発火ログの項目表 ────────────────────────────────
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td2:
        d = Path(td2)
        eng = d / "engine.py"
        eng.write_text(
            "def note(rule, lineno, kind):\n"
            "    observations.append({\n"
            "        'ts': 1, 'rule': 2, 'severity': 3, 'kind': 4,\n"
            "    })\n", encoding="utf-8")
        check(log_keys(eng) == ["ts", "rule", "severity", "kind"],
              f"実装からキーを読めない: {log_keys(eng)}")
        rm2 = d / "README.md"
        rm2.write_text("## 発火ログ\n`ts` `rule` `severity` `kind`\n",
                       encoding="utf-8")
        check(check_log_schema(rm2, eng) == 0, "全部載っているのに落ちた")
        # **キーが増えたら落ちる**（表を手で書き写す層にしない）
        eng.write_text(eng.read_text(encoding="utf-8").replace(
            "'kind': 4,", "'kind': 4, 'source': 5,"), encoding="utf-8")
        check(check_log_schema(rm2, eng) == 1, "増えたキーを見逃した")
        # 表そのものが無ければ落ちる
        rm2.write_text("なにもない\n", encoding="utf-8")
        check(check_log_schema(rm2, eng) == 1, "表が無いのに通した")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
