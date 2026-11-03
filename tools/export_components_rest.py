#!/usr/bin/env python3
"""部品の書き出しを Figma の REST API から作る（器 exporters/export_components.js と同じ形・#185）。

## なぜ要るか

器の戻りは use_figma の 1 回あたり約 48KB までで、414 の部品は全量で約 71 万文字ある。会話に書き写すと
20 回前後に分かれる。2026-11-04、414 は export_frames_rest.py で変異ごとに行を作り、作業フォルダの手書きの
assemble.py で componentSets の形に組み替えた。そのとき次の3つが手作業だった（ここで面倒を見る）:

| | 手作業のときの実害 | ここでは |
|---|---|---|
| frames → componentSets の組み替え | 案件ごとに書く | 器と同じ形（id・kind・variantTotal・variants・board・order・key）で書く |
| 外したセット（Icons）の置き場所 | use_figma で測って手で宣言 | **REST の木から実測する**（宣言は why だけ） |
| 既存の `$meta`（restDigests・bodyHash） | 組み立て直すたびに消え、鮮度の検査が黙って壊れる | `--previous` から引き継ぐ |

**値は作りません。** 行は export_frames_rest.py の export() が作り、ここは組み替えだけを行います。

## 使い方

    python3 tools/export_components_rest.py --file <key> --page "⚙️_System" \\
        --variables <variables.json> --exclude excluded.json --previous <いまの書き出し> --out <出力>

`--exclude` は `{"Icons": {"why": "…"}}`。外したセットは行を書かず、`$meta.excluded` に why・board・order を書く。
器との一致は、器に行のハッシュだけを返させて `export_frames_rest.py --compare-hashes` で確かめる
（`--previous` から引き継ぐのは restDigests・bodyHash・既知の差だけ。**照合はやり直すこと**）。

## 器と同じにしていること

- セットを先に、単体をあとに、それぞれページの中の出てくる順で並べる（器の collect() と同じ）
- 同じ名前のセット・単体、同じ名前の変異があれば止める（どちらが正か機械で決められない）
- 置き場所は器の placement() と同じ読み方（ページの直下のボードの y・x、部品の y・x）
- 確かめた方法: --self-test（REST の応答を差し替えて、組み替え・外したセット・引き継ぎ・止まる場面を見る）
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）
import export_frames_rest as rest

#: `--previous` から引き継ぐ `$meta` の欄。**照合の結果は引き継がない**（取り直したら古くなる）
CARRY = ("restDigests", "bodyHash", "既知の差")


def structure(file_key, pages, tok=None):
    """許可ページのセットと単体を、器の collect() と同じ順で集める。置き場所も測る。"""
    doc = rest.get(f"/files/{file_key}", None, tok)
    keys_cs = {k: v.get("key") for k, v in (doc.get("componentSets") or {}).items()}
    keys_c = {k: v.get("key") for k, v in (doc.get("components") or {}).items()}
    sets, singles, dup, seen = {}, {}, [], []

    def place(board, node):
        bb = board.get("absoluteBoundingBox") or {}
        nb = node.get("absoluteBoundingBox") or {}
        return board.get("name"), [rest.round_half_up(bb.get("y", 0)), rest.round_half_up(bb.get("x", 0)),
                                   rest.round_half_up(nb.get("y", 0)), rest.round_half_up(nb.get("x", 0))]

    def visit(node, board, in_set):
        for c in node.get("children") or []:
            b = board or c
            t = c.get("type")
            if t == "COMPONENT_SET":
                if c["name"] in sets or c["name"] in singles:
                    dup.append(c["name"])
                vs = [[v["name"], v["id"], keys_c.get(v["id"])] for v in c.get("children") or []
                      if v.get("type") == "COMPONENT"]
                bname, order = place(b, c)
                sets[c["name"]] = {"id": c["id"], "kind": "set", "key": keys_cs.get(c["id"]), "variants": vs,
                                   "board": bname, "order": order}
            elif t == "COMPONENT" and not in_set:
                if c["name"] in sets or c["name"] in singles:
                    dup.append(c["name"])
                bname, order = place(b, c)
                singles[c["name"]] = {"id": c["id"], "kind": "single", "key": keys_c.get(c["id"]),
                                      "variants": [["-", c["id"], keys_c.get(c["id"])]],
                                      "board": bname, "order": order}
            if t != "INSTANCE":
                visit(c, b, t == "COMPONENT_SET")

    for pg in doc["document"].get("children") or []:
        if pg.get("name") in pages:
            seen.append(pg["name"])
            visit(pg, None, False)
    return {**sets, **singles}, seen, sorted(set(dup))


def build(file_key, pages, var_paths, excluded, previous=None, tok=None):
    found, seen, dup = structure(file_key, pages, tok)
    if not seen:
        raise RuntimeError(f"許可ページが見つかりません: {pages}")
    if dup:
        raise RuntimeError(f"同名のコンポーネント: {dup}")
    unknown = sorted(set(excluded) - set(found))
    if unknown:
        raise RuntimeError(f"外すと宣言したセットが Figma にありません: {unknown}")
    for name, d in excluded.items():
        if not isinstance(d, dict) or not str(d.get("why", "")).strip():
            raise RuntimeError(f"外したセット {name} に why がありません（なぜ外すかを書く）")
    ids = [v[1] for name, s in found.items() if name not in excluded for v in s["variants"]]
    frames = rest.export(file_key, ids, var_paths, tok=tok)
    out = {}
    for name, s in found.items():
        if name in excluded:
            continue
        variants = {}
        for vname, vid, vkey in s["variants"]:
            key = "-" if s["kind"] == "single" else vname
            if key in variants:
                raise RuntimeError(f"同名の変異: {name}/{key}")
            variants[key] = {"id": vid, "rows": frames["frames"][vid]["rows"]}
            if vkey:
                variants[key]["key"] = vkey
        entry = {"id": s["id"], "kind": s["kind"], "variantTotal": len(s["variants"]), "variants": variants,
                 "board": s["board"], "order": s["order"]}
        if s.get("key"):
            entry["key"] = s["key"]
        out[name] = entry
    body = rest.js(out)
    meta = {
        # **このファイルに入っている数**を宣言する（外したセットは excludedSets で別に数える）。
        # 読み手（FlashEnglish の gen_layout.py）は「入っているセットの数 == declared.componentSets」を見る。
        # 外す前の数を書くと食い違う（2026-11-04・414 で見つかった）
        "declared": {"componentSets": sum(1 for s in out.values() if s["kind"] == "set"),
                     "singleComponents": sum(1 for s in out.values() if s["kind"] == "single"),
                     "variants": sum(len(s["variants"]) for s in out.values()),
                     "rows": sum(len(v["rows"]) for s in out.values() for v in s["variants"].values()),
                     "excludedSets": len(excluded), "pages": len(seen)},
        "pages": seen,
        "excluded": {n: {"why": excluded[n]["why"], "board": found[n]["board"], "order": found[n]["order"]}
                     for n in sorted(excluded)},
        "source": "REST（tools/export_components_rest.py）。行は export_frames_rest.py の export() が作る",
        "読めなかったもの": frames["$meta"]["読めなかったもの"],
    }
    carried = []
    for k in CARRY:
        if previous and k in (previous.get("$meta") or {}):
            meta[k] = previous["$meta"][k]
            carried.append(k)
    doc = {"$meta": meta, "componentSets": out,
           "digest": {"algo": "FNV-1a 32bit", "sets": len(out),
                      "variants": sum(len(s["variants"]) for s in out.values()),
                      "chars": len(body), "value": rest.fnv(body)}}
    return doc, carried


def self_test():
    import os
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    def comp(i, name, x, y, w=10):
        return {"id": i, "name": name, "type": "COMPONENT", "layoutSizingHorizontal": "FIXED",
                "layoutSizingVertical": "FIXED", "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": 10},
                "children": [{"id": i + ";1", "name": "Label", "type": "TEXT", "characters": name,
                              "absoluteBoundingBox": {"x": x, "y": y, "width": 5, "height": 5}}]}

    btn = {"id": "S:1", "name": "Button", "type": "COMPONENT_SET", "layoutMode": "HORIZONTAL",
           "absoluteBoundingBox": {"x": 120, "y": 20, "width": 40, "height": 10},
           "children": [comp("V:1", "Size=M", 120, 20), comp("V:2", "Size=L", 140, 20)]}
    icons = {"id": "S:2", "name": "Icons", "type": "COMPONENT_SET",
             "absoluteBoundingBox": {"x": 500, "y": 30, "width": 10, "height": 10},
             "children": [comp("V:3", "Name=a", 500, 30)]}
    header = comp("C:9", "Header", 110, 60, 50)
    board = {"id": "B:1", "name": "Buttons", "type": "FRAME", "absoluteBoundingBox": {"x": 100, "y": 0},
             "children": [btn, header]}
    board2 = {"id": "B:2", "name": "Icons", "type": "FRAME", "absoluteBoundingBox": {"x": 480, "y": 0},
              "children": [icons]}
    file_doc = {"document": {"type": "DOCUMENT", "children": [
        {"id": "0:1", "name": "System", "type": "CANVAS", "children": [board, board2]},
        {"id": "0:2", "name": "Sandbox", "type": "CANVAS", "children": [comp("C:7", "Header", 0, 0)]}]},
        "componentSets": {"S:1": {"key": "ks1"}, "S:2": {"key": "ks2"}},
        "components": {"V:1": {"key": "kv1"}, "V:2": {"key": "kv2"}, "C:9": {"key": "kc9"}}}
    nodes = {"nodes": {k: {"document": v, "components": {}, "componentSets": {}} for k, v in
                       (("V:1", btn["children"][0]), ("V:2", btn["children"][1]), ("C:9", header))}}
    nodes["nodes"]["V:1"]["components"] = {"V:1": {"name": "Size=M", "componentSetId": "S:1"},
                                           "V:2": {"name": "Size=L", "componentSetId": "S:1"}}
    set_node = {"nodes": {"S:1": {"document": {k: v for k, v in btn.items() if k != "children"}}}}

    def fake_get(path, params=None, tok=None):
        if path == "/files/F" and params and "ids" in params:
            return {"document": {"type": "DOCUMENT", "children": [
                {"id": "0:1", "name": "System", "type": "CANVAS", "children": [board]}]}}
        if path == "/files/F":
            return file_doc
        if params and params.get("depth") == "1" and "S:1" in params.get("ids", ""):
            return set_node
        return nodes

    keep = rest.get
    rest.get = fake_get
    try:
        with tempfile.TemporaryDirectory() as td:
            vf = Path(td) / "v.json"
            vf.write_text(rest.js({"map": {}, "values": {}}), encoding="utf-8")
            # 変数の対応表が空だと export() が止まるので、1 つだけ入れる
            vf.write_text(rest.js({"map": {"VariableID:" + "a" * 40 + "/1:1": ["a" * 40, "Gap/M"]}}), encoding="utf-8")
            prev = {"$meta": {"restDigests": {"Button": "x"}, "bodyHash": "b", "既知の差": [1], "器との照合": "古い"}}
            doc, carried = build("F", ["System"], [str(vf)], {"Icons": {"why": "字形はフォント"}}, prev)
            cs = doc["componentSets"]
            ck(list(cs) == ["Button", "Header"], f"器と同じ順（セット → 単体）でない・外したセットを書いた: {list(cs)}")
            ck(list(cs["Button"]) == ["id", "kind", "variantTotal", "variants", "board", "order", "key"],
               f"欄の並びが器と違う: {list(cs['Button'])}")
            ck(cs["Button"]["board"] == "Buttons" and cs["Button"]["order"] == [0, 100, 20, 120]
               and cs["Header"]["order"] == [0, 100, 60, 110], f"置き場所が器の placement() と違う: {cs['Button']}")
            ck(list(cs["Button"]["variants"]) == ["Size=M", "Size=L"] and cs["Button"]["variants"]["Size=M"]["key"] == "kv1"
               and cs["Header"]["variants"]["-"]["key"] == "kc9", "変異の名前・key が器と違う")
            ck("sz=FIXED,FIXED" in cs["Button"]["variants"]["Size=M"]["rows"][0], "変異の行が export() の行でない")
            ck(doc["$meta"]["excluded"] == {"Icons": {"why": "字形はフォント", "board": "Icons", "order": [0, 480, 30, 500]}},
               f"外したセットの置き場所を実測していない: {doc['$meta']['excluded']}")
            ck(carried == list(CARRY) and doc["$meta"]["restDigests"] == {"Button": "x"}
               and "器との照合" not in doc["$meta"], "鮮度の記録を引き継がない、または照合の結果まで引き継いだ")
            ck(doc["$meta"]["declared"] == {"componentSets": 1, "singleComponents": 1, "variants": 3, "rows": 6,
                                            "excludedSets": 1, "pages": 1}
               and doc["$meta"]["pages"] == ["System"], f"数え方が器と違う（許可ページだけ数える）: {doc['$meta']['declared']}")
            ck(doc["digest"]["value"] == rest.fnv(rest.js(cs)), "ハッシュが本体と合わない")
            for bad, why in (({"Icons": {}}, "why の無い外し"), ({"Nope": {"why": "x"}}, "Figma に無いセットの外し")):
                try:
                    build("F", ["System"], [str(vf)], bad)
                    ck(False, f"{why}で止まらない")
                except RuntimeError:
                    pass
            try:
                build("F", ["System", "Sandbox"], [str(vf)], {})
                ck(False, "同名の部品（別ページの Header）で止まらない")
            except RuntimeError:
                pass
            try:
                build("F", ["None"], [str(vf)], {})
                ck(False, "許可ページが無いのに止まらない")
            except RuntimeError:
                pass
            ex = Path(td) / "ex.json"
            ex.write_text(rest.js({"Icons": {"why": "字形はフォント"}}), encoding="utf-8")
            pv = Path(td) / "prev.json"
            pv.write_text(rest.js(prev), encoding="utf-8")
            out = Path(td) / "o.json"
            keep_tok = os.environ.get("FIGMA_TOKEN")
            os.environ["FIGMA_TOKEN"] = "x"
            try:
                ck(main(["--file", "F", "--page", "System", "--variables", str(vf), "--exclude", str(ex),
                         "--previous", str(pv), "--out", str(out)]) == 0
                   and json.loads(out.read_text(encoding="utf-8"))["$meta"]["bodyHash"] == "b", "入口から書き出せない")
                ck(main(["--file", "F", "--variables", str(vf)]) == 2, "ページと出力先が無いのに 2 でない")
                ck(main(["--file", "F", "--page", "None", "--variables", str(vf), "--out", str(out)]) == 2,
                   "許可ページが無いのに 2 でない")
                ck(main(["--file", "F", "--page", "System", "--variables", str(vf), "--exclude",
                         str(Path(td) / "none.json"), "--out", str(out)]) == 2, "外しの宣言が読めないのに 2 でない")
            finally:
                if keep_tok is None:
                    os.environ.pop("FIGMA_TOKEN", None)
                else:
                    os.environ["FIGMA_TOKEN"] = keep_tok
    finally:
        rest.get = keep
    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="部品の書き出しを REST から作る（器と同じ形）")
    ap.add_argument("--file")
    ap.add_argument("--page", action="append", default=[], help="許可ページ（page-scope の allowed）。複数可")
    ap.add_argument("--variables", action="append", default=[])
    ap.add_argument("--exclude", type=Path, help='外すセットの宣言 {"名前": {"why": "…"}}')
    ap.add_argument("--previous", type=Path, help="いまの書き出し（restDigests・bodyHash・既知の差を引き継ぐ）")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not (a.file and a.page and a.out):
        print("--file・--page・--out が要ります", file=sys.stderr)
        return 2
    try:
        excluded = json.loads(a.exclude.read_text(encoding="utf-8")) if a.exclude else {}
        excluded = {k: v for k, v in excluded.items() if not k.startswith("$")}
        previous = json.loads(a.previous.read_text(encoding="utf-8")) if a.previous and a.previous.exists() else None
        doc, carried = build(a.file, a.page, a.variables, excluded, previous)
    except (RuntimeError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"書き出せませんでした: {e}", file=sys.stderr)
        return 2
    a.out.write_text(rest.safe(json.dumps(doc, ensure_ascii=False, indent=1)) + "\n", encoding="utf-8")
    d = doc["$meta"]["declared"]
    print(f"セット {d['componentSets']}・単体 {d['singleComponents']}（外した {d['excludedSets']}）・"
          f"変異 {d['variants']}・行 {d['rows']} を書きました: {a.out}"
          f"（読めなかったもの {len(doc['$meta']['読めなかったもの'])} 件・引き継いだ {', '.join(carried) or 'なし'}）")
    print("**器との照合をやり直してください**（export_frames_rest.py --compare-hashes）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
