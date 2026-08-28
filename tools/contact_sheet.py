#!/usr/bin/env python3
"""golden 画像を1枚のタイル画像にまとめる（コンタクトシート）。

【このテンプレートの使い方】
  - submodule から直接呼ぶ（`design/harness/tools/contact_sheet.py`）。出力はアプリの `design/.contact_sheets/`。他のハーネスの治具
    （design_check.py・harness_stats.py）と同じ場所にそろえる。golden は PNG を読むだけなので
    Flutter / RN どちらでも書き換えなしでそのまま使える
  - 実行結果の PNG は git 管理外にする（`.gitignore` に出力先を追記する）
  - 下の【案件ごとに転記】1件（golden の置き場所）だけ、プロジェクトに合わせて書き換える

    python3 design/harness/tools/contact_sheet.py              全 golden を1枚にまとめる
    python3 design/harness/tools/contact_sheet.py --changed    直前の実行との差分がある画像だけ集める
    python3 design/harness/tools/contact_sheet.py --cols 6      列数を指定する（既定は自動）

golden の枚数が増えると「生成した golden は必ず画像として開いて見る」が現実的でなくなる
（一覧の見出し FSCK: `references/verification-phases.md` Phase 3 参照）。1枚にまとめて、
見る手間を実行可能な規模に保つのがこのスクリプトの役目。

**まとめて1枚にするだけで、個別の画像を差し替えたり注釈を焼き込んだりはしない**
（golden 本体を汚さないため）。ラベルはシート側にだけ足す。
"""
import hashlib
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow が要ります: pip install Pillow")
    sys.exit(1)

# ── 案件ごとに転記: golden の置き場所 ───────────────────────────────────────
GOLDENS_DIR = Path("{{golden の置き場所（例 test/ui/goldens）}}")

OUT_DIR = Path("design/.contact_sheets")   # git 管理外にする（.gitignore に追記）
HASH_CACHE = OUT_DIR / ".hashes.txt"       # --changed の比較用（前回実行時のハッシュ）

LABEL_HEIGHT = 24
PADDING = 4
MAX_TILE_WIDTH = 360   # これより大きい golden は縮小してタイルに収める


def load_font():
    """ラベル用フォント。見つからなければ既定のビットマップフォントにフォールバックする。"""
    for candidate in ("/System/Library/Fonts/Helvetica.ttc",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, 14)
    return ImageFont.load_default()


def file_hash(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def pick_changed(files):
    """前回実行時のハッシュと比べて、変わった golden だけを残す。

    初回実行（キャッシュが無い）は全件を変化ありとして扱う。
    """
    prev = {}
    if HASH_CACHE.exists():
        for line in HASH_CACHE.read_text().splitlines():
            if "\t" in line:
                h, name = line.split("\t", 1)
                prev[name] = h

    changed = [f for f in files if prev.get(f.name) != file_hash(f)]
    return changed


def save_hashes(files):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{file_hash(f)}\t{f.name}" for f in files]
    HASH_CACHE.write_text("\n".join(lines) + "\n")


def make_tile(path, font):
    """1枚の golden を「画像＋ファイル名ラベル」のタイルにする。"""
    img = Image.open(path).convert("RGBA")
    if img.width > MAX_TILE_WIDTH:
        ratio = MAX_TILE_WIDTH / img.width
        img = img.resize((MAX_TILE_WIDTH, int(img.height * ratio)))

    tile = Image.new("RGBA", (img.width, img.height + LABEL_HEIGHT), "white")
    tile.paste(img, (0, 0), img)
    draw = ImageDraw.Draw(tile)
    draw.rectangle([0, img.height, img.width, img.height + LABEL_HEIGHT], fill="#222")
    draw.text((4, img.height + 4), path.stem, fill="white", font=font)
    return tile


def build_sheet(tiles, cols):
    if not cols:
        cols = max(1, int(len(tiles) ** 0.5))
    rows = (len(tiles) + cols - 1) // cols

    cell_w = max(t.width for t in tiles) + PADDING * 2
    cell_h = max(t.height for t in tiles) + PADDING * 2
    sheet = Image.new("RGBA", (cell_w * cols, cell_h * rows), "white")

    for i, tile in enumerate(tiles):
        x = (i % cols) * cell_w + PADDING
        y = (i // cols) * cell_h + PADDING
        sheet.paste(tile, (x, y), tile)
    return sheet


def main():
    args = sys.argv[1:]
    only_changed = "--changed" in args
    cols = None
    if "--cols" in args:
        cols = int(args[args.index("--cols") + 1])

    if not GOLDENS_DIR.exists():
        print(f"golden の置き場所が見つかりません: {GOLDENS_DIR}")
        return 1

    files = sorted(GOLDENS_DIR.glob("*.png"))
    if not files:
        print(f"{GOLDENS_DIR} に PNG がありません。")
        return 1

    target = pick_changed(files) if only_changed else files
    save_hashes(files)   # 次回の --changed のために、常に現在のハッシュを残す

    if not target:
        print("前回実行から変化した golden はありません。")
        return 0

    font = load_font()
    tiles = [make_tile(f, font) for f in target]
    sheet = build_sheet(tiles, cols)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "changed" if only_changed else "all"
    out_path = OUT_DIR / f"contact_sheet_{suffix}.png"
    sheet.save(out_path)

    print(f"{len(target)} 枚 / 全 {len(files)} 枚 を1枚にまとめました: {out_path}")
    print("このシートを開いて見てください（個別に golden を1枚ずつ開く代わり）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
