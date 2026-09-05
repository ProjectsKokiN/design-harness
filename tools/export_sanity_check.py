#!/usr/bin/env python3
"""書き出しの中だけで見つかる矛盾を、実装の前に出す（2026-09-04 新設・#24）。

## 実害（aub-familywalk）

**書き出したデータの中だけで見つけられる矛盾**を見つけずに実装し、
**3件とも実機・ユーザーの指摘で戻る**ことになりました。

| どこ | 書き出しの値 | 親の中身の幅 | 結果 |
|---|---|---|---|
| カメラの正方形 | **FIXED 360** | 350 | **10 はみ出す** |
| ALBUM の行 | **FIXED 355** | 350 | **5 はみ出す** |
| ALBUM の行の中身 | 写真 187 ＋ 帯 148 = **335** | 350（余り **15**） | **実機の書体で 12px はみ出した** |

**どれも Figma を1回読めば分かる矛盾です。** 子の幅が親の中身より広い。
3件目は「まだ収まっているが余裕が 15 しかない」ので、**書体が少し違うだけで
破れる**と分かる状態でした。

`sz=FIXED` と `w=360` をそのまま実装して、**「Figma がそう言っているから」で
止まっていました。** 隣の値（親の余白）と突き合わせていません。

## なぜ既存の段では捕まらないか

- 既存の照合は **「Figma の値」と「実装の実測」** を突き合わせます。
  **書き出しの中の値どうし**は見ていません
- `conflicts.json`（Figma の中の食い違いの申告）は**人が気づいたときだけ**
  書かれます。**気づく手がかりが機械にありません**
- #8 / #16 は「実装が幅に追随するか」の話で、**Figma 自身の矛盾**はその手前です

## 見るもの

    python3 tools/export_sanity_check.py --frames design/figma/frames.json

行は `深さ|名前|型|w|h|x|y|k=v…` で、`layout=` は
`上,右,下,左,すき間,向き,主軸,交差軸,主寄せ,交差寄せ` です。

| 見るもの | 落ちるか |
|---|---|
| 子の右端（`x + 幅`）が親の使える右端を超える | **落とす** |
| 余りが `--min-slack`（既定 20）未満 | 注意（件数のラチェット） |

**並び順を仮定しません。書き出しにある位置と幅をそのまま使います。**
Auto Layout の中に絶対配置の子が混ざる設計（写真を散らす等）があり、
「幅の合計＋すき間」で計算すると**数が嘘になります**
（aub の ALBUM: 合計では 76 はみ出すのに、実際は 5.5 でした）。

## 捕まえないもの

- 縦のはみ出し。ここは**横だけ**を見ます
- 高さ。縦は文字の量で伸びるので、書き出しの1点では判定できない
- `sz=FILL` の子。**親に合わせて縮む**ので、書かれた w は測ったときの値
- 確かめた方法: --self-test（はみ出しと薄い余りを仕込むと落ちること）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 余りがこれ未満なら注意（書体が少し違うだけで破れる）
DEFAULT_MIN_SLACK = 20.0

#: `名前×5` の形（同じ形の兄弟を畳んだ行）
TIMES_RX = re.compile(r"×(\d+)$")


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_row(line):
    """1行を辞書にする。読めない行は None。"""
    parts = line.split("|")
    if len(parts) < 7:
        return None
    depth = num(parts[0])
    if depth is None:
        return None
    kv = {}
    for p in parts[7:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k] = v
    name = parts[1]
    m = TIMES_RX.search(name)
    xs = []
    if kv.get("at"):
        # 畳んだ兄弟は `at=x,y x,y …` で位置を持つ
        for pair in kv["at"].split():
            a = pair.split(",")
            if len(a) == 2 and num(a[0]) is not None:
                xs.append(num(a[0]))
    x = num(parts[5])
    if x is not None:
        xs = [x]
    return {"depth": int(depth), "name": name, "type": parts[2],
            "w": num(parts[3]), "h": num(parts[4]), "xs": xs,
            "count": int(m.group(1)) if m else 1, "kv": kv}


def layout_of(row):
    """`layout=` を読む。無ければ None（Auto Layout ではない）。"""
    v = row["kv"].get("layout")
    if not v:
        return None
    f = v.split(",")
    if len(f) < 6:
        return None
    return {"pt": num(f[0]), "pr": num(f[1]), "pb": num(f[2]), "pl": num(f[3]),
            "gap": num(f[4]) or 0.0, "dir": f[5]}


def children_of(rows, i):
    """i 番の行の直下の子を返す。"""
    d = rows[i]["depth"]
    out = []
    for j in range(i + 1, len(rows)):
        if rows[j]["depth"] <= d:
            break
        if rows[j]["depth"] == d + 1:
            out.append(rows[j])
    return out


def check_frame(name, rows, min_slack):
    """1画面ぶんの行を検算する。

    **並び順を仮定しません。書き出しにある位置と幅をそのまま使います。**

    2026-09-04 の実測でそう変えました。最初は「横並びなら幅の合計＋すき間」で
    計算しましたが、aub の ALBUM の行は Auto Layout の中に**絶対配置の子**
    （写真を散らす設計）を持っており、**合計では 76 はみ出すのに、実際の
    はみ出しは 5.5** でした。**仮定を置くと数が嘘になります。**
    """
    errs, thin = [], []
    for i, r in enumerate(rows):
        lay = layout_of(r)
        if not lay or r["w"] is None:
            continue
        pl, pr = lay["pl"] or 0.0, lay["pr"] or 0.0
        right_edge = r["w"] - pr
        kids = children_of(rows, i)
        worst = None
        for k in kids:
            if k["w"] is None or not k["xs"]:
                continue
            if str(k["kv"].get("sz", "")).startswith("FILL"):
                continue          # 親に合わせて縮む。書かれた幅は測ったときの値
            for x in k["xs"]:
                edge = x + k["w"]
                if worst is None or edge > worst[0]:
                    worst = (edge, k, x)
        if worst is None:
            continue
        edge, k, x = worst
        slack = right_edge - edge
        where = f'{name} / {r["name"]}'
        detail = (f'    親 {r["w"]:g}（右の余白 {pr:g}）→ 使える右端 {right_edge:g}\n'
                  f'    いちばん右の子 {k["name"]}: x={x:g} + 幅 {k["w"]:g} = {edge:g}')
        if slack < 0:
            errs.append((where, f'  {where}: 子が親の中身より **{-slack:g} 広い**\n'
                        f'{detail}\n'
                        f'    **Figma の値どうしが矛盾しています。**'
                        f'実装する前に Figma を直してください。'))
        elif slack < min_slack:
            thin.append(f'  {where}: 余りが **{slack:g} しかありません**'
                        f'（右端 {right_edge:g} / 子の右 {edge:g} = {k["name"]}）')
    return errs, thin


def main(argv=None):
    ap = argparse.ArgumentParser(description="書き出しの中の矛盾を検算する")
    ap.add_argument("--frames", type=Path, default=Path("design/figma/frames.json"))
    ap.add_argument("--min-slack", type=float, default=DEFAULT_MIN_SLACK)
    ap.add_argument("--expected-thin", type=int, metavar="N",
                    help="薄い余りの件数の宣言（上回れば落ちる）")
    ap.add_argument("--declared", type=Path, metavar="JSON",
                    help='Figma 側の矛盾の宣言 {"画面 / フレーム": {"why","reviewBy"}}。'
                         '宣言済みは注意に落とす。期限切れ・古い宣言は落とす')
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.frames.exists():
        print(f"画面の書き出しがありません: {args.frames}\n"
              f"  **書き出しの中の矛盾を、誰も見ていない状態です。**", file=sys.stderr)
        return 2
    try:
        doc = json.loads(args.frames.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"書き出しが読めません: {args.frames}: {e}", file=sys.stderr)
        return 2

    frames = doc.get("frames") or {}
    if not frames:
        print(f"画面が1つもありません: {args.frames}\n"
              f"  **0件は「矛盾なし」ではなく「見ていない」です。**", file=sys.stderr)
        return 2

    # **Figma 側の矛盾を、理由と期限つきで宣言する口**（2026-09-05・aub の取り込みで新設）。
    # aub には矛盾が 11 件あり（ALBUM の写真の行が 5.5 はみ出す等）、Figma を直すのは
    # デザイナーの仕事。宣言が無いと push 前の関門が止まり続け、`--no-verify` へ逃げる
    # 誘因になる。**隠すのではなく、誰が・いつまで・なぜ、を書かせて注意に落とす。**
    declared = {}
    if args.declared:
        if not args.declared.exists():
            print(f"宣言がありません: {args.declared}", file=sys.stderr)
            return 2
        try:
            declared = {k: v for k, v in json.loads(
                args.declared.read_text(encoding="utf-8")).items() if not k.startswith("$")}
        except (OSError, json.JSONDecodeError) as e:
            print(f"宣言が読めません: {args.declared}: {e}", file=sys.stderr)
            return 2
    from datetime import date as _date
    today = _date.today().isoformat()

    errs, thin, seen, waived = [], [], 0, []
    hit_keys = set()
    for key, fr in sorted(frames.items()):
        if key.startswith("$"):
            continue
        raw = fr.get("rows") if isinstance(fr, dict) else fr
        if not isinstance(raw, list):
            continue
        seen += 1
        rows = [r for r in (parse_row(x) for x in raw if isinstance(x, str)) if r]
        e, t = check_frame(fr.get("name", key) if isinstance(fr, dict) else key,
                           rows, args.min_slack)
        for where, msg in e:
            hit_keys.add(where)
            d = declared.get(where)
            if isinstance(d, dict) and str(d.get("why", "")).strip():
                if str(d.get("reviewBy", "")) < today:
                    errs.append(msg + f"\n    宣言の期限（{d.get('reviewBy')}）が切れています。"
                                f"**まだ直っていないなら期限を更新してください。**")
                else:
                    waived.append(f"  {where}: 宣言あり（{d['why']} / 期限 {d['reviewBy']}）")
            else:
                errs.append(msg)
        thin += t
    # **宣言だけ残っているものは落とす**（直ったのに宣言が消えていない＝宣言が古い）
    for where in sorted(set(declared) - hit_keys):
        errs.append(f"  {where}: 宣言がありますが、いまの書き出しに矛盾がありません。"
                    f"**宣言のほうが古くなっています。消してください。**")

    if isinstance(args.expected_thin, int) and len(thin) > args.expected_thin:
        errs.append(f"  余りの薄い箇所が {len(thin)} 件で、"
                    f"宣言（{args.expected_thin}）を上回りました。")
    if waived:
        print(f"注意: Figma 側の矛盾 {len(waived)} 件を理由つきで宣言しています"
              f"（直したら宣言を消すこと）:")
        print("\n".join(waived))
    if errs:
        print(f"書き出しの中に矛盾があります（画面 {seen} 枚）:", file=sys.stderr)
        print("\n".join(errs[:20]), file=sys.stderr)
        if thin:
            print(f"\n  余りが {args.min_slack:g} 未満（{len(thin)}件）:",
                  file=sys.stderr)
            print("\n".join(thin[:10]), file=sys.stderr)
        return 1
    if thin:
        print(f"注意: 余りが {args.min_slack:g} 未満の箇所が {len(thin)} 件あります"
              f"（**書体が少し違うだけで破れます**）:")
        for x in thin[:10]:
            print(x)
    print(f"書き出しの検算: はみ出し 0件（画面 {seen} 枚 / 薄い余り {len(thin)}件）。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True

    def rows(*rs):
        return list(rs)

    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "frames.json"

        def run(frames, *extra):
            f.write_text(json.dumps({"frames": frames}, ensure_ascii=False),
                         encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--frames", str(f), *extra])
            return rc, buf.getvalue()

        # 収まっている（親 390 − 20×2 = 350、子 350）
        okf = {"1:1": {"name": "OK", "rows": rows(
            "0|OK|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|350|100|20|20")}}
        rc, out = run(okf)
        if rc != 0:
            print(f"self-test NG: 収まっているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False

        # **はみ出す**（カメラの 360 / 中身 350）
        rc, out = run({"1:1": {"name": "CAMERA", "rows": rows(
            "0|CAMERA|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Images|INSTANCE|360|360|20|20|sz=FIXED,FIXED")}})
        if rc != 1 or "10 広い" not in out:
            print(f"self-test NG: はみ出しを見逃した（{rc}）\n   {out[:300]}"); ok = False
        # ALBUM の 355
        rc, out = run({"1:1": {"name": "ALBUM", "rows": rows(
            "0|ALBUM|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|355|100|20|20|sz=FIXED,HUG")}})
        if rc != 1 or "5 広い" not in out:
            print(f"self-test NG: 5px のはみ出しを見逃した（{rc}）"); ok = False

        # **余りが薄い**（子の右端 343 / 使える右端 350 → 余り 7）
        thinf = {"1:1": {"name": "ALBUM", "rows": rows(
            "0|ALBUM|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|350|100|20|20|layout=0,0,0,0,8,HORIZONTAL,FIXED,HUG,MIN,MIN",
            "2|Photo|FRAME|187|100|0|0|sz=FIXED,FIXED",
            "2|Band|FRAME|148|100|195|0|sz=FIXED,FIXED")}}
        rc, out = run(thinf)
        if rc != 0 or "余りが **7 しかありません**" not in out:
            print(f"self-test NG: 薄い余りを出していない（{rc}）\n   {out[:400]}")
            ok = False
        # 宣言を超えたら落ちる
        rc, out = run(thinf, "--expected-thin", "0")
        if rc != 1:
            print(f"self-test NG: 薄い余りの宣言を超えても通した（{rc}）"); ok = False
        # **絶対配置の子が右へはみ出す**（aub の ALBUM の実際の形）
        rc, out = run({"1:1": {"name": "X", "rows": rows(
            "0|X|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|350|100|20|20|layout=0,0,0,0,25,HORIZONTAL,FIXED,HUG,SPACE_BETWEEN,CENTER",
            "2|A|FRAME|148|100|0|0|sz=HUG,HUG",
            "2|B|RECTANGLE|180|180|148|0|sz=FIXED,FIXED",
            "2|C|INSTANCE|48|48|307.5|0|sz=FIXED,FIXED")}})
        if rc != 1 or "5.5 広い" not in out:
            print(f"self-test NG: 位置で見たはみ出しを捕まえていない（{rc}）\n   {out[:400]}")
            ok = False
        if "幅の合計" in out or "76" in out:
            print("self-test NG: 並び順を仮定して数を膨らませた"); ok = False

        # **FILL の子は判定しない**（親に合わせて縮む）
        rc, out = run({"1:1": {"name": "F", "rows": rows(
            "0|F|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|999|100|20|20|sz=FILL,HUG")}})
        if rc != 0:
            print(f"self-test NG: FILL の子で落ちた（{rc}）"); ok = False

        # 畳んだ兄弟（×5）の合計を数える
        rc, out = run({"1:1": {"name": "B", "rows": rows(
            "0|B|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Row|FRAME|350|100|20|20|layout=0,0,0,0,0,HORIZONTAL,FIXED,HUG,MIN,MIN",
            "2|Cell×5|FRAME|80|80|-|-|sz=FIXED,FIXED|at=0,0 90,0 180,0 270,0 320,0")}})
        if rc != 1 or "50 広い" not in out:
            print(f"self-test NG: 畳んだ兄弟の数を見ていない（{rc}）\n   {out[:300]}")
            ok = False

        # 画面が0枚なら落ちる（この道具自身の空振り）
        rc, out = run({})
        if rc != 2 or "見ていない" not in out:
            print(f"self-test NG: 画面0枚で通した（{rc}）"); ok = False
        # ─── --declared（Figma 側の矛盾を理由と期限つきで宣言する）────────────
        dec = Path(td) / "declared.json"
        CAM = {"1:1": {"name": "CAMERA", "rows": rows(
            "0|CAMERA|FRAME|390|844|0|0|layout=20,20,20,20,0,VERTICAL,FIXED,FIXED,MIN,MIN",
            "1|Images|INSTANCE|360|360|20|20|sz=FIXED,FIXED")}}

        def with_decl(frames, d):
            dec.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            return run(frames, "--declared", str(dec))

        rc, out = with_decl(CAM, {"CAMERA / CAMERA": {"why": "Figma の Images が 360 のまま。デザイナーが直す", "reviewBy": "2099-01-01"}})
        if rc != 0 or "宣言あり" not in out:
            print(f"self-test NG: 理由つきで宣言したのに落ちた（{rc}）\n   {out[:300]}"); ok = False
        rc, out = with_decl(CAM, {"CAMERA / CAMERA": {"why": "x", "reviewBy": "2020-01-01"}})
        if rc != 1 or "期限" not in out:
            print(f"self-test NG: 期限切れの宣言を通した（{rc}）"); ok = False
        rc, _ = with_decl(CAM, {"CAMERA / CAMERA": {"why": "  ", "reviewBy": "2099-01-01"}})
        if rc != 1:
            print(f"self-test NG: 理由が空の宣言を通した（{rc}）"); ok = False
        # **直ったのに宣言が残っている**＝宣言のほうが古い → 落とす
        rc, out = with_decl(okf, {"OK / Row": {"why": "x", "reviewBy": "2099-01-01"}})
        if rc != 1 or "宣言のほうが古く" not in out:
            print(f"self-test NG: 古い宣言を通した（{rc}）"); ok = False
        rc, _ = run(CAM, "--declared", str(Path(td) / "ない.json"))
        if rc != 2:
            print(f"self-test NG: 宣言ファイルが無いのに 2 で止まらなかった（{rc}）"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
