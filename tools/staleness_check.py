#!/usr/bin/env python3
"""下流のファイルが上流より古くないかを見る（鮮度差の検査）。

414 の実害（2026-08-28 発覚）: Figma の全量書き出し（figma/components.json・
08-27 更新）に判定記録（components/components.json・08-12 更新）が15日
追随せず、その断絶を検知する仕組みが無かった。依存の鎖のうち

    Figma 本体 → 書き出し        … figma_freshness.py が見る
    書き出し → 判定・生成物      … ★ここ（この検査）
    判定・生成物 → 実装          … 各案件の照合テストが見る

の真ん中だけが無検査だった。

設定はリポジトリ側の staleness.json に「上流・下流の対」を書く:

    {
      "pairs": [
        {"up": "414/figma/components.json", "down": "414/components/components.json"},
        {"up": "414/figma/variables.json",  "down": "414/tokens/tokens.json"},
        {"up": "414/figma/styles.json",     "down": "414/FLUTTER_GAPS.md"}
      ]
    }

比較は次の優先順位:
  1. 両方の JSON に $meta.updatedAt / $meta.syncedAt があれば、その日付
  2. 無ければ git の最終コミット日時（作業ツリーの mtime は使わない——
     クローンやブランチ切り替えで動くため。generation-rules-flutter.md の
     「古さは更新時刻で見ない」と同じ理由。git 履歴はその点で安定）
  3. git 管理外なら mtime（最後の手段。その旨を表示する）

使い方:
    python3 tools/staleness_check.py --config <staleness.json>
    python3 tools/staleness_check.py --config <staleness.json> --max-lag-days 3

下流が上流より古ければ exit 1。対の一方が無ければ exit 2（設定の誤り）。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

DATE_KEYS = ("updatedAt", "syncedAt", "verifiedAt", "extractedAt", "fetchedAt")


def json_meta_date(path):
    """JSON の $meta から日付を読む。無ければ None。"""
    if path.suffix != ".json":
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    meta = doc.get("$meta", {}) if isinstance(doc, dict) else {}
    for key in DATE_KEYS:
        v = meta.get(key)
        if isinstance(v, str) and len(v) >= 10:
            try:
                return datetime.fromisoformat(v[:10]).replace(tzinfo=timezone.utc), f"$meta.{key}"
            except ValueError:
                continue
    return None


def git_date(path):
    """git の最終コミット日時。管理外なら None。"""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", path.name],
            capture_output=True, text=True, cwd=path.parent, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    if not out:
        return None
    try:
        return datetime.fromisoformat(out), "git"
    except ValueError:
        return None


def date_of(path):
    """比較に使う日付と、その出どころを返す。"""
    for getter in (json_meta_date, git_date):
        got = getter(path)
        if got:
            return got
    return (datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            "mtime（git 管理外。クローンで動くため参考値）")


def main(argv=None):
    ap = argparse.ArgumentParser(description="下流が上流より古くないかを見る")
    ap.add_argument("--config", type=Path,
                    help="pairs を書いた staleness.json")
    ap.add_argument("--max-lag-days", type=int, default=0,
                    help="許容する遅れ（日）。既定 0 = 上流より1日でも古ければ失敗")
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
    pairs = conf.get("pairs", [])
    if not pairs:
        print(f"設定に pairs がありません: {args.config}", file=sys.stderr)
        return 2

    stale, broken = [], []
    for pair in pairs:
        up = (base / pair["up"]).resolve()
        down = (base / pair["down"]).resolve()
        if not up.exists() or not down.exists():
            broken.append(f"  対の一方がありません: {pair['up']} → {pair['down']}")
            continue
        (u_date, u_src), (d_date, d_src) = date_of(up), date_of(down)
        lag = u_date - d_date
        mark = "OK" if lag <= timedelta(days=args.max_lag_days) else "NG"
        print(f"{mark}: {pair['down']}"
              f"（下流 {d_date.date()} / 上流 {pair['up']} {u_date.date()}"
              f"・遅れ {max(lag.days, 0)} 日・出どころ {d_src} / {u_src}）")
        if mark == "NG":
            stale.append(pair["down"])

    if broken:
        print("\n設定の誤り:", file=sys.stderr)
        print("\n".join(broken), file=sys.stderr)
        return 2
    if stale:
        print(f"\n{len(stale)} 件の下流が上流より古くなっています。"
              "取り直すか、意図した保留なら $meta に日付と理由を書いてください。",
              file=sys.stderr)
        return 1
    print(f"\n{len(pairs)} 対すべて鮮度に問題ありません。")
    return 0


def self_test():
    """落ちるケースを持つ（この道具だけ self-test が無く、2026-08-29 に足した）。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def w(name, date):
            (base / name).write_text(
                json.dumps({"$meta": {"syncedAt": date}}), encoding="utf-8")

        def cfg(pairs, **kw):
            d = {"pairs": pairs}
            (base / "c.json").write_text(json.dumps(d), encoding="utf-8")
            a = ["--config", str(base / "c.json")]
            for k, v in kw.items():
                a += [f"--{k.replace('_', '-')}", str(v)]
            return a

        # 下流が新しい → 通る
        w("up.json", "2026-08-01"); w("down.json", "2026-08-05")
        if main(cfg([{"up": "up.json", "down": "down.json"}])) != 0:
            print("self-test NG: 下流が新しいのに落ちた"); ok = False

        # 下流が古い → 落ちる（本体）
        w("down.json", "2026-07-20")
        if main(cfg([{"up": "up.json", "down": "down.json"}])) != 1:
            print("self-test NG: 下流が古いのに落ちなかった"); ok = False

        # 猶予の範囲内なら通る
        if main(cfg([{"up": "up.json", "down": "down.json"}], max_lag_days=30)) != 0:
            print("self-test NG: 猶予の範囲内なのに落ちた"); ok = False

        # 対の一方が無い → 落ちる（黙って skip しない）
        if main(cfg([{"up": "up.json", "down": "missing.json"}])) == 0:
            print("self-test NG: 対の一方が無いのに通した"); ok = False

        # pairs が空 → 落ちる（空振りを通さない）
        if main(cfg([])) != 2:
            print("self-test NG: pairs が空なのに落ちなかった"); ok = False

    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
