"""案件のソースの拡張子を、**宣言ではなく `design/rules.json` から導く。**

design-harness #124（2026-09-18）。SwiftUI の案件を足すにあたり、
道具の中に `*.dart` が直接書かれていると、**Swift の案件では検査が
1件も当たらないまま通ります**（0件は「綺麗」ではなく「見ていない」）。

拡張子の正本は `design/rules.json` の `file_extensions` です。
**新しく持つのではなく、既にあるものを使います。**

見つからないときは `[".dart"]` を返します。**既存の案件の挙動を変えないため**です。
"""
from __future__ import annotations

import json
from pathlib import Path

FALLBACK = [".dart"]


def source_exts(start: Path | str | None = None) -> list[str]:
    """`design/rules.json` の `file_extensions` を返す。無ければ `[".dart"]`。

    **`start` は案件のどこでもよい。** 見つかるまで上へ辿ります
    （呼ぶ側が案件の根を知らなくてよくするため）。
    """
    here = Path(start) if start else Path.cwd()
    if here.is_file():
        here = here.parent
    here = here.resolve()
    for d in [here, *here.parents]:
        for rel in ("design/rules.json", "rules.json"):
            f = d / rel
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue  # mutation-ok: 壊れた rules.json は別の道具が咎める
            exts = data.get("file_extensions")
            if isinstance(exts, list) and exts:
                out = [e if e.startswith(".") else "." + e
                       for e in exts if isinstance(e, str)]
                if out:
                    return out
    return list(FALLBACK)


GENERATED_SUFFIXES = (".g.dart", ".generated.swift", ".generated.ts", ".g.ts")


def is_generated(path: Path) -> bool:
    """生成物か。**手で書いた層と混ぜないため**に使う。"""
    return any(path.name.endswith(x) for x in GENERATED_SUFFIXES)


def rglob_sources(base: Path, project_root: Path | str | None = None) -> list[Path]:
    """`base` の下のソースを、案件の拡張子で集めて返す（並びは決まった順）。

    **既定は `base` から上へ辿ります。** ここをカレントにすると、
    道具を案件の外から呼んだときに拡張子が `.dart` に倒れ、
    **Swift の案件で「0 件」を返します**（0 件は「綺麗」ではなく「見ていない」）。
    2026-09-18 に仕込みで実際に踏みました。
    """
    out: list[Path] = []
    for ext in source_exts(project_root or base):
        out += base.rglob("*" + ext)
    return sorted(set(out))


def glob_sources(base: Path, project_root: Path | str | None = None) -> list[Path]:
    """`base` の直下だけを見る版。既定は `base` から上へ辿る（上記と同じ理由）。"""
    out: list[Path] = []
    for ext in source_exts(project_root or base):
        out += base.glob("*" + ext)
    return sorted(set(out))


def self_test() -> int:
    import tempfile

    bad = []

    def case(name, got, want):
        if got != want:
            bad.append(f"{name}: {want} のはずが {got}")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        root = Path(d)
        # 1. rules.json が無いときは Dart に倒す（既存の案件を壊さない）
        case("宣言が無いとき", source_exts(root), [".dart"])

        # 2. Swift の案件を読む
        (root / "design").mkdir()
        (root / "design/rules.json").write_text(
            json.dumps({"file_extensions": [".swift"]}), encoding="utf-8")
        case("Swift の案件", source_exts(root), [".swift"])

        # 3. 点が無くても補う
        (root / "design/rules.json").write_text(
            json.dumps({"file_extensions": ["swift", "m"]}), encoding="utf-8")
        case("点の補い", source_exts(root), [".swift", ".m"])

        # 4. 壊れた JSON でも落とさず Dart に倒す
        (root / "design/rules.json").write_text("{壊れている", encoding="utf-8")
        case("壊れた宣言", source_exts(root), [".dart"])

        # 5. **実際にファイルを集められるか**（空振りしていないか）
        (root / "design/rules.json").write_text(
            json.dumps({"file_extensions": [".swift"]}), encoding="utf-8")
        src = root / "Sources/App"
        src.mkdir(parents=True)
        (src / "A.swift").write_text("//", encoding="utf-8")
        (src / "B.dart").write_text("//", encoding="utf-8")
        got = [p.name for p in rglob_sources(root / "Sources", root)]
        case("Swift だけ集める", got, ["A.swift"])

        # 6. **深いところから呼んでも見つかる**（上へ辿る）
        case("上へ辿る", source_exts(src), [".swift"])

        # 6-2. **案件の外から呼んでも 0 件にならない**（2026-09-18 に実際に踏んだ）
        import os
        keep = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())   # 案件の外に居る状態を作る
            case("外から呼んでも見つかる",
                 [p.name for p in rglob_sources(root / "Sources")], ["A.swift"])
        finally:
            os.chdir(keep)

        # 7. 生成物の判定
        case("生成物 dart", is_generated(Path("a.g.dart")), True)
        case("生成物 swift", is_generated(Path("A.generated.swift")), True)
        case("手書き", is_generated(Path("A.swift")), False)

    if bad:
        for b in bad:
            print(b)
        print(f"NG: 自己検査が {len(bad)} 件落ちました")
        return 1
    print("OK: 自己検査 10 件とも期待どおりでした")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(self_test())
