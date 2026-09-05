#!/usr/bin/env python3
"""参照してよい Figma ページを、フェーズで縛る（2026-08-29 ユーザー確定）。

> Dart によるデザインシステムを作成し、カタログが作成し終わるまで、
> `⚙️_Styles&Components` 以外の Figma ページを参照しない。

**なぜ縛るか。** 画面ページを見ると、AI は部品の仕様を「画面での使われ方」から
推測してしまう。デザインシステムを作る段階で必要なのはコンポーネントの定義であって、
それがどう使われているかではない。推測が入ると、Figma の定義ではなく AI の解釈が
実装に混ざる。既存の実害: 2026-08-07 に Sandbox の無名フレームを実測して
FlashEnglish の画面を実装し、確定 UI と別物になって作り直しになった。

## 3段で守る

1. **宣言** — `design/figma/page-scope.json` に、いまのフェーズと許可ページを書く
2. **構造** — 書き出し器を**許可リスト方式**にする（除外リストではなく）。
   許可ページ以外は書き出しに入らないので、生成物に混ざりようがない
3. **検査（このファイル）** — フェーズに反する記録が残っていないかを見る

## この検査が捕まえるもの

- `phase: design-system` なのに `screens.json` に画面が登録されている
- 同じく `conventions.json` に画面から抽出した規約が入っている
- 書き出しの `$meta` が、許可ページ以外を参照したと記録している

## この検査が捕まえないもの

- **その場かぎりの Figma MCP 呼び出し。** AI が画面ノードを1回読むこと自体は
  止められない（ノードがどのページにあるかは、Figma を呼ばないと分からないため）。
  止められるのは「読んだ結果が記録・生成物に残ること」まで。
  だからこの規則は**宣言と書き出しの許可リストが本体**で、この検査は最後の網
- 確かめた方法: --self-test（フェーズ違反の記録を仕込んで落ちること）

## 使い方

    python3 <harness>/tools/page_scope_check.py --config design/figma/page-scope.json

page-scope.json:

    {
      "phase": "design-system",
      "allowed": ["⚙️_Styles&Components"],
      "reason": "カタログ完成まで画面ページを見ない（使われ方からの推測を防ぐ）",
      "unlockedBy": "Dart のデザインシステムとカタログの完成",
      "screens": "design/screens.json",
      "conventions": "design/conventions.json",
      "exports": ["../<ds>/figma/components.json"]
    }

フェーズを `screens` に進めると、画面ページの参照が解禁される。
**進めるのはユーザーの判断**（AI が勝手に進めない）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

PHASES = ("design-system", "screens")


#: ページ名らしくない文字（説明が入っている印）
PROSE_MARKS = ("（", "(", "、", "。", " のみ", "です", "ます", "ため")


def _looks_prose(s: str) -> bool:
    """ページ名ではなく説明に見えるか（#35）。

    Figma のページ名は短く、句読点や括弧を持ちません。**長さと印で見ます。**
    """
    return len(s) > 24 or any(m in s for m in PROSE_MARKS)


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="参照してよい Figma ページの検査")
    ap.add_argument("--config", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.config:
        ap.error("--config が要ります（--self-test を除く）")

    conf = load(args.config)
    if conf is None:
        print(f"設定が読めません: {args.config}", file=sys.stderr)
        return 2
    base = args.config.resolve().parent

    phase = conf.get("phase")
    allowed = conf.get("allowed") or []
    if phase not in PHASES:
        print(f"phase が不正です: {phase!r}（{PHASES} のいずれか）", file=sys.stderr)
        return 2
    if not allowed:
        print("allowed（参照してよいページ）が空です", file=sys.stderr)
        return 2

    print(f"フェーズ: {phase} / 参照してよいページ: {', '.join(allowed)}")
    if conf.get("reason"):
        print(f"  理由: {conf['reason']}")
    if phase == "design-system" and conf.get("unlockedBy"):
        print(f"  解禁の条件: {conf['unlockedBy']}（進めるのはユーザーの判断）")

    problems = []

    if phase == "design-system":
        # 画面を読んだ痕跡が記録に残っていないか
        sp = conf.get("screens")
        if sp and (base / sp).exists():
            doc = load(base / sp) or {}
            n = len(doc.get("sections") or [])
            if n:
                problems.append(
                    f"{sp}: 画面が {n} セクション登録されています。"
                    f"このフェーズでは画面ページを参照しません")
        cp = conf.get("conventions")
        if cp and (base / cp).exists():
            doc = load(base / cp) or {}
            n = len(doc.get("conventions") or [])
            if n:
                problems.append(
                    f"{cp}: 画面から抽出した規約が {n} 件あります。"
                    f"conventions は画面が10枚以上そろってから作ります")

    # 書き出しが許可外ページを参照したと記録していないか
    for ep in conf.get("exports") or []:
        p = base / ep
        if not p.exists():
            continue
        doc = load(p) or {}
        meta = doc.get("$meta", {})
        pages = meta.get("pages") or meta.get("参照したページ")
        if isinstance(pages, str):
            pages = [pages]
        if isinstance(pages, list):
            # **ページ名ではなく説明が入っていないか**（2026-09-04・#35）。
            # qnd-database の実害: `$meta` に散文で書いた説明が、そのまま
            # ページ名として扱われ「許可外のページを参照しています:
            # ["⚙️_Systems のみ（変数とスタイルはファイル単位でページに属さない）"]」
            # で落ちた。既存の案件（414・planttalk）も散文のキーを持っており、
            # `pages` を足すときに同じ書き方をすれば同じところで落ちる。
            prose = [x for x in pages if isinstance(x, str) and _looks_prose(x)]
            if prose:
                problems.append(
                    f"{ep}: `$meta.pages` に**ページ名ではなく説明が入っていませんか**"
                    f"\n      {prose[0][:60]}…"
                    f"\n      `pages` は**ページ名の配列**です。"
                    f"説明は別のキー（`なぜ` など）に書いてください。")
                continue
            extra = [x for x in pages if x not in allowed]
            if extra:
                problems.append(f"{ep}: 許可外のページを参照しています: {extra}")

    if problems:
        print("\nフェーズの約束に反する状態です:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("OK: フェーズの約束どおりです。")
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def cfg(extra=None):
            d = {"phase": "design-system", "allowed": ["⚙️_Styles&Components"],
                 "screens": "screens.json", "conventions": "conventions.json",
                 "exports": ["export.json"]}
            d.update(extra or {})
            (base / "c.json").write_text(json.dumps(d, ensure_ascii=False),
                                         encoding="utf-8")
            return ["--config", str(base / "c.json")]

        (base / "screens.json").write_text('{"sections": []}', encoding="utf-8")
        (base / "conventions.json").write_text('{"conventions": []}', encoding="utf-8")
        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components"]}}', encoding="utf-8")
        if main(cfg()) != 0:
            print("self-test NG: 約束どおりなのに落ちた"); ok = False

        (base / "screens.json").write_text('{"sections": [{"name": "Home"}]}',
                                           encoding="utf-8")
        if main(cfg()) != 1:
            print("self-test NG: 画面が登録されていても落ちなかった"); ok = False
        (base / "screens.json").write_text('{"sections": []}', encoding="utf-8")

        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components", "🎨_AppDesign"]}}',
            encoding="utf-8")
        if main(cfg()) != 1:
            print("self-test NG: 許可外ページの参照で落ちなかった"); ok = False
        (base / "export.json").write_text(
            '{"$meta": {"pages": ["⚙️_Styles&Components"]}}', encoding="utf-8")

        # フェーズを進めれば画面の登録は許される
        (base / "screens.json").write_text('{"sections": [{"name": "Home"}]}',
                                           encoding="utf-8")
        if main(cfg({"phase": "screens"})) != 0:
            print("self-test NG: screens フェーズで画面が許されなかった"); ok = False

    # ─── #35: 散文をページ名として扱わない ─────────────────────────
    for s, want in (
        ("⚙️_Systems のみ（変数とスタイルはファイル単位でページに属さない）", True),
        ("参照しないページ", False),
        ("⚙️_Styles&Components", False),
        ("🎨_AppDesign", False),
        ("Page 1", False),
        ("下書き、AI出力", True),
        ("このページだけを見ます。", True),
        ("とても長い名前がずっと続くページの名前でページ名には見えないもの", True),
    ):
        got = _looks_prose(s)
        if got != want:
            print(f"self-test NG: 散文の見分けが違う: {s!r} → {got}（期待 {want}）")
            ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
