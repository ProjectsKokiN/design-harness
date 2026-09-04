#!/usr/bin/env python3
"""画面のノード木が全部書き出されているかを見る（2026-09-04 新設・#14）。

## なぜ要るか

`production-gate.md` にこう書いてあります。

> **画面固有の値の照合先は `figma/frames.json`**（画面のノード木の機械書き出し）。
> これが無い案件は記録層を消せない（廃止の前提条件）

**この前提条件を機械で測る段がありませんでした。** 散文でしか書かれていないので、

- `frames.json` が**在るかどうか**しか読めない
- **中身が画面の木かどうか**は書いていない

flash-compose には `frames.json` が在ります（3件）。**前提条件を満たしている
ように見えます。** ところが中身は「部品にならない枠」（`bottomNavigationFrame` /
`header` / `footer`）で、**画面のノード木ではありません。**

結果、手書きの記録層 `design/values/layout.json` は 63 件 assert したまま残り、
**そのうち置き換えられるのは 9 件だけ**でした。残り 54 件はほぼ全部が画面固有の値
（`body.margin` / `Illusts.*` / `QuizScreen.*` / `MyPage.*`）で、**照合先が
存在しませんでした。** 「記録層を廃止する」という 2026-08-29 の決定は、画面の値に
ついては**実行不可能**でした。決定から5日、誰も気づいていません。

**「在る」と「足りている」の差です。**

## 見るもの

    python3 tools/screen_export_check.py --config design/screens-check.json

| 見るもの | 落ちる条件 |
|---|---|
| 索引（`screens.json`）の画面が全部書き出されているか | 1枚でも欠けたら |
| 木になっているか | 行が `MIN_ROWS` 未満の画面があれば（1行は木ではない） |
| 宣言の件数と合うか | `$meta.declared` と実際の件数が違えば |
| **画面ごとの書き出しが全画面を覆っているか** | `perScreenExports` の1つでも画面を取りこぼしていれば（**理由つきで宣言すれば通る**） |
| **宣言した**記録層の値が増えていないか | `expectedHandwritten` を上回れば（ラチェット） |

## 捕まえないもの

- 書き出しの中身が Figma と合っているか → 鮮度の段（`figma_freshness.py`）
- 記録層の値が正しいか → この道具は**件数だけ**を見る
- 画面ごとの書き出しの**中身**。ここは「その画面を見たか」だけを見る
- **どの値が assert されているか。** 数えるのは `recordLayer` に**宣言した
  ファイルの葉の数**で、テストが実際に読んでいる数ではない。生成物
  （`figma-layout.json` など）を宣言に入れると数が跳ねるので、
  **手で書いたファイルだけを宣言する**
- 確かめた方法: --self-test（画面を1枚落とすと落ちること）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: これ未満の行数しかない画面は「木」ではない。1行は枠が在るだけ
MIN_ROWS = 2


def load(path, what):
    if not path.exists():
        return None, f"{what}がありません: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as e:
        return None, f"{what}が読めません: {path}: {e}"


def count_values(obj):
    """記録層の葉の数。**宣言したファイルの中身の量**であって、
    テストが assert している数ではない（そこまでは機械で追えない）。"""
    if isinstance(obj, dict):
        return sum(count_values(v) for k, v in obj.items() if not k.startswith("$"))
    if isinstance(obj, list):
        return sum(count_values(v) for v in obj)
    return 1


def check_per_screen(base, conf, index):
    """画面ごとの書き出しが、全画面を覆っているかを見る（2026-09-04・#48）。

    実害（aub-familywalk・2026-09-04）: `export_instance_overrides.js` が
    **画面フレームの直下のインスタンスだけ**を見ており、ダイアログのように
    1段深いところにあるボタンが**4画面すべてで0行**だった。

    結果、`ButtonsGroup` の中のボタンが何個で、それぞれ何色かが**どの書き出しにも
    存在せず、実装が何でも通る**状態だった。「リセットするのボタンの文字が
    赤くなっていない」はこれ。

    器を再帰にするのは器側の直し。**こちらが本命**で、器を直しても
    次に別の入れ子が出たらまた静かに漏れるので、**件数で押さえる**。
    その器は `$meta` に `scanned: 140 / declared: 20` を持っていた——
    **31画面のうち11画面ぶんが入っていないことが、数として出力に出ていた。**
    突き合わせる検査が無かっただけ。
    """
    want = len(index)
    ids = {s.get("node") or s.get("id") for s in index}
    errs = []
    spec = conf.get("perScreenExports", [])
    # 一覧で書けば「全画面ぶん要る」。**部分的でよいものは理由を書かせる**
    # （`screen_text_exclusions.json` は例外だけを並べるので全画面ぶんは要らない）。
    # 理由が無いまま部分的なのと、意図して部分的なのを**区別できる形にする**
    items = spec.items() if isinstance(spec, dict) else [(r, None) for r in spec]
    for rel, decl in items:
        if isinstance(decl, dict) and str(decl.get("why", "")).strip():
            continue
        f = base / rel
        doc, e = load(f, "画面ごとの書き出し")
        if e:
            errs.append(f"  {e}\n    **この面は誰も見ていません。**")
            continue
        meta = doc.get("$meta") or {}
        rows = {k for k in doc if not k.startswith("$")}
        if len(rows) == 1 and isinstance(doc.get(next(iter(rows))), dict):
            rows = {k for k in doc[next(iter(rows))] if not k.startswith("$")}
        covered = rows & ids if ids else rows
        dec = meta.get("declared")
        if isinstance(dec, int) and dec != want:
            errs.append(f"  {rel}: 宣言が {dec} で、画面は {want} 枚です。\n"
                        f"    **{want - dec} 画面ぶんが書き出しに入っていません。**"
                        f"（数は出力に出ていますが、突き合わせていませんでした）")
        elif ids and len(covered) < want:
            miss = sorted(ids - rows)
            errs.append(f"  {rel}: {len(covered)}/{want} 画面しか入っていません。\n"
                        f"    抜け: {' / '.join(miss[:8])}"
                        + ("…" if len(miss) > 8 else "") +
                        f"\n    **その画面の中身は、どの検査からも見えません。**")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description="画面の書き出しが足りているかを見る")
    ap.add_argument("--config", type=Path, default=Path("design/screens-check.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    conf, err = load(args.config, "設定")
    if err:
        print(f"{err}\n"
              f"  画面の書き出しが足りているかを**誰も見ていない状態です。**\n"
              f"  screens / frames のパスを書いた設定を置いてください。",
              file=sys.stderr)
        return 2
    base = args.root.resolve()
    screens_doc, e1 = load(base / conf.get("screens", "design/screens.json"), "画面の索引")
    frames_doc, e2 = load(base / conf.get("frames", "design/figma/frames.json"),
                          "画面の書き出し")
    for e in (e1, e2):
        if e:
            print(f"{e}\n  **記録層はまだ消せません**（照合先がありません）。",
                  file=sys.stderr)
            return 2

    index = screens_doc.get("screens", screens_doc)
    if isinstance(index, dict):
        index = [{"node": k, **(v if isinstance(v, dict) else {})}
                 for k, v in index.items() if not k.startswith("$")]
    frames = {k: v for k, v in (frames_doc.get("frames") or {}).items()
              if not k.startswith("$")}

    errs = []
    if not index:
        print("画面の索引が空です。**画面が1枚も宣言されていません。**", file=sys.stderr)
        return 2
    if not frames:
        errs.append(f"  画面の書き出しが空です（索引は {len(index)} 枚）。\n"
                    f"    **frames.json が『在る』だけで、画面の木がありません。**\n"
                    f"    exporters/export_frames.js を案件に置いて回してください。")

    missing, thin = [], []
    for s in index:
        node = s.get("node") or s.get("id")
        name = s.get("name") or node
        got = frames.get(node)
        if got is None:
            missing.append(f"{name}（{node}）")
            continue
        rows = got.get("rows") if isinstance(got, dict) else got
        if not isinstance(rows, list) or len(rows) < MIN_ROWS:
            thin.append(f"{name}（{node}・{len(rows) if isinstance(rows, list) else 0}行）")

    if missing:
        errs.append(f"  書き出されていない画面が {len(missing)} 枚あります:\n"
                    f"    " + " / ".join(missing[:10]) +
                    ("\n    …" if len(missing) > 10 else "") +
                    f"\n    **この画面の値には照合先がありません。**")
    if thin:
        errs.append(f"  木になっていない画面が {len(thin)} 枚あります:\n"
                    f"    " + " / ".join(thin[:10]) +
                    f"\n    行が {MIN_ROWS} 未満は「枠が在る」だけで木ではありません。")

    errs += check_per_screen(base, conf, index)

    declared = (frames_doc.get("$meta") or {}).get("declared")
    if isinstance(declared, int) and declared != len(frames):
        errs.append(f"  書き出しの宣言（declared: {declared}）と実際の件数"
                    f"（{len(frames)}）が違います。**取り直しが途中で切れています。**")

    # 手書きの記録層はラチェットで見る。**減る方向にしか動かせない**
    hand, hand_files = 0, []
    for rel in conf.get("recordLayer", []):
        f = base / rel
        if not f.exists():
            continue
        doc, e = load(f, "記録層")
        if e:
            continue
        n = count_values(doc)
        hand += n
        hand_files.append(f"{rel}: {n}件")
    exp = conf.get("expectedHandwritten")
    warns = []
    if isinstance(exp, int):
        if hand > exp:
            errs.append(f"  宣言した記録層の値が {hand} 件で、宣言（{exp}）を"
                        f"上回りました。**自己採点の層が増えています。**\n"
                        f"    " + " / ".join(hand_files))
        elif hand < exp:
            warns.append(f"宣言した記録層の値が {hand} 件に減りました。"
                         f"{args.config.name} の expectedHandwritten を下げてください。")

    for w in warns:
        print(f"注意: {w}")
    if errs:
        print("画面の書き出しが足りていません（記録層はまだ消せません）:",
              file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    tail = (f" / 宣言した記録層の値 {hand}件" if hand_files
            else " / 記録層の宣言なし")
    print(f"画面の書き出し: 索引 {len(index)} 枚をすべて木で持っています{tail}。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma").mkdir(parents=True)
        (root / "design" / "values").mkdir()
        sp = root / "design" / "screens.json"
        fp = root / "design" / "figma" / "frames.json"
        cp = root / "design" / "screens-check.json"
        vp = root / "design" / "values" / "layout.json"
        sp.write_text(json.dumps({"screens": [
            {"node": "1:1", "name": "ALBUM"}, {"node": "2:2", "name": "CAMERA"}]}),
            encoding="utf-8")
        vp.write_text(json.dumps({"body": {"margin": 20}, "Illusts": {"gap": 8}}),
                      encoding="utf-8")
        cp.write_text(json.dumps({"screens": "design/screens.json",
                                  "frames": "design/figma/frames.json"}),
                      encoding="utf-8")
        argv = ["--config", str(cp), "--root", str(root)]

        def run(frames, conf=None):
            fp.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
            if conf is not None:
                cp.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv)
            return rc, buf.getvalue()

        full = {"$meta": {"declared": 2},
                "frames": {"1:1": {"name": "ALBUM", "rows": ["0|a|FRAME", "1|b|TEXT"]},
                           "2:2": {"name": "CAMERA", "rows": ["0|c|FRAME", "1|d|TEXT"]}}}
        rc, out = run(full)
        if rc != 0:
            print(f"self-test NG: そろっているのに落ちた（{rc}）\n   {out[:300]}"); ok = False

        # **画面を1枚落とすと落ちる**（これが本体）
        one = json.loads(json.dumps(full))
        del one["frames"]["2:2"]
        one["$meta"]["declared"] = 1
        rc, out = run(one)
        if rc != 1 or "CAMERA" not in out or "照合先がありません" not in out:
            print(f"self-test NG: 画面が欠けたのに落ちなかった（{rc}）"); ok = False

        # 「在る」だけで木になっていない（flash-compose の形）
        thin = json.loads(json.dumps(full))
        thin["frames"]["2:2"]["rows"] = ["0|c|FRAME"]
        rc, out = run(thin)
        if rc != 1 or "木になっていない" not in out:
            print(f"self-test NG: 1行だけの画面を通した（{rc}）"); ok = False

        # 宣言と件数の食い違い（取り直しが途中で切れた）
        cut = json.loads(json.dumps(full))
        cut["$meta"]["declared"] = 5
        rc, out = run(cut)
        if rc != 1 or "途中で切れて" not in out:
            print(f"self-test NG: 宣言とのズレを通した（{rc}）"); ok = False

        # frames.json が空（在るだけ）
        rc, out = run({"$meta": {}, "frames": {}})
        if rc != 1 or "画面の木がありません" not in out:
            print(f"self-test NG: 空の書き出しを通した（{rc}）"); ok = False

        # 記録層のラチェット
        base_conf = {"screens": "design/screens.json",
                     "frames": "design/figma/frames.json",
                     "recordLayer": ["design/values/layout.json"]}
        rc, out = run(full, {**base_conf, "expectedHandwritten": 2})
        if rc != 0 or "宣言した記録層の値 2件" not in out:
            print(f"self-test NG: 宣言どおりの記録層で落ちた（{rc}）\n   {out[:300]}")
            ok = False
        rc, out = run(full, {**base_conf, "expectedHandwritten": 1})
        if rc != 1 or "自己採点の層が増えています" not in out:
            print(f"self-test NG: 記録層が増えたのに落ちなかった（{rc}）"); ok = False
        rc, out = run(full, {**base_conf, "expectedHandwritten": 9})
        if rc != 0 or "下げてください" not in out:
            print(f"self-test NG: 記録層が減った注意が出ない（{rc}）"); ok = False

        # ─── 画面ごとの書き出しの網羅（#48）────────────────────────
        ov = root / "design" / "figma" / "overrides.json"
        pc = {**base_conf, "perScreenExports": ["design/figma/overrides.json"]}
        ov.write_text(json.dumps({"$meta": {"declared": 2},
                                  "1:1": {"rows": ["x"]}, "2:2": {"rows": ["y"]}}),
                      encoding="utf-8")
        rc, out = run(full, pc)
        if rc != 0:
            print(f"self-test NG: 全画面そろっているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        # **宣言が画面数より小さければ落ちる**（実害そのものの形）
        ov.write_text(json.dumps({"$meta": {"declared": 1},
                                  "1:1": {"rows": ["x"]}}), encoding="utf-8")
        rc, out = run(full, pc)
        if rc != 1 or "画面ぶんが書き出しに入っていません" not in out:
            print(f"self-test NG: 宣言の食い違いを通した（{rc}）"); ok = False
        # 宣言が無くても、画面の取りこぼしを名指しする
        ov.write_text(json.dumps({"1:1": {"rows": ["x"]}}), encoding="utf-8")
        rc, out = run(full, pc)
        if rc != 1 or "2:2" not in out:
            print(f"self-test NG: 抜けた画面を名指ししていない（{rc}）"); ok = False
        # **理由つきで宣言すれば、部分的でも通る**（例外だけを並べる書き出し）
        ov.write_text(json.dumps({"1:1": {"rows": ["x"]}}), encoding="utf-8")
        rc, _ = run(full, {**base_conf, "perScreenExports": {
            "design/figma/overrides.json": {"why": "例外だけを並べる"}}})
        if rc != 0:
            print(f"self-test NG: 理由つきの宣言があるのに落ちた（{rc}）"); ok = False
        rc, _ = run(full, {**base_conf, "perScreenExports": {
            "design/figma/overrides.json": {"why": "  "}}})
        if rc != 1:
            print(f"self-test NG: 理由が空の宣言を通した（{rc}）"); ok = False

        # 書き出しそのものが無ければ落ちる
        ov.unlink()
        rc, out = run(full, pc)
        if rc != 1 or "誰も見ていません" not in out:
            print(f"self-test NG: 書き出しが無いのを通した（{rc}）"); ok = False
        cp.write_text(json.dumps(base_conf, ensure_ascii=False), encoding="utf-8")

        # 設定も書き出しも無いときは落ちる（黙って通さない）
        fp.unlink()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = main(argv)
        if rc != 2 or "記録層はまだ消せません" not in buf.getvalue():
            print(f"self-test NG: 書き出しが無いのに通した（{rc}）"); ok = False
        cp.unlink()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            if main(argv) != 2:
                print("self-test NG: 設定が無いのに通した"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
