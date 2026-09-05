#!/usr/bin/env python3
"""同じ絵を2か所で組んでいるのを、実装側から見つける（2026-09-04 新設・#53）。

## 実害（FlashEnglish・2026-09-04）

**1日に2回、同じ形で同じ失敗をしました。** どちらも机上の検査は緑で、
実機を持つ機体が見つけています。

| 直した部品 | 届いていなかった場所 | 症状 |
|---|---|---|
| `Header`（セーフエリア） | トップ画面3つの `StudyTopBlock` | 中央タイトルのアイコンが**7割以上隠れた** |
| `Tabs`（文字の折り返し） | `BottomNavigation` | 「ディクテーショ」で切れた |

**どちらも「部品は直したが、同じ絵を手で組んでいる画面には届いていない」形です。**

## なぜ既存の段では捕まらないか

**分母がどれも Figma 側です。**

| 道具 | 分母 |
|---|---|
| `impl_coverage_check` | Figma にあるものが実装されているか |
| `tree_test_check` | 状態とスロットを持つセットに widget test があるか |
| 案件の `component_spec_test` | 変異表を読む部品が数値を持っていないか（**読まない手組みは対象外**） |
| `duplication_check` | **複数案件に**同じ名前で中身の違うファイルがないか |

**実装側から見た重複を数えるものがありません。**

前の監査は「Figma が部品を置いているのに実装が手組みしている箇所は 0 件」と
報告しました。**間違ってはいませんが、見ている向きが違いました。**
Figma のトップ画面が Header を使っていなければ、その監査の分母に入りません。
**必要なのは「Figma と実装の対応」ではなく「実装の中の重複」でした。**

## 見るもの

    python3 tools/impl_duplication_check.py --config design/impl-duplication.json

対応表（`component-map.json`）に載っている部品の実装ファイルから
**トークンの並び**を取り、**その部品を使っていないファイルが同じ並びを
自前で持っている**箇所を出します。

「並び」は `AppSpace.gapM` `AppColor.frameNeutralDefault` のような
**トークンの列**です。値ではなく**組み合わせ**を見るので、数値を変えただけでは
逃げられません。

## 捕まえないもの

- **同じ絵かどうか**の最終判断。**似た並びを出すところまで**で、
  同じものかは人が見ます
- トークンを使わない手組み（生の数値だけで組んだもの）。そこは
  `impl_value_check` の領域です
- 確かめた方法: --self-test（部品の並びを別ファイルに写すと出ること）
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: トークンの参照。`AppSpace.gapM` / `AppColor.frameNeutralDefault`
TOKEN_RX = re.compile(r"\bApp[A-Z]\w*\.[a-zA-Z_]\w*")
#: 何個そろえば「同じ並び」とみなすか
DEFAULT_RUN = 4


def token_runs(text, size):
    """トークンの並びを、長さ `size` の窓で取り出す。"""
    toks = TOKEN_RX.findall(text)
    # **特徴の無い並びは数えない。** `AppSpacing.m` が4つ並ぶ窓は、余白を持つ画面なら
    # どこにでも出る（FlashEnglish 2026-09-05: 4件の誤検出が全部これ）。
    # 窓の中に**3種類以上**のトークンがあるものだけを「同じ絵」の印に使う
    return {tuple(toks[i:i + size]) for i in range(max(0, len(toks) - size + 1))
            if len(set(toks[i:i + size])) >= 3}


def impl_files(map_path, base):
    """対応表に載っている部品の実装ファイルを返す（クラス名 → ファイル）。"""
    try:
        doc = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    names = set()
    direct = {}

    def add(x):
        """`impl` の書き方は1つではない。**実データから受ける形を増やす。**

        aub: `"lib/ui/widgets/chips.dart#ChipsDefault"`（パス＋クラス）
        FlashEnglish: `[{"path": "…", "class": "ButtonsM", "note": "…"}]`
        ひな形: `["AppButtonL"]`（クラス名の配列）
        """
        if isinstance(x, dict):
            cls, path = x.get("class"), x.get("path")
            if isinstance(cls, str) and cls.strip():
                names.add(cls.strip())
                if isinstance(path, str) and path.strip():
                    direct[cls.strip()] = path.strip()
            return
        if not isinstance(x, str) or not x.strip():
            return
        if "#" in x:
            path, cls = x.split("#", 1)
            names.add(cls.strip())
            direct[cls.strip()] = path.strip()
        else:
            names.add(x.strip())

    if isinstance(doc, dict) and isinstance(doc.get("components"), list):
        for c in doc["components"]:
            v = c.get("impl")
            for x in (v if isinstance(v, list) else [v]):
                add(x)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            if k.startswith("$"):
                continue
            names.add(k)
            for x in (v if isinstance(v, list) else [v]):
                add(x)
    out = {}
    for cls, path in direct.items():
        f = base.parent / path if not (base / path).exists() else base / path
        if f.exists():
            out[cls] = f
    for f in sorted(base.rglob("*.dart")):
        if f.name.endswith(".g.dart") or ".dart_tool" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for n in names:
            if n in out:
                continue
            if re.search(r"\bclass\s+" + re.escape(n) + r"\b", text):
                out[n] = f
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="実装の中の重複を見つける")
    ap.add_argument("--config", type=Path,
                    default=Path("design/impl-duplication.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.config.exists():
        print(f"設定がありません: {args.config}\n"
              f'  例: {{"map": "design/component-map.json", "lib": "lib",\n'
              f'        "run": 4, "expectedPairs": 0, "許す": {{}}}}\n'
              f"  **実装の中の重複を、誰も見ていない状態です。**", file=sys.stderr)
        return 2
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        return 2
    base = args.root.resolve()
    lib = base / conf.get("lib", "lib")
    mp = base / conf.get("map", "design/component-map.json")
    size = int(conf.get("run", DEFAULT_RUN))
    if not lib.exists() or not mp.exists():
        print(f"実装か対応表がありません: {lib} / {mp}", file=sys.stderr)
        return 2

    comps = impl_files(mp, lib)
    if not comps:
        print(f"対応表の部品が実装に1つも見つかりません: {mp}\n"
              f"  **0件は「重複なし」ではなく「見ていない」です。**",
              file=sys.stderr)
        return 2

    allow = conf.get("許す") or {}
    pairs = []
    for name, cf in sorted(comps.items()):
        runs = token_runs(cf.read_text(encoding="utf-8", errors="ignore"), size)
        if not runs:
            continue
        for f in sorted(lib.rglob("*.dart")):
            if f == cf or f.name.endswith(".g.dart"):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\b" + re.escape(name) + r"\s*\(", text):
                continue        # その部品を使っているので手組みではない
            shared = runs & token_runs(text, size)
            if not shared:
                continue
            rel = str(f.relative_to(base))
            why = allow.get(f"{name}:{rel}") or allow.get(rel)
            if isinstance(why, str) and why.strip():
                continue
            pairs.append((name, cf.relative_to(base), rel, sorted(shared)[0]))

    exp = conf.get("expectedPairs")
    if isinstance(exp, int) and len(pairs) <= exp:
        if len(pairs) < exp:
            print(f"注意: 重複が {len(pairs)} 件に減りました。"
                  f"{args.config.name} の expectedPairs を下げてください。")
        print(f"実装の中の重複: {len(pairs)} 件（宣言 {exp}・部品 {len(comps)} 件）")
        return 0
    if pairs:
        print(f"**同じ絵を2か所で組んでいる可能性があります**"
              f"（部品 {len(comps)} 件）:", file=sys.stderr)
        for name, cf, rel, run in pairs[:15]:
            print(f"  {rel} が `{name}`（{cf}）と同じ並びを持っています\n"
                  f"    共通: {' → '.join(run)}\n"
                  f"    **部品を直してもここには届きません。**"
                  f"部品を使うか、{args.config.name} の「許す」に理由を"
                  f"書いてください。", file=sys.stderr)
        if len(pairs) > 15:
            print(f"  …ほか {len(pairs) - 15} 件", file=sys.stderr)
        return 1
    print(f"実装の中の重複: 0 件（部品 {len(comps)} 件）")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "lib" / "widgets").mkdir(parents=True)
        (root / "lib" / "screens").mkdir()
        (root / "design").mkdir()
        head = root / "lib" / "widgets" / "header.dart"
        scr = root / "lib" / "screens" / "top.dart"
        mp = root / "design" / "component-map.json"
        cp = root / "design" / "impl-duplication.json"
        mp.write_text(json.dumps({"components": [
            {"figma": "Header", "impl": ["AppHeader"]}]}), encoding="utf-8")
        head.write_text(
            "class AppHeader extends StatelessWidget {\n"
            "  Widget build(c) => Padding(padding: AppSpace.gapL,\n"
            "    child: Container(color: AppColor.frameInverseDefault,\n"
            "      child: Text('x', style: AppText.headlineS),\n"
            "      decoration: AppShadow.subtler));\n}\n", encoding="utf-8")

        def run(src, conf=None):
            scr.write_text(src, encoding="utf-8")
            cp.write_text(json.dumps(conf or {"map": "design/component-map.json",
                                              "lib": "lib"}, ensure_ascii=False),
                          encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(["--config", str(cp), "--root", str(root)])
            return rc, buf.getvalue()

        # 部品を使っている画面は咎めない
        rc, out = run("class Top extends StatelessWidget {\n"
                      "  Widget build(c) => AppHeader();\n}\n")
        if rc != 0:
            print(f"self-test NG: 部品を使う画面で落ちた（{rc}）\n   {out[:300]}")
            ok = False

        # **同じ並びを手で組んでいる**（実害そのものの形）
        rc, out = run(
            "class Top extends StatelessWidget {\n"
            "  Widget build(c) => Padding(padding: AppSpace.gapL,\n"
            "    child: Container(color: AppColor.frameInverseDefault,\n"
            "      child: Text('x', style: AppText.headlineS),\n"
            "      decoration: AppShadow.subtler));\n}\n")
        if rc != 1 or "同じ並びを持っています" not in out:
            print(f"self-test NG: 手組みの重複を見逃した（{rc}）\n   {out[:400]}")
            ok = False
        if "部品を直してもここには届きません" not in out:
            print("self-test NG: なぜ問題かを書いていない"); ok = False

        # 理由つきで許せば通る
        rc, _ = run(
            "class Top extends StatelessWidget {\n"
            "  Widget build(c) => Padding(padding: AppSpace.gapL,\n"
            "    child: Container(color: AppColor.frameInverseDefault,\n"
            "      child: Text('x', style: AppText.headlineS),\n"
            "      decoration: AppShadow.subtler));\n}\n",
            {"map": "design/component-map.json", "lib": "lib",
             "許す": {"lib/screens/top.dart": "Figma もここは別の組み方"}})
        if rc != 0:
            print("self-test NG: 理由つきで許しても落ちた"); ok = False

        # 並びが短ければ出ない（たまたま同じトークンを使っただけ）
        rc, _ = run("class Top { Widget b() => Text('x', style: AppText.headlineS); }\n")
        if rc != 0:
            print("self-test NG: 短い一致で鳴った"); ok = False

        # 対応表の部品が実装に無ければ落ちる（この道具自身の空振り）
        head.unlink()
        rc, out = run("class Top {}\n")
        if rc != 2 or "見ていない" not in out:
            print(f"self-test NG: 部品0件で通した（{rc}）"); ok = False
    # 特徴の無い並び（同じトークンの連続）は印にしない
    if token_runs("AppSpacing.m AppSpacing.m AppSpacing.m AppSpacing.m AppSpacing.m", 4):
        print("self-test NG: 同じトークンの連続を印にした"); ok = False
    if not token_runs("AppSpacing.m AppText.body AppRadius.s AppSpacing.l", 4):
        print("self-test NG: 3種類以上の並びを印にしていない"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
