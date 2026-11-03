#!/usr/bin/env python3
"""**Figma の中で、変数・スタイルに結ばれていない値**を並べる（候補6・2026-11-03）。

**これはデザイナーへの報せです。実装の合否には使いません**（Figma が唯一の正なので、
Figma の直値を直すかどうかはデザイナーが決める）。verify.sh では note（落とさない段）で呼ぶ。

外部の実践例 ds-base-ui の `audit.figma.js`（自動レイアウトの余白・塗り・線・角丸が変数に
結ばれていない所と、文字スタイルの無い文字を全件洗い出す）から取り入れた。

## 見るもの（書き出しの行から）

    色       fill= の `SOLID:#…`（単色）とグラデーションの止め色の `#…`
    角丸     radius= の数字
    余白     layout= の上・右・下・左・すき間のうち 0 でない数字で、bind= に無いもの
             （**bind= は 2026-11-03 からの書き出し器が書く。**書き出しに1件も無ければ余白は見ていないと言う）
    線の太さ strokeWeight= の数字
    文字     ts=（文字スタイル）の無い文字

**意図した直値**は、Figma の節点に印を付けて外す（`setSharedPluginData('harness', 'raw', '<欄,欄>')`。
欄は fill・radius・padding・gap・strokeWeight・textStyle）。書き出し器が `raw=` として行に書く。

## 終了コード

    0  直値は無い（印つきは除く）
    1  直値がある（**報せ**。直すかどうかはデザイナーが決める）
    2  確かめられなかった（書き出しが無い・行が1つも無い）
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401

HEX_RX = re.compile(r"#[0-9a-fA-F]{6,8}\b")
NUM_RX = re.compile(r"^-?\d+(?:\.\d+)?$")
SPACING_FIELDS = ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "itemSpacing")


def blocks_of(doc):
    """書き出しから (場所の名前, 行の一覧) を取り出す。"""
    out = []
    for fid, fr in (doc.get("frames") or {}).items():
        if isinstance(fr, dict) and isinstance(fr.get("rows"), list):
            out.append((f"画面 {fr.get('name') or fid}", fr["rows"]))
    for key in ("componentSets", "singleComponents"):
        sets = doc.get(key) or {}
        if not isinstance(sets, dict):
            continue
        for name, s in sets.items():
            # **古い形の書き出し**（414 の components.json は variants が数）は行を持たないので数えない。
            # 例外で止めず、行が1つも無ければ「見ていない」（2）になる（2026-11-03 FlashEnglish のセッションが踏んだ）
            variants = s.get("variants") if isinstance(s, dict) else None
            if not isinstance(variants, dict):
                continue
            for vname, v in variants.items():
                if isinstance(v, dict) and isinstance(v.get("rows"), list):
                    out.append((f"部品 {name}" + ("" if vname == "-" else f"/{vname}"), v["rows"]))
    return out


def scan_rows(where, rows, has_bind):
    found = []
    for row in rows:
        cols = row.split("|")
        if len(cols) < 3 or not cols[0].isdigit():
            continue
        name, kind = cols[1], cols[2]
        seg = {}
        for c in cols[3:]:
            k, sep, v = c.partition("=")
            if sep:
                seg[k] = v
        raw = {x.strip() for x in seg.get("raw", "").split(",") if x.strip()}
        place = f"{where} > {name}"
        fill = seg.get("fill", "")
        if fill and "fill" not in raw and ("SOLID:#" in fill or ("@" in fill and HEX_RX.search(fill))):
            found.append(("色", place, fill[:60]))
        if "radius" in seg and "radius" not in raw:
            nums = [x for x in seg["radius"].split(",") if NUM_RX.match(x) and float(x) != 0]
            if nums:
                found.append(("角丸", place, seg["radius"]))
        sw = seg.get("strokeWeight")
        # **線の無い節点は数えない。** 器は線の有無にかかわらず strokeWeight を書く（既定 1）。
        # 2026-11-03、aub で取り直した書き出しに当てると「線の太さ 860 件」と出た（線の無い節点の既定値）
        if sw and "stroke" in seg and "strokeWeight" not in raw and NUM_RX.match(sw) and float(sw) != 0:
            found.append(("線の太さ", place, sw))
        if kind == "TEXT" and "ts" not in seg and "textStyle" not in raw:
            found.append(("文字", place, "文字スタイルが無い"))
        if has_bind and "layout" in seg:
            vals = seg["layout"].split(",")[:5]
            bound = {b.split(":")[0] for b in seg.get("bind", "").split(",") if b}
            for f, v in zip(SPACING_FIELDS, vals):
                key = "gap" if f == "itemSpacing" else "padding"
                if NUM_RX.match(v) and float(v) != 0 and f not in bound and key not in raw and f not in raw:
                    found.append(("余白", place, f"{f}={v}"))
    return found


def check(paths):
    docs = []
    for p in paths:
        try:
            docs.append((p, json.loads(Path(p).read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as e:
            return 2, [f"書き出しが読めません: {p}: {e}"]
    blocks = [b for _, d in docs for b in blocks_of(d)]
    n_rows = sum(len(r) for _, r in blocks)
    if not blocks or not n_rows:
        return 2, [f"**行が1つもありません**（{', '.join(map(str, paths))}）。見ていません"]
    has_bind = any("|bind=" in r for _, rows in blocks for r in rows)
    found = [f for where, rows in blocks for f in scan_rows(where, rows, has_bind)]
    head = (f"Figma の直値: 書き出し {len(docs)} 本・場所 {len(blocks)}・行 {n_rows}"
            + ("" if has_bind else "・**余白は見ていません**（書き出しに bind= が無い。2026-11-03 以降の書き出し器で取り直す）"))
    if not found:
        return 0, [head, "  変数・スタイルに結ばれていない値はありません"]
    by_kind = {}
    for k, place, detail in found:
        by_kind.setdefault(k, []).append(f"  {place}: {detail}")
    lines = ["**Figma の中に、変数・スタイルに結ばれていない値があります**（デザイナーへの報せ。実装の合否には使いません）:"]
    for k, items in by_kind.items():
        lines.append(f" {k} {len(items)} 件")
        lines += items[:30] + ([f"  …ほか {len(items) - 30} 件"] if len(items) > 30 else [])
    lines += ["  意図した直値なら、Figma の節点に印を付けると外れます: "
              "setSharedPluginData('harness', 'raw', '<fill,radius,padding,gap,strokeWeight,textStyle>')", head]
    return 1, lines


def self_test():
    import tempfile
    ok = True

    def ck(c, m):
        nonlocal ok
        if not c:
            ok = False
            print(f"  NG: {m}")

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "frames.json"

        def run(rows):
            f.write_text(json.dumps({"frames": {"1:1": {"name": "Top", "rows": rows}}}), encoding="utf-8")
            return check([f])

        rc, out = run(["0|Top|FRAME|10|10|0|0|fill=Frame/Neutral/Default|layout=16,0,0,0,8,VERTICAL,HUG,FIXED,MIN,MIN|bind=paddingTop:Gap/M,itemSpacing:Gap/S",
                       "1|T|TEXT|1|1|0|0|fill=Text/Neutral/Default|ts=Body/M"])
        ck(rc == 0, f"結ばれている値を直値と言った: {rc} {out}")
        rc, out = run(["0|Top|FRAME|10|10|0|0|fill=SOLID:#ff0000|radius=8|strokeWeight=2|stroke=あり|layout=16,0,0,0,8,VERTICAL,HUG,FIXED,MIN,MIN|bind=paddingTop:Gap/M",
                       "1|T|TEXT|1|1|0|0|fill=Text/Neutral/Default"])
        text = "\n".join(out)
        ck(rc == 1, f"直値を報せない: {rc}")
        for k in ("色 1 件", "角丸 1 件", "線の太さ 1 件", "文字 1 件", "余白 1 件"):
            ck(k in text, f"{k} を数えていない: {text}")
        ck("itemSpacing=8" in text and "paddingTop" not in text.split("余白")[1], f"結んだ余白まで直値と言った: {text}")
        rc, out = run(["0|Top|FRAME|10|10|0|0|strokeTopWeight=1|strokeWeight=1"])
        ck(rc == 0, f"線の無い節点の既定の太さを直値と言った: {rc} {out}")
        rc, out = run(["0|Top|FRAME|10|10|0|0|fill=SOLID:#ff0000|radius=8|raw=fill,radius"])
        ck(rc == 0, f"印を付けた直値を報せた: {rc} {out}")
        rc, out = run(["0|Top|FRAME|10|10|0|0|fill=Frame/A>#ffffff@1"])
        ck(rc == 1 and "色 1 件" in "\n".join(out), f"グラデーションの止め色の直値を見ていない: {out}")
        rc, out = run(["0|Top|FRAME|10|10|0|0|layout=16,0,0,0,8,VERTICAL,HUG,FIXED,MIN,MIN"])
        ck(rc == 0 and any("余白は見ていません" in x for x in out), f"bind= の無い書き出しで、余白を見ていないと言わない: {out}")
        rc, _ = run([])
        ck(rc == 2, f"行が無いのに 2 でない: {rc}")
        comp = Path(td) / "components.json"
        comp.write_text(json.dumps({"componentSets": {"Button": {"variants": {"Size=M": {"rows": [
            "0|Size=M|COMPONENT|10|10|0|0|fill=SOLID:#000000"]}}}}}), encoding="utf-8")
        rc, out = check([comp])
        ck(rc == 1 and any("部品 Button/Size=M" in x for x in out), f"部品の直値を場所つきで言わない: {out}")
        old = Path(td) / "old.json"
        old.write_text(json.dumps({"componentSets": {"Button": {"variants": 4, "props": {}}}}), encoding="utf-8")
        rc, out = check([old])
        ck(rc == 2, f"古い形（variants が数）で 2 を返さない: {rc} {out}")
        ck(main([str(comp)]) == 1 and main([str(Path(td) / "none.json")]) == 2, "入口の終了コードが違う")
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            ck(main([]) == 2, "書き出しを指定しないのに 2 でない")
        f.write_text(json.dumps({"frames": {"1:1": {"rows": ["0|Top|FRAME|1|1|0|0|fill=Frame/A"]}}}), encoding="utf-8")
        ck(main([str(f)]) == 0, "入口が直値の無い書き出しで 0 を返さない")

    print("self-test: OK" if ok else "self-test: NG")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Figma の中で変数・スタイルに結ばれていない値を並べる（報せ）")
    ap.add_argument("exports", nargs="*", type=Path, help="frames.json・components.json")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.exports:
        print("書き出しを指定してください（frames.json・components.json）。見ていません", file=sys.stderr)
        return 2
    rc, lines = check(a.exports)
    for x in lines:
        print(x, file=sys.stderr if rc else sys.stdout)
    if rc == 2:
        return 2
    if rc != 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
