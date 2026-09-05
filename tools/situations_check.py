#!/usr/bin/env python3
"""案件の機能から「守る状況」を導き、実機で確かめた記録が古くなっていないかを見る（2026-09-05 新設・#75）。

## なぜ要るか

これまでの課題は全部「実際に起きた失敗」から生まれた。転んだ場所に手すりをつけてきた。
端末の設定や状況で見た目が変わる10のクラスのうち、**7つに検査が1つも無かった**
（暗い配色・回転・許可拒否・動きを減らす・キーボード・圏外・言語）。

## 決定（2026-09-05 ユーザー確定・原文）

> プロジェクトごとに何を検査するべきかを作った機能によってあなたが定めるようにしてほしいです。
> 毎回のビルドごとにこれを検査する必要はないです。最初の検査でパスしてそれ以降更新がない場合は、
> わざわざ検査をもう一度する必要はないと思ってます。

だからこの道具は2つのことだけをする。

1. **守る状況を、人が選ばずに実装の機能から導く。** カメラを使うなら「許可を断られた」、
   通信するなら「圏外」、入力欄があるなら「キーボードで隠れる」。根拠（どのファイルの何）を書く
2. **一度確かめたら、関わる実装が変わったときだけ「もう一度見て」と言う。** 確かめた記録に
   関わるファイルの指紋を持ち、指紋が動いたときだけ落とす。**毎回のビルドでは何も求めない**

## 使い方（案件のルートで）

    python3 tools/situations_check.py --lib lib --out design/situations.json          # 導いて書く
    python3 tools/situations_check.py --lib lib --out design/situations.json --check  # 古い確認を落とす
    python3 tools/situations_check.py --lib lib --out design/situations.json --confirm 許可を断られた --by "Mac mini"

## 見るもの・見ないもの

- 見る: 状況が**未確認**（記録が無い）／確認が**古い**（関わるファイルの指紋が動いた）
- 見ない: 見た目が良いか。**確かめるのは実機で人がやる**（大小2台。#18）。この道具は
  「いつ・誰が・何を根拠に確かめたか」と「その後に関わる実装が動いたか」だけを持つ
- 確かめた方法: --self-test（機能を足すと状況が増えること・関わるファイルを変えると確認が古くなること）
"""

import argparse
import hashlib
import json
import re
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 状況 → (それを引き起こす実装の印, 実機で見ること)。**印は機能の有無**で、値ではない
SITUATIONS = {
    "許可を断られた": (
        r"permission_handler|Permission\.|ImagePicker|camera|geolocator|Geolocator|"
        r"NSCameraUsageDescription|NSLocationWhenInUse",
        "カメラ・位置情報などの許可を**断った**あとに、真っ黒の画面や進めない画面にならないか。"
        "設定へ誘導する道があるか"),
    "圏外・遅い通信": (
        r"\bhttp\.|\bdio\b|HttpClient|connectivity|Uri\.https?\(|WebSocket",
        "機内モードにして開く。読み込み中のまま止まらないか。**何も出ない画面**にならないか。"
        "戻ったとき自分で復帰するか"),
    "文字倍率": (
        r"\bText\(|RichText\(|Text\.rich",
        "端末の文字サイズを最大にする。枠からはみ出す・ボタンの中で2行になる・切れる文字が無いか"),
    "暗い配色": (
        r"ThemeMode|Brightness\.dark|darkTheme|platformBrightness",
        "端末を暗い配色にする。白地前提の色が見えなくならないか。画像の背景が浮かないか"),
    "回転・横向き": (
        r"OrientationBuilder|Orientation\.landscape|MediaQuery\.of\(context\)\.orientation",
        "横向きにする。縦向きで組んだ画面が崩れないか。**回転を止めているなら、その宣言を確かめる**"),
    "動きを減らす": (
        r"AnimationController|AnimatedSwitcher|AnimatedContainer|Duration\(milliseconds|"
        r"TweenAnimationBuilder|disableAnimations",
        "「視差効果を減らす」を入れる。動きで伝えていた変化（切り替わり・出現）が伝わらなくならないか"),
    "キーボードで隠れる": (
        r"TextField\(|TextFormField\(|EditableText\(|CupertinoTextField\(",
        "入力欄を押してキーボードを出す。入力欄や決定ボタンがキーボードの下に隠れないか"),
    "読み上げ": (
        r"GestureDetector\(|InkWell\(|onTap:|onPressed:",
        "読み上げ（VoiceOver / TalkBack）を入れる。押せるものに名前があるか。順番が画面の順か"),
    "言語・右書き": (
        r"Localizations|AppLocalizations|Intl\.|Directionality|locale",
        "別の言語にする。文字が伸びて崩れないか。右から書く言語なら並びが逆になるか"),
}

