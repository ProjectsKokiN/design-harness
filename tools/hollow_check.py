#!/usr/bin/env python3
"""検査が回っているのに何も見ていない書き方を見つける（2026-09-04 新設・#17）。

## 実害（aub-familywalk・2026-09-02〜03）

2日で**5件**出た。**全部「緑」だった。うち3件は実機とユーザーが見つけている。**

| | 形 | どうやって分かったか |
|---|---|---|
| 1 | **例外を捨てていた。** `tester.takeException()` ではみ出しの例外を捨てた | **Mac mini が実機で 12px のはみ出しを発見** |
| 2 | **空の状態しか描いていなかった。** 写真ゼロで始まる画面なので行が1つも出ず、「行が幅いっぱいか」が空回り | 仕込み試験 |
| 3 | **期待値が検査対象そのものだった。** 日付の場所を実装の関数から取っていたので、**そこから日付を消しても通る** | 仕込み試験 |
| 4 | **finder が別の widget を拾っていた。** 「幅いっぱいの `SizedBox`」で探していたので、固定値に戻しても通る | 仕込み試験 |
| 5 | **画面に直書きした文字を誰も突き合わせていない。** アプリ名を変えても `verify.sh` も **805件の試験も全部通った** | 名前を変える作業のついで |

**1件目がいちばん重い。**「試験の書体では正しい実装でもはみ出す」という思い込みを
`takeException()` という1行で固定した。**その1行があるかぎり、この画面のはみ出しは
永久に見えない。**

## 既存の段では捕まらない理由

- `#12`（関門の段が飛ぶ）は**段が飛ぶ**話。こちらは**段は回っている**のに中身が空
- `expectation_source_check` は**期待値の出どころ**を見るが、
  **その期待値に到達しているか**は見ない（3件目・4件目はここをすり抜ける）
- 仕込み試験は**規律として書いてある**だけで、**やった記録がどこにも残らない**

## 見るもの

    python3 tools/hollow_check.py --config design/hollow.json

| 形 | 見つけ方 |
|---|---|
| 1 例外を捨てる | `takeException()` の**戻り値を捨てている**文（`expect` にも代入にも渡していない） |
| 3 期待値の自己参照 | `expect(実際, 期待)` の**期待の側**が `lib/` の手書きの識別子を呼んでいる（生成物 `.g.dart` は書き出しなので除く） |
| 4 緩い finder | 何百個もある widget（`SizedBox` `Container` …）で探して `.first` / `.at(n)` を当てている |
| 5 誰も見ていない文字 | 画面に直書きされていて、試験にも書き出しにも1度も出てこない文字（**件数のラチェット**） |
| 6 1つの幅でしか回らない検査 | 案件が宣言した画面幅のうち、**2つ以上を試験が使っていない** |
| 7 文字幅を素のスタイルで測る | `TextPainter` に `DefaultTextStyle` を混ぜず、文字倍率も落としている |
| 8 打ち消し合い（#70） | `expect` の**両辺が同じ実装ファイルの関数**を呼んでいて、その検査ファイルが描いた値（`getSize` / `getRect`）も書き出しも**1度も読んでいない**。実装を壊しても両辺で打ち消し合って通る |

形6 の実害（aub-familywalk・2026-09-02）: 画面のコードが Figma の幅 390 に
焼き付いていた（`MediaQuery` の使用が **0件**）。**照合は 390 の1点だけ**なので、
伸びるべきものを固定値で書いても**必ず通る**。ユーザーが4機種で確認して
**14件**のずれが出た。個別の不具合ではなく、**写し方の誤りが14通りに現れたもの**。

> Figmaの幅390に焼き付いてしまうのはかなり問題です。基本的にFigmaで設定している
> FigHugFixedの分類は私の方で適切に行うので、それに合わせて描画内もデバイスに
> 応じて縦幅横幅を変更するようにしてほしいです。（2026-09-02 ユーザー）

守るべき幅は案件が宣言する（`design/devices.json`）。**形は案件によって違う**
（aub は `min` / `max`、FlashEnglish は `widths`）ので、**数だけを拾う**。

形2（空の状態しか描かない）は静的には見つからない。`--sabotage` の記録で見る。

## 捕まえないもの

- 形2 そのもの。**描いた状態が中身のあるものか**は、実際に描かないと分からない
- 期待値が正しいか。**この道具は「誰も見ていない書き方」だけを見る**
- 検査が自分で書いた補助関数が、その中で実装を呼んでいる形（2段目の自己参照）。
  検査ファイルが自分で宣言した名前は分母から外している（そうしないと、
  期待値を自分で組み直しただけの正しい書き方を咎める。aub 実測で8件が誤検出）
- 確かめた方法: --self-test（5形それぞれを仕込むと落ちること）
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _utf8  # noqa: F401  出力の文字コードで死なない（tools/_utf8.py）

#: 何百個も並ぶ入れ物。これで探して1つ選ぶと、別の widget を拾う
GENERIC_WIDGETS = {
    "SizedBox", "Container", "Padding", "Align", "Center", "Column", "Row",
    "Stack", "ConstrainedBox", "DecoratedBox", "Positioned", "Expanded",
    "Flexible", "ClipRRect", "Opacity", "Transform", "Material", "Semantics",
}

#: Dart の予約語と、どこにでもある名前。識別子として数えない
DART_KEYWORDS = {
    "switch", "return", "assert", "await", "catch", "throw", "case", "else",
    "while", "yield", "super", "this", "print", "const", "final", "class",
    "main", "build", "test", "setUp", "tearDown", "expect", "group", "when",
}

#: この行は見ない、という印（エンジンの harness-ignore と同じ考え方）
IGNORE_RX = re.compile(r"harness-ignore:\s*(.+?)(?:\s+expires=(\d{4}-\d{2}-\d{2}))?\s*$")

#: 画面に出る文字。`Text('…')` と `title: '…'` と `label: '…'`
STRING_RX = re.compile(r"""(?:Text\(|title:\s*|label:\s*|hintText:\s*)['"]([^'"\n]{2,})['"]""")

#: 「描いた値」を測っている印（形3 はここが実際の側にあるときだけ見る）
MEASURE_RX = re.compile(r"\b(getSize|getRect|getTopLeft|getTopRight|getBottomLeft|getBottomRight|"
                        r"getCenter|widget<|widgetList|renderObject|firstWidget|getSemantics)\b")

#: lib/ の識別子（トップレベル関数・static メソッド・const）
DECL_RX = re.compile(
    r"^\s*(?:static\s+)?(?:[\w<>,\s\[\]?]+\s+)?([a-z][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:async\s*)?(?:=>|\{)",
    re.M)
CONST_RX = re.compile(r"^\s*(?:static\s+)?const\s+(?:[\w<>,\s]+\s+)?([a-z][A-Za-z0-9_]*)\s*=", re.M)


def statements(text):
    """Dart のソースを「文」に割る。**丸括弧の中の改行では割らない。**

    行で見ると `expect(\\n  tester.takeException(),\\n  isNull)` を
    **「戻り値を捨てている」と誤って読む**（aub に実在する書き方）。

    括弧を積んで見る。`;` で割るのは、**いちばん内側の開き括弧が `{` のとき**
    （か何も開いていないとき）だけ。Dart の検査は
    `testWidgets('…', (tester) async { … });` の形で、**中身は丸括弧の中にある**
    ので、丸括弧の深さだけで見ると1文も割れない。
    文字列の中の `;` と `//` から先は数えない。
    """
    out, buf, stack, i = [], [], [], 0
    line_no, start, quote = 1, 1, ""
    while i < len(text):
        c = text[i]
        if c == "\n":
            line_no += 1
        if quote:
            buf.append(c)
            if c == "\\":
                if i + 1 < len(text):
                    buf.append(text[i + 1])
                    i += 2
                    continue
            elif c == quote:
                quote = ""
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "/" and text[i:i + 2] == "//":
            j = text.find("\n", i)
            i = len(text) if j < 0 else j
            continue
        if c in "([{":
            stack.append(c)
        elif c in ")]}" and stack:
            stack.pop()
        if c == ";" and (not stack or stack[-1] == "{"):
            out.append((start, "".join(buf)))
            buf, start = [], line_no
            i += 1
            continue
        if not buf and c in " \t\n{}":
            start = line_no
        else:
            buf.append(c)
        i += 1
    if "".join(buf).strip():
        out.append((start, "".join(buf)))
    return out


def line_of(start, st, idx):
    """文の中の位置から、実際の行番号を出す。

    文の先頭の行で報告すると、`void main() {` の行を指してしまい、
    その行の `harness-ignore` の印も読めない。**印は当の行に書く。**
    """
    return start + st[:idx].count("\n")


def ignored(lines, line_no):
    """その行（か直前の行）に harness-ignore の印があるか。期限切れは印とみなさない。"""
    for n in (line_no - 1, line_no - 2):
        if 0 <= n < len(lines):
            m = IGNORE_RX.search(lines[n])
            if m:
                exp = m.group(2)
                if exp and exp < date.today().isoformat():
                    return False
                return True
    return False


def dart_files(root):
    if not root or not root.exists():
        return []
    return [f for f in sorted(root.rglob("*.dart"))
            if ".dart_tool" not in f.parts and "build" not in f.parts]


def check_swallowed(tests, base):
    """形1: 例外を捨てている。**この1行があるかぎり、その画面の例外は永久に見えない。**"""
    out = []
    for f in tests:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if "takeException" not in text:
            continue
        lines = text.splitlines()
        for ln, st in statements(text):
            if "takeException()" not in st:
                continue
            # expect に渡している / 変数に受けているなら捨てていない
            if "expect(" in st or re.search(r"=[^=]", st.split("takeException")[0]):
                continue
            at = line_of(ln, st, st.index("takeException()"))
            if ignored(lines, at):
                continue
            out.append((f.relative_to(base), at,
                        "takeException() の戻り値を捨てています。"
                        "この画面の例外は**永久に見えません**"))
    return out


def lib_symbols(lib, generated=(".g.dart",)):
    """lib/ で宣言されている識別子。期待値の側に出てきたら自己参照。

    **生成物（`.g.dart`）は外す。** それは書き出しそのもので、
    期待値が書き出し由来であることは**この仕組みが求めている形**
    （`expectation_source_check` と同じ考え方）。手で書いた実装を
    期待値にするのだけが自己参照。
    """
    names = set()
    for f in dart_files(lib):
        if any(f.name.endswith(g) for g in generated):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        names |= set(DECL_RX.findall(text)) | set(CONST_RX.findall(text))
    return {n for n in names if len(n) > 3} - DART_KEYWORDS


def lib_symbol_files(lib, generated=(".g.dart",)):
    """lib/ の識別子 → それを宣言しているファイル（形8 で「同じ出どころ」を判定する）。"""
    out = {}
    for f in dart_files(lib):
        if any(f.name.endswith(g) for g in generated):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for n in set(DECL_RX.findall(text)) | set(CONST_RX.findall(text)):
            if len(n) > 3 and n not in DART_KEYWORDS:
                out.setdefault(n, f)
    return out


#: 書き出しを読んでいる印（別経路の1つ）
EXPORT_READ_RX = re.compile(r"figma/|design/|\.json['\"]|loadExport|readExport")


def check_same_source(tests, base, sym_files, allow):
    """形8: 期待値と実測が**同じ実装**から来ていて、別経路と1度も突き合わせていない。

    aub 2026-09-04（#70）: `expect(cropFraction(...) を戻したもの, square(...))` は両辺が
    同じ `square()` を呼ぶので、**`square()` を壊しても両辺で打ち消し合って通った。**
    描いた四角（`tester.getRect`）と突き合わせて初めて落ちた。

    「1か所にまとめる」は正しい方針だが、**まとめた関数を検査の両辺で使うと、検査は自分を
    検査する。** 通るのが当たり前なので、書いた本人は「検査した」と思う。

    **検査ファイル単位で見る。** 実装どうしの突き合わせが1件以上あり、そのファイルに描いた値
    （MEASURE_RX）も書き出しの読みも1つも無ければ、実装を実装で採点しているだけ。
    形3 が見るのは「描いた値を実装で採点」で、こちらは「実装を実装で採点」。
    """
    out = []
    if not sym_files:
        return out
    for f in tests:
        rel = f.relative_to(base).as_posix()
        text = f.read_text(encoding="utf-8", errors="ignore")
        if MEASURE_RX.search(text) or EXPORT_READ_RX.search(text):
            continue                           # 別経路と1つは突き合わせている
        mine = set(DECL_RX.findall(text)) | set(CONST_RX.findall(text))
        pairs = []
        for ln, st in statements(text):
            i = st.find("expect(")
            if i < 0:
                continue
            args = split_args(st[i + len("expect("):st.rfind(")")])
            if len(args) < 2:
                continue
            sides = []
            for a in args[:2]:
                a = re.sub(r"'[^']*'|\"[^\"]*\"", "''", a)
                sides.append({sym_files[n] for n in sym_files
                              if n not in mine and re.search(r"\b" + re.escape(n) + r"\s*\(", a)})
            common = sides[0] & sides[1]
            if common:
                pairs.append((line_of(ln, st, i), sorted(p.name for p in common)[0]))
        if pairs and rel not in allow:
            out.append((f.relative_to(base), pairs[0][0],
                        f"期待値と実測が同じ実装（{pairs[0][1]}）から来ている突き合わせが "
                        f"{len(pairs)} 件あり、描いた値（getSize / getRect）も書き出しも"
                        f"1度も読んでいません。**実装を壊しても両辺で打ち消し合って通ります。** "
                        f"別経路と1つは突き合わせるか、hollow.json の「打ち消し合い」に"
                        f"理由つきで宣言してください"))
    return out


def split_args(inner):
    """`expect(a, b)` の中身を、いちばん外側のカンマで割る。"""
    parts, buf, depth = [], [], 0
    for c in inner:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(c)
    parts.append("".join(buf))
    return parts


def check_self_reference(tests, base, symbols):
    """形3: 期待値が検査対象そのもの。**そこから値を消しても通る。**"""
    out = []
    if not symbols:
        return out
    for f in tests:
        text = f.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        # **その検査ファイルが自分で宣言している名前は外す。**
        # 検査が期待値を自分で組み直すのは正しい書き方で、たまたま実装と
        # 同じ名前になっただけのものを咎めると誤検出になる
        # （aub 実測: `naka` `tabOf` の8件が全部これだった）
        mine = set(DECL_RX.findall(text)) | set(CONST_RX.findall(text))
        here = symbols - mine
        if not here:
            continue
        for ln, st in statements(text):
            i = st.find("expect(")
            if i < 0:
                continue
            args = split_args(st[i + len("expect("):st.rfind(")")])
            if len(args) < 2:
                continue
            # **文字列の中の名前は呼び出しではない。** FlashEnglish 2026-09-05:
            # `expect(Footer.heightFor(), value('Footer.heightFor()'))` の期待値は
            # 書き出しを鍵で引いており、鍵の文字列に名前が入っているだけだった（7件誤検出）
            expected = re.sub(r"'[^']*'|\"[^\"]*\"", "''", args[1])
            # **実際の側が「描いた値」のときだけ見る。** 形3 の実害は
            # 「描いた位置を、実装の計算で採点した」（aub の hardAreasFor / FlashEnglish の
            # getSize vs heightFor）。純粋な関数どうしの整合性の試験
            # （`expect(levels(), questionsByLevel().keys)`）は Figma と無関係で、
            # 実装を呼ぶのが自然（FlashEnglish 2026-09-05: 10件が全部これだった）
            if not MEASURE_RX.search(args[0]):
                continue
            hit = [n for n in here if re.search(r"\b" + re.escape(n) + r"\s*\(", expected)]
            at = line_of(ln, st, i)
            if not hit or ignored(lines, at):
                continue
            out.append((f.relative_to(base), at,
                        f"期待値が実装の `{hit[0]}()` を呼んでいます。"
                        f"**そこから値を消しても通ります**"))
    return out


def check_loose_finder(tests, base):
    """形4: 何百個もある widget で探して1つ選んでいる。**別の widget を拾う。**"""
    out = []
    pick = re.compile(r"\.(?:first|last|at\(\d+\))")
    for f in tests:
        text = f.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for ln, st in statements(text):
            for m in re.finditer(r"find\.byType\((\w+)\)", st):
                tail = st[m.end():m.end() + 40]
                at = line_of(ln, st, m.start())
                if m.group(1) in GENERIC_WIDGETS and pick.match(tail.lstrip()):
                    if ignored(lines, at):
                        continue
                    out.append((f.relative_to(base), at,
                                f"`{m.group(1)}` は画面に何十個もあります。"
                                f"そこから1つ選ぶと**別の widget を拾います**"))
            # 型で絞らない predicate から1つ選ぶのも同じ
            if "byWidgetPredicate(" in st and pick.search(st):
                j = st.find("byWidgetPredicate(")
                body = st[j:j + 400]
                at = line_of(ln, st, j)
                if not re.search(r"\bis\s+[A-Z]\w+", body) and not ignored(lines, at):
                    out.append((f.relative_to(base), at,
                                "型で絞らない predicate から1つ選んでいます"))
    return out


def check_unmatched_strings(lib, tests, exports, base):
    """形5: 画面に直書きされていて、誰も突き合わせていない文字。

    aub の実害: アプリ名を変えても `verify.sh` も **805件の試験も全部通った**。
    """
    corpus = []
    for f in tests:
        corpus.append(f.read_text(encoding="utf-8", errors="ignore"))
    for d in exports:
        if d.exists():
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix in (".json", ".dart", ".md"):
                    corpus.append(f.read_text(encoding="utf-8", errors="ignore"))
    blob = "\n".join(corpus)
    out = []
    for f in dart_files(lib):
        text = f.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().startswith("//"):
                continue
            for m in STRING_RX.finditer(line):
                s = m.group(1)
                if s.startswith(("http", "assets/", "package:")) or s.isascii() and s.islower():
                    continue
                if s in blob or ignored(lines, i + 1):
                    continue
                out.append((f.relative_to(base), i + 1, f"「{s}」"))
    return out


def declared_widths(path):
    """案件が宣言した画面幅を集める。**形は案件によって違うので数だけ拾う。**

    aub:            {"min": [{"size": [360, 640]}], "max": [...]}
    FlashEnglish:  {"widths": [{"dp": 320}, ...], "height": {"dp": 844}}

    どちらの形も「幅らしい数」を拾えばよい。**共通の形を決めない**
    （決めると片方が書き換えになり、決定の記録が散る）。
    """
    if not path or not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    out = set()

    def walk(o, key=None):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.startswith("$"):
                    continue
                walk(v, k)
        elif isinstance(o, list):
            # size: [w, h] は先頭が幅
            if o and all(isinstance(x, (int, float)) for x in o):
                out.add(int(o[0]))
                return
            for v in o:
                walk(v, key)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            if key in ("dp", "width", "w") and 200 <= o <= 2000:
                out.add(int(o))
    walk(doc)
    return sorted(out)


def check_widths(tests, widths):
    """試験が、宣言した幅を2つ以上使っているかを見る。

    **1つの幅でしか回らない検査は、伸びるべきものを固定値で写しても通る。**
    """
    if not widths or len(widths) < 2:
        return []
    blob = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in tests)
    used = [w for w in widths if re.search(r"(?<![\w.])" + str(w) + r"(?:\.\d+)?(?![\w.])",
                                           blob)]
    if len(used) >= 2:
        return []
    return [f"  [1つの幅でしか回らない] 宣言した幅 {widths} のうち、"
            f"試験が使っているのは {used or 'なし'} だけです。\n"
            f"    **1点でしか測らない照合は、伸びるべきものを固定値で写しても"
            f"必ず通ります。**\n"
            f"    aub の実測: 390 の1点だけで回していて、実機で14件出ました。"]


#: 文字幅を測っている箇所
PAINTER_RX = re.compile(r"TextPainter\s*\(")


def check_text_measure(files, base):
    """形7: 文字幅を素のスタイルで測っていないか（2026-09-04・#54）。

    FlashEnglish の実害: **同じ 2px の誤りを2箇所で独立にやりました。**

    | 場所 | 素の style で測ると | 実際の描画 |
    |---|---|---|
    | シートの上タブ | 96.0 | **98.0** |
    | 下部ナビ | 80.0 | **82.0** |

    `MaterialApp` の既定が `letterSpacing: 0.25` を持ち、8文字で **+2.0** に
    なります。案件のスタイルは `letterSpacing` を `null` にしているので
    `DefaultTextStyle` から継ぎます。**`Text` は継ぐのに、`TextPainter` に
    素のスタイルを渡すと継ぎません。**

    **文字倍率（`textScaler`）も落としていました。** OS の文字拡大を上げると
    必要な幅は増えるのに、素の `TextPainter` は 1.0 で測ります。

    正しい測り方:

        final effective = DefaultTextStyle.of(context).style.merge(myStyle);
        TextPainter(text: TextSpan(text: label, style: effective),
                    textDirection: TextDirection.ltr,
                    textScaler: MediaQuery.textScalerOf(context))..layout();

    **翻訳規則に書いていなかったので、AI は毎回素の `TextPainter` を書きます。**
    """
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if not PAINTER_RX.search(text):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if not PAINTER_RX.search(line):
                continue
            # 呼び出しは複数行にまたがる。前後8行をひとまとまりで見る
            blob = "\n".join(lines[max(0, i - 4):i + 9])
            miss = []
            if "DefaultTextStyle" not in blob:
                miss.append("`DefaultTextStyle.of(context).style.merge(…)` を"
                            "混ぜていません（**字間が落ちて短く出ます**）")
            if "textScaler" not in blob:
                miss.append("`textScaler` を渡していません"
                            "（**OS の文字拡大で必要な幅が増えます**）")
            if miss and not ignored(lines, i + 1):
                out.append((f.relative_to(base), i + 1,
                            "文字幅を素のスタイルで測っています。"
                            + " / ".join(miss)))
    return out


def check_sabotage(config_path, base):
    """仕込み試験の記録が、検査の最後の変更より古くないか。

    aub では**5件のうち3件が仕込み試験で見つかった**。回すかどうかが人の記憶に
    依っているのが、いちばん薄いところ。だから**記録として残させる。**
    """
    errs = []
    rec = {}
    if config_path and config_path.exists():
        try:
            rec = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return [f"仕込みの記録が読めません: {config_path}: {e}"]
    for path, entries in sorted(rec.items()):
        if path.startswith("$"):
            continue
        f = base / path
        if not f.exists():
            errs.append(f"  記録にある検査がありません: {path}"
                        f"（記録のほうが古くなっています）")
            continue
        if not isinstance(entries, list) or not entries:
            errs.append(f"  {path} の記録が空です")
            continue
        try:
            out = subprocess.run(["git", "-C", str(base), "log", "-1",
                                  "--format=%cs", "--", path],
                                 capture_output=True, text=True, timeout=20)
            changed = out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            changed = ""
        newest = max((str(e.get("at", "")) for e in entries), default="")
        bad = [e for e in entries if not e.get("落ちた")]
        if bad:
            errs.append(f"  {path}: 壊しても**落ちなかった**仕込みが "
                        f"{len(bad)} 件あります: "
                        + " / ".join(str(e.get("壊し方")) for e in bad))
        if changed and newest and newest < changed:
            errs.append(f"  {path}: 検査は {changed} に変わったのに、"
                        f"仕込みの記録は {newest} のままです。\n"
                        f"    **直したあとに壊して試していません。**")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description="何も見ていない検査の書き方を見つける")
    ap.add_argument("--config", type=Path, default=Path("design/hollow.json"))
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    conf = {}
    if args.config.exists():
        try:
            conf = json.loads(args.config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"設定が読めません: {args.config}: {e}", file=sys.stderr)
            return 2
    base = args.root.resolve()
    tests_dir = base / conf.get("tests", "test")
    lib_dir = base / conf.get("lib", "lib")
    exports = [base / p for p in conf.get("exports", ["design"])]

    tests = dart_files(tests_dir)
    if not tests:
        print(f"検査が1つもありません: {tests_dir}\n"
              f"  **この道具の「0件」は『見ていない』であって『綺麗』ではありません。**",
              file=sys.stderr)
        return 2

    findings = []
    generated = tuple(conf.get("generated", [".g.dart"]))
    same_allow = (conf.get("打ち消し合い") or {}).get("allow") or {}
    for rel, why in same_allow.items():
        if not str(why).strip():
            findings.append(f"  [打ち消し合い] 宣言に理由がありません: {rel}")
    for label, hits in (
        ("例外を捨てている", check_swallowed(tests, base)),
        ("期待値が実装を呼んでいる", check_self_reference(tests, base, lib_symbols(
            lib_dir, generated))),
        ("打ち消し合い", check_same_source(tests, base, lib_symbol_files(lib_dir, generated),
                                        set(same_allow))),
        ("緩い finder", check_loose_finder(tests, base)),
    ):
        for path, ln, why in hits:
            findings.append(f"  [{label}] {path}:{ln} {why}")

    for path, ln, why in check_text_measure(dart_files(lib_dir) + tests, base):
        findings.append(f"  [文字幅の測り方] {path}:{ln} {why}")

    strings = check_unmatched_strings(lib_dir, tests, exports, base)
    decl = conf.get("文字の照合", {}).get("expectedUnmatched")
    warns = []
    if isinstance(decl, int):
        if len(strings) > decl:
            findings.append(
                f"  [誰も見ていない文字] {len(strings)}件で、宣言（{decl}）を"
                f"上回りました。**画面の文字を変えても全部通る状態が増えています。**")
            for path, ln, s in strings[:8]:
                findings.append(f"    {path}:{ln} {s}")
        elif len(strings) < decl:
            warns.append(f"誰も見ていない文字が {len(strings)} 件に減りました。"
                         f"{args.config.name} の expectedUnmatched を下げてください。")
    elif strings:
        warns.append(f"誰も見ていない文字が {len(strings)} 件あります。"
                     f"{args.config.name} に expectedUnmatched を書くと"
                     f"**増えたときに落ちます**（いまは数えるだけ）。")

    sab = check_sabotage(base / conf["sabotage"], base) if conf.get("sabotage") else []
    findings.extend(sab)

    dev = conf.get("devices")
    if dev:
        widths = declared_widths(base / dev)
        if widths is None:
            findings.append(f"  [1つの幅でしか回らない] 画面幅の宣言が読めません: {dev}")
        elif len(widths) < 2:
            findings.append(
                f"  [1つの幅でしか回らない] 宣言された幅が {widths} だけです。\n"
                f"    **どの幅で成り立てばよいのかが決まっていません。**"
                f"最小と最大を書いてください。")
        else:
            findings.extend(check_widths(tests, widths))
    else:
        warns.append("画面幅の宣言（devices）が設定にありません。"
                     "**検査が1つの幅でしか回っていないかを見ていません。**")

    for w in warns:
        print(f"注意: {w}")
    if findings:
        print(f"検査が回っているのに何も見ていない書き方があります"
              f"（検査 {len(tests)} ファイル）:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"空振りの書き方 0件（検査 {len(tests)} ファイル / "
          f"誰も見ていない文字 {len(strings)}件）。")
    return 0


def self_test():
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "test").mkdir()
        (root / "lib").mkdir()
        (root / "design").mkdir()
        lib = root / "lib" / "screen.dart"
        t = root / "test" / "a_test.dart"
        conf = root / "design" / "hollow.json"
        lib.write_text(
            "List<double> hardAreasFor(double w) => [w];\n"
            "Widget build() => Text('いい調子Walk');\n", encoding="utf-8")
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 1}}),
                        encoding="utf-8")
        argv = ["--config", str(conf), "--root", str(root)]

        import contextlib, io

        def run(src):
            t.write_text(src, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = main(argv)
            return rc, buf.getvalue()

        CLEAN = ("void main() {\n"
                 "  test('x', () {\n"
                 "    expect(t.takeException(), isNull);\n"
                 "    expect(w, 100.0);\n"
                 "    expect(find.byType(ScreenFooter), findsOneWidget);\n"
                 "  });\n"
                 "}\n")
        rc, out = run(CLEAN)
        if rc != 0:
            print(f"self-test NG: 綺麗な検査で落ちた（{rc}）\n   {out[:300]}"); ok = False

        # 形1: 例外を捨てる。**複数行の expect を誤検出しないこと**が要点
        rc, out = run(CLEAN.replace("expect(t.takeException(), isNull);",
                                    "tester.takeException();"))
        if rc != 1 or "例外を捨てている" not in out:
            print(f"self-test NG: 捨てた例外を見逃した（{rc}）"); ok = False
        rc, out = run(CLEAN.replace("expect(t.takeException(), isNull);",
                                    "expect(\n      tester.takeException(),\n"
                                    "      isNull,\n    );"))
        if rc != 0:
            print(f"self-test NG: 複数行の expect を誤検出した（{rc}）"); ok = False
        rc, _ = run(CLEAN.replace("expect(t.takeException(), isNull);",
                                  "// harness-ignore: 理由あり\n"
                                  "    tester.takeException();"))
        if rc != 0:
            print(f"self-test NG: 印のある行で落ちた（{rc}）"); ok = False
        rc, _ = run(CLEAN.replace("expect(t.takeException(), isNull);",
                                  "// harness-ignore: 理由 expires=2020-01-01\n"
                                  "    tester.takeException();"))
        if rc != 1:
            print(f"self-test NG: 期限切れの印を通した（{rc}）"); ok = False

        # 形3: 期待値の自己参照
        rc, out = run(CLEAN.replace("expect(w, 100.0);",
                                    "expect(tester.getTopLeft(find.byKey(k)).dy, hardAreasFor(10).last);"))
        if rc != 1 or "期待値が実装" not in out:
            print(f"self-test NG: 描いた値を実装で採点しているのを見逃した（{rc}）"); ok = False
        # 純粋な関数どうしの整合性は形3 ではない（描いた値を見ていない）——が、
        # **同じ実装どうしを突き合わせるだけで、描いた値も書き出しも読まないファイル**は
        # 形8（打ち消し合い・#70）。実装を壊しても両辺で打ち消し合って通る
        SAME = CLEAN.replace("expect(w, 100.0);",
                             "expect(hardAreasFor(10).length, hardAreasFor(20).length);")
        rc, out = run(SAME)
        if rc != 1 or "打ち消し合い" not in out or "期待値が実装" in out:
            print(f"self-test NG: 同じ実装どうしの突き合わせだけの検査を通した／形3 と混同した（{rc}）\n"
                  f"   {out[:300]}"); ok = False
        # 同じファイルで描いた値と1つ突き合わせていれば通る
        rc, _ = run(SAME.replace("expect(find.byType(ScreenFooter), findsOneWidget);",
                                 "expect(tester.getSize(find.byKey(k)).width, 100.0);"))
        if rc != 0:
            print(f"self-test NG: 描いた値と突き合わせているのに打ち消し合いで落ちた（{rc}）"); ok = False
        # 書き出しを読んでいれば通る
        rc, _ = run(SAME.replace("expect(find.byType(ScreenFooter), findsOneWidget);",
                                 "final doc = File('design/figma/frames.json');"))
        if rc != 0:
            print(f"self-test NG: 書き出しを読んでいるのに打ち消し合いで落ちた（{rc}）"); ok = False
        # 理由つきの宣言なら通り、理由が無ければ落ちる
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 1},
                                    "打ち消し合い": {"allow": {"test/a_test.dart": "純粋な計算の整合性。描くものが無い"}}},
                                   ensure_ascii=False), encoding="utf-8")
        if run(SAME)[0] != 0:
            print("self-test NG: 理由つきの打ち消し合いの宣言を通さない"); ok = False
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 1},
                                    "打ち消し合い": {"allow": {"test/a_test.dart": ""}}},
                                   ensure_ascii=False), encoding="utf-8")
        if run(SAME)[0] != 1:
            print("self-test NG: 理由の無い打ち消し合いの宣言を通した"); ok = False
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 1}}), encoding="utf-8")
        rc, _ = run(CLEAN.replace("expect(w, 100.0);",
                                  "expect(hardAreasFor(10).last, 10.0);"))
        if rc != 0:
            print(f"self-test NG: 実際の側で呼んだだけで落ちた（{rc}）"); ok = False
        # 期待値が書き出しを**鍵の文字列**で引いていて、その鍵に名前が入っているだけ
        rc, _ = run(CLEAN.replace("expect(w, 100.0);",
                                  "expect(hardAreasFor(10).last, value('hardAreasFor(10)'));"))
        if rc != 0:
            print(f"self-test NG: 鍵の文字列の中の名前を呼び出しと取り違えた（{rc}）"); ok = False

        # 形4: 緩い finder
        rc, out = run(CLEAN.replace("find.byType(ScreenFooter), findsOneWidget",
                                    "find.byType(SizedBox).first, findsOneWidget"))
        if rc != 1 or "緩い finder" not in out:
            print(f"self-test NG: 緩い finder を見逃した（{rc}）"); ok = False
        rc, _ = run(CLEAN.replace("find.byType(ScreenFooter), findsOneWidget",
                                  "find.byType(ScreenFooter).first, findsOneWidget"))
        if rc != 0:
            print(f"self-test NG: 固有の型で1つ選んだだけで落ちた（{rc}）"); ok = False
        rc, out = run(CLEAN.replace(
            "find.byType(ScreenFooter), findsOneWidget",
            "find.byWidgetPredicate((w) => w.width == 100).first, findsOneWidget"))
        if rc != 1 or "型で絞らない" not in out:
            print(f"self-test NG: 型で絞らない predicate を見逃した（{rc}）"); ok = False

        # 形5: 誰も見ていない文字（ラチェット）
        lib.write_text(lib.read_text(encoding="utf-8")
                       + "Widget b2() => Text('ファミリーウォーク');\n", encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 1 or "誰も見ていない文字" not in out:
            print(f"self-test NG: 文字が増えたのに落ちなかった（{rc}）"); ok = False
        # 検査に書けば「見ている」ことになる
        rc, out = run(CLEAN.replace("expect(w, 100.0);",
                                    "expect(find.text('ファミリーウォーク'), findsOne);"))
        if rc != 0:
            print(f"self-test NG: 検査が突き合わせているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False

        # ─── 形7: 文字幅を素のスタイルで測る（#54）────────────────
        # ここまでで文字が2件になっているので、宣言を合わせてから見る
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 2}}),
                        encoding="utf-8")
        WRONG = ("final tp = TextPainter(\n"
                 "  text: TextSpan(text: label, style: AppText.labelBoldMedium),\n"
                 "  textDirection: TextDirection.ltr,\n"
                 ")..layout();\n")
        RIGHT = ("final e = DefaultTextStyle.of(context).style.merge(s);\n"
                 "final tp = TextPainter(\n"
                 "  text: TextSpan(text: label, style: e),\n"
                 "  textDirection: TextDirection.ltr,\n"
                 "  textScaler: MediaQuery.textScalerOf(context),\n"
                 ")..layout();\n")
        lib.write_text(lib.read_text(encoding="utf-8") + WRONG, encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 1 or "文字幅の測り方" not in out:
            print(f"self-test NG: 素の TextPainter を見逃した（{rc}）"); ok = False
        if "字間が落ちて短く出ます" not in out or "文字拡大" not in out:
            print("self-test NG: 何が落ちるかを書いていない"); ok = False
        base_lib = lib.read_text(encoding="utf-8").replace(WRONG, "")
        lib.write_text(base_lib + RIGHT, encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 0:
            print(f"self-test NG: 正しい測り方で落ちた（{rc}）\n   {out[:300]}")
            ok = False
        lib.write_text(base_lib, encoding="utf-8")

        # ─── 形6: 1つの幅でしか回らない検査（#8）──────────────────
        dev = root / "design" / "devices.json"
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 2},
                                    "devices": "design/devices.json"}),
                        encoding="utf-8")
        # aub の形（min / max に size: [w, h]）
        dev.write_text(json.dumps({"min": [{"size": [360, 640]}],
                                   "max": [{"size": [440, 956]}]}), encoding="utf-8")
        if declared_widths(dev) != [360, 440]:
            print(f"self-test NG: aub の形から幅を拾えない: {declared_widths(dev)}")
            ok = False
        rc, out = run(CLEAN + "// 360 だけ\n    expect(w, 360.0);\n")
        if rc != 1 or "1つの幅でしか回らない" not in out:
            print(f"self-test NG: 1つの幅だけの試験を通した（{rc}）"); ok = False
        rc, out = run(CLEAN.replace("expect(w, 100.0);",
                                    "expect(w, 360.0);\n    expect(w2, 440.0);"))
        if rc != 0:
            print(f"self-test NG: 2つの幅を使っているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        # FlashEnglish の形（widths に dp）
        dev.write_text(json.dumps({"widths": [{"dp": 320}, {"dp": 390}, {"dp": 430}],
                                   "height": {"dp": 844}}), encoding="utf-8")
        if declared_widths(dev) != [320, 390, 430, 844]:
            print(f"self-test NG: flash の形から幅を拾えない: {declared_widths(dev)}")
            ok = False
        # 宣言が1つしか無ければ落ちる（どの幅で成り立てばよいか決まっていない）
        dev.write_text(json.dumps({"widths": [{"dp": 390}]}), encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 1 or "決まっていません" not in out:
            print(f"self-test NG: 幅の宣言が1つなのに通した（{rc}）"); ok = False
        # 宣言そのものが無ければ注意を出す（黙って飛ばさない）
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 2}}),
                        encoding="utf-8")
        rc, out = run(CLEAN)
        if "1つの幅でしか回っていないかを見ていません" not in out:
            print("self-test NG: 幅の宣言が無いことを言っていない"); ok = False

        # 仕込みの記録
        sab = root / "design" / "sabotage.json"
        conf.write_text(json.dumps({"文字の照合": {"expectedUnmatched": 2},
                                    "sabotage": "design/sabotage.json"}),
                        encoding="utf-8")
        sab.write_text(json.dumps({"test/a_test.dart": [
            {"壊し方": "固定値に戻す", "落ちた": True, "at": "2099-01-01"}]},
            ensure_ascii=False), encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 0:
            print(f"self-test NG: 記録がそろっているのに落ちた（{rc}）\n   {out[:300]}")
            ok = False
        sab.write_text(json.dumps({"test/a_test.dart": [
            {"壊し方": "固定値に戻す", "落ちた": False, "at": "2099-01-01"}]},
            ensure_ascii=False), encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 1 or "落ちなかった" not in out:
            print(f"self-test NG: 落ちない仕込みを通した（{rc}）"); ok = False
        sab.write_text(json.dumps({"test/gone_test.dart": [
            {"壊し方": "x", "落ちた": True, "at": "2099-01-01"}]},
            ensure_ascii=False), encoding="utf-8")
        rc, out = run(CLEAN)
        if rc != 1 or "記録のほうが古く" not in out:
            print(f"self-test NG: 消えた検査の記録を通した（{rc}）"); ok = False

        # 検査が1つも無ければ落ちる（この道具自身の空振り）
        t.unlink()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            if main(argv) != 2:
                print("self-test NG: 検査0件なのに落ちなかった"); ok = False
    print("self-test:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
