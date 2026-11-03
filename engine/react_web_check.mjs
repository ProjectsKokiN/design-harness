// Reactの静的な見た目の値を読む。実行時の値とトークン対応は断定しない。
import ts from 'typescript';
import { pathToFileURL } from 'node:url';

const colorKey = /^(?:color|background(?:Color)?|border(?:Top|Right|Bottom|Left)?Color|outlineColor|fill|stroke|caretColor|textDecorationColor)$/;
const dimensionKey = /^(?:(?:padding|margin)(?:Top|Right|Bottom|Left|Block|Inline|BlockStart|BlockEnd|InlineStart|InlineEnd)?|(?:row|column)?[Gg]ap|border(?:(?:Top|Bottom)(?:Left|Right)|(?:Start|End)(?:Start|End))?Radius)$/;
const rawUnit = /(?:^|[^\w-])-?(?:\d*\.)?\d+(?:px|rem|em|pt|vw|vh|%|ch|vmin|vmax)(?!\w)/i;
const rawColor = /#[\da-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color|color-mix)\s*\(/i;
const colorKeywords = new Set(['transparent', 'currentColor', 'inherit', 'none', 'unset', 'initial', 'revert']);
const layoutKeywords = new Set(['0', 'auto', 'inherit', 'unset', 'initial', 'revert', 'normal']);

export function cssValue(value, kind) {
  value = value.trim();
  if ((kind === 'color' ? colorKeywords : layoutKeywords).has(value)) return 'ok';
  if (rawColor.test(value) || rawUnit.test(value)) return 'raw';
  // 名前に含まれる数字は寸法ではない。フォールバックは別に判定する。
  let v = value.replace(/var\(\s*--[\w-]+\s*\)/g, 'T');
  if (v === 'T') return 'ok';
  if (kind === 'color') return v.includes('var(') ? 'unknown' : 'raw';
  if (!v.includes('T')) return /^-?(?:\d*\.)?\d+$/.test(v) ? 'raw' : 'unknown';
  const remainder=value.replace(/var\(\s*--[\w-]+\s*\)/g,'').replace(/\b(?:calc|min|max|clamp)\b/g,'');
  if(/[a-zA-Z_]/.test(remainder)) return 'unknown';
  // 無次元の乗除係数だけを許す。加算の生値やfallbackは許さない。
  if (/\/\s*-?0(?:\.0+)?(?![\w.])/.test(v)) return 'unknown';
  v = v.replace(/([*/])\s*-?(?:\d*\.)?\d+(?![\w.])/g, '$1 S');
  v = v.replace(/-?(?:\d*\.)?\d+\s*\*/g, 'S *');
  if (/\d/.test(v)) return 'raw';
  if (/^T(?:\s+T){1,3}$/.test(v)) return 'ok'; // padding/marginのトークンだけの並記
  const math=ts.createSourceFile('math.ts',`const x=(${v});`,ts.ScriptTarget.Latest,true);
  if(math.parseDiagnostics.length) return 'unknown';
  const kindOf=n=>{
    if(ts.isParenthesizedExpression(n))return kindOf(n.expression);
    if(ts.isIdentifier(n))return n.text==='T'?'dimension':n.text==='S'?'scalar':null;
    if(ts.isPrefixUnaryExpression(n)&&[ts.SyntaxKind.PlusToken,ts.SyntaxKind.MinusToken].includes(n.operator))return kindOf(n.operand);
    if(ts.isCallExpression(n)&&ts.isIdentifier(n.expression)&&['calc','min','max','clamp'].includes(n.expression.text)) {
      const arity=n.expression.text==='clamp'?n.arguments.length===3:n.expression.text==='calc'?n.arguments.length===1:n.arguments.length>0;
      return arity&&n.arguments.every(a=>kindOf(a)==='dimension')?'dimension':null;
    }
    if(ts.isBinaryExpression(n)) {
      const a=kindOf(n.left),b=kindOf(n.right),op=n.operatorToken.kind;
      if([ts.SyntaxKind.PlusToken,ts.SyntaxKind.MinusToken].includes(op))return a===b?a:null;
      if(op===ts.SyntaxKind.AsteriskToken)return (a==='dimension'&&b==='scalar')||(a==='scalar'&&b==='dimension')?'dimension':null;
      if(op===ts.SyntaxKind.SlashToken)return a==='dimension'&&b==='scalar'?'dimension':null;
    }
    return null;
  };
  return kindOf(math.statements[0].declarationList.declarations[0].initializer)==='dimension'?'ok':'unknown';
}

