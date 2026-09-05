#!/usr/bin/env python3
"""検査が「見なかったもの」を機械が出す（2026-08-29 新設）。

## なぜ要るか

いま完了レポートの「残っている限界」を書いているのは **AI 自身**。
自己申告なので、書き落とせば報告書は合格したように読める。
記録層を廃止したのと同じ構図——自分の答案を自分で採点している。

実害: `check_flutter_gaps.py` が「**× 0件 / exit 0**」と報告した裏で、
Figma の26セットのうち **10セットに評価が付いていなかった**。
「0件」は「違反が0件」であって「10セットを見ていない」とは書いていない。
出力上はまったく同じに見える。

この道具は各検査の**穴**を集めて、そのまま報告書に貼れる形で出す。
AI が短くできない。

## 集めるもの

| 出どころ | 穴 |
|---|---|
| 実コードの走査 | **1件も発火していないルール**（種が無ければ「効いているか不明」） |
| 同上 | `harness-ignore` で除外した箇所と理由・期限 |
| `figma/frames.json` | 画面はあるが照合テストが見当たらない |
| `page-scope.json` | いま参照を止めているページ |
| 設定の `notVerifiable` | **数値で検証できないと宣言したもの**（ぼかし・影など） |

## 集められないもの（正直に書く）

- 「照合テストが**正しく**書けているか」。存在の有無しか見ない
- 実装の意味的な誤り。これは定性検査（人）の領域
- `notVerifiable` は人が書く宣言。ここだけは手書きが残る（機械には
  「何が数値化できないか」が分からないため）。**空なら空と出す**
- 確かめた方法: --self-test（穴を仕込んで、出力に現れること）

## 使い方（案件のルートで）

    python3 design/harness/tools/gap_report.py --config design/gaps.json

出力は `design/.gaps.md` にも書く。**マシンごとの生成物なので .gitignore に入れる。**

    # design/gaps.json
    {
      "rules": "design/rules.json",
      "seeds": "design/seeds",
      "frames": "../design-systems/414/figma/frames.json",
      "page_scope": "design/figma/page-scope.json",
      "tests": "test",
      "notVerifiable": [
        {"item": "ぼかしの半径", "why": "描画結果でしか確かめられない",
         "reviewBy": "2026-12-31"}
      ]
    }

`notVerifiable` は **why（なぜ測れないか）と reviewBy（棚卸しの期限）が必須**
（aub 提案8・2026-08-29）。理由が消えた項目が黙って素通りし続けるのを止める。
期限を過ぎたら落ちるので、そのとき「まだ測れないか」を確かめて期限を延ばすか、
測れるようになっていたら宣言から消す。
"""

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine" / "design_check.py"
IGNORE_RX = re.compile(r"harness-ignore[^\n]*")

#: 棚卸しの期限の比較に使う。テストから差し替えられるようにモジュール変数にする
TODAY = date.today().isoformat()


