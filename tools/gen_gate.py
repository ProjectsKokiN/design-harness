#!/usr/bin/env python3
"""関門の合格条件を、正本の散文から生成する（2026-09-04 新設・#12）。

## なぜ要るか

`production-gate.md` は「**条件は全部満たす。1つでも欠けたらリリースに進まない**」
と書いているが、**それを確かめる機械がなかった。**

FlashEnglish の実害（2026-09-03）: 条件5（再現性の判定）と条件7（実装網羅）を
**誰も測っていなかった。** 条件7 は「飛ばしました。条件7 が誰も見ていません」と
自分で言いながら CI は緑、条件5 は**段そのものが無く**、飛ばした記録すら残らない。
気づいたのは偶然（リリース前に人が条件を1つずつ手で回したとき）。

判定していたのは人（AI）で、AI は CI の緑を見て「満たしている」と報告できる。

## 正本がリポジトリの外にある問題

条件の正本は `~/.claude/skills/mobile-harness-setup/references/production-gate.md`
で、**どの案件のリポジトリからも、GitHub Actions からも見えない。** 手で写せば
古くなる（このハーネスが繰り返し潰してきた病そのもの）。

だから **生成して、指紋で鮮度を見る**。gen_rules.py と同じ処方。

- 生成: 正本を読んで `gate/conditions.json` を書く（正本の sha256 を同梱）
- `--check`: 生成し直して1バイトでも違えば落ちる
- 正本が**読めない機体**（CI）では、`--check` は指紋の照合を飛ばし、
  「生成物があること」だけを見る。**飛ばしたことは必ず出力に書く**

## 何を生成しないか

- 条件の中身（散文）は写さない。**番号・見出し・測る道具の名前だけ**を持つ。
  中身が要るなら正本を読む（DESIGN.md と同じ「参照であって複製ではない」）
- 廃止した条件は載せない。番号が飛ぶのは正しい状態

## 使い方

    python3 tools/gen_gate.py --source <production-gate.md> --out gate/conditions.json
    python3 tools/gen_gate.py --check --out gate/conditions.json

確かめた方法: --self-test（条件を1行足したら --check が落ちること）
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

DEFAULT_SOURCE = (Path.home() / ".claude" / "skills" / "mobile-harness-setup"
                  / "references" / "production-gate.md")
DEFAULT_OUT = Path("gate/conditions.json")

#: 合格条件の表の行。`| 7 | **実装網羅 …** | `impl_coverage_check.py` … |`
ROW_RX = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|")

#: 見出しの強調・脚注を落として、条件の短い名前だけにする
TRIM_RX = re.compile(r"\*\*|`")


def parse(text):
    """正本の表から、生きている条件だけを拾う。

    表の行は `| # | 条件 | 何で測るか | 落ちたときの意味 |`。
    見出し行（`| # |`）と区切り行（`|---|`）は落とす。
    """
    out = {}
    for line in text.splitlines():
        m = ROW_RX.match(line)
        if not m:
            continue
        num, title, measured = m.group(1), m.group(2), m.group(3)
        # 条件の見出しは「**鮮度** — 書き出しが…」の形。em ダッシュの前だけ使う
        short = TRIM_RX.sub("", title).split("—")[0].split(" - ")[0].strip()
        tools = sorted(set(re.findall(r"([a-z_]+\.py|design/verify\.sh)", measured)))
        out[num] = {"見出し": short, "測る道具": tools}
    return out


def build(source):
    text = source.read_text(encoding="utf-8")
    conds = parse(text)
    if not conds:
        return None, "正本から条件の表を読めませんでした（表の形が変わった？）"
    return {
        "$生成元": str(source).replace(str(Path.home()), "~"),
        "$生成元の指紋": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "$手で書き換えない": "tools/gen_gate.py が生成します",
        "生きている条件": conds,
    }, None


def dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="関門の合格条件を正本から生成する")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="生成し直して、ディスク上の出力と違えば落ちる")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.source.exists():
        if not args.check:
            print(f"正本がありません: {args.source}", file=sys.stderr)
            return 2
        # CI にはこの正本が無い。**飛ばしたことを必ず書く**（黙って緑にしない）
        if not args.out.exists():
            print(f"関門の条件がありません: {args.out}\n"
                  f"  正本（{args.source}）も読めないので、条件が何件かを"
                  f"確かめる手段がありません。", file=sys.stderr)
            return 2
        try:
            got = json.loads(args.out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"関門の条件が読めません: {args.out}: {e}", file=sys.stderr)
            return 2
        n = len(got.get("生きている条件", {}))
        print(f"関門の条件 {n} 件（生成物）。正本がこの機体に無いので"
              f"**鮮度は見ていません**（指紋: {got.get('$生成元の指紋')}）。")
        return 0

    data, err = build(args.source)
    if err:
        print(err, file=sys.stderr)
        return 2
    text = dump(data)

    if args.check:
        if not args.out.exists():
            print(f"関門の条件がありません: {args.out}\n"
                  f"  --check を外して生成してください。", file=sys.stderr)
            return 1
        if args.out.read_text(encoding="utf-8") != text:
            print(f"関門の条件が正本とズレています: {args.out}\n"
                  f"  正本（{args.source}）が直されたのに生成し直していません。\n"
                  f"  `python3 tools/gen_gate.py` で作り直してください。",
                  file=sys.stderr)
            return 1
        print(f"関門の条件 {len(data['生きている条件'])} 件、正本と一致します。")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    nums = " / ".join(f"条件{k}" for k in data["生きている条件"])
    print(f"{args.out} を生成しました（{nums}）")
    return 0


def self_test():
    import tempfile
    ok = True
    src_text = """# 本番リリースの合格条件