export function analyze(source, filename = 'input.tsx') {
  const sf = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true,
    filename.endsWith('.jsx') ? ts.ScriptKind.JSX : ts.ScriptKind.TSX);
  const out = { parsed: 0, unparsed: 0, violations: [], unknown: [], limits: [], files: 1 };
  const loc = n => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
  const unknown = (n, why) => { out.unparsed++; out.unknown.push({ line: loc(n), why }); };
  const violation = (n, category, value) => out.violations.push({ line: loc(n), category, value });
  if (sf.parseDiagnostics.length) {
    for (const d of sf.parseDiagnostics) {
      const line = sf.getLineAndCharacterOfPosition(d.start ?? 0).line + 1;
      out.unparsed++; out.unknown.push({ line, why: ts.flattenDiagnosticMessageText(d.messageText, '\n') });
    }
    return out;
  }
  const declarations = new Map();
  const gather = n => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name)) {
      const list = declarations.get(n.name.text) ?? [];
      list.push(n); declarations.set(n.name.text, list);
    }
    ts.forEachChild(n, gather);
  };
  gather(sf);
  const mutated = new Set();
  const identifierOf = n => {
    while (ts.isPropertyAccessExpression(n) || ts.isElementAccessExpression(n)) n = n.expression;
    return ts.isIdentifier(n) ? n.text : null;
  };
  const findMutations = n => {
    if (ts.isBinaryExpression(n) && n.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
        n.operatorToken.kind <= ts.SyntaxKind.LastAssignment) mutated.add(identifierOf(n.left));
    if ((ts.isPrefixUnaryExpression(n) || ts.isPostfixUnaryExpression(n)) &&
        [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(n.operator)) mutated.add(identifierOf(n.operand));
    if (ts.isDeleteExpression(n)) mutated.add(identifierOf(n.expression));
    if (ts.isCallExpression(n)) {
      if (ts.isPropertyAccessExpression(n.expression)) mutated.add(identifierOf(n.expression.expression));
      for (const a of n.arguments) if (ts.isIdentifier(a)) mutated.add(a.text);
    }
    ts.forEachChild(n, findMutations);
  };
  findMutations(sf);
  // aliasや別オブジェクトに入れて変更しても、元の定数を静的値として信用しない。
  const dependencies = new Map();
  for (const [name, ds] of declarations) {
    const refs = new Set();
    const collect = n => {
      if (!n) return;
      if (ts.isIdentifier(n) && declarations.has(n.text)) refs.add(n.text);
      ts.forEachChild(n, collect);
    };
    for (const d of ds) collect(d.initializer);
    dependencies.set(name, refs);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const name of [...mutated]) for (const ref of dependencies.get(name) ?? []) {
      if (!mutated.has(ref)) { mutated.add(ref); changed = true; }
    }
  }
  const unwrap = n => {
    while (n && (ts.isParenthesizedExpression(n) || ts.isAsExpression(n) ||
      ts.isSatisfiesExpression(n) || ts.isTypeAssertionExpression(n))) n = n.expression;
    return n;
  };
  // 同名・可変・別スコープの定数は推測しない。
  function binding(n, seen) {
    const bindsName = name => ts.isIdentifier(name) ? name.text === n.text :
      (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) &&
      name.elements.some(e => ts.isBindingElement(e) && bindsName(e.name));
    for (let p = n.parent; p; p = p.parent) {
      if (ts.isFunctionLike(p) && p.parameters.some(param => bindsName(param.name))) return null;
      if (ts.isCatchClause(p) && p.variableDeclaration && bindsName(p.variableDeclaration.name)) return null;
    }
    const ds = declarations.get(n.text);
    if (!ds || ds.length !== 1 || seen.has(ds[0]) || mutated.has(n.text)) return null;
    const d = ds[0];
    if (!(d.parent.flags & ts.NodeFlags.Const)) return null;
    let scope = d.parent.parent.parent;
    while (scope && !ts.isBlock(scope) && !ts.isSourceFile(scope)) scope = scope.parent;
    let p = n;
    while (p && p !== scope) p = p.parent;
    if (!p || d.pos > n.pos) return null;
    return [d.initializer, new Set([...seen, d])];
  }
  function string(n, seen = new Set()) {
    n = unwrap(n);
    if (!n) return null;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) return n.text;
    if (ts.isIdentifier(n)) { const b = binding(n, seen); return b ? string(...b) : null; }
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const a = string(n.left, seen), b = string(n.right, seen);
      return a !== null && b !== null ? a + b : null;
    }
    if (ts.isTemplateExpression(n)) {
      let s = n.head.text;
      for (const span of n.templateSpans) {
        const v = string(span.expression, seen);
        if (v === null) return null;
        s += v + span.literal.text;
      }
      return s;
    }
    return null;
  }
  function visibleRaw(n, kind) {
    n = unwrap(n);
    if (!n) return false;
    if (ts.isNumericLiteral(n)) return Number(n.text) !== 0;
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) return cssValue(n.text, kind) === 'raw';
    if (ts.isTemplateExpression(n)) return [n.head, ...n.templateSpans.map(s => s.literal)]
      .some(s => rawUnit.test(s.text) || rawColor.test(s.text)) || n.templateSpans.some(s => visibleRaw(s.expression, kind));
    if (ts.isBinaryExpression(n)) {
      // 乗除の右辺の数字は係数。ただし左辺が寸法参照かは未検証。
      return visibleRaw(n.left, kind) ||
        (![ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken].includes(n.operatorToken.kind) && visibleRaw(n.right, kind));
    }
    if (ts.isConditionalExpression(n)) return visibleRaw(n.whenTrue, kind) || visibleRaw(n.whenFalse, kind);
    if (ts.isPrefixUnaryExpression(n)) return visibleRaw(n.operand, kind);
    return false;
  }
  function value(n, kind, seen = new Set()) {
    n = unwrap(n);
    if (ts.isIdentifier(n)) {
      const b = binding(n, seen);
      if (b) return value(b[0], kind, b[1]);
    }
    const s = string(n, seen);
    if (s !== null) {
      const result = cssValue(s, kind);
      if (result === 'unknown') unknown(n, 'CSS式を解釈できません');
      else { out.parsed++; if (result === 'raw') violation(n, 'style', s); }
      if (s.includes('var(')) out.limits.push('CSS変数の存在・用途・Figmaとの対応は未検証です');
    } else if (ts.isNumericLiteral(n) || (ts.isPrefixUnaryExpression(n) && ts.isNumericLiteral(n.operand))) {
      out.parsed++; if (Number(n.getText(sf)) !== 0) violation(n, 'style', n.getText(sf));
    } else {
      if (visibleRaw(n, kind)) violation(n, 'style', n.getText(sf));
      unknown(n, '動的な値・別ファイルの参照・未対応の式です');
    }
  }
  function object(n, seen = new Set()) {
    n = unwrap(n);
    if (!n) return;
    if (ts.isIdentifier(n)) {
      const b = binding(n, seen);
      if (b) return object(...b);
      unknown(n, 'styleの参照先を解析できません（別の.ts・可変値・循環・スコープ）'); return;
    }
    if (ts.isConditionalExpression(n)) {
      object(n.whenTrue, seen); object(n.whenFalse, seen);
      unknown(n, 'styleの条件分岐の実行結果は未検証です'); return;
    }
    if (!ts.isObjectLiteralExpression(n)) { unknown(n, 'styleオブジェクトを静的に解析できません'); return; }
    for (const p of n.properties) {
      if (ts.isSpreadAssignment(p)) { object(p.expression, seen); continue; }
      if (!ts.isPropertyAssignment(p) || ts.isComputedPropertyName(p.name)) { unknown(p, 'styleのキー・メソッド・省略形が未対応です'); continue; }
      const key = p.name.text;
      if (colorKey.test(key) || dimensionKey.test(key)) value(p.initializer, colorKey.test(key) ? 'color' : 'dimension', seen);
      else out.limits.push('色・余白・角丸以外のstyleプロパティはこのReact検査の対象外です');
    }
  }
  function classString(s, n) {
    // 空白を含む任意値も壊さず、任意variantの中の角括弧を値と混同しない。
    const classes = s.match(/(?:[^\s\[]|\[[^\]]*\])+/g) ?? [];
    for (const c of classes) {
      const m = c.match(/(?:^|:)(?:-?(?:p[trblxyse]?|m[trblxyse]?|gap(?:-[xy])?|space-[xy]|rounded(?:-[a-z]+)?|bg|text|border(?:-[a-z]+)?|fill|stroke))-\[(.*)\]!?$/);
      const arbitrary = c.match(/(?:^|:)\[([\w-]+):(.*)\]!?$/);
      const prop = arbitrary?.[1]?.replace(/-([a-z])/g, (_, x) => x.toUpperCase());
      const v = m?.[1] ?? arbitrary?.[2];
      if (v !== undefined && (!arbitrary || colorKey.test(prop) || dimensionKey.test(prop))) {
        const color = /(?:^|:)(?:bg|text|fill|stroke)-/.test(c) || (prop && colorKey.test(prop));
        const result = cssValue(v.replaceAll('_', ' '), color ? 'color' : 'dimension');
        if (result === 'unknown') unknown(n, `Tailwind任意値が未対応です: ${c}`);
        else { out.parsed++; if (result === 'raw') violation(n, 'tailwind', c); }
        if (v.includes('var(')) out.limits.push('CSS変数の存在・用途・Figmaとの対応は未検証です');
      } else {
        if (c.includes('[')) unknown(n, `対象外または未対応のTailwind構文です: ${c}`);
        else out.parsed++;
        out.limits.push('意味付きTailwindクラスとトークンの対応は未検証です');
      }
    }
  }
  function classes(n) {
    const s = string(n);
    if (s !== null) return classString(s, n);
    if (ts.isConditionalExpression(unwrap(n))) {
      classes(unwrap(n).whenTrue); classes(unwrap(n).whenFalse);
      unknown(n, '条件の実行結果は未検証です'); return;
    }
    if (ts.isTemplateExpression(unwrap(n))) {
      const t = unwrap(n);
      // 隣接する静的断片をつなげて仮のクラスを作らない。
      for (const s of [t.head, ...t.templateSpans.map(x => x.literal)]) {
        for (const c of s.text.match(/(?:[\w:-]+-\[[^\]]+\]|\[[\w-]+:[^\]]+\])/g) ?? []) classString(c, n);
      }
    }
    unknown(n, 'classNameの動的値・補間・参照先は未解析です');
  }
  const walk = n => {
    if (ts.isJsxAttribute(n) && ['style', 'className'].includes(n.name.getText(sf))) {
      const v = n.initializer;
      if (!v) unknown(n, '値のないstyle/classNameです');
      else if (ts.isJsxExpression(v) && v.expression) {
        if (n.name.getText(sf) === 'style') object(v.expression); else classes(v.expression);
      } else if (ts.isStringLiteral(v) && n.name.getText(sf) === 'className') classes(v);
      else unknown(n, '属性の形式が未対応です');
    }
    if (ts.isJsxSpreadAttribute(n)) unknown(n, 'JSXスプレッドに含まれるstyle/classNameは未解析です');
    ts.forEachChild(n, walk);
  };
  walk(sf);
  out.limits = [...new Set(out.limits)];
  return out;
}

