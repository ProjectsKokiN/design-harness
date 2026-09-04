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

## 捕まえないもの

- 器を**回した結果が正しいか**。それは書き出しの中身の検査（照合テスト）の領域
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
import sys
from datetime import date
from pathlib import Path

TODAY = date.today().isoformat()

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fingerprint"))
from text_digest import text_digest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）


def digest_of(path):
    return text_digest(path.read_bytes().decode("utf-8", errors="replace"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="書き出しを作った器の保存と指紋")
    ap.add_argument("--config", type=Path, default=Path("design/exporters.json"))
    ap.add_argument("--root", type=Path)
    ap.add_argument("--update", action="store_true",
                    help="いまの器の指紋を書き出しに記録し直す（取り直した直後だけ）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f"  書き出しを作った器が保存されているかを、誰も見ていない状態です。",
              file=sys.stderr)
        return 1
    conf = json.loads(args.config.read_text(encoding="utf-8"))
    base = (args.root.resolve() if args.root
            else args.config.resolve().parent.parent)
    ex_dir = base / conf.get("exports_dir", "design/figma")
    exclude = set(conf.get("exclude", []))

    if not ex_dir.exists():
        print(f"書き出しの置き場がありません: {ex_dir}", file=sys.stderr)
        return 1

    files = [f for f in sorted(ex_dir.glob("*.json")) if f.name not in exclude]
    if not files:
        print(f"書き出しが1件もありません: {ex_dir}（空振り）", file=sys.stderr)
        return 1

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
        if main(argv) != 1:
            print("self-test NG: 書き出しが0件なのに落ちなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