#: 実機で確かめる相手を決めるのは人（#18 の段取り）。ここでは「どの設定か」だけ持つ
SUFFIXES = (".dart", ".swift", ".kt", ".plist", ".xml")


def derive(lib: Path, extra=()):
    """実装を歩いて、状況ごとに根拠（ファイル）を集める。**人が選ばない。**"""
    files = [f for root in (lib, *extra) if root.exists()
             for f in sorted(root.rglob("*")) if f.is_file() and f.suffix in SUFFIXES
             and "catalog" not in f.parts and ".g." not in f.name]
    found = {}
    for name, (rx, how) in SITUATIONS.items():
        pat = re.compile(rx)
        hits = []
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            text = re.sub(r"//.*", "", text)
            if pat.search(text):
                hits.append(f)
        if hits:
            found[name] = {"根拠": [str(p) for p in hits[:12]] + (["…"] if len(hits) > 12 else []),
                           "関わるファイル": len(hits),
                           "実機で見ること": how,
                           "指紋": fingerprint(hits)}
    return found


def fingerprint(paths):
    """関わるファイルの中身の指紋。動けば「もう一度見て」の合図。"""
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p).encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load(out: Path):
    if not out.exists():
        return {}
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def head_sha(root: Path):
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="機能から守る状況を導き、確認が古くなっていないかを見る")
    ap.add_argument("--lib", type=Path, default=Path("lib"))
    ap.add_argument("--extra", type=Path, nargs="*", default=[],
                    help="lib 以外にも歩く場所（ios/Runner など。許可の宣言が plist にある）")
    ap.add_argument("--out", type=Path, default=Path("design/situations.json"))
    ap.add_argument("--check", action="store_true", help="未確認・古い確認があれば落とす")
    ap.add_argument("--confirm", metavar="状況", help="実機で確かめた状況を記録する")
    ap.add_argument("--by", default=socket.gethostname().split(".")[0],
                    help="確かめた機体（既定: このホスト名）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.lib.exists():
        print(f"実装がありません: {args.lib}\n  **0件は「守る状況が無い」ではなく「見ていない」です。**",
              file=sys.stderr)
        return 2

    now = derive(args.lib, args.extra)
    if not now:
        print(f"守る状況が1つも導けません（{args.lib}）。実装が空か、印が合っていません。"
              f"**0件は「無い」ではなく「見ていない」です。**", file=sys.stderr)
        return 2
    prev = load(args.out)
    if prev is None:
        print(f"記録が読めません: {args.out}", file=sys.stderr)
        return 2
    rec = prev.get("状況", {})

    # 記録を組み直す。導いた状況は根拠と指紋を更新し、確認の記録は引き継ぐ
    merged = {}
    for name, info in now.items():
        old = rec.get(name, {})
        merged[name] = {**info, "確認": old.get("確認")}
    gone = sorted(set(rec) - set(now))

    if args.confirm:
        if args.confirm not in merged:
            print(f"その状況は導かれていません: {args.confirm}（いま導けるのは "
                  f"{' / '.join(merged)}）", file=sys.stderr)
            return 2
        root = args.out.resolve().parent.parent
        merged[args.confirm]["確認"] = {"at": date.today().isoformat(), "by": args.by,
                                        "commit": head_sha(root),
                                        "指紋": merged[args.confirm]["指紋"]}
        print(f"記録しました: {args.confirm}（{args.by}・{merged[args.confirm]['確認']['commit']}）")

    doc = {
        "$なぜ": "案件の機能から導いた「守る状況」と、実機で確かめた記録。人が選ばない。"
                "確認は、関わる実装が変わったときだけ求める（2026-09-05 ユーザー確定）",
        "$手で書き換えない": "tools/situations_check.py が導く。確認は --confirm で記録する",
        "状況": merged,
    }
    if gone:
        doc["$消えた状況"] = {g: "実装からその機能が消えたので、守る対象から外れた" for g in gone}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    if not args.check:
        n_ok = sum(1 for v in merged.values() if v.get("確認"))
        print(f"守る状況 {len(merged)} 件を導きました（確認済み {n_ok}）→ {args.out}")
        for name, v in merged.items():
            mark = "済" if v.get("確認") else "**未確認**"
            print(f"  {mark} {name}（関わるファイル {v['関わるファイル']}）")
        return 0

    errs = []
    for name, v in merged.items():
        c = v.get("確認")
        if not c:
            errs.append(f"  {name}: **一度も実機で確かめていません。** "
                        f"見ること: {v['実機で見ること']}")
        elif c.get("指紋") != v["指紋"]:
            errs.append(f"  {name}: 確認（{c.get('at')}・{c.get('by')}）のあとに"
                        f"**関わる実装が変わりました**（{v['関わるファイル']} ファイル）。"
                        f"もう一度見て --confirm してください")
    if errs:
        print(f"守る状況 {len(merged)} 件のうち、確認が要るものがあります:", file=sys.stderr)
        print("\n".join(errs), file=sys.stderr)
        return 1
    print(f"守る状況 {len(merged)} 件、すべて確認済みで、そのあと関わる実装は変わっていません。")
    return 0


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "design").mkdir()
        lib = root / "lib"; lib.mkdir()
        out = root / "design" / "situations.json"
        subprocess.run(["git", "init", "-q", str(root)], capture_output=True)
        (lib / "a.dart").write_text("Widget b() => Text('こんにちは');\n", encoding="utf-8")
        argv = ["--lib", str(lib), "--out", str(out)]

        def run(*extra):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv + list(extra))
            return rc, buf.getvalue()

        rc, out_txt = run()
        d = json.loads(out.read_text(encoding="utf-8"))
        if rc != 0 or set(d["状況"]) != {"文字倍率"}:
            print(f"self-test NG: 文字だけの実装から「文字倍率」だけが導けない: {list(d['状況'])}"); ok = False
        # **機能を足すと状況が増える**（人が選ばない）
        (lib / "cam.dart").write_text("final c = ImagePicker();\nfinal f = TextField();\n", encoding="utf-8")
        run()
        d = json.loads(out.read_text(encoding="utf-8"))
        if not {"許可を断られた", "キーボードで隠れる"} <= set(d["状況"]):
            print(f"self-test NG: カメラと入力欄から状況が導けない: {list(d['状況'])}"); ok = False
        if "cam.dart" not in " ".join(d["状況"]["許可を断られた"]["根拠"]):
            print("self-test NG: 根拠のファイルが書かれていない"); ok = False
        # 未確認なら --check は落ちる
        rc, txt = run("--check")
        if rc != 1 or "一度も実機で確かめていません" not in txt:
            print(f"self-test NG: 未確認なのに通した（{rc}）"); ok = False
        # 全部確認したら通る
        for s in ("文字倍率", "許可を断られた", "キーボードで隠れる"):
            run("--confirm", s, "--by", "試験機")
        rc, txt = run("--check")
        if rc != 0:
            print(f"self-test NG: 全部確認したのに落ちた（{rc}）\n   {txt[:300]}"); ok = False
        # **関わる実装が変わったら、その状況だけ古くなる**
        (lib / "cam.dart").write_text("final c = ImagePicker(); // 変えた\nfinal f = TextField();\n", encoding="utf-8")
        rc, txt = run("--check")
        if rc != 1 or "許可を断られた" not in txt or "関わる実装が変わりました" not in txt:
            print(f"self-test NG: 実装が変わったのに古くならない（{rc}）"); ok = False
        if "文字倍率:" in txt:
            print("self-test NG: 関係ない状況まで古くした"); ok = False
        # コメントの中の印は数えない
        (lib / "cmt.dart").write_text("// dio を使う予定\n", encoding="utf-8")
        run()
        if "圏外・遅い通信" in json.loads(out.read_text(encoding="utf-8"))["状況"]:
            print("self-test NG: コメントの中の印から状況を導いた"); ok = False
        # 導けない状況を --confirm しようとしたら止まる
        rc, _ = run("--confirm", "暗い配色")
        if rc != 2:
            print(f"self-test NG: 導かれていない状況の確認を通した（{rc}）"); ok = False
        # 実装が無ければ 2
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            if main(["--lib", str(root / "ない"), "--out", str(out)]) != 2:
                print("self-test NG: 実装が無いのに通した"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
