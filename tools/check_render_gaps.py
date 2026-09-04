#!/usr/bin/env python3
"""Figma の指定のうち Flutter で再現できないものと、判定の網羅を検査する。

【この検査が捕まえるもの】負の spread・内側の影・PROGRESSIVE・行間・
未知のウェイトなど、**値が一致しても描画で別物になる指定**（production-gate 条件5）。
あわせて「Figma の全セットに判定があるか」（網羅）と「Figma に無い記録」（棚卸し）。
【捕まえないもの】値そのものの一致（数値照合の領域）と、判定の中身の正しさ
（判定は人が実測して書く。ここは判定の有無と形しか見ない）。
【確かめた方法】--self-test（入力が欠けたら落ちること・網羅の穴で落ちること）。
414 で穴10件を検出して exit 1（2026-08-28）。

Figma を読んだあと（ハーネスを同期したあと）に必ず走らせる。
判定の根拠は config の ledger が指す台帳を参照（案件ごとに違う）。

    python3 <harness>/tools/check_render_gaps.py --config render-gaps.json

警告があれば終了コード 1 を返す。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

# config JSON（--config）から埋める。414 直下にあった実装を 2026-08-28 に
# design-harness へ回収して案件非依存にしたもの（planttalk 第2便の提案1:
# 「production-gate の条件5を 414 以外のどの案件も測れない」）。
COMPONENTS = None       # 判定記録（components/components.json）
TOKENS = None           # tokens.json
FIGMA_COMPONENTS = None # 全量書き出し（figma/components.json）
IGNORED_TOKENS = set()  # UI に出ない表記用トークン
RENAMED = {}            # 書き出し側の名前 → 判定記録側の名前
LEDGER = None           # 判定の根拠を書いた台帳（案件ごとに違う）
DS_NAME = "?"           # デザインシステム名（表示用）

# Flutter が素直に出せるフォントウェイト
SUPPORTED_WEIGHTS = {100, 200, 300, 400, 500, 600, 700, 800, 900}


def check_effect_styles(doc):
    """エフェクトスタイルの中身を見る。"""
    out = []
    for s in doc.get("effectStyles", []):
        name = s.get("name", "?")
        for e in s.get("effects", []):
            m = re.search(r"spread(-?\d+)", e.replace(" ", ""))
            if m and int(m.group(1)) < 0:
                out.append((
                    "×", f"EffectStyle {name}",
                    f"負の spread（{m.group(1)}）。Flutter は影の矩形が縮んで、"
                    f"要素の高さが 2×|spread| を下回ると影が要素の下に隠れて見えなくなる。"
                    f"blur か色の不透明度で締めること"))
            if "INNER_SHADOW" in e:
                m = re.search(r"spread(\d+)", e.replace(" ", ""))
                if m and int(m.group(1)) > 0:
                    out.append((
                        "×", f"EffectStyle {name}",
                        "内側の影の spread は自前実装（inner_shadow.dart）が未対応"))
                out.append((
                    "△", f"EffectStyle {name}",
                    "内側の影は自前描画。小さい要素で Figma と乖離しやすい"))
            if "PROGRESSIVE" in e:
                out.append((
                    "△", f"EffectStyle {name}",
                    "プログレッシブなぼかしは Flutter に機能が無い。"
                    "一様ぼかし＋マスクの近似になる"))
            if "BACKGROUND_BLUR" in e and "INNER_SHADOW" in " ".join(s.get("effects", [])):
                out.append((
                    "△", f"EffectStyle {name}",
                    "背景ぼかしと内側の影が同居。Flutter では別ウィジェットに分かれ、"
                    "合成が厳密には一致しない"))
    return out


def check_components(doc):
    """コンポーネントが使っている指定を見る。"""
    out = []
    for c in doc.get("componentSets", []):
        name = c.get("name", "?")
        tokens = " | ".join(c.get("tokens", []))
        if "Stroke/Glass" in tokens:
            out.append((
                "○", name,
                "グラデーションの線。Flutter で再現可（GlassOutlinePainter）。"
                "ただし Variables に載らずカラースタイルでしか持てないため同期漏れに注意"))
        m = re.search(r"Weight/(\w+)", tokens)
        if m:
            w = {"S": 400, "M": 600}.get(m.group(1))
            if w is None:
                out.append(("×", name,
                            f"未知のフォントウェイト Weight/{m.group(1)}。"
                            f"Flutter は標準ウェイトに丸めるため fontVariations が要る"))
    return out


def check_tokens(doc):
    """トークン体系から外れた名前を拾う。"""
    out = []
    text = json.dumps(doc, ensure_ascii=False)
    for name in re.findall(r'"([A-Za-z][A-Za-z0-9 ]*\d)"\s*:\s*\{', text):
        if name in IGNORED_TOKENS:
            continue
        if "/" not in name and re.match(r"^[A-Z][a-z]+ \d+$", name):
            out.append(("△", f"Token {name}",
                        f"{DS_NAME} のトークン命名（役割ベース・スラッシュ区切り）から外れている。"
                        "外部ライブラリの残りでないか確認"))
    return out


def check_coverage(doc):
    """判定の網羅を見る（照合の穴を数える）。

    figma/components.json（Figma の現状の全量書き出し）にある component set の
    それぞれに、components/components.json の flutter 判定があるかを突き合わせる。
    無いセットが1つでもあれば ×。

    なぜ要るか: 2026-08-28 の監査で、Figma の 26 セット中 10 セットに判定が無いのに
    このスクリプトが「× 0件」・終了コード 0 で通っていた。判定済みのものだけを見て
    全部を見た顔をする——generation-rules-flutter.md が禁じる「照合の穴を数えない」
    そのものだった。
    """
    out = []
    if not FIGMA_COMPONENTS.exists():
        out.append(("×", "figma/components.json",
                    "全量書き出しが無い。判定の網羅を確かめられない"))
        return out

    figma_doc = json.loads(FIGMA_COMPONENTS.read_text(encoding="utf-8"))
    figma_sets = figma_doc.get("componentSets", {})
    figma_names = set(figma_sets.keys() if isinstance(figma_sets, dict)
                      else (c.get("name") for c in figma_sets))

    rated = set()
    for c in doc.get("componentSets", []):
        if isinstance(c, dict) and "flutter" in c:
            rated.add(c.get("name"))

    missing = sorted(n for n in figma_names
                     if n and RENAMED.get(n, n) not in rated)
    for n in missing:
        out.append(("×", n,
                    "Figma の全量書き出しに存在するが、Flutter 再現性の判定が無い。"
                    "components/components.json に実測して flutter フィールドを足すこと"))

    # 「Figma に見当たらない記録」は再現性の△とは別の軸で数える
    # （414 要望8・2026-08-28: 同じ△に入れると「近似が20件」とも
    # 「棚卸しが11件」とも読めず、改善と片付けの区別がつかなかった）。
    stale = sorted(n for c in doc.get("componentSets", [])
                   if isinstance(c, dict) and (n := c.get("name"))
                   and n not in figma_names and n not in RENAMED.values())
    if stale:
        print(f"記録の整合: Figma に無い記録 {len(stale)} 件"
              f"（棚卸し待ち・各行の note に対応先を書くこと）")
        for n in stale:
            print(f"  - {n}")

    total = len(figma_names)
    covered = total - len(missing)
    print(f"判定の網羅: Figma の {total} セット中 {covered} セットに判定あり"
          f"（穴 {len(missing)}）")
    # 空振り検知（2026-08-29）。書き出しに component set が 0 件だと
    # 「0 セット中 0 セット・穴 0」で通っていた。**穴が無いのではなく、
    # 何も見ていない。** 網羅検査そのものが同じ病にかかっていた
    if total == 0:
        out.append(("×", "figma/components.json",
                    "全量書き出しに component set が 1 件もない。"
                    "『穴 0』は『何も見ていない』という意味。書き出し器か"
                    "パスの指定を確かめること"))
    return out


def load_config(argv=None):
    global COMPONENTS, TOKENS, FIGMA_COMPONENTS, IGNORED_TOKENS, RENAMED
    global LEDGER, DS_NAME
    ap = argparse.ArgumentParser(
        description="Figma の指定のうちスタックで再現できないものと、判定の網羅を見る")
    ap.add_argument("--config", type=Path,
                    help="render-gaps.json（components / tokens / figma_components 等）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return True
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")
    try:
        conf = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
        sys.exit(2)
    base = args.config.resolve().parent
    COMPONENTS = base / conf["components"]
    TOKENS = base / conf["tokens"]
    FIGMA_COMPONENTS = base / conf["figma_components"]
    IGNORED_TOKENS = set(conf.get("ignored_tokens", []))
    RENAMED = dict(conf.get("renamed", {}))
    # 台帳とデザインシステム名は案件ごとに違う。固定文字列にしない
    # （qnd/design-systems 2026-08-28: planttalk で走らせても
    # 「414/FLUTTER_GAPS.md を参照」と出ていた）
    LEDGER = conf.get("ledger", "FLUTTER_GAPS.md")
    DS_NAME = conf.get("name") or base.name
    return False


def main(argv=None):
    if load_config(argv):
        return self_test()

    # 入力が無ければ**落とす**（2026-08-29）。それまで exists() で分岐しており、
    # ファイルが1つでも欠けるとその検査を黙って飛ばして exit 0 を返していた。
    # 「違反 0 件」と「そもそも見ていない」が出力上まったく同じになる型の穴。
    missing = [str(x) for x in (COMPONENTS, TOKENS, FIGMA_COMPONENTS) if not x.exists()]
    if missing:
        print("再現性の判定に必要な入力がありません。**確認せずに通すことはしません**:",
              file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print("  書き出しを取り直すか、render-gaps.json のパスを直してください。",
              file=sys.stderr)
        return 2

    findings = []
    doc = json.loads(COMPONENTS.read_text(encoding="utf-8"))
    findings += check_effect_styles(doc)
    findings += check_components(doc)
    findings += check_coverage(doc)
    findings += check_tokens(json.loads(TOKENS.read_text(encoding="utf-8")))

    # 同じ指摘の重複をまとめる
    seen, uniq = set(), []
    for f in findings:
        if f not in seen:
            seen.add(f)
            uniq.append(f)

    blockers = [f for f in uniq if f[0] == "×"]
    for mark in ("×", "△", "○"):
        rows = [f for f in uniq if f[0] == mark]
        if not rows:
            continue
        label = {"×": "再現できない・別物になる", "△": "近似になる",
                 "○": "再現できる（注意点あり）"}[mark]
        print(f"\n{mark} {label}")
        for _, where, why in rows:
            print(f"  - {where}\n      {why}")

    print(f"\n判定: × {len(blockers)} 件 / "
          f"△ {len([f for f in uniq if f[0]=='△'])} 件 / "
          f"○ {len([f for f in uniq if f[0]=='○'])} 件")
    print(f"詳細は {LEDGER} を参照してください。")
    return 1 if blockers else 0


def self_test():
    """落ちるケースを持つ（2026-08-29 新設。入力欠落と空振りの穴を潰した回）。"""
    import tempfile
    ok = True
    BASE = {
        "components.json": {"componentSets": [{"name": "Button", "flutter": "○"}]},
        "figma.json": {"componentSets": {"Button": {}}},
        "tokens.json": {"Typography": {"Weight/M": 600}},
    }
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def setup(**over):
            """ファイル名をキーにして中身を差し替える。None で削除。"""
            data = dict(BASE)
            data.update(over)
            for name, doc in data.items():
                path = base / name
                if doc is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(json.dumps(doc), encoding="utf-8")
            (base / "c.json").write_text(json.dumps({
                "components": "components.json", "tokens": "tokens.json",
                "figma_components": "figma.json"}), encoding="utf-8")
            return ["--config", str(base / "c.json")]

        def expect(rc, argv, msg):
            nonlocal ok
            got = main(argv)
            if got != rc:
                print(f"self-test NG: {msg}（戻り値 {got}・期待 {rc}）")
                ok = False

        expect(0, setup(), "そろっているのに落ちた")

        # 入力が欠けたら落ちる（黙って飛ばさない）——この回の本体
        for miss in ("components.json", "tokens.json", "figma.json"):
            expect(2, setup(**{miss: None}), f"{miss} が無いのに落ちなかった")

        # 網羅の穴（Figma にあるのに判定が無い）
        expect(1, setup(**{"figma.json": {"componentSets": {"Button": {}, "Card": {}}}}),
               "判定の無いセットがあるのに落ちなかった")

        # 書き出しが空（「穴 0」が「何も見ていない」を意味する場合）
        expect(1, setup(**{"figma.json": {"componentSets": {}}}),
               "書き出しが空なのに『穴 0』で通した")

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
