#!/usr/bin/env python3
"""push 前のフックが「何を飛ばし、何を止めるか」を実際に回して見る（#61・#60）。

## なぜ要るか

`ci/app-pre-push` は**シェルで書かれていて、誰も試していなかった。**

実害（flash-compose・2026-09-04）: マージ済みの枝6本を消そうとして
**10分で時間切れ**になり、3本が消えないまま残った。削除は**送る中身が
1バイトもありません**。それでも検査が丸ごと3分走る。

もう1つ（#60）: ピンの検査が `2>/dev/null || true` で呼ばれており、
**出力を捨てて必ず成功していた。**

## 何をするか

雛形をそのまま `sh` に渡し、`design/verify.sh` を合成した偽物に差し替えて、
**押された枝の一覧（stdin）ごとに何が起きるか**を見る。
"""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "ci" / "app-pre-push"

ZERO = "0" * 40
SHA = "a" * 40


def run_case(refs, uname="Darwin", verify=True):
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "design").mkdir()
        if verify:
            (d / "design" / "verify.sh").write_text(
                "#!/bin/sh\necho '検査を回しました'\n", encoding="utf-8")
        # uname を差し替える（Mac かどうかで分岐するため）
        bin_ = d / "bin"
        bin_.mkdir()
        (bin_ / "uname").write_text(f"#!/bin/sh\necho {uname}\n", encoding="utf-8")
        (bin_ / "uname").chmod(0o755)
        env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(d)}
        r = subprocess.run(["sh", str(HOOK)], input=refs, capture_output=True,
                           text=True, cwd=d, env=env)
        return r.returncode, r.stdout + r.stderr


CASES = [
    ("枝の削除だけなら検査を飛ばす",
     f"(delete) {ZERO} refs/heads/old {SHA}\n"
     f"(delete) {ZERO} refs/heads/old2 {SHA}\n",
     0, "検査を飛ばします", "検査を回しました"),
    ("**1行でも削除以外があれば検査する**（混ぜた push を素通りさせない）",
     f"(delete) {ZERO} refs/heads/old {SHA}\n"
     f"refs/heads/work {SHA} refs/heads/work {ZERO}\n",
     0, "検査を回しました", "検査を飛ばします"),
    ("ふつうの push は検査に入る",
     f"refs/heads/work {SHA} refs/heads/work {ZERO}\n",
     0, "検査を回しました", None),
    ("Mac から main への直 push は止める",
     f"refs/heads/main {SHA} refs/heads/main {ZERO}\n",
     1, "直 push は止めています", "検査を回しました"),
    ("main 宛ての削除も止める（stdin を1度しか読めない罠）",
     f"(delete) {ZERO} refs/heads/main {SHA}\n",
     1, "直 push は止めています", None),
    ("Mac 以外なら main へ push できる",
     f"refs/heads/main {SHA} refs/heads/main {ZERO}\n",
     0, "検査を回しました", "直 push は止めています"),
    ("verify.sh が無ければ落とす（黙って通さない）",
     f"refs/heads/work {SHA} refs/heads/work {ZERO}\n",
     1, "検査せずに push はしません", None),
]


def main():
    ok = True
    for i, (name, refs, want, needle, absent) in enumerate(CASES):
        uname = "Linux" if "Mac 以外" in name else "Darwin"
        verify = "verify.sh が無ければ" not in name
        rc, out = run_case(refs, uname=uname, verify=verify)
        if rc != want:
            print(f"NG: {name} → exit {rc}（期待 {want}）")
            print("   " + out.strip().replace("\n", "\n   ")[:400])
            ok = False
            continue
        if needle and needle not in out:
            print(f"NG: {name} → 「{needle}」が出ていない\n   {out.strip()[:300]}")
            ok = False
        if absent and absent in out:
            print(f"NG: {name} → 「{absent}」が出てはいけない")
            ok = False

    # **ピンの検査が握り潰されていないこと**（#60。`2>/dev/null || true` の再発防止）
    text = HOOK.read_text(encoding="utf-8")
    for bad in ("pin_check.py 2>/dev/null", "pin_check.py || true"):
        if bad in text:
            print(f"NG: ピンの検査が握り潰されています: {bad}")
            ok = False
    if "pin_check.py --root . || exit 1" not in text:
        print("NG: ピンの検査の結果を見ていません")
        ok = False

    print(f"prepush_test: {'OK' if ok else 'NG'}（{len(CASES) + 2} 件）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
