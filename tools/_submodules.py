"""submodule の置き場を **git から導く**（名前で決め打ちしない）。

## なぜ要るか（design-harness #97 / #105）

道具が `"harness" in parts` や `"/harness/" in str(f)` で submodule を外していた。
**名前で外している**ので、ハーネス一式を `site/design/harness/` に置いている案件
（QnD）では、**案件のファイルまで全部外れる**。

実害（2026-09-09・qnd-database で実測）:

- `generated_check` が「生成物が1件も見つかりません」と出た。**生成器は4本あり、
  生成物は6件ある。** 全部 `site/design/harness/` の下なので名前で外れていた
- `issue_sync` が**案件の宣言を1件も見つけられない**。同じ根

**submodule かどうかは、名前ではなく `.gitmodules` に書いてあります。**

## 分からないときは、外しません

git が無い・リポジトリでない・`.gitmodules` が無いときは **空を返します**。
呼ぶ側は**何も外さない**ことになります。**多く見えるほうを選びます**——
外しすぎて `0 件` になると、**「綺麗」と読み違える**からです（#97 がその形でした）。
"""
import shutil
import subprocess
from pathlib import Path


def submodule_paths(root):
    """`(root からの相対パスの集合, 導き方)` を返す。

    導き方は `"git"`（`.gitmodules` から読めた）か `"不明"`（読めなかった）。
    **`"不明"` のときは集合が空で、呼ぶ側は何も外しません。**
    """
    root = Path(root)
    exe = shutil.which("git")
    if not exe or not (root / ".gitmodules").is_file():
        return set(), "不明"
    try:
        r = subprocess.run(
            [exe, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace")
    except OSError:
        return set(), "不明"
    if r.returncode != 0:
        return set(), "不明"
    out = set()
    for line in r.stdout.split("\n"):
        line = line.strip()
        if not line:
            continue
        # `submodule.<名前>.path <パス>`。**パスに空白が入りうる**ので1回だけ割る
        _, _, path = line.partition(" ")
        path = path.strip()
        if path:
            out.add(Path(path))
    return out, ("git" if out else "不明")


def is_inside(rel, subs) -> bool:
    """`rel`（root からの相対）が、`subs` のどれかの中にあるか。

    **前方一致で見ます。** `design/harness` と `design/harness2` を
    取り違えないよう、`Path` の部分列で比べます。
    """
    rel = Path(rel)
    for s in subs:
        parts = Path(s).parts
        if rel.parts[:len(parts)] == parts:
            return True
    return False
