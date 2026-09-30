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

## 中核の段は「確かめて違反」を宣言で覆えない（design-harness #134・2026-09-24）

planttalk（2026-09-19）で実害が出ました。**幾何は照合していない**と自分で書き、
gaps.json にも宣言し、**それで verify.sh は 0 のまま通り、push もできました。**
実機では Figma と全く違う画面が出ました。

**穴を宣言することと、穴を埋めることは別**です。この仕組みは立ち上げ期に
「測る対象がまだ無い段」のためのものでしたが、**中核の照合（Figma と合っているか）を
免除するためにも使えて**いました。覆う範囲に上限がありませんでした。

そこで**段が返した終了コードで分けます**（規約22）。

    2 … 確かめられなかった   → 測る対象が無い。**宣言で覆える**（立ち上げ期はこちら）
    1 … 確かめて違反         → 測れた。違反が出た。**中核の段なら、宣言では覆えない**

中核の段とは、名前に「条件N」を持つ段です（関門の条件 1・4・5・7・8・9。
`stage_check.py` と同じ見分け方）。

**落ちた段の一覧は `<名前>\t<終了コード>` の形で受け取ります。**古い verify.sh は名前だけを
書いてきます。そのときはコードが分からないので**この規則は当てず、そう言います**
（黙って厳しくもしない・黙って緩めもしない）。

## Figma の作り直し中は、無関係な push だけ条件4・7 を通す（#147・2026-09-30）

`design/stages.json` の `Figma の作り直し` に why・reviewBy・`Figma に関わるパス` を書くと、
**宣言したパスに1つも触れていない push だけ**、鮮度（条件4）と実装網羅（条件7）の違反を
関門で通します（表示は落ちたまま）。関わるパスに触れた push・期限切れ・触ったファイルを
git で読めないときは、今までどおり通しません。ほかの中核の条件は対象にしません。

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
#: **Figma の作り直し中の宣言**（#147・2026-09-30 ユーザー確定「3はBでいい。」）
REBUILD_KEY = "Figma の作り直し"
REBUILD_PATHS = "Figma に関わるパス"
#: 作り直し中に、無関係な push なら通してよい中核の条件（鮮度・実装網羅）
REBUILD_CONDS = {"4", "7"}


def norm(s: str) -> str:
    """段の名前を突き合わせるための正規化（記号と空白の揺れを吸収する）。"""
    import re
    return re.sub(r"[\s（）()・:：/／、。.*`\"'\-—]+", "", str(s or ""))


import re as _re
#: 中核の段（関門の条件）。**stage_check.py の COND_RX と同じ見分け方**
COND_RX = _re.compile(r"条件(\d+)")


def is_core(name: str) -> bool:
    return bool(COND_RX.search(str(name or "")))


def parse_failed(lines):
    """`<名前>\t<終了コード>` を (名前, コード) に。コードが無ければ None。"""
    out = []
    for l in lines:
        if "\t" in l:
            name, rc = l.rsplit("\t", 1)
            try:
                out.append((name.strip(), int(rc.strip())))
            except ValueError:
                out.append((l.strip(), None))
        else:
            out.append((l.strip(), None))
    return out


def load(conf_path: Path):
    data = json.loads(conf_path.read_text(encoding="utf-8", errors="replace"))
    decl = data.get(KEY)
    if decl is None:
        return {}
    if not isinstance(decl, dict):
        raise ValueError(f"`{KEY}` は辞書で書いてください（いまは {type(decl).__name__}）")
    return decl


