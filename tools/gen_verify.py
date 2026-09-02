#!/usr/bin/env python3
"""生成し直して差分が出たら落ちる（べき等性の検査）。**共有の正本**。

2026-09-02 に aub-familywalk の `design/gen/verify.py` から回収した。
それまで案件ごとの複製で、**3案件のうち1件しか台帳（generators.json）を
持っていなかった**（aub 9本＋台帳／flash-compose 8本・台帳なし／planttalk 0本）。

## なぜ要るか

**生成器を通さず生成物を手で直すと、ここで止まる。** 手直しが黙って残ると、
次に生成し直したときに消えて原因が分からなくなる。

さらに `impl_coverage_check` の `generated_by` は、それまで
**ディレクトリが在るかしか見ていなかった**——`design/gen/` という空の
ディレクトリがあるだけでトークン網羅の検査が全部消えていた。確かめて
いなかったのは3つ:

  1. 生成器が**回されたか**
  2. 生成物が**いまの書き出しと一致するか**
  3. 生成器の**入力が書き出しか**（`gen_input_check.py` の担当）

この道具が 1 と 2 を見る。

## 台帳（generators.json）が唯一の正

    {
      "generators": [
        {"file": "gen_colors.py", "out": "lib/theme/tokens/colors.g.dart",
         "in": "variables.json", "idempotent": true,
         "covers": ["variables:ColorPrimitive", "variables:ColorSemantic"]}
      ]
    }

**ここに手書きで並べない。** aub の 2026-08-29 の作り直し前、一覧が3か所にあって
足し忘れが起きた。台帳とディスクの**両方向**を突き合わせる:

  - 台帳に載っていない生成器 → **載せないと誰も回さず、生成物だけが古くなる**
  - 台帳にあるのに実在しない生成器 → 綴りか削除

## この検査が捕まえないもの

- 生成器のロジックの誤り（べき等でも間違った値を作れる）。それは
  `token_coverage_check` と照合テストの領域
- 生成器の入力が書き出しかどうか（`gen_input_check.py` の担当）
- 確かめた方法: --self-test（生成物を手で直したら落ちること・生成器が
  何も書かなくても落ちること・台帳とディスクのズレで落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/gen_verify.py [--manifest design/gen/generators.json]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成し直して差分が出たら落ちる")
    ap.add_argument("--manifest", type=Path,
                    default=Path("design/gen/generators.json"))
    ap.add_argument("--root", type=Path,
                    help="案件のルート（既定: 台帳の親の親の親）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.manifest.exists():
        print(f"生成器の台帳がありません: {args.manifest}\n"
              f"  **生成器の一覧が1か所に無い状態です。** 一覧が複数あると、"
              f"足し忘れた生成器を誰も回さず、生成物だけが古くなります。\n"
              f"  書式は design/harness/tools/gen_verify.py の冒頭を参照してください。",
              file=sys.stderr)
        return 2

    here = args.manifest.resolve().parent
    root = args.root.resolve() if args.root else here.parent.parent
    try:
        gens = json.loads(args.manifest.read_text(encoding="utf-8"))["generators"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"台帳が読めません: {args.manifest}: {e}", file=sys.stderr)
        return 2

    if not gens:
        print(f"台帳に生成器が1つもありません: {args.manifest}\n"
              f"  **『差分なし』は『何も生成していない』という意味になります。**",
              file=sys.stderr)
        return 1

    on_disk = {p.name for p in here.glob("gen_*.py")} | {p.name for p in here.glob("gen_*.dart")} \
        | {p.name for p in here.glob("gen_*.mjs")} | {p.name for p in here.glob("gen_*.js")}
    listed = {g["file"] for g in gens}
    if on_disk - listed:
        print(f"[NG] 台帳に載っていない生成器があります: {sorted(on_disk - listed)}\n"
              f"  {args.manifest} に足してください。"
              f"**載せないと誰も回さず、生成物だけが古くなります。**", file=sys.stderr)
        return 1
    if listed - on_disk:
        print(f"[NG] 台帳にあるのに実在しない生成器: {sorted(listed - on_disk)}",
              file=sys.stderr)
        return 1

    failed, checked = [], 0
    for g in gens:
        out = root / g["out"]
        before = out.read_text(encoding="utf-8") if out.exists() else None
        cmd = _command(here / g["file"])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        if r.returncode != 0:
            print(f'[NG] {g["file"]} が落ちました:\n{r.stdout}{r.stderr}', file=sys.stderr)
            failed.append(g["file"])
            continue
        after = out.read_text(encoding="utf-8") if out.exists() else None

        # **生成器が何も書かなくても落とす**（2026-09-02 に塞いだ穴）。
        # それまで `before is None` を「新規」として通していたため、
        # 生成器が黙って何も書かなくても検査が通っていた
        if after is None:
            print(f'[NG] {g["file"]} を回しても {g["out"]} ができません。'
                  f'**生成器が何も書いていません。**', file=sys.stderr)
            failed.append(g["out"])
            continue
        checked += 1
        if g.get("idempotent", True) is False:
            print(f'  変わってよい: {g["out"]}')
        elif before is None:
            print(f'  新規: {g["out"]}')
        elif before != after:
            print(f'[NG] {g["out"]} が生成し直しで変わりました。'
                  f'**生成器を通さず手で直しています。**', file=sys.stderr)
            failed.append(g["out"])
        else:
            print(f'  変化なし: {g["out"]}')

    if failed:
        print(f"\n検査: 落ちました（{len(failed)} 件）", file=sys.stderr)
        return 1
    print(f"\n検査: 通った（生成物 {checked} ファイルが変わらない）")
    return 0


def _command(path):
    """拡張子から回し方を決める。Flutter では Dart の生成器が自然。"""
    if path.suffix == ".py":
        return [sys.executable, str(path)]
    if path.suffix == ".dart":
        return ["dart", "run", str(path)]
    if path.suffix in (".mjs", ".js"):
        return ["node", str(path)]
    return [str(path)]


def self_test():
    import tempfile, os
    ok = True

    def check(cond, msg):
        nonlocal ok
        if not cond:
            print(f"self-test NG: {msg}"); ok = False

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gen = root / "design" / "gen"
        gen.mkdir(parents=True)
        (root / "out").mkdir()

        def writer(name, body):
            (gen / name).write_text(body, encoding="utf-8")

        def manifest(entries):
            (gen / "generators.json").write_text(
                json.dumps({"generators": entries}), encoding="utf-8")
            return ["--manifest", str(gen / "generators.json"), "--root", str(root)]

        writer("gen_a.py", "from pathlib import Path\n"
                           "Path('out/a.txt').write_text('X')\n")
        argv = manifest([{"file": "gen_a.py", "out": "out/a.txt"}])
        check(main(argv) == 0, "べき等なのに落ちた")

        # 生成物を手で直したら落ちる（この道具の本題）
        (root / "out" / "a.txt").write_text("手で直した", encoding="utf-8")
        check(main(argv) == 1, "手で直したのに落ちなかった")

        # **生成器が何も書かなくても落ちる**（2026-09-02 に塞いだ穴）
        writer("gen_a.py", "pass\n")
        (root / "out" / "a.txt").unlink()
        check(main(argv) == 1, "生成器が何も書かないのに通した")

        writer("gen_a.py", "from pathlib import Path\n"
                           "Path('out/a.txt').write_text('X')\n")
        check(main(argv) == 0, "戻したのに落ちた")

        # 台帳に載っていない生成器
        writer("gen_b.py", "pass\n")
        check(main(argv) == 1, "台帳に載っていない生成器を通した")
        (gen / "gen_b.py").unlink()

        # 台帳にあるのに実在しない
        check(main(manifest([{"file": "gen_a.py", "out": "out/a.txt"},
                             {"file": "gen_missing.py", "out": "out/b.txt"}])) == 1,
              "実在しない生成器を通した")

        # 台帳が空（空振り）
        check(main(manifest([])) == 1, "台帳が空なのに通した")

        # 生成器が落ちる
        argv = manifest([{"file": "gen_a.py", "out": "out/a.txt"}])
        writer("gen_a.py", "raise SystemExit(3)\n")
        check(main(argv) == 1, "生成器が落ちたのに通した")

        # 台帳が無い
        (gen / "generators.json").unlink()
        check(main(argv) == 2, "台帳が無いのに通した")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
