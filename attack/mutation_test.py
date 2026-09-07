#!/usr/bin/env python3
"""変異試験。各道具の「落とす」経路を1つずつ潰して、自己検査が赤くなるかを見る（2026-09-05・#72）。

## なぜ要るか

2026-09-05 の実測: 38本の道具の `return 1` / `return 2`（違反を見つけたときの帰り道）185本を
1本ずつ `return 0` に書き換えて self-test を回したところ、**88本（47%）が素通りした。**
自己検査があっても、その経路を試していなければ「壊しても気づかない」。
**「落ちることを見てから採用する」を、記憶ではなく機械にする。**

計測の誤りも記録する: `return True` は Python では `1` と等しく、`return 1` の置換に
当たらないので素通りに見える（10本）。ここでは AST の定数が bool のものを除く。

## 使い方

    python3 attack/mutation_test.py            # 理由の無い素通りがあれば落ちる
    python3 attack/mutation_test.py --list     # 全部の結果を出す
    python3 attack/mutation_test.py --allowed  # いま許している印を一覧する（走査しない）
    python3 attack/mutation_test.py --self-test

## 素通りを許す2つの形

| 形 | どこに書くか | 何のため |
|---|---|---|
| **行の印** | その `return` の行に `# mutation-ok: 理由` | git や GitHub の失敗など、**その1本だけ**試験しにくい経路 |
| **型** | `attack/mutation-allow.json` の `$patterns` | 「設定が無い・壊れている」の停止（`return 2`）。`attack/broken_input_test.py` が全道具に一律で当てているので、道具ごとの self-test に同じ試験を並べない |

**理由の無い印は落とす**（`tools/swallow_check.py` の `swallow-ok:`・
`tools/reachability_check.py` の `reachability-ok:` と同じ書式・同じ扱い）。

### なぜ行番号をやめたか（2026-09-06・issue #79）

除外は `attack/mutation-allow.json` に **`ファイル名:行番号`** で書いていた。
`machine_scope.py` に引数を1つ足しただけで 487 → 505 へ動き、除外が効かなくなった。

移すときに**全部を測り直したら、11件のうち効いていたのは3件だけだった**。
残り8件は `$patterns` と重複していて要らず、うち **2件は行が `return` ですらない化石**
（`shared_check.py:218` は文字列の続きの行を指していた）。**赤くならずに死んでいた。**

行に書けば印はコードと一緒に動くのでずれない。**要らなくなった印も機械が見つける**
（下の「化石の印」）。手で書いた一覧が古くなる、という #66 / #73 と同じ族だった。
"""

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW = ROOT / "attack" / "mutation-allow.json"


def selftest_ok(f, cwd):
    try:
        r = subprocess.run([sys.executable, str(f), "--self-test"],
                           capture_output=True, text=True, timeout=240, cwd=cwd, errors="replace")
    except subprocess.TimeoutExpired:
        return None
    o = r.stdout + r.stderr
    return ("self-test: OK" in o) or ("件パス" in o and "NG" not in o)


#: 除外の印。**行に書く**（`attack/mutation-allow.json` の行番号をやめた・#79）。
#: 書式は tools/swallow_check.py の `swallow-ok:` と
#: tools/reachability_check.py の `reachability-ok:` にそろえる
MARK = "mutation-ok:"


def mark_reason(line):
    """その行の `# mutation-ok: 理由` の理由。**印が無ければ None、理由が空なら ""。**"""
    if MARK not in line:
        return None
    return line.split(MARK, 1)[1].strip()


def judge(orig, ctx, patterns):
    """その素通りを何で許すか（純粋関数）。戻り: (判定, 理由)

    判定は次の5つ。**許すのは頭の3つだけ。**

    | 判定 | 意味 |
    |---|---|
    | `印` | その行に理由つきの `# mutation-ok:` がある |
    | `印（型と重複）` | 印があるが、型でも許されている。**印は要らない**（注意を出す） |
    | `型` | `$patterns` に当たる停止（`return 2`）|
    | `理由なし` | 何も無い。self-test がその経路を見ていない |
    | `印に理由なし` | `# mutation-ok:` はあるが理由が書いていない |

    **型で許すのは停止（`return 2`）だけ。** 違反（`return 1`）の帰り道は必ずその道具の
    self-test で見る（近くの案内文に当たって違反の経路まで許し、`exporter_check:243` を
    一度隠した）。
    """
    reason = mark_reason(orig)
    by_pattern = "return 2" in orig and any(rx.search(ctx) for rx, _ in patterns)
    if reason is None:
        return ("型" if by_pattern else "理由なし", "")
    if not reason:
        return ("印に理由なし", "")
    return ("印（型と重複）" if by_pattern else "印", reason)