def rebuild_scope(conf_path: Path, today: dt.date, root=None):
    """**Figma の作り直し中に、この push が作り直しと無関係か**（#147・2026-09-30）。

    実害（PlantTalk・2026-09-25）: Figma を大きく作り直した直後、作り直しと無関係な直し
    （DNA の背景・`Sources/PlantTalk/DNA/` だけ）が、鮮度（条件4）と実装網羅（条件7）で
    止まった。どちらも #134 で「確かめて違反なら宣言で覆えない」ので、作り直しが終わるまで
    **案件の誰も push できなくなった**（未 push 9 件・Mac mini の確認も止まった）。

    `design/stages.json` に次を書くと、**宣言したパスに1つも触れていない push だけ**、
    条件4・7 の違反を関門で通す（表示は落ちたまま）:

        "Figma の作り直し": {
          "why": "2026-09-25 に Figma を作り直した。部品と画面がそろうまで",
          "reviewBy": "2026-10-31",
          "Figma に関わるパス": ["Sources/PlantTalk/UI/", "design/"]
        }

    **どこまで緩めるかは、宣言したパスで案件が決める**（AI が関係の有無を推し量らない）。
    触ったファイルは作業ツリー＋どのリモートにも無いコミット（`_worktree.changed_files`）。
    読めなければ「無関係」と言わない。

    戻り: (通してよいか, 説明の行)
    """
    try:
        data = json.loads(conf_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False, "宣言が読めないので、作り直しの宣言も見ていません"
    v = data.get(REBUILD_KEY)
    if v is None:
        return False, (f"Figma を作り直している途中なら、`{REBUILD_KEY}` を宣言すると、"
                       f"作り直しと無関係な push だけ通せます（#147）")
    if not isinstance(v, dict):
        return False, f"`{REBUILD_KEY}` は辞書で書いてください"
    missing = [k for k in NEEDED if not str(v.get(k, "")).strip()]
    paths = v.get(REBUILD_PATHS)
    if not isinstance(paths, list) or not [x for x in paths if str(x).strip()]:
        missing.append(REBUILD_PATHS)
    if missing:
        return False, f"`{REBUILD_KEY}` に {'と'.join(missing)} がありません"
    try:
        due = dt.date.fromisoformat(str(v["reviewBy"]).strip())
    except ValueError:
        return False, f"`{REBUILD_KEY}` の reviewBy が日付ではありません（YYYY-MM-DD）"
    if due < today:
        return False, (f"`{REBUILD_KEY}` の期限が切れています（{due}）。作り直しが終わったか、"
                       f"期限を延ばす理由を書いてください")
    from _worktree import changed_files, repo_root
    base = root or repo_root(conf_path.parent)
    if base is None:
        return False, "git の根が見つからないので、触ったファイルを見ていません"
    touched, complete = changed_files(base)
    if not complete:
        return False, "触ったファイルを git で全部は読めませんでした。**無関係とは言えません**"
    prefixes = [str(x).strip().rstrip("/") for x in paths if str(x).strip()]
    hit = sorted(t for t in touched
                 if any(t == p or t.startswith(p + "/") for p in prefixes))
    if hit:
        return False, (f"この push は、作り直しに関わるパスに触れています（{len(hit)} 件。"
                       f"例: {', '.join(hit[:3])}）。作り直しと一緒に直してください")
    return True, (f"**作り直しと無関係な push です**（触ったファイル {len(touched)} 件は、"
                  f"宣言したパス {', '.join(prefixes)} の外）。期限 {due}")


def run(stages_file: Path, conf_path: Path, today: dt.date | None = None, root=None) -> int:
    today = today or dt.date.today()
    if not stages_file.is_file():
        print(f"落ちた段の一覧がありません: {stages_file}")
        return 2
    failed = parse_failed([l for l in
              stages_file.read_text(encoding="utf-8", errors="replace").splitlines()
              if l.strip()])
    if not failed:
        print("落ちた段がありません（この道具を呼ぶ必要がありません）")
        return 2
    try:
        decl = load(conf_path)
    except Exception as e:
        print(f"宣言が読めません: {conf_path} — {e}")
        return 2

    by_norm = {norm(k): (k, v) for k, v in decl.items()}
    ok, bad, core_refused, no_code = [], [], [], 0
    scope = None                       # 作り直しの宣言は、要るときに1回だけ見る
    for name, rc in failed:
        if rc is None:
            no_code += 1
        # **作り直しと無関係な push なら、条件4・7 の違反を通す**（#147）
        m = COND_RX.search(str(name or ""))
        if rc == 1 and m and m.group(1) in REBUILD_CONDS:
            if scope is None:
                scope = rebuild_scope(conf_path, today, root)
            if scope[0]:
                ok.append(f"  {name} — {scope[1]}")
                continue
        # **中核の段が「確かめて違反」なら、宣言では覆えない**（#134）
        if rc == 1 and is_core(name):
            hit0 = by_norm.get(norm(name))
            declared = "（宣言はありますが）" if hit0 else ""
            core_refused.append(
                f"  **中核の段が、確かめたうえで違反を出しています**{declared}: {name}\n"
                f"    これは「まだ測れない」ではありません。**測れて、合っていません。**\n"
                f"    宣言では覆えません。直すか、Figma の側を直してください"
                + (f"\n    {scope[1]}" if scope and m and m.group(1) in REBUILD_CONDS else ""))
            continue
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

    if no_code:
        print(f"注意: 落ちた段のうち {no_code} 件は終了コードが控えられていません"
              f"（古い verify.sh）。**「確かめて違反」と「確かめられなかった」を区別できない**ので、"
              f"中核の規則（#134）はその段には当てていません。雛形を取り込んでください")
    if core_refused or bad:
        print("**関門は通しません。**")
        for l in core_refused:
            print(l)
        for l in bad:
            print(l)
        if ok:
            print(f"（期限内の宣言で覆われている段は {len(ok)} 件ありました）")
        print(f"NG: 落ちた {len(failed)} 段のうち、覆えたのは {len(ok)} 段です"
              + (f"（**中核で覆えないもの {len(core_refused)} 件**）" if core_refused else ""))
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

        # ── **中核の段は、確かめて違反（1）なら宣言で覆えない**（#134）──────
        core = "実装網羅（条件7: Figma にあるものは全部実装）"
        case("**中核が 1 なら、宣言があっても通さない**",
             go([core + "\t1"], {core: good})[0], 1)
        case("中核が 2（確かめられなかった）なら、宣言で覆える",
             go([core + "\t2"], {core: good})[0], 0)
        case("中核でない段は 1 でも宣言で覆える",
             go(["アプリアイコン\t1"], {"アプリアイコン": good})[0], 0)
        case("終了コードが無い（古い verify.sh）なら、中核でも規則を当てず宣言で覆える",
             go([core], {core: good})[0], 0)

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

        # ── **Figma の作り直し中は、無関係な push だけ条件4・7 を通す**（#147）──────
        import subprocess as _sp
        repo = root / "repo"
        (repo / "design").mkdir(parents=True)
        (repo / "Sources" / "UI").mkdir(parents=True)
        (repo / "Sources" / "DNA").mkdir(parents=True)
        remote = root / "remote.git"

        def g(*a, cwd=repo):
            _sp.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
                     "-c", "commit.gpgsign=false", *a], capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
        _sp.run(["git", "init", "-q", "--bare", str(remote)], capture_output=True)
        g("init", "-q")
        for f in ("Sources/UI/tabs.swift", "Sources/DNA/bg.swift"):
            (repo / f).write_text("x\n", encoding="utf-8")
        rsf, rcf = repo / "failed.txt", repo / "design" / "stages.json"
        rcf.write_text("{}", encoding="utf-8")
        g("add", "-A"); g("commit", "-qm", "x")
        g("remote", "add", "origin", str(remote)); g("push", "-q", "-u", "origin", "HEAD")
        fresh = "鮮度（条件4: Figma 本体 → 書き出し）"
        rebuild = {"why": "Figma を作り直した", "reviewBy": "2026-10-31",
                   "Figma に関わるパス": ["Sources/UI/", "design/"]}

        def rgo(failed, extra):
            rsf.write_text("\n".join(failed) + "\n", encoding="utf-8")
            rcf.write_text(json.dumps({KEY: {}, **extra}, ensure_ascii=False),
                           encoding="utf-8")
            g("add", "design/stages.json"); g("commit", "-qm", "decl")
            g("push", "-q")                          # 宣言は push 済みにしておく
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run(rsf, rcf, today, root=repo)
            return rc, buf.getvalue()

        (repo / "Sources" / "DNA" / "bg.swift").write_text("y\n", encoding="utf-8")   # 無関係な直し
        rc, out = rgo([fresh + "\t1", core + "\t1"], {REBUILD_KEY: rebuild})
        case("**作り直しと無関係な push なら、条件4・7 の違反を通す**", rc, 0)
        if "作り直しと無関係な push です" not in out or "表示は落ちたまま" not in out:
            bad.append("作り直しで通すときに、理由と「表示は落ちたまま」を言っていない")
        case("作り直しの宣言が無ければ、今までどおり通さない",
             rgo([fresh + "\t1"], {})[0], 1)
        case("期限が切れた作り直しの宣言では通さない",
             rgo([fresh + "\t1"], {REBUILD_KEY: {**rebuild, "reviewBy": "2026-09-18"}})[0], 1)
        case("パスを書いていない作り直しの宣言では通さない",
             rgo([fresh + "\t1"], {REBUILD_KEY: {**rebuild, "Figma に関わるパス": []}})[0], 1)
        case("条件4・7 以外の中核（条件5）は、作り直しでも通さない",
             rgo(["再現性の判定（条件5: 描画で別物）\t1"], {REBUILD_KEY: rebuild})[0], 1)
        (repo / "Sources" / "UI" / "tabs.swift").write_text("z\n", encoding="utf-8")   # 関わるパス
        rc, out = rgo([fresh + "\t1"], {REBUILD_KEY: rebuild})
        case("**作り直しに関わるパスに触れた push は、今までどおり通さない**", rc, 1)
        if "作り直しに関わるパスに触れています" not in out or "Sources/UI/tabs.swift" not in out:
            bad.append("関わるパスに触れたときに、どのファイルかを言っていない")
        _sp.run(["git", "-C", str(repo), "checkout", "--", "Sources/UI/tabs.swift"],
                capture_output=True)
        (repo / "Sources" / "UI" / "new.swift").write_text("n\n", encoding="utf-8")    # 新規も数える
        case("関わるパスに足した新しいファイルも「触れた」と数える",
             rgo([fresh + "\t1"], {REBUILD_KEY: rebuild})[0], 1)
        (repo / "Sources" / "UI" / "new.swift").unlink()
        plain = root / "plain"; (plain / "design").mkdir(parents=True)
        pcf = plain / "design" / "stages.json"
        pcf.write_text(json.dumps({KEY: {}, REBUILD_KEY: rebuild}, ensure_ascii=False),
                       encoding="utf-8")
        rsf.write_text(fresh + "\t1\n", encoding="utf-8")
        import contextlib as _c2, io as _i2
        with _c2.redirect_stdout(_i2.StringIO()):
            rc_plain = run(rsf, pcf, today, root=plain)
        case("git で触ったファイルを読めなければ、無関係と言わない", rc_plain, 1)

        # **期限内でも、落ちたことは出す**（嘘の緑にしない）
        rc, out = go(["実装網羅"], {"実装網羅": good})
        if "表示は落ちたまま" not in out:
            bad.append("関門を通すときに、表示が落ちたままだと言っていない")

    # **--stages-file を渡さなければ 2**（2026-09-28・変異試験が見ていなかった経路）
    import contextlib as _cl
    import io as _io
    with _cl.redirect_stdout(_io.StringIO()):
        rc_noarg = main([])
    if rc_noarg != 2:
        bad.append(f"--stages-file を渡さないのに 2 を返しませんでした（{rc_noarg}）")

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました。**この道具が空振りしています。**")
        return 1
    print("self-test: OK（自己検査が全部期待どおりでした）")
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
    except Exception as e:  # 例外の帰り道。中からは通せない
        print(f"例外で止まりました: {e}")
        sys.exit(2)
