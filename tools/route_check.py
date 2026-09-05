#!/usr/bin/env python3
"""画面をまたぐ矛盾を見る（2026-09-04 に aub-familywalk から回収・#57）。

**画面まわりの検査が共有層に1本もありませんでした。** aub は39本持っていますが
`design-harness/tools/` には上がっておらず、他の案件では
「遷移先が存在しない画面を指している」「どこからも行けない画面がある」が
**通ってしまいます。1画面ずつの検査では原理的に拾えない層**です。

## 実害（aub-familywalk・2026-08-30）

**`/bingo` `/album` `/scrapboard` `/settings` は `appRouter` に定義だけあって、
どこからも呼ばれていませんでした。** アプリは「スプラッシュ → Start →
カウントダウン → PROGRESS で行き止まり」で、**Mac mini が実機の通し確認で
見つけるまで誰も気づきませんでした。**

`flutter analyze` は通ります。テストも通ります。**定義したのに呼ばれない、は
静的解析では捕まりません**（行き先は文字列で結ぶため）。

## 見るもの

    python3 tools/route_check.py --lib lib [--allow /debug=デバッグ用]

1. `GoRoute(path: '…')` として定義された行き先を集める（**包んだ作り役
   `_fadeRoute('/a', …)` からの定義も数える**）
2. そのほかの場所に文字列として出てくる行き先を集める
3. **どこからも行けない行き先**と、**定義されていない行き先へ行こうとする箇所**
   を出す

呼び出しの**形**では数えません。多行の三項演算子・`pushReplacement`・`switch` 式
では、呼び出し名と行き先が同じ行に並ばないためです（2026-08-30 に `/photo` を
「どこからも行けない」と誤診しました）。

## 捕まえないもの

- 行き先が**正しい画面を出すか**。ここは「結ばれているか」だけ
- 条件つきの導線（実行時にしか通らない道）。**文字列として出ていれば数えます**
- 確かめた方法: --self-test（6件。定義0件を「問題なし」で通さないことを含む）
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 起点。ここから辿る。
START = '/'

def collect(lib: Path):
    """定義された行き先と、**そのほかに文字列として出てくる行き先**を集める。

    呼び出しの形で数えない。**多行の三項演算子・`pushReplacement`・
    `switch` 式の中では、呼び出し名と行き先が同じ行に並ばない**からで、
    2026-08-30 に `/photo` を「どこからも行けない」と誤診した。

    数えるのは単純に「`GoRoute(path: ...)` **以外の場所**にその文字列が
    出てくるか」。出てこなければ、どこからも指されていない。
    """
    defined, elsewhere = {}, set()
    _ALL_SRC[str(lib)] = "\n".join(
        f.read_text(encoding='utf-8', errors='ignore') for f in lib.rglob('*.dart')
        if 'catalog' not in f.parts)
    for f in sorted(lib.rglob('*.dart')):
        if 'catalog' in f.parts:
            continue
        src = f.read_text(encoding='utf-8')
        # **定義の書き方は1つとは限らない。** `GoRoute(path: '…')` のほかに、
        # 出方（フェード等）を変えるために包んだ作り役から定義することがある。
        # 2026-08-30、`_fadeRoute('/photo', …)` へ移した3つが「定義されて
        # いない」と誤診された。**包み方を変えただけで見張りが外れる**のは
        # 検査の穴なので、作り役の呼び出しも定義として数える。
        teigi = (r"GoRoute\(\s*path:\s*'([^']+)'"
                 r"|\b_\w*[Rr]oute\(\s*'([^']+)'")
        for m in re.finditer(teigi, src):
            defined[m.group(1) or m.group(2)] = f.name
        # 定義そのものを消してから、残りに出てくる行き先を拾う
        nokori = re.sub(teigi, '', src)
        for m in re.finditer(r"'(/[A-Za-z0-9_/-]*)(?:\?[^']*)?'", nokori):
            elsewhere.add(m.group(1))
        # **シェルの枝は番号で遷移する**（`shell.goBranch(1)`）。行き先の文字列が
        # 定義以外の場所に出てこないので、そのままだと「どこからも行けない」と
        # 誤診する（FlashEnglish 2026-09-05: `/mypage` を誤診）。
        # `StatefulShellRoute(` の中で定義された行き先は、lib のどこかで
        # `goBranch(` が呼ばれていれば届いているとみなす
        if 'goBranch(' in _ALL_SRC.get(str(lib), ''):
            for block in _shell_blocks(src):
                for m in re.finditer(teigi, block):
                    elsewhere.add(m.group(1) or m.group(2))
    return defined, elsewhere


_ALL_SRC = {}


def _shell_blocks(src):
    """`StatefulShellRoute(` から対応する `)` までの塊を返す（括弧を数える）。"""
    out, i = [], 0
    while True:
        i = src.find('StatefulShellRoute', i)
        if i < 0:
            return out
        j = src.find('(', i)
        if j < 0:
            return out
        depth, k = 0, j
        while k < len(src):
            c = src[k]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(src[j:k + 1])
        i = k + 1


def check(lib: Path, allow=None) -> int:
    allow = allow or {}
    defined, called = collect(lib)
    if not defined:
        print('[NG] GoRoute の定義が1つも見つかりません。'
              '**0件・問題なしは「何も見ていない」という意味です。**', file=sys.stderr)
        return 2

    todokanai = sorted(p for p in defined
                       if p != START and p not in called and p not in allow)
    shiranai = sorted(p for p in called if p not in defined and p.startswith('/')
                      and len(p) > 1)

    ng = []
    for p in todokanai:
        ng.append(f'{p}（{defined[p]}）に**どこからも行けません**。'
                  '導線を足すか、定義を消してください')
    for p in shiranai:
        ng.append(f"'{p}' へ行こうとしていますが、その行き先は定義されていません")

    if ng:
        print('[NG] 行き先に届きません。')
        for x in ng:
            print(f'  - {x}')
        return 1
    print(f'行き先の到達: 通った（定義 {len(defined)} 件すべてに導線がある）')
    return 0


def self_test() -> int:
    """**落ちるところを見る。** 通るだけの検査は何も見ていないのと同じ。"""
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / 'lib'
        lib.mkdir()
        r = lib / 'router.dart'

        r.write_text("GoRoute(path: '/'), GoRoute(path: '/a')\ncontext.go('/a');", encoding='utf-8')
        if check(lib) != 0:
            print('self-test NG: 全部つながっているのに落ちた'); ok = False

        r.write_text("GoRoute(path: '/'), GoRoute(path: '/a')\n", encoding='utf-8')
        if check(lib) != 1:
            print('self-test NG: 呼ばれない行き先があるのに落ちなかった'); ok = False

        r.write_text("GoRoute(path: '/')\ncontext.go('/nowhere');", encoding='utf-8')
        if check(lib) != 1:
            print('self-test NG: 無い行き先へ行こうとしたのに落ちなかった'); ok = False

        # **包んだ作り役からの定義も見る。** ここが無いと、出方を変える
        # ために包んだだけで「定義されていない」と誤診する
        # （2026-08-30 に実際に誤診した）。
        r.write_text("GoRoute(path: '/')\n_fadeRoute('/a', b);\n"
                     "context.go('/a');", encoding='utf-8')
        if check(lib) != 0:
            print('self-test NG: 包んだ作り役の定義を見落とした'); ok = False

        r.write_text("GoRoute(path: '/')\n_fadeRoute('/a', b);\n", encoding='utf-8')
        if check(lib) != 1:
            print('self-test NG: 包んだ作り役でも、呼ばれない行き先を見逃した')
            ok = False

        r.write_text("// 何も無い\n", encoding='utf-8')
        if check(lib) != 2:
            print('self-test NG: 定義0件を「問題なし」で通した'); ok = False
    # **理由つきの宣言があれば通す**（共有層に上げるにあたって追加・2026-09-04）
    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / 'lib'
        lib.mkdir()
        (lib / 'r.dart').write_text("GoRoute(path: '/'), GoRoute(path: '/debug')\n",
                                    encoding='utf-8')
        if check(lib, {'/debug': 'デバッグ用。導線は持たない'}) != 0:
            print('self-test NG: 理由つきの宣言があるのに落ちた'); ok = False
        if check(lib, {}) != 1:
            print('self-test NG: 宣言なしで通した'); ok = False
    # **main() を通す。** ここまでの検査は check() を直に呼んでおり、
    # 引数の読み取り・理由の必須・実装の不在を1行も通っていなかった
    import contextlib as _ctx
    import io as _io
    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / 'lib'
        lib.mkdir()
        (lib / 'r.dart').write_text(
            "GoRoute(path: '/'), GoRoute(path: '/a')\ncontext.go('/a');",
            encoding='utf-8')

        def call(*a):
            b = _io.StringIO()
            with _ctx.redirect_stdout(b), _ctx.redirect_stderr(b):
                rc = main(['--lib', str(lib), *a])
            return rc, b.getvalue()

        if call()[0] != 0:
            print('self-test NG: main() が通らない'); ok = False
        rc, out = call('--allow', '/debug')
        if rc != 2 or '理由が要ります' not in out:
            print(f'self-test NG: 理由の無い --allow を通した（{rc}）'); ok = False
        rc, out = call('--allow', '/debug=  ')
        if rc != 2:
            print('self-test NG: 空白だけの理由を通した'); ok = False
        (lib / 'r.dart').write_text("GoRoute(path: '/'), GoRoute(path: '/b')\n",
                                    encoding='utf-8')
        rc, out = call('--allow', '/b=デバッグ用。導線は持たない')
        if rc != 0:
            print(f'self-test NG: 理由つきの --allow が効かない（{rc}）'); ok = False
        rc, out = call()
        if rc != 1 or '/b' not in out:
            print(f'self-test NG: main() 経由で落ちない（{rc}）'); ok = False
        b = _io.StringIO()
        with _ctx.redirect_stdout(b), _ctx.redirect_stderr(b):
            rc = main(['--lib', str(Path(td) / 'ない')])
        if rc != 2 or '見ていない' not in b.getvalue():
            print(f'self-test NG: 実装が無いのに通した（{rc}）'); ok = False

    # シェルの枝（番号で遷移）を誤診しないこと（FlashEnglish 2026-09-05）
    import tempfile as _tf, io as _io, contextlib as _ctx
    with _tf.TemporaryDirectory() as td2:
        lib2 = Path(td2) / "lib"; lib2.mkdir()
        (lib2 / "router.dart").write_text(
            "final r = GoRouter(routes: [\n"
            "  GoRoute(path: '/', builder: (c, s) => Start()),\n"
            "  StatefulShellRoute(branches: [\n"
            "    StatefulShellBranch(routes: [GoRoute(path: '/study')]),\n"
            "    StatefulShellBranch(routes: [GoRoute(path: '/mypage')]),\n"
            "  ]),\n]);\n", encoding="utf-8")
        (lib2 / "nav.dart").write_text(
            "void go(StatefulNavigationShell s, int i) => s.goBranch(i);\n"
            "void start(BuildContext c) => c.go('/study');\n", encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            rc = check(lib2)
        if rc != 0:
            print("self-test NG: シェルの枝（goBranch）を「行けない」と誤診した"); ok = False
        (lib2 / "nav.dart").write_text("void start(BuildContext c) => c.go('/study');\n",
                                       encoding="utf-8")
        with _ctx.redirect_stdout(_io.StringIO()), _ctx.redirect_stderr(_io.StringIO()):
            rc = check(lib2)
        if rc != 1:
            print("self-test NG: goBranch が無いのにシェルの枝を届いたことにした"); ok = False

    print('self-test: ' + ('OK' if ok else 'NG'))
    return 0 if ok else 1



def main(argv=None):
    ap = argparse.ArgumentParser(description="画面をまたぐ矛盾を見る")
    ap.add_argument("--lib", type=Path, default=Path("lib"))
    ap.add_argument("--allow", nargs="*", default=[],
                    help="呼ばれなくてよい行き先。**理由が要る**（/debug=デバッグ用）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.lib.exists():
        print(f"実装がありません: {args.lib}\n"
              f"  **0件は「問題なし」ではなく「見ていない」です。**", file=sys.stderr)
        return 2
    allow = {}
    for a in args.allow:
        if "=" not in a or not a.split("=", 1)[1].strip():
            print(f"--allow には理由が要ります: {a}（例: /debug=デバッグ用）",
                  file=sys.stderr)
            return 2
        k, v = a.split("=", 1)
        allow[k] = v
    return check(args.lib, allow)


if __name__ == "__main__":
    sys.exit(main())
