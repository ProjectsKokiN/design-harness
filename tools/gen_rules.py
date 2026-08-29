#!/usr/bin/env python3
"""段の値が入るルールを tokens.json から生成する（2026-08-29 新設）。

## なぜ要るか

`no-offscale-radius` の正規表現に、角丸のスケールが**手で書き写されていた**:

    BorderRadius\\.circular\\(\\s*(?!(?:9999|32|24|16|12|8|4|2|0)(?:\\.0)?\\s*\\))[0-9]

2026-08-29 の確認では 414 の CornerRadius と一致していたが、**Figma で段を1つ足した
瞬間に静かに古くなる**。しかも古くなったことを誰も検知しない——正規表現は動き続け、
新しい段の値を「スケール外」として誤検出するか、逆に消えた段を許し続ける。

これはハーネスが繰り返し潰してきた「手で写した層」そのもの（記録層・DESIGN.md・
検査エンジンの複製と同じ病）。同じ処方を当てる: **生成して、ズレを機械で見る。**

## ルールの3層

| 層 | 置き場 | 中身 |
|---|---|---|
| A スタック共通 | `design-harness/rules/<stack>.json` | 生値の直書き禁止。DS の値に依存しない |
| **B 段の値に依存** | **`<DS>/rules/<stack>.generated.json`（この生成器の出力）** | 角丸・ウェイトのスケール |
| C DS の命名・用途 | `<DS>/rules/<stack>.json` | セマンティックの用途規約（scope-*） |
| D 案件固有 | `<案件>/design/rules.json` | その案件だけの禁止 |

engine の `extends` で下から順に継承する。

## 使い方（DS のルートで）

    python3 <harness>/tools/gen_rules.py --config rules/gen-rules.json          # 生成
    python3 <harness>/tools/gen_rules.py --config rules/gen-rules.json --check  # ズレを見る

`--check` は生成し直して**ディスク上の出力と1バイトでも違えば落ちる**。
tokens.json を取り直したのに生成し直していない状態を捕まえる（べき等性検査）。

## この生成器が捕まえないもの

- スケールに載っている値を「トークンを経由せず」書くこと → A 層の no-raw-* が見る
- 生成した正規表現が実際に発火するか → 種まき欠陥テスト（design/seeds/）が見る
- 確かめた方法: --self-test（段を1つ変えたら --check が落ちること）
"""

import argparse
import json
import sys
from pathlib import Path

#: (stack, scale) -> ルールを組み立てる関数。ここに無い scale は無視して注意を出す
BUILDERS = {}


def builder(stack, scale):
    def deco(fn):
        BUILDERS[(stack, scale)] = fn
        return fn
    return deco


def fmt(v):
    """スケールの値を正規表現の選択肢の形にする（1.0 → 1、0.5 → 0\\.5）。"""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace(".", "\\.")


def alts(values):
    """大きい順に並べた選択肢。長い候補を先に置いて部分一致を避ける。"""
    return "|".join(fmt(v) for v in sorted(set(values), key=float, reverse=True))


@builder("flutter", "radius")
def _radius(values, src):
    return {
        "id": "no-offscale-radius",
        "severity": "error",
        "pattern": (r"BorderRadius\.circular\(\s*(?!(?:" + alts(values) +
                    r")(?:\.0)?\s*\))[0-9]"),
        "forbidden": "角丸のスケールに無い値を使うこと",
        "instead": f"角丸トークンの段を使う（{src} の段: {', '.join(fmt(v) for v in sorted(set(values), key=float))}）。"
                   "必要な段が無ければ実装せず token-missing で報告する",
        "generatedFrom": src,
    }


@builder("flutter", "fontWeight")
def _weight(values, src):
    return {
        "id": "no-offscale-fontweight",
        "severity": "error",
        "pattern": (r"FontWeight\.(?:bold\b|w(?!" +
                    "|".join(fmt(v) + r"\b" for v in
                             sorted(set(values), key=float)) + r")[0-9]+)"),
        "forbidden": "タイポグラフィのスケールに無いウェイトを使うこと",
        "instead": f"ウェイトの段を使う（{src} の段: {', '.join(fmt(v) for v in sorted(set(values), key=float))}）。"
                   "FontWeight.bold は段が曖昧なので使わない",
        "generatedFrom": src,
    }


def pick(tokens, group, prefix=None):
    """tokens.json の1グループから数値を取り出す。"""
    g = tokens.get(group)
    if not isinstance(g, dict):
        raise KeyError(f"tokens.json に {group} がありません")
    out = []
    for k, v in g.items():
        if prefix and not k.startswith(prefix):
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(v)
    if not out:
        raise KeyError(f"{group}{'/' + prefix if prefix else ''} に数値がありません")
    return out