ALLOWING = ("印", "印（型と重複）", "型")


def fossil_marks(lines, survived):
    """**要らなくなった印**（純粋関数）。印はあるのに、その行が素通りではない。

    その行が落とす経路でないか、self-test がすでに見ている、のどちらか。
    **行番号の宣言が赤くならずに死んだのと同じ形**なので、印でも見る
    （2026-09-06 の実測: 行番号の宣言 11 件のうち 8 件がこれだった）。
    """
    return [(i, line.strip()[:70]) for i, line in enumerate(lines, 1)
            if MARK in line and i not in survived]


def _is_tool(src) -> bool:
    """**単体で合否を出す道具か**（`main()` を持つか）。部品なら False。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return True          # 読めないものは道具として扱い、別の段に落とさせる
    return any(isinstance(n, ast.FunctionDef) and n.name == "main"
               for n in tree.body)


def failure_returns(src):
    """self_test の外にある `return 1` / `return 2`（bool は除く）の行番号。"""
    tree = ast.parse(src)
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name.startswith("self_test"):
            skip |= set(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    out = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                and type(n.value.value) is int and n.value.value in (1, 2)
                and n.lineno not in skip):
            out.append(n.lineno)
    return sorted(set(out))


def load_patterns(allow):
    """`$patterns` を読む。**行番号の宣言が残っていたら受け付けない**（#79）。"""
    stale = [k for k in allow if not k.startswith("$")]
    if stale:
        print(f"{ALLOW.name} に**行番号での宣言**が残っています（{len(stale)}件）:",
              file=sys.stderr)
        for k in stale:
            print(f"  {k}", file=sys.stderr)
        print("  除外は**その行に `# mutation-ok: 理由`** を書きます（2026-09-06・#79）。\n"
              "  行番号はコードが動くとずれ、**赤くならずに死にます**"
              "（実測: 11件中8件が要らないか化石でした）。", file=sys.stderr)
        return None
    return [(re.compile(x["match"]), x["why"]) for x in allow.get("$patterns", [])]


def scanned_files(root=None):
    """変異と印の一覧が**同じ範囲**を見るための、唯一の走査規則。

    **2か所で別々に範囲を書くと必ずずれる。** 実際に 2026-09-06、変異のほうは
    `build/` まで広げたのに印の一覧は `tools/` だけを見ていて、`build/` に印を
    書いても一覧に出ない（＝理由が人の目に触れない）状態になっていた。

    **2026-09-07 に `build/` は machine-relay（非公開）へ移した**ので、範囲は
    `tools/` に戻っている。**階層を増やしたら、ここも増やすこと。**
    """
    base = ROOT if root is None else root
    out = sorted((base / "tools").glob("*.py"))
    return out


