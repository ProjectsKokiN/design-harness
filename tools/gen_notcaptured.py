#!/usr/bin/env python3
"""書き出しが「読まなかったプロパティ」を宣言する（2026-09-04 新設・#21）。

## なぜ要るか

FlashEnglish の一連の作業で、AI が Figma を読み違えた **7件**のうち **3件が
同じ根**でした。

> **書き出しに入っていない情報を、入っていないと知らずに推測で埋めた。**

| 何が書き出しに無かったか | 何をしたか | 誰が見つけたか |
|---|---|---|
| `itemReverseZIndex`（キャンバススタッキング） | `children` の並びだけで重なり順を判断し、**「Figma が壊れている」と誤報**した（実際は正しかった） | ユーザー |
| 辺ごとの線の太さ（書き出しは色しか持たない） | 下線だけのタブを**四角い箱で囲んだ** | ゴールデン差分 |
| アイコンの寸法 | `Buttons/L` だから 36 だろうと当てた。**Figma は 32** | ユーザー |

**3件とも「読み直して気づいた」ものはありません。** 外から数字が合わないと
分かって初めて見つかっています。**無い情報は、無いように見えるからです。**

`$meta.excluded` は**部品まるごとの除外**にしか使えず、プロパティ単位の欠落を
書く場所がありませんでした。だから消費側からは

- 「Figma に無い」
- 「Figma に在るが書き出し器が拾っていない」

が**区別できません**。区別できないので、前者だと思って推測で埋めます。

## なぜ「畳んだ書き出しの展開の間違い」はすぐ捕まったか

同じ一連で、展開を2回まちがえました（`Images` が 8 のところ 16 に膨らんだ／
`Lists/Text` の6行が3通りの名前に潰れた）。**どちらもすぐ捕まりました。**
書き出しが正解の数を宣言しているからです（`declared`）。

**同じ仕掛けを「プロパティの網羅」にも作る**、というのがこの道具です。

## 何をするか

一覧（`figma-properties.json`・6,764 ノードの実測で確定済み）と、**書き出し器が
実際に読んでいるキー**の差を取って `design/figma/notcaptured.json` を生成します。

    python3 tools/gen_notcaptured.py --config design/notcaptured.json
    python3 tools/gen_notcaptured.py --config design/notcaptured.json --check

**手で書きません。** 手で書くと、書き出し器を直したときに宣言だけ残ります。

読んでいるキーは器のソースから拾います（`n.itemReverseZIndex` / `'itemSpacing'` /
`bn(n, 'fills')` のような出方を全部見る）。**器を直せば宣言が動き、
`--check` が落ちます。**

## 消費側からの問い方

    import gen_io
    gen_io.absent('itemReverseZIndex')
    # → 'キャンバススタッキング。**children の並びだけで重なり順を判断しないこと**'
    # 読めているキーなら None

**問える形になっていれば、AI は問います。** いまは問う先が無いので推測します。

## 捕まえないもの

- 読んでいるキーの**値が正しいか**。ここは「読んだか読まないか」だけ
- 一覧に載っていないプロパティ。一覧そのものの網羅は `figma-properties.json` の
  `$meta` にある棚卸しが正
- 確かめた方法: --self-test（器からキーを1つ消すと --check が落ちること）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

DEFAULT_LIST = (Path.home() / ".claude" / "skills" / "mobile-implement-ui"
                / "references" / "figma-properties.json")

#: 器のソースからキーを拾う出方。`n.foo` / `'foo'` / `"foo"` / `foo:`
KEY_RX = re.compile(r"""(?:\.([a-zA-Z][A-Za-z0-9_]*)\b|['"]([a-zA-Z][A-Za-z0-9_]*)['"])""")


def wanted(list_path):
    """一覧に載っているプロパティ名を、群ごとに返す。"""
    doc = json.loads(list_path.read_text(encoding="utf-8"))
    out = {}
    for group, body in doc.items():
        if group.startswith("$") or not isinstance(body, dict):
            continue
        for key, meta in body.items():
            if key in ("note",) or not isinstance(meta, dict):
                continue
            # 「strokeTopWeight/strokeRightWeight/…」のように束ねた行もある
            for k in re.split(r"\s*/\s*", key):
                out[k] = {"群": group,
                          "意味": meta.get("figma") or meta.get("note") or "",
                          "注意": meta.get("note", "")}
    return out


def captured(exporter_paths):
    """器のソースが実際に読んでいるキー。"""
    got = set()
    for p in exporter_paths:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for a, b in KEY_RX.findall(text):
            got.add(a or b)
    return got


def build(list_path, exporters):
    want = wanted(list_path)
    got = captured(exporters)
    missing = {k: v for k, v in sorted(want.items()) if k not in got}
    return {
        "$手で書き換えない": "tools/gen_notcaptured.py が生成します",
        "$生成元": str(list_path).replace(str(Path.home()), "~"),
        "$読んだ器": sorted(str(p) for p in exporters),
        "declared": {"一覧のプロパティ": len(want),
                     "読めているプロパティ": len(want) - len(missing),
                     "読めていないプロパティ": len(missing)},
        "notCaptured": {
            k: (v["意味"] + ("／" + v["注意"] if v["注意"] and v["注意"] != v["意味"]
                             else "")) or "（一覧に説明なし）"
            for k, v in missing.items()},
    }


def dump(d):
    return json.dumps(d, ensure_ascii=False, indent=2) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="読まなかったプロパティを宣言する")
    ap.add_argument("--config", type=Path, default=Path("design/notcaptured.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f'  例: {{"list": "~/…/figma-properties.json",\n'
              f'        "exporters": ["design/figma/exporters/export_frames.js"],\n'
              f'        "out": "design/figma/notcaptured.json"}}\n'
              f"  **書き出しが何を読んでいないかを、誰も宣言していない状態です。**",
              file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.root.resolve()
    lp = Path(str(conf.get("list", DEFAULT_LIST)).replace("~", str(Path.home())))
    if not lp.is_absolute():
        lp = base / lp
    if not lp.exists():
        print(f"プロパティの一覧がありません: {lp}", file=sys.stderr)
        return 2
    exporters = [base / p for p in conf.get("exporters", [])]
    if not exporters:
        print("器が1つも宣言されていません（exporters が空）。\n"
              "  **この状態の「読めていない0件」は嘘になります。**", file=sys.stderr)
        return 2
    found = [p for p in exporters if p.exists()]
    if not found:
        print(f"宣言された器が1つも実在しません: "
              f"{', '.join(str(p) for p in exporters)}", file=sys.stderr)
        return 2

    out = base / conf.get("out", "design/figma/notcaptured.json")
    data = build(lp, exporters)
    text = dump(data)

    if args.check:
        if not out.exists():
            print(f"宣言がありません: {out}\n  --check を外して生成してください。",
                  file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(f"読めていないプロパティの宣言がズレています: {out}\n"
                  f"  器か一覧が変わったのに生成し直していません。\n"
                  f"  `python3 tools/gen_notcaptured.py --config "
                  f"{args.config}` で作り直してください。", file=sys.stderr)
            return 1
        d = data["declared"]
        print(f"読めていないプロパティ {d['読めていないプロパティ']} 件"
              f"（一覧 {d['一覧のプロパティ']} 件中）。宣言と一致します。")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    d = data["declared"]
    print(f"{out} を生成しました"
          f"（一覧 {d['一覧のプロパティ']} 件 / 読めている {d['読めているプロパティ']} 件 "
          f"/ **読めていない {d['読めていないプロパティ']} 件**）")
    return 0


def self_test():
    import tempfile
    ok = True
    LIST = {"$meta": {"unit": "x"},
            "layout": {"layoutMode": {"figma": "Auto layout の方向"},
                       "itemSpacing": {"figma": "すき間"},
                       "itemReverseZIndex": {"figma": "キャンバススタッキング",
                                             "note": "children の並びだけで"
                                                     "重なり順を判断しないこと"}},
            "stroke": {"strokeTopWeight/strokeBottomWeight": {"figma": "辺ごとの太さ"}}}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma" / "exporters").mkdir(parents=True)
        lp = root / "list.json"
        ex = root / "design" / "figma" / "exporters" / "e.js"
        cp = root / "design" / "notcaptured.json"
        out = root / "design" / "figma" / "notcaptured.json"
        lp.write_text(json.dumps(LIST, ensure_ascii=False), encoding="utf-8")
        cp.write_text(json.dumps({"list": str(lp),
                                  "exporters": ["design/figma/exporters/e.js"],
                                  "out": "design/figma/notcaptured.json"}),
                      encoding="utf-8")
        argv = ["--config", str(cp), "--root", str(root)]
        SRC = "p.push('layout=' + n.layoutMode + ',' + n.itemSpacing);\n"
        ex.write_text(SRC, encoding="utf-8")

        import contextlib, io

        def run(extra=()):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv + list(extra))
            return rc, buf.getvalue()

        if run()[0] != 0:
            print("self-test NG: 生成が落ちた"); ok = False
        d = json.loads(out.read_text(encoding="utf-8"))
        nc = d["notCaptured"]
        if sorted(nc) != ["itemReverseZIndex", "strokeBottomWeight", "strokeTopWeight"]:
            print(f"self-test NG: 読めていないキーが違う: {sorted(nc)}"); ok = False
        if "重なり順を判断しないこと" not in nc.get("itemReverseZIndex", ""):
            print("self-test NG: 注意が宣言に入っていない"); ok = False
        # 束ねた行（strokeTopWeight/strokeBottomWeight）は2件に割れる
        if d["declared"] != {"一覧のプロパティ": 5, "読めているプロパティ": 2,
                             "読めていないプロパティ": 3}:
            print(f"self-test NG: 件数の宣言が違う: {d['declared']}"); ok = False
        if run(["--check"])[0] != 0:
            print("self-test NG: 生成直後なのに --check が落ちた"); ok = False

        # **器からキーを1つ消したら --check が落ちる**（これが本体）
        ex.write_text(SRC.replace(" + ',' + n.itemSpacing", ""), encoding="utf-8")
        if run(["--check"])[0] != 1:
            print("self-test NG: 器が変わったのに --check が落ちなかった"); ok = False
        if run()[0] != 0 or run(["--check"])[0] != 0:
            print("self-test NG: 作り直しても --check が通らない"); ok = False
        if "itemSpacing" not in json.loads(
                out.read_text(encoding="utf-8"))["notCaptured"]:
            print("self-test NG: 消したキーが宣言に入っていない"); ok = False

        # 器がキーを読み始めたら宣言から消える（宣言だけ残らない）
        ex.write_text(SRC + "const z = n.itemReverseZIndex;\n", encoding="utf-8")
        run()
        if "itemReverseZIndex" in json.loads(
                out.read_text(encoding="utf-8"))["notCaptured"]:
            print("self-test NG: 読み始めたのに宣言が残った"); ok = False

        # 一覧が増えたら --check が落ちる
        ex.write_text(SRC, encoding="utf-8")
        run()
        more = json.loads(json.dumps(LIST))
        more["text"] = {"maxLines": {"figma": "行数制限"}}
        lp.write_text(json.dumps(more, ensure_ascii=False), encoding="utf-8")
        if run(["--check"])[0] != 1:
            print("self-test NG: 一覧が増えたのに --check が落ちなかった"); ok = False
        lp.write_text(json.dumps(LIST, ensure_ascii=False), encoding="utf-8")

        # 生成物を消したら落ちる
        run()
        out.unlink()
        if run(["--check"])[0] != 1:
            print("self-test NG: 生成物が無いのに --check が落ちなかった"); ok = False

        # 器が1つも宣言されていない／実在しないときは落ちる（0件の嘘を防ぐ）
        cp.write_text(json.dumps({"list": str(lp), "exporters": []}), encoding="utf-8")
        if run()[0] != 2:
            print("self-test NG: 器の宣言が空なのに通した"); ok = False
        cp.write_text(json.dumps({"list": str(lp), "exporters": ["ghost.js"]}),
                      encoding="utf-8")
        if run()[0] != 2:
            print("self-test NG: 器が実在しないのに通した"); ok = False
        cp.unlink()
        if run()[0] != 2:
            print("self-test NG: 設定が無いのに通した"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