def generate(conf, base):
    tokens_path = (base / conf["tokens"]).resolve()
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    stack = conf["stack"]

    rules, notes = [], []
    for scale, spec in sorted(conf.get("scales", {}).items()):
        fn = BUILDERS.get((stack, scale))
        if not fn:
            notes.append(f"{stack} の scale '{scale}' を組み立てる方法がありません"
                         f"（gen_rules.py に builder を足してください）")
            continue
        group, prefix = spec["group"], spec.get("prefix")
        values = pick(tokens, group, prefix)
        rules.append(fn(values, f"{group}{'/' + prefix if prefix else ''}"))

    meta = tokens.get("$meta", {})
    doc = {
        "$meta": {
            "layer": "B: 段の値に依存",
            "生成物": "手で編集しない。tokens.json を直して gen_rules.py を回す",
            "生成元": conf["tokens"],
            "tokensSyncedAt": meta.get("syncedAt"),
            "tokensSource": meta.get("source"),
            "生成器": "design-harness/tools/gen_rules.py",
        },
        "extends": conf.get("extends", []),
        "rules": rules,
    }
    return doc, notes


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="段の値が入るルールを tokens から生成")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="生成し直して、ディスク上の出力と違えば落ちる")
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
    base = args.config.resolve().parent
    try:
        doc, notes = generate(conf, base)
    except (OSError, KeyError, json.JSONDecodeError) as e:
        print(f"生成に失敗しました: {e}", file=sys.stderr)
        return 2

    out_path = base / conf["out"]
    text = dump(doc)
    for n in notes:
        print(f"  注意: {n}")

    if args.check:
        if not out_path.exists():
            print(f"生成物がありません: {out_path}\n"
                  f"  --check を外して生成してください。", file=sys.stderr)
            return 1
        current = out_path.read_text(encoding="utf-8")
        if current != text:
            print(f"ルールの生成物が tokens.json とズレています: {out_path}\n"
                  f"  tokens.json を取り直したのに生成し直していない可能性があります。\n"
                  f"  直し方: python3 <harness>/tools/gen_rules.py --config {args.config}",
                  file=sys.stderr)
            _show_diff(current, text)
            return 1
        print(f"OK: ルールの生成物は tokens.json と一致しています"
              f"（{len(doc['rules'])}件・{out_path.name}）。")
        return 0

    out_path.write_text(text, encoding="utf-8")
    print(f"生成しました: {out_path}（{len(doc['rules'])}件）")
    for r in doc["rules"]:
        print(f"  {r['id']}  ← {r['generatedFrom']}")
    return 0


def _show_diff(a, b):
    import difflib
    for line in list(difflib.unified_diff(
            a.splitlines(), b.splitlines(),
            fromfile="ディスク上", tofile="tokens から生成", lineterm=""))[:24]:
        print(f"  {line}", file=sys.stderr)


def self_test():
    import tempfile
    ok = True
    tokens = {"$meta": {"syncedAt": "2026-08-29", "source": "test"},
              "CornerRadius": {"Infinity": 9999, "L": 16, "S": 8, "None": 0},
              "Typography": {"Weight/L": 800, "Weight/S": 400, "Size/M": 20}}
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        (base / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
        conf = {"stack": "flutter", "tokens": "tokens.json", "out": "gen.json",
                "scales": {"radius": {"group": "CornerRadius"},
                           "fontWeight": {"group": "Typography", "prefix": "Weight/"}}}
        (base / "c.json").write_text(json.dumps(conf), encoding="utf-8")
        argv = ["--config", str(base / "c.json")]

        if main(argv) != 0:
            print("self-test NG: 生成に失敗した"); ok = False
        doc = json.loads((base / "gen.json").read_text(encoding="utf-8"))

        # 段が正規表現に入っているか
        rad = next(r for r in doc["rules"] if r["id"] == "no-offscale-radius")
        for v in ("9999", "16", "8", "0"):
            if v not in rad["pattern"]:
                print(f"self-test NG: 角丸の段 {v} が正規表現に無い"); ok = False
        # Size/* が Weight のスケールに混ざっていないか（prefix の効き）
        wt = next(r for r in doc["rules"] if r["id"] == "no-offscale-fontweight")
        if "20" in wt["pattern"].replace("800", "").replace("400", ""):
            print("self-test NG: prefix が効かず Size/M が混ざった"); ok = False

        # 生成直後は --check が通る
        if main(argv + ["--check"]) != 0:
            print("self-test NG: 生成直後なのに --check が落ちた"); ok = False

        # 段を変えたら --check が落ちる（これが本体）
        tokens["CornerRadius"]["XS"] = 4
        (base / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8")
        if main(argv + ["--check"]) != 1:
            print("self-test NG: 段を足したのに --check が落ちなかった"); ok = False
        if main(argv) != 0 or main(argv + ["--check"]) != 0:
            print("self-test NG: 生成し直しても一致しない（べき等でない）"); ok = False

        # 生成物を消したら --check が落ちる
        (base / "gen.json").unlink()
        if main(argv + ["--check"]) != 1:
            print("self-test NG: 生成物が無いのに --check が落ちなかった"); ok = False

        # 知らない scale は注意を出して続行（落ちない）
        conf["scales"]["shadowBlur"] = {"group": "Effects"}
        (base / "c.json").write_text(json.dumps(conf), encoding="utf-8")
        if main(argv) != 0:
            print("self-test NG: 知らない scale で落ちた"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
