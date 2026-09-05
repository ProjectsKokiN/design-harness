#!/usr/bin/env python3
"""書き出しを作った器が保存され、いまも同じ器かを見る（aub 提案6・2026-08-29）。

## 実害

> 書き出し器が保存されておらず、README には3つ載っていたが**実在は1つ**。
> 17個を保存して回したら**3つ間違っていた**（aub-familywalk 2026-08-29）

書き出しは「正」として下流に流れます。その正を作った器が保存されていなければ、
**誰も再現できず、正しさを確かめる方法がありません。** 器が更新されたのに
書き出しを取り直していない場合も、下流は静かに古い正を使い続けます。

## 見るもの

書き出し（`figma/*.json`）の `$meta` に:

1. `producer` — 作った器のパス。**無ければ落とす**（「名前を書いただけ」を許さない）
2. その器が**実在する**こと
3. `producerDigest` — 取ったときの器の指紋。**いまの器の指紋と一致する**こと

指紋は `fingerprint/text_digest.py`（JS 側と同じ式）で取ります。
案件が自前の指紋関数を書きません。

## `--style`: 器の書き方（2026-09-04 新設・#32）

**`figma.mixed` を返しうる値を、素で読んでいないか**を見ます。

実害（qnd-database・2026-09-03）: Footer が辺ごとに違う線の太さを持っており、
`strokeWeight` が `figma.mixed`（Symbol）を返しました。それをテンプレート文字列に
入れた瞬間 `TypeError: cannot convert symbol to string` で**書き出しごと止まり、
12部品のうち1件も取れませんでした。**

`cornerRadius` には mixed の処理があったのに `strokeWeight` には**無く、
同じ形の抜け**でした。**キーごとに書く限り、次のキーでまた起きます。**
だから `exporters/_preamble.js` の `val()` / `num()` を通させます。

## `--samples`: 見本の変異が子を隠していないか（2026-09-04 新設・#22）

`childSizes` は component set ごとに**1変異だけをサンプルして**子の寸法を記録します。
**サンプルした変異にその子が無ければ、その子の寸法は書き出しに現れません。**

実害（FlashEnglish・2026-09-03）: `Buttons/L/Default` の見本が
`Icon=False, PrependIcon=False, AppendIcon=False`（アイコンが1つも無い変異）
だったため、**アイコンの寸法がどこにも入っていませんでした。** 私は名前
（`Buttons/L` → `AppIconSize.l`）から 36 と当てました。**Figma は 32 です。**

同じ器で、set によって在ったり無かったりします。どちらなのかは書き出しからは
分かりません。

**「子を消す軸」の一覧は手で書きません。導出します**——書き出しの中で
**実際に子として現れている名前**を集め、見本がその名前の軸を「無し」に
していたら出します。414 の実測では 27 セットのうち **4 セット**が当たり、
`Selected=False` のような**状態の軸では鳴りません**。

## 捕まえないもの

- 器を**回した結果が正しいか**。それは書き出しの中身の検査（照合テスト）の領域
- `--style` の**読み手がノードかどうか**。`s.lineHeight` の `s` が TextStyle なら
  mixed は来ないが、行だけを見て区別できない。**だから件数のラチェットにしてある**
  （増えたら落とす。いま在るぶんは宣言して先へ進める）
- Figma 側が変わったこと。それは `figma_freshness.py`（条件4）
- 確かめた方法: --self-test（器を書き換えると落ちること・producer が無いと落ちること）

## 使い方（案件のルートで）

    python3 design/harness/tools/exporter_check.py --config design/exporters.json
    python3 design/harness/tools/exporter_check.py --config design/exporters.json --update

`--update` は**書き出しを取り直した直後だけ**回します（指紋を記録し直す）。

    {
      "exports_dir": "design/figma",
      "exclude": ["_varmap.json"],
      "allow": [{"file": "components.json", "why": "器の特定が未了",
                 "reviewBy": "2026-11-30"}]
    }

例外は `allow` に**理由と棚卸しの期限つきで**宣言する（期限切れは落ちる）。
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fingerprint"))
from text_digest import text_digest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


#: `figma.mixed` を**返しうる**プロパティ。素で読むと書き出しごと止まる。
#:
#: **絞ってあります。** 1つのノードで値が割れるのは
#:   - 角ごとに違う角丸（`cornerRadius`）
#:   - 辺ごとに違う線の太さ（`strokeWeight`。**qnd の実害はこれ**）
#:   - TEXT の**字ごとに違う**文字の指定と塗り
#: の3種類です。`opacity` / `strokes` / `effects` / `characters` はノード1つに
#: 対して1つなので**入れていません**（入れると誤検出が増え、この検査が読まれなくなる）。
#: 新しい形の実害が出たらここへ足します。
MIXED_PROPS = (
    "strokeWeight", "cornerRadius",
    "fontSize", "fontName", "letterSpacing", "lineHeight",
    "textDecoration", "textCase", "fills", "fillStyleId", "textStyleId",
)

#: 素で読んでいる形。`n.strokeWeight` / `node.cornerRadius`
BARE_RX = None


def check_style(paths):
    """器が figma.mixed を素で読んでいないかを見る。

    **同じ行の同じキーは1件に畳む。** また、**手前3行までに同じキーの
    mixed の見張り**（`n.fills !== figma.mixed` / `typeof … === 'symbol'`）が
    あれば、その塊の中は守られているとみなす。

    ここは**件数のラチェット**で使う（`expectedBareMixed`）。行だけを見て
    塊の外まで正確に判定するのは無理なので、**増えたら落とす**形にする。
    """
    import re as _re
    global BARE_RX
    if BARE_RX is None:
        BARE_RX = _re.compile(
            r"(?<![\w.])(\w+)\.(" + "|".join(MIXED_PROPS) + r")\b")
    ng = []
    for f in paths:
        if not f.exists() or f.suffix != ".js":
            continue
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("//") or s.startswith("*"):
                continue
            seen = set()
            for m in BARE_RX.finditer(line):
                obj, prop = m.group(1), m.group(2)
                if prop in seen:
                    continue                       # 同じ行の同じキーは1件
                seen.add(prop)
                guard = "\n".join(lines[max(0, i - 4):i])
                if prop in guard and ("figma.mixed" in guard or "typeof" in guard):
                    continue                       # 手前に見張りがある
                ng.append((f.name, i,
                           f"`{obj}.{prop}` を素で読んでいます。"
                           f"**figma.mixed（Symbol）を返しうる値です。"
                           f"来ると書き出しごと止まります。**"
                           f" `val({obj}, '{prop}')` を通してください"))
    return ng


#: 「無し」を表す変異の値
OFF_RX = re.compile(r"([A-Za-z]\w*)\s*=\s*(?:False|None|Off|No)\b", re.I)


def child_names(sets):
    """書き出しの中で**実際に子として現れている名前**。手で並べない。"""
    names = set()
    for v in sets.values():
        if not isinstance(v, dict):
            continue
        for c in (v.get("childSizes") or {}).get("children") or []:
            if c.get("n"):
                names.add(c["n"])
    return names


def check_samples(doc):
    """見本の変異が、子を隠していないかを見る。"""
    sets = doc.get("componentSets") or doc
    if not isinstance(sets, dict):
        return [], 0
    names = child_names(sets)
    ng, seen = [], 0
    for key, v in sorted(sets.items()):
        if not isinstance(v, dict):
            continue
        cs = v.get("childSizes")
        if not cs:
            continue
        seen += 1
        sample = cs.get("sample") or ""
        bad = [a for a, in ((m.group(1),) for m in OFF_RX.finditer(sample))
               if a in names]
        if bad:
            ng.append((key, sample, sorted(set(bad)),
                       len(cs.get("children") or [])))
    return ng, seen


def digest_of(path):
    return text_digest(path.read_bytes().decode("utf-8", errors="replace"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="書き出しを作った器の保存と指紋")
    ap.add_argument("--config", type=Path, default=Path("design/exporters.json"))
    ap.add_argument("--root", type=Path)
    ap.add_argument("--update", action="store_true",
                    help="いまの器の指紋を書き出しに記録し直す（取り直した直後だけ）")
    ap.add_argument("--style", action="store_true",
                    help="器が figma.mixed を素で読んでいないかを見る")
    ap.add_argument("--exporters", type=Path,
                    help="--style で見る器の置き場（既定: 設定の器の親）")
    ap.add_argument("--samples", type=Path, metavar="COMPONENTS_JSON",
                    help="見本の変異が子を隠していないかを見る")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.samples:
        if not args.samples.exists():
            print(f"書き出しがありません: {args.samples}", file=sys.stderr)
            return 2
        try:
            doc = json.loads(args.samples.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"書き出しが読めません: {args.samples}: {e}", file=sys.stderr)
            return 2
        ng, seen = check_samples(doc)
        if seen == 0:
            print(f"childSizes を持つセットがありません: {args.samples}\n"
                  f"  **0件は「綺麗」ではなく「見ていない」です。**", file=sys.stderr)
            return 2
        if ng:
            print(f"見本の変異が子を隠しています（{len(ng)}/{seen} セット）:",
                  file=sys.stderr)
            for key, sample, bad, n in ng:
                print(f"  {key}: 見本が `{' / '.join(bad)}` を無しにしています"
                      f"（子 {n}個）\n    見本: {sample}\n"
                      f"    **その子の寸法は、どの書き出しにもありません。**",
                      file=sys.stderr)
            print(f"\n  器が全変異を見て子の union を取るようにするか、"
                  f"子を持つ変異を見本にしてください。", file=sys.stderr)
            return 1
        print(f"見本の変異（{seen} セット）: 子を隠しているものはありません。")
        return 0

    if args.style:
        d = args.exporters or (args.config.parent / "figma" / "exporters")
        if not d.exists():
            print(f"器の置き場がありません: {d}\n"
                  f"  **0件は「綺麗」ではなく「見ていない」です。**", file=sys.stderr)
            return 2
        files = sorted(d.glob("*.js"))
        if not files:
            print(f"器が1つもありません: {d}\n"
                  f"  **0件は「綺麗」ではなく「見ていない」です。**", file=sys.stderr)
            return 2
        ng = check_style(files)
        exp = None
        if args.config.exists():
            try:
                exp = json.loads(args.config.read_text(
                    encoding="utf-8")).get("expectedBareMixed")
            except (OSError, json.JSONDecodeError):
                exp = None
        if isinstance(exp, int):
            if len(ng) > exp:
                print(f"器が figma.mixed を素で読んでいる箇所が {len(ng)} 件で、"
                      f"宣言（expectedBareMixed: {exp}）を上回りました"
                      f"（器 {len(files)} 本）:", file=sys.stderr)
                for name, line, why in ng[:12]:
                    print(f"  {name}:{line}  {why}", file=sys.stderr)
                return 1
            if len(ng) < exp:
                print(f"注意: 素で読んでいる箇所が {len(ng)} 件に減りました。"
                      f"{args.config.name} の expectedBareMixed を下げてください。")
            print(f"器の書き方（{len(files)} 本）: 素で読んでいる箇所 {len(ng)} 件"
                  f"（宣言 {exp}）")
            return 0
        if ng:
            print(f"器が figma.mixed を素で読んでいる箇所が {len(ng)} 件あります"
                  f"（器 {len(files)} 本）。"
                  f"{args.config.name} に expectedBareMixed を書くと"
                  f"**増えたときに落ちます**（いまは数えるだけ）:")
            for name, line, why in ng[:12]:
                print(f"  {name}:{line}  {why}")
            return 0
        print(f"器の書き方（{len(files)} 本）: 0 件")
        return 0

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f"  書き出しを作った器が保存されているかを、誰も見ていない状態です。",
              file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = (args.root.resolve() if args.root
            else args.config.resolve().parent.parent)
    ex_dir = base / conf.get("exports_dir", "design/figma")
    exclude = set(conf.get("exclude", []))

    if not ex_dir.exists():
        print(f"書き出しの置き場がありません: {ex_dir}", file=sys.stderr)
        return 2

    files = [f for f in sorted(ex_dir.glob("*.json")) if f.name not in exclude]
    if not files:
        print(f"書き出しが1件もありません: {ex_dir}（空振り）", file=sys.stderr)
        return 2

    allow = {}
    problems, updated, okc = [], 0, 0
    for a in conf.get("allow", []):
        if not isinstance(a, dict) or not a.get("why") or not a.get("reviewBy"):
            problems.append(f"allow の「{a}」に why と reviewBy が要ります")
            continue
        if a["reviewBy"] < TODAY:
            problems.append(f"allow の「{a['file']}」は期限（{a['reviewBy']}）を"
                            f"過ぎています。**器を保存して producer を書いてください**")
        allow[a["file"]] = a["why"]

    for f in files:
        if f.name in allow and not args.update:
            print(f"  例外: {f.name}（{allow[f.name]}）")
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{f.name}: 読めません（{e}）")
            continue
        meta = doc.get("$meta") if isinstance(doc, dict) else None
        if not isinstance(meta, dict) or not meta.get("producer"):
            problems.append(
                f"{f.name}: $meta.producer がありません。"
                f"**どの器が作ったか分からない書き出しは、正として使えません**")
            continue
        prod = base / meta["producer"]
        if not prod.exists():
            problems.append(f"{f.name}: 器が実在しません: {meta['producer']}"
                            f"（名前を書いただけの状態）")
            continue
        now = digest_of(prod)
        rec = meta.get("producerDigest")
        if args.update:
            if rec != now:
                meta["producerDigest"] = now
                f.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
                updated += 1
            continue
        if not rec:
            problems.append(f"{f.name}: producerDigest がありません。"
                            f"--update で記録してください")
        elif rec != now:
            problems.append(
                f"{f.name}: 器が変わっています（{meta['producer']}）\n"
                f"      記録: {rec[:16]}…  いま: {now[:16]}…\n"
                f"      **器を直したのに書き出しを取り直していません。**"
                f"取り直してから --update してください")
        else:
            okc += 1

    if args.update:
        print(f"器の指紋を記録し直しました: {updated}件 / 全{len(files)}件")
        # **--update でも problems を捨てない**（2026-09-02。planttalk 指摘9）。
        # それまで producer が無い・器が実在しない・**allow の期限切れ**を
        # 表示せずに捨てて常に成功していた。保守用のコマンドで
        # **期限切れの棚卸しを消せてしまう**のは、この道具が守ろうとしている
        # 規律と噛み合わない。終了コードは 0 のままにして、表示だけする
        if problems:
            print(f"\n**--update では直らない問題が {len(problems)} 件あります"
                  f"（終了コードは 0 ですが、放置しないでください）:**", file=sys.stderr)
            for m in problems:
                print(f"  - {m}", file=sys.stderr)
        return 0
    print(f"書き出しの器: {okc}/{len(files)}件が保存済みで指紋も一致")
    if problems:
        print("\n書き出しの出どころが確かめられていません:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design" / "figma").mkdir(parents=True)
        prod = root / "design" / "export_components.mjs"
        prod.write_text("// 書き出し器 v1\n", encoding="utf-8")
        cfg = root / "design" / "exporters.json"
        cfg.write_text(json.dumps({"exports_dir": "design/figma"}), encoding="utf-8")
        out = root / "design" / "figma" / "components.json"
        argv = ["--config", str(cfg), "--root", str(root)]

        def write(meta):
            out.write_text(json.dumps({"$meta": meta, "componentSets": {}}),
                           encoding="utf-8")

        write({"producer": "design/export_components.mjs"})
        if main(argv) != 1:
            print("self-test NG: producerDigest が無いのに通した"); ok = False
        if main(argv + ["--update"]) != 0:
            print("self-test NG: --update に失敗した"); ok = False
        if main(argv) != 0:
            print("self-test NG: 記録直後なのに落ちた"); ok = False

        prod.write_text("// 書き出し器 v2（直した）\n", encoding="utf-8")
        if main(argv) != 1:
            print("self-test NG: 器が変わったのに落ちなかった"); ok = False
        main(argv + ["--update"])

        write({})
        if main(argv) != 1:
            print("self-test NG: producer が無いのに通した"); ok = False

        write({"producer": "design/nope.mjs"})
        if main(argv) != 1:
            print("self-test NG: 器が実在しないのに通した"); ok = False

        # 期限つきの例外は通り、期限切れは落ちる
        def with_allow(by):
            cfg.write_text(json.dumps({"exports_dir": "design/figma", "allow": [
                {"file": "components.json", "why": "器の特定が未了",
                 "reviewBy": by}]}), encoding="utf-8")
            return main(argv)
        if with_allow("2099-01-01") != 0:
            print("self-test NG: 期限内の例外で落ちた"); ok = False
        if with_allow("2020-01-01") != 1:
            print("self-test NG: 期限切れの例外を通した"); ok = False
        cfg.write_text(json.dumps({"exports_dir": "design/figma"}), encoding="utf-8")

        out.unlink()
        if main(argv) != 2:
            print("self-test NG: 書き出しが0件なのに 2 で止まらなかった"); ok = False

    # ─── --style（#32・qnd-database 2026-09-03 の再現）──────────────
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td2:
        d = Path(td2)
        (d / "bad.js").write_text(
            "const p = [];\n"
            "p.push('sw=' + n.strokeWeight);\n", encoding="utf-8")
        r = check_style([d / "bad.js"])
        if not r or "strokeWeight" not in r[0][2]:
            print("self-test NG: 素で読む strokeWeight を見逃した"); ok = False
        (d / "good.js").write_text(
            "const p = [];\n"
            "p.push('sw=' + val(n, 'strokeWeight'));\n"
            "p.push('r=' + num(n, 'cornerRadius'));\n", encoding="utf-8")
        if check_style([d / "good.js"]):
            print(f"self-test NG: val() を通した器を咎めた: "
                  f"{check_style([d / 'good.js'])}"); ok = False
        # 自分で mixed を見ている行は咎めない（ひな形の中身）
        (d / "own.js").write_text(
            "if (n.strokeWeight !== figma.mixed) { }\n"
            "if (typeof n.cornerRadius === 'symbol') { }\n", encoding="utf-8")
        if check_style([d / "own.js"]):
            print("self-test NG: 自分で mixed を見ている行を咎めた"); ok = False
        # コメント行は咎めない
        (d / "cmt.js").write_text("// n.strokeWeight は mixed を返しうる\n",
                                  encoding="utf-8")
        if check_style([d / "cmt.js"]):
            print("self-test NG: コメントを咎めた"); ok = False
        # **main の帰り道まで見る**（2026-09-05 変異試験: check_style だけ見ていて、
        # `return 1` を `return 0` にしても自己検査が通った）
        cfg2 = d / "exporters.json"
        cfg2.write_text(json.dumps({"exports_dir": "figma", "expectedBareMixed": 0}),
                        encoding="utf-8")
        sargv = ["--config", str(cfg2), "--style", "--exporters", str(d)]
        if main(sargv) != 1:
            print("self-test NG: 宣言（0）を上回る素読みがあるのに 1 で落ちなかった"); ok = False
        cfg2.write_text(json.dumps({"exports_dir": "figma", "expectedBareMixed": 1}),
                        encoding="utf-8")
        if main(sargv) != 0:
            print("self-test NG: 宣言どおりの件数なのに落ちた"); ok = False

    # ─── --samples（#22・FlashEnglish 2026-09-03 の再現）──────────────
    DOC = {"componentSets": {
        "Nav": {"childSizes": {"sample": "Selected=False, State=Enabled",
                               "children": [{"n": "PrependIcon", "w": 24}]}},
        "Buttons/L": {"childSizes": {
            "sample": "Style=Neutral, Icon=False, PrependIcon=False",
            "children": [{"n": "Label"}]}}}}
    ng, seen = check_samples(DOC)
    if seen != 2:
        print(f"self-test NG: childSizes の数が違う: {seen}"); ok = False
    if len(ng) != 1 or ng[0][0] != "Buttons/L":
        print(f"self-test NG: 子を隠す見本を捕まえていない: {[n[0] for n in ng]}")
        ok = False
    if ng and ng[0][2] != ["PrependIcon"]:
        print(f"self-test NG: 隠している軸が違う: {ng[0][2]}"); ok = False
    # **状態の軸（Selected=False）では鳴らない**——鳴ると誰も読まなくなる
    if any(n[0] == "Nav" for n in ng):
        print("self-test NG: 状態の軸で鳴った"); ok = False
    # 子として現れない名前の軸では鳴らない（一覧を手で持たないことの確認）
    D2 = {"componentSets": {"X": {"childSizes": {
        "sample": "Closable=False", "children": [{"n": "Label"}]}}}}
    if check_samples(D2)[0]:
        print("self-test NG: 子に現れない名前の軸で鳴った"); ok = False
    # 子を持つ変異を見本にすれば通る
    D3 = {"componentSets": {"X": {"childSizes": {
        "sample": "PrependIcon=True", "children": [{"n": "PrependIcon"}]}}}}
    if check_samples(D3)[0]:
        print("self-test NG: 子のある見本を咎めた"); ok = False
    # main の帰り道: 隠している見本があれば 1、無ければ 0
    with _tf.TemporaryDirectory() as td3:
        sp = Path(td3) / "components.json"
        sp.write_text(json.dumps(DOC), encoding="utf-8")
        if main(["--samples", str(sp)]) != 1:
            print("self-test NG: 子を隠す見本があるのに 1 で落ちなかった"); ok = False
        sp.write_text(json.dumps(D3), encoding="utf-8")
        if main(["--samples", str(sp)]) != 0:
            print("self-test NG: 隠していないのに落ちた"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
