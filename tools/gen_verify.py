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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def _restore(path, before):
    """実体を元に戻す。**この道具は作業ツリーを変えない**（#5）。"""
    try:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)
    except OSError:
        pass


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
        # **探索の規則を文言に書く**（2026-09-04・#33）。
        # qnd-database で `gen-tokens.py`（ハイフン）を載せて落ち続けたが、
        # 「アンダースコアで始める」はコードを読むまで分からなかった。
        missing = sorted(listed - on_disk)
        hint = ""
        for name in missing:
            if (here / name).exists():
                hint = (f"\n  **{name} は実在します。** ただしこの道具が探すのは"
                        f" `gen_*.py` / `gen_*.dart` / `gen_*.mjs` / `gen_*.js` で、"
                        f"\n  **アンダースコアで始まる名前**だけです"
                        f"（`gen-tokens.py` のようなハイフンは拾いません）。"
                        f"\n  生成器の名前を `gen_` で始めてください。")
                break
        print(f"[NG] 台帳にあるのに実在しない生成器: {missing}\n"
              f"  この道具が探す形: `gen_*.py` / `gen_*.dart` / `gen_*.mjs` /"
              f" `gen_*.js`（{here} の中）{hint}", file=sys.stderr)
        return 1

    failed, checked = [], 0
    for g in gens:
        out = root / g["out"]
        # **バイトで読む**（2026-09-04・#2）。テキストで読んでいたので、PNG などの
        # binary を出す生成器は台帳に載せると UnicodeDecodeError で落ちた。
        # **載せられないものは、べき等の検査から漏れる。**
        before = out.read_bytes() if out.exists() else None
        cmd = _command(here / g["file"])
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
        if r.returncode != 0:
            print(f'[NG] {g["file"]} が落ちました:\n{r.stdout}{r.stderr}', file=sys.stderr)
            _restore(out, before)
            failed.append(g["file"])
            continue
        after = out.read_bytes() if out.exists() else None
        # **実体を元に戻す**（2026-09-04・#5）。この道具は「生成し直すと変わるか」を
        # 見るだけで、**作業ツリーを変えてよいわけではない。**
        # 実害（Windows・2026-09-02）: 機体をまたいで同じバイト列を出さない
        # 生成器があり、`verify.sh` を回すだけで作業ツリーが汚れた。
        # しかも NG の文言が「**生成器を通さず手で直しています**」と
        # **原因を誤って断定する**（手では直していない）。
        _restore(out, before)

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
            print(f'[NG] {g["out"]} が生成し直しで変わりました。\n'
                  f'  次のどちらかです。**原因はこの道具には分かりません。**\n'
                  f'    - 生成器を通さず手で直した\n'
                  f'    - 生成器が**機体をまたいで同じバイト列を出さない**'
                  f'（改行・並び順・時刻・浮動小数）\n'
                  f'  前者なら生成器を回して差分をコミットし、後者なら生成器を'
                  f'直してください\n'
                  f'  （出力が機体で変わってよいなら台帳に "idempotent": false）。',
                  file=sys.stderr)
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

    # ─── #2 binary / #5 実体を戻す / #33 名前の規則 ────────────────
    import tempfile as _tf
    import contextlib as _ctx
    import io as _io
    with _tf.TemporaryDirectory() as td:
        root = Path(td)
        gen = root / "design" / "gen"
        gen.mkdir(parents=True)
        (root / "assets").mkdir()
        png = root / "assets" / "icon.png"
        PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(200, 256))
        # **binary を出す生成器**（テキストで読むと UnicodeDecodeError）
        (gen / "gen_png.py").write_text(
            "import pathlib\n"
            f"pathlib.Path({str(png)!r}).write_bytes({PNG!r})\n", encoding="utf-8")
        man = gen / "generators.json"
        man.write_text(json.dumps({"generators": [
            {"file": "gen_png.py", "out": "assets/icon.png"}]}), encoding="utf-8")
        png.write_bytes(PNG)

        def call():
            b = _io.StringIO()
            with _ctx.redirect_stdout(b), _ctx.redirect_stderr(b):
                rc = main(["--manifest", str(man), "--root", str(root)])
            return rc, b.getvalue()

        rc, out = call()
        check(rc == 0, f"binary の生成物で落ちた: {out[:300]}")

        # **実体を戻す**（機体差で毎回変わる生成器）
        (gen / "gen_png.py").write_text(
            "import pathlib, random\n"
            f"pathlib.Path({str(png)!r}).write_bytes(bytes([random.randrange(256)]*8))\n",
            encoding="utf-8")
        keep = png.read_bytes()
        rc, out = call()
        check(rc == 1, "毎回変わる生成物で落ちなかった")
        check(png.read_bytes() == keep,
              "**作業ツリーが汚れた**（生成物を元に戻していない）")
        check("原因はこの道具には分かりません" in out,
              "NG の文言が原因を断定している")

        # **生成器が落ちても実体を戻す**
        (gen / "gen_png.py").write_text(
            "import pathlib, sys\n"
            f"pathlib.Path({str(png)!r}).write_bytes(b'こわれた'.decode().encode())\n"
            "sys.exit(1)\n", encoding="utf-8")
        rc, out = call()
        check(rc == 1, "落ちる生成器で通った")
        check(png.read_bytes() == keep, "落ちたときに実体を戻していない")

        # **名前の規則を文言に書く**（#33）
        (gen / "gen_png.py").unlink()
        (gen / "gen-tokens.py").write_text("pass\n", encoding="utf-8")
        man.write_text(json.dumps({"generators": [
            {"file": "gen-tokens.py", "out": "assets/icon.png"}]}), encoding="utf-8")
        rc, out = call()
        check(rc == 1, "ハイフンの生成器で通った")
        check("アンダースコアで始まる名前" in out,
              f"名前の規則を書いていない: {out[:250]}")
        check("gen-tokens.py は実在します" in out, "実在することを言っていない")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