def list_allowed():
    """いま許している印を一覧する（走査しない）。**一覧は持たず、コードから導く。**"""
    rows, no_reason = [], []
    for f in scanned_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if MARK not in line:
                continue
            why = mark_reason(line)
            (rows if why else no_reason).append((f.name, i, why, line.strip()[:60]))
    print(f"行の印（# {MARK}）: {len(rows)} 件")
    for name, i, why, code in rows:
        print(f"  {name}:{i}  {code}\n      理由: {why}")
    if no_reason:
        print(f"**理由の無い印: {len(no_reason)} 件**", file=sys.stderr)
        for name, i, _, code in no_reason:
            print(f"  {name}:{i}  {code}", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    listing = "--list" in argv
    allow = json.loads(ALLOW.read_text(encoding="utf-8")) if ALLOW.exists() else {}
    patterns = load_patterns(allow)
    if patterns is None:
        return 2
    if "--allowed" in argv:
        return list_allowed()
    work = Path(tempfile.mkdtemp())
    try:
        for d in ("tools", "engine", "gate", "rules", "ci", "fingerprint", "exporters",
                  "build"):
            if (ROOT / d).exists():
                shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__"))
        for f in ("README.md", "DESIGN.md"):
            if (ROOT / f).exists():
                shutil.copy(ROOT / f, work / f)
        # **飛ばした道具を必ず名前で出す。** 出さないと「素通り 0」が
        # 「見た結果 0」なのか「見なかったから 0」なのか分からない（分母が黙って縮む形）
        survivors, measured, paths_total, fossils, skipped = [], 0, 0, [], []
        # **階層を作ったら網も広げる**——広げないと、新しい道具は測られないまま緑になる
        # （2026-09-06 に build/ が増えて広げた。2026-09-07 に machine-relay へ移して戻した）
        parts = []
        for f in scanned_files(work):
            src = f.read_text(encoding="utf-8")
            # **部品は測る対象ではありません。** `main()` を持たないものは
            # 単体で合否を出さない共有の部品で、**self-test が無いのは正しい状態**です。
            # ここを分けないと「まだ測れていない穴」と混ざり、
            # **数を見ても何をすればよいか分からなくなります**（2026-09-07）。
            # **一覧を宣言していません。`main()` の有無から導いています。**
            if not _is_tool(src):
                parts.append(f.name)
                continue
            if '"--self-test"' not in src and "--selftest" not in src:
                skipped.append((f.name, "`--self-test` の旗が無い"))
                continue
            targets = failure_returns(src)
            if not targets:
                skipped.append((f.name, "落とす帰り道（return 1 / 2）が無い"))
                continue
            if selftest_ok(f, work) is not True:
                # 基準で通らない道具は測れない（別の段が見る）。**黙って消さない**
                skipped.append((f.name, "**いま self-test が通らない**（測れない）"))
                continue
            measured += 1
            lines = src.splitlines(keepends=True)
            survived_here = set()
            for ln in targets:
                paths_total += 1
                orig = lines[ln - 1]
                lines[ln - 1] = orig.replace("return 1", "return 0").replace("return 2", "return 0")
                f.write_text("".join(lines), encoding="utf-8")
                r = selftest_ok(f, work)
                lines[ln - 1] = orig
                if r is not False:
                    survived_here.add(ln)
                    ctx = "".join(lines[max(0, ln - 7):ln])   # 長い案内文の帰り道も拾う
                    verdict, why = judge(orig, ctx, patterns)
                    survivors.append((f"{f.name}:{ln}", orig.strip()[:70], verdict, why))
            f.write_text(src, encoding="utf-8")
            for i, code in fossil_marks(lines, survived_here):
                fossils.append((f"{f.name}:{i}", code))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    unlisted = [s for s in survivors if s[2] not in ALLOWING]
    dup = [s for s in survivors if s[2] == "印（型と重複）"]
    by_mark = len([s for s in survivors if s[2].startswith("印")])
    if listing:
        for key, code, verdict, _ in survivors:
            mark = verdict if verdict in ALLOWING else f"**{verdict}**"
            print(f"  {mark} {key}  {code}")
    print(f"mutation_test: 道具 {measured} 本 / 落とす経路 {paths_total} 本 / 素通り {len(survivors)} 本"
          f"（行の印 {by_mark} / 型 {len(survivors) - by_mark - len(unlisted)} / "
          f"**理由なし {len(unlisted)}**）")
    for key, code, _, _ in dup:
        print(f"注意: {key} の印は要りません（型で許されています）: {code}")
    if parts:
        print(f"部品（`main()` を持たない共有の部品。**測る対象ではありません**）: "
              f"{len(parts)} 本 — {', '.join(sorted(parts))}")
    if skipped:
        print(f"測れなかった道具: {len(skipped)} 本"
              f"（**「素通り 0」は、この {len(skipped)} 本については「見ていない」という意味です**）")
        for name, why in skipped:
            print(f"  {name}  {why}")
    if fossils:
        print(f"要らなくなった印があります（{len(fossils)}件）。"
              f"**その行は落とす経路ではないか、self-test がすでに見ています:**", file=sys.stderr)
        for key, code in fossils:
            print(f"  {key}  {code}", file=sys.stderr)
        print("  → 印を消してください。**残すと、行番号の宣言と同じで黙って死にます**",
              file=sys.stderr)
    if unlisted:
        print("理由の無い素通り（self-test がその経路を見ていない）:", file=sys.stderr)
        for key, code, verdict, _ in unlisted:
            print(f"  {key}  {code}  （{verdict}）", file=sys.stderr)
        print(f"  → その経路を通す self-test を足すか、**その行に "
              f"`# {MARK} 理由`** を書く", file=sys.stderr)
    return 1 if (unlisted or fossils) else 0


def self_test():
    """**判定そのもの**を見る（走査は回さない）。

    2026-09-06、除外を行番号から行の印へ移したとき、この道具は自分の判定を
    1行も試験していませんでした。**判定が壊れると、素通りを全部「許可」と読んで黙ります。**
    """
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    pats = [(re.compile("ありません|読めません"), "入力が壊れているときの停止")]

    # ── 印の読み方 ──────────────────────────────────────────
    check(mark_reason("        return 1\n") is None, "印が無い行を印ありと読んだ")
    check(mark_reason(f"        return 1  # {MARK} git の失敗\n") == "git の失敗",
          "印の理由を読めない")
    check(mark_reason(f"        return 1  # {MARK}\n") == "", "理由の無い印を空文字で返さない")
    check(mark_reason(f"        return 1  # {MARK}   \n") == "",
          "空白だけの理由を理由ありと読んだ")

    # ── 判定 ────────────────────────────────────────────────
    check(judge("        return 1\n", "", pats) == ("理由なし", ""), "何も無い素通りを許した")
    v, why = judge(f"        return 1  # {MARK} 環境の経路\n", "", pats)
    check((v, why) == ("印", "環境の経路"), f"理由つきの印を許さない（{v}）")
    check(judge(f"        return 1  # {MARK}\n", "", pats)[0] == "印に理由なし",
          "**理由の無い印を許した**")
    # 型で許すのは停止（return 2）だけ
    ctx = '        print("設定がありません", file=sys.stderr)\n'
    check(judge("        return 2\n", ctx, pats)[0] == "型", "型で許すべき停止を許さない")
    check(judge("        return 1\n", ctx, pats)[0] == "理由なし",
          "**違反（return 1）を型で許した**（案内文に当たって隠れる形）")
    check(judge("        return 2\n", "", pats)[0] == "理由なし",
          "型に当たらない停止を許した")
    check(judge(f"        return 2  # {MARK} 理由\n", ctx, pats)[0] == "印（型と重複）",
          "型と重なる印を重複と言わない")
    check(all(v in ALLOWING for v in ("印", "印（型と重複）", "型")), "許す判定の一覧が違う")
    check(not any(v in ALLOWING for v in ("理由なし", "印に理由なし")), "落とす判定を許している")

    # ── 変異させても印は残る（この道具の前提）─────────────────
    line = f"        return 1  # {MARK} git rm の失敗\n"
    mutated = line.replace("return 1", "return 0").replace("return 2", "return 0")
    check(mark_reason(mutated) == "git rm の失敗",
          "**書き換えたら印が消えた**（判定は書き換え前の行で行う前提が崩れている）")

    # ── 落とす経路の拾い方（`return True` は 1 と等しいので除く）──
    src = ("def f():\n    return 1\n"
           "def g():\n    return True\n"
           "def h():\n    return 2\n"
           "def self_test():\n    return 1\n")
    check(failure_returns(src) == [2, 6], f"落とす経路の拾い方が違う: {failure_returns(src)}")

    # ── 要らなくなった印（化石）────────────────────────────
    L = ["def f():\n", f"    return 1  # {MARK} 環境の経路\n",
         f"    return 2  # {MARK} もう見ている\n", "    return 0\n"]
    check(fossil_marks(L, {2}) == [(3, f"return 2  # {MARK} もう見ている")],
          f"**要らない印を見つけられない**: {fossil_marks(L, {2})}")
    check(fossil_marks(L, {2, 3}) == [], "効いている印を化石と言った")
    check(fossil_marks(["    return 1\n"], set()) == [], "印の無い行を化石と言った")

    # ── 行番号の宣言は受け付けない（#79）────────────────────
    check(load_patterns({"$patterns": []}) == [], "正しい宣言を受け付けない")
    check(load_patterns({"pin_check.py:147": "理由"}) is None,
          "**行番号での宣言を受け付けた**")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