## 合格条件（3つ）

| # | 条件 | 何で測るか | 落ちたときの意味 |
|---|---|---|---|
| 1 | 禁止パターン 0 | `design/verify.sh`（統合入口） | 違反が残っている |
| 5 | **再現性の判定に穴が無い** — ○△× があり × は 0 | `tools/check_render_gaps.py` | 描画で別物 |
| 7 | **実装網羅 100%** — 全部実装 | `impl_coverage_check.py` | 独断で省いた |

**番号が飛んでいるのは廃止したためです。**
"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        src = root / "gate.md"
        out = root / "gate" / "conditions.json"
        src.write_text(src_text, encoding="utf-8")
        argv = ["--source", str(src), "--out", str(out)]

        if main(argv) != 0:
            print("self-test NG: 生成が落ちた"); ok = False
        got = json.loads(out.read_text(encoding="utf-8"))
        conds = got["生きている条件"]
        if sorted(conds) != ["1", "5", "7"]:
            print(f"self-test NG: 条件の番号が違う: {sorted(conds)}"); ok = False
        if conds["7"]["見出し"] != "実装網羅 100%":
            print(f"self-test NG: 見出しが取れていない: {conds['7']['見出し']}")
            ok = False
        if conds["5"]["測る道具"] != ["check_render_gaps.py"]:
            print(f"self-test NG: 道具が取れていない: {conds['5']['測る道具']}")
            ok = False
        if main(argv + ["--check"]) != 0:
            print("self-test NG: 生成直後なのに --check が落ちた"); ok = False

        # 正本に条件を1行足したら --check が落ちる（これが本体）
        src.write_text(src_text.replace(
            "**番号が飛んでいる",
            "| 9 | **見本と相互作用** — 形と数 | `tree_test_check.py` | 木が違う |\n\n"
            "**番号が飛んでいる"), encoding="utf-8")
        if main(argv + ["--check"]) != 1:
            print("self-test NG: 正本が増えたのに --check が落ちなかった"); ok = False
        if main(argv) != 0 or main(argv + ["--check"]) != 0:
            print("self-test NG: 作り直しても --check が通らない"); ok = False
        if sorted(json.loads(out.read_text(encoding="utf-8"))["生きている条件"]) != \
                ["1", "5", "7", "9"]:
            print("self-test NG: 足した条件が入っていない"); ok = False

        # 条件を1つ削っても落ちる（減るほうが危ない。黙って測らなくなる）
        src.write_text(src_text.replace(
            "| 5 | **再現性の判定に穴が無い** — ○△× があり × は 0 | "
            "`tools/check_render_gaps.py` | 描画で別物 |\n", ""), encoding="utf-8")
        if main(argv + ["--check"]) != 1:
            print("self-test NG: 正本が減ったのに --check が落ちなかった"); ok = False
        src.write_text(src_text, encoding="utf-8")
        main(argv)

        # 生成物を消したら落ちる
        out.unlink()
        if main(argv + ["--check"]) != 1:
            print("self-test NG: 生成物が無いのに --check が落ちなかった"); ok = False

        # 正本が無い機体（CI）: 生成物があれば通すが、飛ばしたと必ず書く
        main(argv)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--source", str(root / "no-such.md"), "--out", str(out),
                       "--check"])
        if rc != 0:
            print(f"self-test NG: 正本の無い機体で落ちた（{rc}）"); ok = False
        if "鮮度は見ていません" not in buf.getvalue():
            print("self-test NG: 鮮度を見ていないことを書いていない"); ok = False

        # 正本も生成物も無ければ落ちる（何件かを確かめる手段が無い）
        out.unlink()
        if main(["--source", str(root / "no-such.md"), "--out", str(out),
                 "--check"]) != 2:
            print("self-test NG: 正本も生成物も無いのに通した"); ok = False

        # 正本はあるが表が読めない（表の形が変わった）→ 2。違反の 1 と区別する
        src.write_text("# 表の無い正本\n\nただの文章です。\n", encoding="utf-8")
        if main(argv) != 2:
            print("self-test NG: 表の無い正本で 2 で止まらなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
