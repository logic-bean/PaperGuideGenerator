// Headless validation of a generated single-file guide.
// Catches the failure mode that a browser would show as "works" while the
// script has in fact died half-way (e.g. a deleted variable still referenced):
// every error goes to the VirtualConsole report, and the exit code is non-zero.
//
// Run with the managed node + managed jsdom:
//   NODE_PATH=/Users/haoyufeng/.workbuddy/binaries/node/workspace/node_modules \
//   NODE_OPTIONS=--max-old-space-size=4096 \
//   /Users/haoyufeng/.workbuddy/binaries/node/versions/22.12.0/bin/node \
//   validate_guide.js [path/to/guide.html]
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const file = process.argv[2] || 'interspeech2026_authors.html';
const html = fs.readFileSync(file, 'utf-8');
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + (e.detail || e.message)));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  virtualConsole: vc,
  beforeParse(window) {
    window.scrollTo = () => {};
    window.Element.prototype.scrollIntoView = () => {};
  }
});
const { window } = dom;
const doc = window.document;

// The page's own data/helpers are top-level `const`, not window properties.
const ev = expr => window.eval(expr);

setTimeout(() => {
  const out = { file, sizeKB: (html.length / 1024).toFixed(0) };
  const nav = Array.from(doc.querySelectorAll('#nav .navitem')).map(n => n.textContent.trim());
  out.nav = nav.slice(0, 24);

  // 1) every declared view must render something and must not throw
  const views = ev('(function(){ var v=[]; document.querySelectorAll("[data-view]").forEach(function(e){v.push(e.dataset.view);}); return v; })()');
  out.views = {};
  views.forEach(v => {
    try {
      window.showView(v);
      const c = doc.querySelector('#content');
      out.views[v] = { len: c ? c.textContent.length : 0, nodes: c ? c.querySelectorAll('*').length : 0 };
    } catch (e) { errors.push(`showView(${v}) threw: ${e.message}`); }
  });

  // 2) hotspot chips must carry real counts, not the legacy count = 1
  try {
    window.showView('overview');
    const chips = Array.from(doc.querySelectorAll('#content .chip'));
    const nums = chips.map(c => {
      const m = c.textContent.match(/(\d+)\s*$/);
      return m ? Number(m[1]) : null;
    }).filter(x => x !== null);
    out.chips = { n: chips.length, min: Math.min(...nums), max: Math.max(...nums) };
    if (nums.length && Math.max(...nums) <= 1) {
      errors.push('hotspot chips are all 1 — the backend probably still emits bare strings');
    }
  } catch (e) { errors.push('hotspot check threw: ' + e.message); }

  // 3) "研究焦点" must be complete phrases, not bare tokens
  try {
    let bare = 0, empty = 0, checked = 0;
    (ev('DATA.themes') || []).forEach(t => {
      window.showView('theme-' + t.id);
      const f = (doc.querySelector('.focusline') || {}).textContent || '';
      const items = (f.split('：')[1] || '');
      if (!items.trim()) empty++;
      items.split('、').forEach(x => {
        if (!x.trim()) return;
        checked++;
        if (x.trim().split(' ').length < 2) bare++;
      });
    });
    out.focus = { checked, bare, empty };
    if (bare) errors.push(`focus line contains ${bare} bare-word items out of ${checked}`);
  } catch (e) { errors.push('focus check threw: ' + e.message); }

  // 4) enrichment coverage across all papers
  try {
    out.enrich = ev(`(function(){
      const keys=['summary','motivation','problem','method','experiments','contribution'];
      const res={n:PAPERS.length}; keys.forEach(k=>res[k]=0);
      let ds=0; PAPERS.forEach(p=>{ keys.forEach(k=>{ const v = k==='summary'? p.summary : (p.six||{})[k]; if(v) res[k]++; });
        if(Array.isArray(p.datasets)&&p.datasets.length) ds++; }); res._ds=ds; return res; })()`);
  } catch (e) { errors.push('enrich check threw: ' + e.message); }

  // 5) Excel 导出必须真的产出内容（0 字节 / 空表是这个管线的典型静默故障）
  try {
    out.export = ev(`(function(){
      const res = {};
      [['author','special-authors'],['paper','overview']].forEach(function(pair){
        CURRENT_VIEW = pair[1];
        const scope = _currentScope();
        const fields = scope.type==='author' ? AUTHOR_FIELDS : PAPER_FIELDS;
        const bytes = _xlsxBuild(_expCollectRows(scope, fields));
        const s = new TextDecoder('latin1').decode(bytes);
        const m = s.match(/dimension ref="([^"]+)"/);
        res[pair[0]] = {
          scope: scope.label, items: scope.items.length, bytes: bytes.length,
          dim: m ? m[1] : null, rows: (s.match(/<row /g) || []).length, cols: (s.match(/<c r=/g) || []).length
        };
      });
      CURRENT_VIEW = 'overview';
      return res;
    })()`);
    ['author', 'paper'].forEach(k => {
      const r = out.export[k];
      if (!r) { errors.push(`导出检查失败：${k} 作用域无结果`); return; }
      if (!r.bytes || r.bytes < 5000) errors.push(`导出 ${k} 只产出 ${r.bytes} 字节，疑似空文件`);
      if (!r.dim) errors.push(`导出 ${k} 的 sheet 缺少 <dimension>，部分表格软件会显示为空表`);
      if (r.rows < 3) errors.push(`导出 ${k} 只有 ${r.rows} 行，数据没进去`);
      if (!r.cols) errors.push(`导出 ${k} 没有任何单元格`);
    });
  } catch (e) { errors.push('export check threw: ' + e.message); }

  // 6) 保存链路：默认必须直接下载（原子落盘，不会留 0 字节文件）；系统对话框只能可选 + 回读重写覆盖
  if (!/_expSave[\s\S]{0,2600}?createObjectURL/.test(html)) {
    errors.push('导出保存缺少直接下载分支（0 字节孤儿文件的根因就是只走 showSaveFilePicker）');
  }
  if (!/_expSave[\s\S]{0,2600}?usePicker[\s\S]{0,400}?checked/.test(html)) {
    errors.push('系统「存储为」对话框必须可被关闭（默认走直接下载），否则 macOS 上仍会落 0 字节文件');
  }
  if (!/_expSave[\s\S]{0,3200}?size<bytes\.length[\s\S]{0,600}?createWritable/.test(html)) {
    errors.push('picker 分支落 0 字节后缺少「同一 handle 重写覆盖 + 回读校验」的重试循环');
  }

  console.log(JSON.stringify({ errors, out }, null, 2));
  process.exit(errors.length ? 1 : 0);
}, 3000);
