#!/usr/bin/env python3
"""**まだ測れない段**を、理由と期限つきで宣言して関門だけ通す（design-harness #124）。

## なぜ要るか

立ち上げたばかりの案件では、**正直に緑にする道が無い段**があります。
planttalk-ios（2026-09-19）では `実装網羅` `アプリアイコン` `生成物のべき等` の3段が
落ちましたが、**どれも「まだ無い」のが正しい状態**でした（部品の実装前・
アイコンの絵はデザイナーが描く・生成器は別セッションの担当）。

**pre-push は止めるので、1日で `--no-verify` を3回使うことになりました。**
**抜け道を常用すると、関門は形だけになります。**

## どう解くか

- **表示は落ちたままにします。**`verify.sh` は NG を出し続けます。**嘘の緑にしません**
- **関門（pre-push）だけ**、宣言した段に限って通します
- **宣言には理由と期限が要ります。**期限が切れたら通しません

## 宣言の書き方（`design/stages.json`）

    "まだ測れない": {
      "実装網羅（条件7: Figma にあるものは全部実装）": {
        "why": "部品の実装がまだ0件。Figma 側の構造は出来ているが、画面実装は未着手",
        "reviewBy": "2026-10-31"
      }
    }

**`why` と `reviewBy` の両方が要ります。**片方だけでは通しません。

## 終了コード

  0 … 落ちた段が全部、期限内の宣言で覆われている（**関門を通してよい**）
  1 … 宣言の無い段がある、期限が切れている、宣言の形が足りない
  2 … 確かめられなかった（設定が読めない・落ちた段の一覧が無い）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

KEY = "まだ測れない"
NEEDED = ("why", "reviewBy")


def norm(s: str) -> str:
    """段の名前を突き合わせるための正規化（記号と空白の揺れを吸収する）。"""
    import re
    return re.sub(r"[\s（）()・:：/／、。.*`\"'\-—]+", "", str(s or ""))


def load(conf_path: Path):
    data = json.loads(conf_path.read_text(encoding="utf-8", errors="replace"))
    decl = data.get(KEY)
    if decl is None:
        return {}
    if not isinstance(decl, dict):
        raise ValueError(f"`{KEY}` は辞書で書いてください（いまは {type(decl).__name__}）")
    return decl


def run(stages_file: Path, conf_path: Path, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    if not stages_file.is_file():
        print(f"落ちた段の一覧がありません: {stages_file}")
        return 2
    failed = [l.strip() for l in
              stages_file.read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()]
    if not failed:
        print("落ちた段がありません（この道具を呼ぶ必要がありません）")
        return 2
    try:
        decl = load(conf_path)
    except Exception as e:
        print(f"宣言が読めません: {conf_path} — {e}")
        return 2

    by_norm = {norm(k): (k, v) for k, v in decl.items()}
    ok, bad = [], []
    for name in failed:
        hit = by_norm.get(norm(name))
        if not hit:
            bad.append(f"  **宣言がありません**: {name}\n"
                       f"    直すか、`design/stages.json` の `{KEY}` に "
                       f"why と reviewBy を書いてください")
            continue
        key, v = hit
        if not isinstance(v, dict):
            bad.append(f"  宣言の形が違います（辞書で書いてください）: {key}")
            continue
        missing = [k for k in NEEDED if not str(v.get(k, "")).strip()]
        if missing:
            bad.append(f"  **{'と'.join(missing)} がありません**: {key}")
            continue
        try:
            due = dt.date.fromisoformat(str(v["reviewBy"]).strip())
        except ValueError:
            bad.append(f"  reviewBy が日付ではありません（YYYY-MM-DD）: {key} → {v['reviewBy']!r}")
            continue
        if due < today:
            bad.append(f"  **期限が切れています**（{due} / いま {today}）: {key}\n"
                       f"    理由: {v['why'][:80]}\n"
                       f"    **測れるようになったか、期限を延ばす理由を書いてください**")
            continue
        ok.append(f"  {key}（期限 {due}）— {v['why'][:70]}")

    if bad:
        print("**関門は通しません。**")
        for l in bad:
            print(l)
        if ok:
            print(f"（期限内の宣言で覆われている段は {len(ok)} 件ありました）")
        print(f"NG: 落ちた {len(failed)} 段のうち、覆えたのは {len(ok)} 段です")
        return 1

    print("**落ちた段は全部、期限内の宣言で覆われています。**"
          "表示は落ちたままですが、関門は通します。")
    for l in ok:
        print(l)
    print(f"OK: 落ちた {len(failed)} 段とも「{KEY}」の宣言があります")
    return 0


def self_test() -> int:
    import tempfile
    bad = []

    def case(name, got, want):
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)
        sf, cf = root / "failed.txt", root / "stages.json"
        today = dt.date(2026, 9, 19)

        def go(failed, decl):
            sf.write_text("\n".join(failed) + "\n", encoding="utf-8")
            cf.write_text(json.dumps({KEY: decl}, ensure_ascii=False), encoding="utf-8")
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(sf, cf, today)
            return rc, buf.getvalue()

        good = {"why": "部品の実装がまだ0件", "reviewBy": "2026-10-31"}

        case("宣言があれば通す", go(["実装網羅"], {"実装網羅": good})[0], 0)
        case("宣言が無ければ通さない", go(["実装網羅"], {})[0], 1)
        case("期限切れは通さない",
             go(["実装網羅"], {"実装網羅": {"why": "x", "reviewBy": "2026-09-18"}})[0], 1)
        case("why が無ければ通さない",
             go(["実装網羅"], {"実装網羅": {"reviewBy": "2026-10-31"}})[0], 1)
        case("reviewBy が無ければ通さない",
             go(["実装網羅"], {"実装網羅": {"why": "x"}})[0], 1)
        case("日付でなければ通さない",
             go(["実装網羅"], {"実装網羅": {"why": "x", "reviewBy": "そのうち"}})[0], 1)
        case("記号の揺れを吸収する",
             go(["実装網羅（条件7: Figma にあるものは全部実装）"],
                {"実装網羅 条件7 Figmaにあるものは全部実装": good})[0], 0)
        case("1つでも覆えなければ通さない",
             go(["実装網羅", "別の段"], {"実装網羅": good})[0], 1)
        case("落ちた段が無ければ 2", go([], {})[0], 2)

        # **期限内でも、落ちたことは出す**（嘘の緑にしない）
        rc, out = go(["実装網羅"], {"実装網羅": good})
        if "表示は落ちたまま" not in out:
            bad.append("関門を通すときに、表示が落ちたままだと言っていない")

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print("OK: 自己検査 10 件とも期待どおりでした")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="まだ測れない段を宣言で覆う")
    ap.add_argument("--stages-file", type=Path, help="落ちた段の名前を1行ずつ書いたファイル")
    ap.add_argument("--config", type=Path, default=Path("design/stages.json"))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.stages_file:
        print("--stages-file を指定してください")
        return 2
    return run(a.stages_file, a.config)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # mutation-ok: 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
