import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root=new URL('../',import.meta.url);
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
async function functions() {
  const src=await readFile(new URL('exporters/export_frames.js',root),'utf8');
  const part=src.slice(src.indexOf('function h('),src.indexOf('const SECTIONS'));
  const figma={mixed:Symbol(),getStyleByIdAsync:async()=>({name:'Display/S'}),
    variables:{getVariableByIdAsync:async()=>({name:'Size/XL',resolveForConsumer:()=>({value:48})})},getNodeByIdAsync:async()=>null};
  return new AsyncFunction('figma',part+'\nreturn {shape,walk,ovValue,NOT_READ,h};')(figma);
}
test('形の追加欄・ゼロ・falseを保存する',async()=>{
  const {shape}=await functions();
  const s=await shape({type:'FRAME',isMask:true,layoutPositioning:'ABSOLUTE',constraints:{horizontal:'STRETCH',vertical:'MIN'},
    clipsContent:false,numberOfFixedChildren:0,strokeWeight:4,strokeTopWeight:0});
  for(const key of ['isMask=true','layoutPositioning=','constraints=','clipsContent=false','numberOfFixedChildren=0','strokeWeight=4','strokeTopWeight=0']) assert.ok(s.includes(key),s);
});
test('字下げと種類を取り、実寸の未検証を出す',async()=>{
  const {shape,NOT_READ}=await functions();
  const s=await shape({id:'text',name:'Label',type:'TEXT',textStyleId:'style',characters:'one',
    getStyledTextSegments:()=>[{start:0,end:3,fontName:{family:'Inter',style:'Regular'},fontSize:16,listOptions:{type:'UNORDERED'},indentation:1}]});
  assert.ok(s.includes('UNORDERED')&&s.includes('indentation'));
  assert.ok(NOT_READ.some(n=>n.fields.includes('listIndentWidth')));
});
test('古い文字変数の束縛を流さない',async()=>{
  const {ovValue,NOT_READ}=await functions();
  const s=await ovValue({id:'text',name:'Label',type:'TEXT',textStyleId:'style',fontSize:16,boundVariables:{fontSize:{id:'v'}}},'boundVariables');
  assert.deepEqual(s,{});
  assert.ok(NOT_READ.some(n=>n.fields.includes('fontSize')));
});
test('SLOTの差し込んだ子だけを取得する',async()=>{
  const {walk}=await functions();
  const leaf={id:'I1;3',type:'RECTANGLE',name:'Content',width:20,height:20,x:0,y:0};
  const slot={id:'I1;2',type:'SLOT',name:'Slot',children:[leaf],width:20,height:20,x:0,y:0};
  const instance={id:'1',type:'INSTANCE',name:'Lists',getMainComponentAsync:async()=>null,children:[slot],width:20,height:20,x:0,y:0};
  const rows=[],ids=[];await walk(instance,0,rows,ids);
  assert.equal(rows.length,3);assert.ok(rows[1].includes('slotPath='));assert.ok(rows[2].includes('Content'));
  assert.deepEqual(ids,['1','I1;2','I1;3']);
});
test('ID の一覧が行と同じ順に並び、畳んだ行は ID の配列になる（#157）',async()=>{
  const {walk}=await functions();
  const dot=id=>({id,type:'ELLIPSE',name:'Dot',width:8,height:8,x:0,y:0});
  const fr={id:'1:1',type:'FRAME',name:'F',width:100,height:100,x:0,y:0,children:[dot('1:2'),dot('1:3'),
    {id:'1:4',type:'RECTANGLE',name:'Bar',width:50,height:4,x:0,y:20}]};
  const rows=[],ids=[];await walk(fr,0,rows,ids);
  assert.equal(ids.length,rows.length);
  assert.deepEqual(ids,['1:1',['1:2','1:3'],'1:4']);assert.ok(rows[1].includes('Dot×2'));
});
test('辺ごとに違う線の太さ（figma.mixed）で落ちず、MIXED と書く（2026-11-03・414）',async()=>{
  const {shape}=await functions();
  const s=await shape({type:'FRAME',strokes:[{type:'SOLID',color:{r:0,g:0,b:0}}],strokeWeight:Symbol('mixed'),strokeAlign:'INSIDE',
    layoutMode:'GRID',gridRowCount:1,gridColumnCount:1,gridRowGap:Symbol('mixed'),gridColumnGap:4,gridRowSizes:[],gridColumnSizes:[],
    paddingTop:0,paddingRight:0,paddingBottom:0,paddingLeft:0,itemSpacing:0});
  assert.ok(s.includes('outline=MIXED,INSIDE'),s);assert.ok(s.includes('grid=1,1,MIXED,4'),s);
});
test('Variablesの全モードと日本語のハッシュを取得する',async()=>{
  const src=await readFile(new URL('exporters/export_variables.js',root),'utf8');
  const figma={fileKey:'fixture',variables:{getLocalVariableCollectionsAsync:async()=>[{name:'色',variableIds:['v'],modes:[{modeId:'l',name:'Light'},{modeId:'d',name:'Dark'}]}],
    getVariableByIdAsync:async()=>({name:'Frame/Default',resolvedType:'COLOR',valuesByMode:{l:{r:1,g:1,b:1},d:{r:0,g:0,b:0}},scopes:[]})},
    getLocalTextStylesAsync:async()=>[],getLocalEffectStylesAsync:async()=>[],getLocalPaintStylesAsync:async()=>[]};
  const d=JSON.parse(await new AsyncFunction('figma',src)(figma));
  assert.equal(d.collections['色'].variables[0].values.Dark,'#000000');
  assert.equal(d.$meta.declared.variables,1);assert.ok(d.$meta.payloadDigest.value);
  figma.variables.getVariableByIdAsync=async()=>null;
  await assert.rejects(new AsyncFunction('figma',src)(figma));
});
test('本物の分割書き出しをPythonで全体照合して復元する',async()=>{
  const src=(await readFile(new URL('exporters/export_frames.js',root),'utf8'))
    .replaceAll('{{節の名前}}','Screens').replaceAll('{{ページ名}}','Comp').replaceAll('{{版面の幅}}','300');
  const leaf={id:'leaf',type:'RECTANGLE',name:'絵😀',width:20,height:20,x:0,y:0};
  const fr={id:'1:1',type:'FRAME',name:'同名画面',width:300,height:400,x:0,y:0,children:[leaf]};
  const page={name:'Comp',loadAsync:async()=>{},children:[{name:'Screens',type:'SECTION',children:[fr]}]};
  const figma={root:{children:[page]},variables:{getVariableByIdAsync:async()=>null},getStyleByIdAsync:async()=>null};
  const manifest=JSON.parse(await new AsyncFunction('figma',src.replace("const TRANSFER_MODE = 'full'","const TRANSFER_MODE = 'manifest'"))(figma));
  const chunks=JSON.parse(await new AsyncFunction('figma',src.replace("const TRANSFER_MODE = 'full'","const TRANSFER_MODE = 'rows'").replace('const ROW_INDICES = []','const ROW_INDICES = [0,1]'))(figma));
  const notread=JSON.parse(await new AsyncFunction('figma',src.replace("const TRANSFER_MODE = 'full'","const TRANSFER_MODE = 'notread'"))(figma));
  // 「読めなかったもの」は件数とハッシュだけが manifest・行の断片に載り、本体は notread で取る（#182）
  assert.equal(typeof manifest.$meta.notReadHash,'number');assert.ok(!('読めなかったもの' in chunks.$meta));
  assert.equal(notread.mode,'notread');assert.equal(notread.$meta.notReadHash,manifest.$meta.notReadHash);
  const script='import sys,json; sys.path.insert(0,"tools"); from frame_io import merge; d=json.load(sys.stdin); print(json.dumps(merge(d["manifest"],[d["chunks"],d["notread"]]),ensure_ascii=False))';
  const result=JSON.parse(execFileSync(process.env.PYTHON??(process.platform==='win32'?'python':'python3'),['-c',script],{cwd:fileURLToPath(root),input:JSON.stringify({manifest,chunks,notread}),encoding:'utf8'}));
  assert.equal(result.frames['1:1'].rows.length,2);assert.ok(result.frames['1:1'].rows[1].includes('絵😀'));
  assert.equal(result.$meta.declared.screens,1);
  assert.deepEqual(result.frames['1:1'].ids,['1:1','leaf']);
});
test('余白・寸法に結んだ変数と、意図した直値の印を書く（候補6）',async()=>{
  const {shape}=await functions();
  const base={type:'FRAME',layoutMode:'VERTICAL',paddingTop:16,paddingRight:0,paddingBottom:0,paddingLeft:0,itemSpacing:8,
    primaryAxisSizingMode:'AUTO',counterAxisSizingMode:'FIXED',primaryAxisAlignItems:'MIN',counterAxisAlignItems:'MIN'};
  const bound=await shape({...base,boundVariables:{paddingTop:{id:'v'}},
    getSharedPluginData:(ns,k)=>ns==='harness'&&k==='raw'?'itemSpacing':''});
  assert.ok(bound.includes('bind=paddingTop:Size/XL'),bound);
  assert.ok(bound.includes('raw=itemSpacing'),bound);
  const plain=await shape(base);
  assert.ok(!plain.includes('bind=')&&!plain.includes('raw='),plain);
});
test('変数の key を書く（候補6）',async()=>{
  const src=await readFile(new URL('exporters/export_variables.js',root),'utf8');
  const figma={fileKey:'fixture',variables:{getLocalVariableCollectionsAsync:async()=>[{name:'色',variableIds:['v'],modes:[{modeId:'l',name:'Light'}]}],
    getVariableByIdAsync:async()=>({name:'Frame/Default',key:'k123',resolvedType:'COLOR',valuesByMode:{l:{r:1,g:1,b:1}},scopes:['FRAME_FILL']})},
    getLocalTextStylesAsync:async()=>[],getLocalEffectStylesAsync:async()=>[],getLocalPaintStylesAsync:async()=>[]};
  const d=JSON.parse(await new AsyncFunction('figma',src)(figma));
  assert.equal(d.collections['色'].variables[0].key,'k123');
});