export function analyzeExpectations(source, filename = 'test.mjs') {
  const sf=ts.createSourceFile(filename,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  const out={parsed:0,unparsed:0,violations:[],unknown:[],files:1,
    limits:['期待値のファイル間参照・実行時データフローは未検証です']};
  if(sf.parseDiagnostics.length) {
    out.unparsed=sf.parseDiagnostics.length;
    out.unknown=sf.parseDiagnostics.map(d=>({line:1,why:ts.flattenDiagnosticMessageText(d.messageText,'\n')}));
    return out;
  }
  const check=(lhs,rhs)=>{
    const text=lhs.getText(sf);
    if(!/\b(?:style|background|color|backdropFilter|borderRadius|padding|margin|gap)|dataset\.(?:style|type|variant)/i.test(text)) return;
    const line=sf.getLineAndCharacterOfPosition(rhs.getStart(sf)).line+1;
    if(ts.isStringLiteral(rhs)||ts.isNoSubstitutionTemplateLiteral(rhs)||ts.isNumericLiteral(rhs)) {
      out.parsed++;
      if(rawUnit.test(rhs.text)||rawColor.test(rhs.text)||
        /dataset\.(?:style|type|variant)/i.test(text)||ts.isNumericLiteral(rhs))
        out.violations.push({line,category:'expectation',value:rhs.getText(sf)});
    } else {
      out.unparsed++; out.unknown.push({line,why:'期待値の式の出どころは静的に追跡していません'});
    }
  };
  const walk=n=>{
    if(ts.isBinaryExpression(n)&&[ts.SyntaxKind.EqualsEqualsToken,ts.SyntaxKind.EqualsEqualsEqualsToken,
      ts.SyntaxKind.ExclamationEqualsToken,ts.SyntaxKind.ExclamationEqualsEqualsToken].includes(n.operatorToken.kind)) check(n.left,n.right);
    if(ts.isCallExpression(n)&&/\.(?:equal|strictEqual|deepEqual)$/.test(n.expression.getText(sf))&&n.arguments.length>=2) check(n.arguments[0],n.arguments[1]);
    if(ts.isCallExpression(n)&&/^(?:evaluate|page\.evaluate)$/.test(n.expression.getText(sf))&&n.arguments[0]) {
      const arg=n.arguments[0];
      let inner=null;
      if(ts.isStringLiteral(arg)||ts.isNoSubstitutionTemplateLiteral(arg))inner=arg.text;
      else if(ts.isTemplateExpression(arg)) {
        inner=arg.head.text+arg.templateSpans.map(s=>'__HARNESS_DYNAMIC__'+s.literal.text).join('');
        out.unparsed++;out.unknown.push({line:sf.getLineAndCharacterOfPosition(arg.getStart(sf)).line+1,why:'ブラウザへ渡す式の補間は未検証です'});
      }
      if(inner!==null) {
        const report=analyzeExpectations(inner,filename);
        out.parsed+=report.parsed;out.unparsed+=report.unparsed;
        const offset=sf.getLineAndCharacterOfPosition(arg.getStart(sf)).line;
        out.violations.push(...report.violations.map(v=>({...v,line:v.line+offset})));
        out.unknown.push(...report.unknown.map(v=>({...v,line:v.line+offset})));
      }
    }
    ts.forEachChild(n,walk);
  };
  walk(sf);
  return out;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const { source, filename, mode } = JSON.parse(input);
  process.stdout.write(JSON.stringify(mode === 'expectations' ? analyzeExpectations(source, filename) : analyze(source, filename)));
}