def load_engine(path=ENGINE):
    spec = importlib.util.spec_from_file_location("_engine", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _decl(config, key):
    """宣言の数を見出しに並べる。「5件」だけでは壊れていると分からない（#30 (c)）。"""
    v = config.get(key)
    return f"（宣言 {v}）" if isinstance(v, int) else ""


def scan_project(engine, config, project_root):
    """実コードを走査し、ルールごとの発火件数と除外の一覧を返す。"""
    hits, ignored, read = {}, [], 0
    for rule in config.get("rules", []):
        if rule.get("id"):
            hits.setdefault(rule["id"], 0)
    for path in sorted(project_root.rglob("*")):
        if set(path.relative_to(project_root).parts) & engine.SKIP_DIRS:
            continue
        _, _, obs, state = engine.scan_path(path, config, project_root, {})
        if state is not True:
            continue
        read += 1
        for o in obs:
            if o.get("kind") == "hit":
                hits[o["rule"]] = hits.get(o["rule"], 0) + 1
            elif str(o.get("kind", "")).startswith("ignored"):
                ignored.append(o)
    return hits, ignored, read


def seeded_rules(seeds_dir):
    exp = seeds_dir / "expected.json" if seeds_dir else None
    if not exp or not exp.exists():
        return set()
    try:
        d = json.loads(exp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {k for k, v in d.items() if not k.startswith("$") and k != "*" and v}


def screens_without_test(frames_path, tests_dir):
    if not frames_path or not frames_path.exists():
        return None, "frames.json がありません（画面固有の値の照合先が無い状態です）"
    try:
        frames = json.loads(frames_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"frames.json が読めません: {e}"
    names = list(frames.get("frames", frames)) if isinstance(frames, dict) else []
    if not tests_dir or not tests_dir.exists():
        return names, f"テストの置き場がありません: {tests_dir}"
    blob = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in tests_dir.rglob("*") if f.is_file() and f.suffix in
        (".dart", ".ts", ".tsx", ".js", ".mjs", ".py"))
    return [n for n in names if n not in blob], None


def main(argv=None):
    ap = argparse.ArgumentParser(description="検査が見なかったものを出す")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--engine", type=Path, default=ENGINE)
    ap.add_argument("--root", type=Path,
                    help="案件のルート（既定: 設定ファイルの親の親）")
    ap.add_argument("--no-write", action="store_true",
                    help="design/.gaps.md を書かない（試しに回すとき）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = (args.root.resolve() if args.root
            else args.config.resolve().parent.parent)
    rel = lambda k, d=None: (base / conf[k]) if conf.get(k) else d

    engine = load_engine(args.engine)
    rules_path = rel("rules", base / "design" / "rules.json")
    config = engine.load_rules(rules_path)
    if not config:
        print(f"ルールが読めません: {rules_path}", file=sys.stderr)
        return 2

    # 入力が壊れていたら報告を出さない。**この道具の出力は完了レポートの冒頭に
    # そのまま貼る決まり**なので、壊れた設定のまま数字を出すと、限界の報告書の
    # ほうが嘘をつく。判定は engine 側の ratchet() に1本化してある（#30）。
    # 走査の前にルール数だけ先に見る（5/11 で 190 ファイル走査しても無駄なため）。
    errs, warns = engine.ratchet(config)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        print("  この状態の報告は数字が信用できません（除外も一緒に落ちます）。",
              file=sys.stderr)
        return 2

    hits, ignored, read = scan_project(engine, config, base)
    # 自分自身の空振りを先に潰す。読んだファイルが0なら、以下の「0件」は
    # 全部「見ていない」であって「綺麗」ではない（この道具が一番やりがちな嘘）
    if read == 0:
        print(f"デザインハーネス異常: {base} で中身を読んだファイルが 0 です。\n"
              f"  この報告の「発火0」は全部『見ていない』という意味で、"
              f"『綺麗』ではありません。\n"
              f"  --root と rules.json の対象設定（file_extensions / "
              f"exclude_paths）を確かめてください。", file=sys.stderr)
        return 2
    errs, warns = engine.ratchet(config, read)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        print("  この状態の報告は数字が信用できません（除外も一緒に落ちます）。",
              file=sys.stderr)
        return 2

    seeded = seeded_rules(rel("seeds"))
    silent = sorted(r for r, n in hits.items() if n == 0)
    unproven = [r for r in silent if r not in seeded]
    missing_tests, frames_note = screens_without_test(rel("frames"), rel("tests"))

    lines = ["## この実装で機械が見ていないもの（gap_report.py が生成。手で縮めない）", "",
             f"走査したファイル: {read}件{_decl(config, 'expected_targets')} / "
             f"ルール: {len(hits)}件{_decl(config, 'expected_rules')} / "
             f"発火: {sum(hits.values())}件", ""]
    if warns:
        lines += ["- " + w.replace("\n", " ") for w in warns] + [""]

    if unproven:
        lines.append(f"- **効いているか不明なルール（{len(unproven)}件）**: "
                     + " / ".join(unproven))
        lines.append("  実コードで1件も発火せず、種（design/seeds/）も無い。"
                     "コードが綺麗なのか、ルールが死んでいるのか区別が付かない")
    proven_clean = [r for r in silent if r in seeded]
    if proven_clean:
        lines.append(f"- 発火0だが種で発火を確認済み（{len(proven_clean)}件・"
                     f"コードが綺麗という意味）: " + " / ".join(proven_clean))

    if ignored:
        lines.append(f"- **検査から除外した箇所（{len(ignored)}件）**")
        for o in ignored[:12]:
            lines.append(f"  - `{o.get('file')}:{o.get('line')}` "
                         f"{o.get('rule')}（{o.get('kind')}）")
        if len(ignored) > 12:
            lines.append(f"  - ほか {len(ignored) - 12}件")

    if frames_note:
        lines.append(f"- **画面の照合**: {frames_note}")
    elif missing_tests:
        lines.append(f"- **照合テストが見当たらない画面（{len(missing_tests)}件）**: "
                     + " / ".join(missing_tests[:10])
                     + (f" ほか{len(missing_tests) - 10}件" if len(missing_tests) > 10 else ""))

    ps = rel("page_scope")
    if ps and ps.exists():
        try:
            d = json.loads(ps.read_text(encoding="utf-8"))
            lines.append(f"- **参照していない Figma ページ**: フェーズ `{d.get('phase')}`。"
                         f"許可 {d.get('allowed')}。ここに無いページは見ていない")
        except (OSError, json.JSONDecodeError):
            pass

    nv = conf.get("notVerifiable") or []
    nv_problems = []
    if nv:
        lines.append(f"- **数値で検証できないもの（人の目視が要る・{len(nv)}件）**")
        for e in nv:
            if isinstance(e, str):
                lines.append(f"  - {e}")
                nv_problems.append(
                    f"notVerifiable の「{e}」に理由と棚卸しの期限がありません。"
                    f'{{"item": …, "why": …, "reviewBy": "YYYY-MM-DD"}} の形で書いてください')
                continue
            item = e.get("item", "?")
            why, by = e.get("why"), e.get("reviewBy")
            lines.append(f"  - {item}（理由: {why or '未記入'} / 棚卸し: {by or '未設定'}）")
            if not why:
                nv_problems.append(f"notVerifiable の「{item}」に why がありません")
            if not by:
                nv_problems.append(f"notVerifiable の「{item}」に reviewBy がありません")
            elif by < TODAY:
                nv_problems.append(
                    f"notVerifiable の「{item}」は棚卸しの期限（{by}）を過ぎています。"
                    f"**理由がまだ生きているか確かめてください**"
                    f"（測れるようになっていたら消す）")
    else:
        lines.append("- 数値で検証できないものの宣言（`notVerifiable`）が**空**です。"
                     "ぼかし・影・階調など目視が要る項目があるなら、"
                     f"{args.config} に書いてください")

    out = "\n".join(lines)
    print(out)
    # 「見ない」の宣言が形を保っているか（aub 提案8・2026-08-29）。
    # 理由が消えた項目が黙って素通りし続けるのを止める
    if nv_problems:
        print("\n『見ない』の宣言が形を保っていません:", file=sys.stderr)
        for x in nv_problems:
            print(f"  - {x}", file=sys.stderr)
        return 1
    if args.no_write:
        return 0
    dest = base / "design" / ".gaps.md"
    try:
        dest.write_text(out + "\n", encoding="utf-8")
        print(f"\n（{dest} にも書きました。完了レポートにこのまま貼ってください）")
    except OSError:
        pass
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design").mkdir()
        (root / "lib").mkdir()
        (root / "design" / "rules.json").write_text(json.dumps({
            "file_extensions": [".dart"],
            "rules": [
                {"id": "fires", "severity": "error", "pattern": "BAD"},
                {"id": "silent-unseeded", "severity": "error", "pattern": "NEVER_HERE"},
                {"id": "silent-seeded", "severity": "error", "pattern": "ALSO_NEVER"},
            ]}), encoding="utf-8")
        (root / "lib" / "a.dart").write_text(
            "var x = BAD;\nvar y = BAD; // harness-ignore: 移行中 expires=2026-12-31\n",
            encoding="utf-8")
        (root / "design" / "seeds").mkdir()
        (root / "design" / "seeds" / "expected.json").write_text(
            json.dumps({"silent-seeded": 1}), encoding="utf-8")
        (root / "design" / "gaps.json").write_text(json.dumps({
            "rules": "design/rules.json", "seeds": "design/seeds",
            "notVerifiable": []}), encoding="utf-8")

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["--config", str(root / "design" / "gaps.json")])
        out = buf.getvalue()
        checks = [
            ("silent-unseeded" in out, "種の無い沈黙ルールが出ていない"),
            ("silent-seeded" in out, "種のある沈黙ルールが出ていない"),
            ("除外した箇所" in out, "harness-ignore の箇所が出ていない"),
            ("notVerifiable" in out or "空" in out, "notVerifiable が空の注意が無い"),
            ("fires" not in out.split("種で発火")[0].split("不明なルール")[-1].split("\n")[0],
             "発火しているルールが穴として出ている"),
            (rc == 0, f"戻り値が 0 でない: {rc}"),
            ((root / "design" / ".gaps.md").exists(), ".gaps.md が書かれていない"),
        ]
        for good, msg in checks:
            if not good:
                print(f"self-test NG: {msg}"); ok = False

        # notVerifiable の形（aub 提案8）
        cfgp = root / "design" / "gaps.json"
        base = {"rules": "design/rules.json", "seeds": "design/seeds"}

        def with_nv(nv):
            cfgp.write_text(json.dumps({**base, "notVerifiable": nv}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                return main(["--config", str(cfgp)])

        if with_nv([{"item": "ぼかし", "why": "描画でしか分からない",
                     "reviewBy": "2099-01-01"}]) != 0:
            print("self-test NG: 形のそろった notVerifiable で落ちた"); ok = False
        if with_nv(["ぼかし"]) != 1:
            print("self-test NG: 理由の無い notVerifiable を見逃した"); ok = False
        if with_nv([{"item": "ぼかし", "why": "x"}]) != 1:
            print("self-test NG: reviewBy の無い項目を見逃した"); ok = False
        if with_nv([{"item": "ぼかし", "why": "x", "reviewBy": "2020-01-01"}]) != 1:
            print("self-test NG: 期限切れの項目を見逃した"); ok = False
        cfgp.write_text(json.dumps({**base, "notVerifiable": []}), encoding="utf-8")

        # ラチェット（#30・FlashEnglish 2026-09-03 の再現）。
        # ルールが宣言を下回ったまま報告を出すと、除外も一緒に落ちるので
        # 走査対象が膨らみ、まちがった発火が並ぶ。**報告を出さずに落とす。**
        rulesp = root / "design" / "rules.json"
        rules = json.loads(rulesp.read_text(encoding="utf-8"))

        def with_decl(**decl):
            rulesp.write_text(json.dumps({**rules, **decl}), encoding="utf-8")
            gaps = root / "design" / ".gaps.md"
            gaps.unlink(missing_ok=True)
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                rc = main(["--config", str(cfgp)])
            return rc, buf2.getvalue(), gaps.exists()

        rc3, out3, wrote3 = with_decl(expected_rules=11)
        if rc3 != 2:
            print(f"self-test NG: ルール 3/11 でも報告を出した（{rc3}）"); ok = False
        if wrote3:
            print("self-test NG: 壊れた設定のまま .gaps.md を書いた"); ok = False
        if "発火" in out3:
            print("self-test NG: 落ちる前に発火件数を出した"); ok = False

        rc4, _, wrote4 = with_decl(expected_targets=99)
        if rc4 != 2:
            print(f"self-test NG: 対象 1/99 でも報告を出した（{rc4}）"); ok = False
        if wrote4:
            print("self-test NG: 対象が足りないのに .gaps.md を書いた"); ok = False

        # 宣言が見出しに並ぶこと（#30 (c)）。「5件」だけでは壊れていると分からない
        rc5, out5, _ = with_decl(expected_rules=3, expected_targets=1)
        if rc5 != 0:
            print(f"self-test NG: 宣言どおりなのに落ちた（{rc5}）"); ok = False
        if "ルール: 3件（宣言 3）" not in out5:
            print("self-test NG: 見出しにルールの宣言が出ていない"); ok = False
        if "走査したファイル: 1件（宣言 1）" not in out5:
            print("self-test NG: 見出しに対象の宣言が出ていない"); ok = False

        # ルールが増えたときは注意にとどめ、報告は出す（止めるのは減ったときだけ）
        rc6, out6, wrote6 = with_decl(expected_rules=2)
        if rc6 != 0 or not wrote6:
            print(f"self-test NG: ルールが増えただけで止まった（{rc6}）"); ok = False
        if "増えています" not in out6:
            print("self-test NG: 増えた注意が報告に出ていない"); ok = False
        rulesp.write_text(json.dumps(rules), encoding="utf-8")

        # 走査が空振りしたら落ちること（この道具自身の嘘を潰す）
        (root / "lib" / "a.dart").unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            rc2 = main(["--config", str(root / "design" / "gaps.json")])
        if rc2 != 2:
            print(f"self-test NG: 読んだファイル0なのに落ちなかった（{rc2}）"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
