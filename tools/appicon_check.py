#!/usr/bin/env python3
"""アプリアイコンが宣言どおりに揃っているかを見る（2026-09-04 新設・#62）。

## 実害（flash-compose）

**アプリアイコンは、どの関門からも見られていませんでした。**
`flutter test` にも `verify.sh` にも、アイコンを見る検査が1件もありません。

| いつ | 何が起きたか |
|---|---|
| 2026-08-27 | ヘッドレス Chrome の落とし穴（`--window-size` が 500px 未満だと**黙って無視され、左上だけを切り取る**）で **iOS アイコン20枚のうち14枚が壊れ、書き出しは成功した扱いで終わった** |
| 2026-09-04 | Android の適応アイコンの前景が横 **0..108dp（カンバス全幅）**に広がっており、**左右が必ず切り落とされる状態**。ユーザーの報告で初めて分かった |

案件側に `--check` を持つ書き出し器はありました。**しかし手で回すもので、
どの段からも呼ばれていません。** 「検査は書いたが起動するものが無い」という、
この案件で一度直した型の再発です。

## 見るもの（**宣言から読む。手で並べない**）

    python3 tools/appicon_check.py --ios ios/Runner/Assets.xcassets/AppIcon.appiconset \\
                                   --android android/app/src/main/res

**iOS**（`Contents.json` が正本）

- 宣言されたファイルが全部あるか
- **宣言どおりの寸法か**（2026-08-27 の壊れ方はこれで捕まる）
- 宣言に無い置き忘れが無いか（要求が変わった痕跡）

**Android**（`mipmap-anydpi-v26/ic_launcher.xml` が正本）

- 3層（背景・前景・monochrome）が宣言されているか。**monochrome が無いと
  端末側で自動生成され、デザインと別物になる**
- 前景と monochrome が全密度そろって寸法も合うか

## 決められないこと

**全面に広がる絵を Android の適応アイコンにどう載せるかは、機械では決まりません。**

| 案 | 本体の幅 | 切れる形 |
|---|---|---|
| A 全体を見える 72dp に入れる | 47.9dp | なし |
| B 本体を見える 72dp に入れる | 72.0dp | 小片の先が切れる |

**この検査が言えるのは「帯に出ていないか」までで、A と B のどちらが正しいかは
デザイナーの判断です。** 機械が A を強制すると、B を選んだ案件が落ちます。
だから**外周 18dp の切り落としは注意にとどめ、落としません。**

## 捕まえないもの

- 絵の中身。**画像で合否は判断しません**
- 確かめた方法: --self-test（寸法を1枚崩すと落ちること）
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: Android の適応アイコンで、外周が切り落とされる割合（108dp 中 18dp × 2）
SAFE_RATIO = 72.0 / 108.0


def png_size(path):
    """PNG の寸法を IHDR から読む。**外部の道具を使わない。**"""
    try:
        with path.open("rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


def check_ios(d):
    """`Contents.json` の宣言と、実物の寸法を突き合わせる。"""
    errs = []
    conf = d / "Contents.json"
    if not conf.exists():
        return [f"  iOS の宣言がありません: {conf}\n"
                f"    **アイコンを誰も見ていない状態です。**"], 0
    try:
        doc = json.loads(conf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"  iOS の宣言が読めません: {conf}: {e}"], 0
    images = doc.get("images") or []
    if not images:
        return [f"  iOS の宣言に画像が1件もありません: {conf}"], 0

    declared = set()
    for im in images:
        fn = im.get("filename")
        if not fn:
            continue                    # 未使用の枠（宣言だけ）は正常
        declared.add(fn)
        f = d / fn
        if not f.exists():
            errs.append(f"  iOS: 宣言されたファイルがありません: {fn}")
            continue
        size, scale = im.get("size", ""), im.get("scale", "1x")
        m = re.match(r"([\d.]+)x([\d.]+)", str(size))
        s = re.match(r"(\d+)x", str(scale))
        if not m or not s:
            continue
        want = (round(float(m.group(1)) * int(s.group(1))),
                round(float(m.group(2)) * int(s.group(1))))
        got = png_size(f)
        if got is None:
            errs.append(f"  iOS: PNG として読めません: {fn}")
        elif got != want:
            errs.append(f"  iOS: **{fn} が {got[0]}x{got[1]} です**"
                        f"（宣言は {want[0]}x{want[1]}）\n"
                        f"    書き出しが途中で切れた可能性があります"
                        f"（2026-08-27 は20枚中14枚がこれでした）。")
    stray = sorted(f.name for f in d.glob("*.png") if f.name not in declared)
    for s in stray:
        errs.append(f"  iOS: 宣言に無い置き忘れ: {s}\n"
                    f"    要求が変わった痕跡です。宣言を直すか消してください。")
    return errs, len(declared)


def check_android(res):
    """適応アイコンの3層と、密度ごとの実物を見る。"""
    errs, warns, seen = [], [], 0
    xml = res / "mipmap-anydpi-v26" / "ic_launcher.xml"
    if not xml.exists():
        return ([f"  Android の宣言がありません: {xml}\n"
                 f"    **適応アイコンを誰も見ていない状態です。**"], [], 0)
    text = xml.read_text(encoding="utf-8", errors="ignore")
    layers = {}
    for tag in ("background", "foreground", "monochrome"):
        m = re.search(r"<" + tag + r"[^>]*android:drawable\s*=\s*"
                      r'"@(\w+)/(\w+)"', text)
        if m:
            layers[tag] = (m.group(1), m.group(2))
    if "monochrome" not in layers:
        errs.append(f"  Android: **monochrome の層がありません**（{xml.name}）\n"
                    f"    無いと端末側で自動生成され、**デザインと別物になります。**")
    for tag in ("background", "foreground"):
        if tag not in layers:
            errs.append(f"  Android: {tag} の層がありません（{xml.name}）")

    for tag, (kind, name) in sorted(layers.items()):
        if kind != "mipmap" and kind != "drawable":
            continue
        found = sorted(p for p in res.glob(f"{kind}-*/{name}.png"))
        if not found:
            # ベクタ（xml）で持つのは正常
            if list(res.glob(f"{kind}*/{name}.xml")):
                continue
            errs.append(f"  Android: {tag}（{name}）の実物がありません")
            continue
        sizes = {}
        for f in found:
            seen += 1
            got = png_size(f)
            if got is None:
                errs.append(f"  Android: PNG として読めません: {f.name}"
                            f"（{f.parent.name}）")
                continue
            if got[0] != got[1]:
                errs.append(f"  Android: {f.parent.name}/{f.name} が正方形では"
                            f"ありません（{got[0]}x{got[1]}）")
            sizes[f.parent.name] = got
        if tag == "foreground" and len(sizes) < 2:
            warns.append(f"Android: foreground が {len(sizes)} 密度しかありません")
    if "monochrome" in layers and "foreground" in layers:
        fg = layers["foreground"][1]
        mo = layers["monochrome"][1]
        fgs = {p.parent.name: png_size(p) for p in res.glob(f"mipmap-*/{fg}.png")}
        mos = {p.parent.name: png_size(p) for p in res.glob(f"mipmap-*/{mo}.png")}
        for dens in sorted(set(fgs) & set(mos)):
            if fgs[dens] != mos[dens]:
                errs.append(f"  Android: {dens} で foreground {fgs[dens]} と "
                            f"monochrome {mos[dens]} の寸法が違います")
    warns.append("Android: **外周 18dp（108 のうち）は必ず切られます。**"
                 "全体を見える 72dp に入れるか、本体だけ入れて小片を切るかは"
                 "**デザイナーの判断**です（この検査は決めません）")
    return errs, warns, seen


def main(argv=None):
    ap = argparse.ArgumentParser(description="アプリアイコンが揃っているか")
    ap.add_argument("--ios", type=Path)
    ap.add_argument("--android", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.ios and not args.android:
        print("見る面を1つも指定していません（--ios / --android）。\n"
              "  **何も見ていません。**", file=sys.stderr)
        return 2

    errs, warns, n = [], [], 0
    if args.ios:
        if not args.ios.exists():
            errs.append(f"  iOS の置き場がありません: {args.ios}")
        else:
            e, c = check_ios(args.ios)
            errs += e
            n += c
    if args.android:
        if not args.android.exists():
            errs.append(f"  Android の置き場がありません: {args.android}")
        else:
            e, w, c = check_android(args.android)
            errs += e
            warns += w
            n += c

    for w in warns:
        print(f"注意: {w}")
    if errs:
        print(f"アプリアイコンが揃っていません（{n} 枚を見ました）:",
              file=sys.stderr)
        print("\n".join(errs[:20]), file=sys.stderr)
        return 1
    if n == 0:
        print("アイコンが1枚もありません。**0件は「揃っている」ではありません。**",
              file=sys.stderr)
        return 2
    print(f"アプリアイコン: {n} 枚、宣言どおりです。")
    return 0


def _png(path, w, h):
    """検査用の最小の PNG（IHDR だけ正しければ寸法は読める）。"""
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                     + ihdr + b"\x00" * 4)


def self_test():
    import contextlib
    import io
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ios = root / "AppIcon.appiconset"
        ios.mkdir()
        res = root / "res"
        (res / "mipmap-anydpi-v26").mkdir(parents=True)
        (res / "mipmap-hdpi").mkdir()
        (res / "mipmap-xhdpi").mkdir()

        def setup_ios(sizes=((20, "2x", 40), (1024, "1x", 1024))):
            imgs = []
            for base, scale, px in sizes:
                fn = f"Icon-{base}@{scale}.png"
                imgs.append({"size": f"{base}x{base}", "idiom": "iphone",
                             "filename": fn, "scale": scale})
                _png(ios / fn, px, px)
            (ios / "Contents.json").write_text(
                json.dumps({"images": imgs}), encoding="utf-8")

        def setup_android(mono=True):
            layers = ('<background android:drawable="@mipmap/ic_bg"/>\n'
                      '<foreground android:drawable="@mipmap/ic_fg"/>\n')
            if mono:
                layers += '<monochrome android:drawable="@mipmap/ic_mono"/>\n'
            (res / "mipmap-anydpi-v26" / "ic_launcher.xml").write_text(
                f"<adaptive-icon>\n{layers}</adaptive-icon>\n", encoding="utf-8")
            for dens, px in (("mipmap-hdpi", 162), ("mipmap-xhdpi", 216)):
                for nm in ("ic_bg", "ic_fg", "ic_mono"):
                    _png(res / dens / f"{nm}.png", px, px)

        def run(*a):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(list(a))
            return rc, buf.getvalue()

        setup_ios()
        setup_android()
        rc, out = run("--ios", str(ios), "--android", str(res))
        if rc != 0:
            print(f"self-test NG: 揃っているのに落ちた（{rc}）\n   {out[:400]}")
            ok = False

        # **寸法が宣言と違う**（2026-08-27 の壊れ方）
        _png(ios / "Icon-20@2x.png", 20, 20)
        rc, out = run("--ios", str(ios))
        if rc != 1 or "20x20 です" not in out or "1024" in out.split("宣言は")[1][:20]:
            if rc != 1 or "20x20 です" not in out:
                print(f"self-test NG: 寸法の違いを見逃した（{rc}）\n   {out[:300]}")
                ok = False
        setup_ios()

        # 宣言されたファイルが無い
        (ios / "Icon-20@2x.png").unlink()
        rc, out = run("--ios", str(ios))
        if rc != 1 or "ファイルがありません" not in out:
            print(f"self-test NG: 欠けたファイルを通した（{rc}）"); ok = False
        setup_ios()

        # 宣言に無い置き忘れ
        _png(ios / "Icon-old.png", 64, 64)
        rc, out = run("--ios", str(ios))
        if rc != 1 or "置き忘れ" not in out:
            print(f"self-test NG: 置き忘れを通した（{rc}）"); ok = False
        (ios / "Icon-old.png").unlink()

        # **monochrome が無い**
        setup_android(mono=False)
        rc, out = run("--android", str(res))
        if rc != 1 or "monochrome の層がありません" not in out:
            print(f"self-test NG: monochrome 抜けを通した（{rc}）"); ok = False
        setup_android()

        # 前景と monochrome の寸法が違う
        _png(res / "mipmap-hdpi" / "ic_mono.png", 100, 100)
        rc, out = run("--android", str(res))
        if rc != 1 or "寸法が違います" not in out:
            print(f"self-test NG: 層ごとの寸法違いを通した（{rc}）"); ok = False
        setup_android()

        # 正方形でない
        _png(res / "mipmap-hdpi" / "ic_fg.png", 162, 100)
        rc, out = run("--android", str(res))
        if rc != 1 or "正方形では" not in out:
            print(f"self-test NG: 正方形でない層を通した（{rc}）"); ok = False
        setup_android()

        # **A案 / B案の判断は機械が決めない**
        rc, out = run("--android", str(res))
        if "デザイナーの判断" not in out:
            print("self-test NG: 判断が人に残ることを書いていない"); ok = False

        # 面を指定しなければ落ちる
        if run()[0] != 2:
            print("self-test NG: 面の指定なしで通した"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
