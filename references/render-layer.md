# 渲染层 / 校验 / 裁剪 / 发布

## 渲染脚本结构

`render.py` = 一个大 HTML 模板（Python 字符串，含内联 CSS + JS）+ 数据注入。

```
模板占位：__DATA__ / __AUTHORS__ / __ASTATS__
末尾：HTML.replace('__DATA__', safe).replace('__AUTHORS__', safe_auth).replace('__ASTATS__', ...)
```

- 注入 JSON 前做 `s.replace('</', '<\\/')`，防止标题里的 `</` 提前闭合 `<script>`。
- 页面数据在前端是 `const DATA = __DATA__;`（不是 `let`/`window.x`），探针要用 `window.eval('DATA.themes.length')` 取值。
- 视图切换是 `showView(id)`：单页 SPA，切换时把 `#content` 的 innerHTML 换掉，所以**静态 grep HTML 查不到论文卡内容**，只能靠 jsdom 渲染后再查。

## jsdom 校验（`assets/validate_guide.js`）

```bash
NODE_PATH=/Users/haoyufeng/.workbuddy/binaries/node/workspace/node_modules \
NODE_OPTIONS=--max-old-space-size=4096 \
/Users/haoyufeng/.workbuddy/binaries/node/versions/22.12.0/bin/node \
validate_guide.js <venue>_authors.html
```

要覆盖的四类检查：

1. **零运行错误**：`VirtualConsole` 的 `jsdomError` / `error` 进 `errors[]`，非空则 exit 1。
2. **所有视图可渲染**：遍历 `data-view` 调 `showView`，捕获抛错；顺带记录渲染字数，为 0 就是白屏。
3. **热点计数是真的**：chip 上的数字若全部 ≤1 → 报错（典型的数据契约退化）。
4. **焦点是词组**：遍历研究方向，检查 `研究焦点` 行的每一项词数 ≥2。
5. **导出真的有内容**：作者/论文两个作用域各跑一遍 `_xlsxBuild(_expCollectRows(...))`，断言字节数、`dimension`、`row`/`c` 数量；再静态检查 `_expSave` 含落盘回读与 blob 回退。

再加一条全站统计（`PAPERS.forEach` 数七维非空数）作为富化覆盖率。

探针踩过的坑：`showView('overview')` 不渲染论文卡，要查研究方向页 `theme-<id>`；`window.DATA` / `window.PAPERS` 取不到（`const` 不挂 window）。

## Excel 导出（纯 JS 手写 xlsx，零依赖）

`_xlsxBuild(rows)` 手写 zip（store 模式，只算 CRC-32）+ OOXML；`_expSave` 只负责落盘。契约：

- 作用域：当前视图决定导出什么——`overview` / `theme-*` / `sess-*` / `favorites` / `search` / `special-authors`（作者）/ `dataset-usage` 等；`_currentScope()` 返回 `{type:'author'|'paper', label, items}`。
- 字段：`PAPER_FIELDS`（12 项）/ `AUTHOR_FIELDS`（7 项），弹窗里全选，逐项取值走 `_expCell()` 兜底。
- **落盘两段式（0 字节文件的根因在 `showSaveFilePicker`）**：
  1. 若 `bytes.length===0` → 直接 `alert` 返回，别存空文件；
  2. **默认路径 = 浏览器直接下载**：`new Blob([bytes])` + `URL.createObjectURL` + `a.download`（`revokeObjectURL` 延后到 8 s，过早释放同样会产 0 字节）。Chrome 是原子落盘（先写 `.crdownload` 再改名），不可能留下 0 字节孤儿文件，而且默认就落到访达「下载」——恰好是用户想要的位置。成功后 `_toast('✅ 已开始下载：<文件名>（macOS 默认保存到访达「下载」）')`。
  3. **系统「存储为」对话框只作备选**：弹窗里加 `#expPickerOpt` 复选框（**默认不勾**）。勾选时才调 `showSaveFilePicker`，且必须带回读 + **同一 handle 重写覆盖**：`for(let i=0;i<3 && size<bytes.length;i++)` 内 `createWritable() → write → close`（每次 `createWritable()` 都会截断文件，正好把已落盘的 0 字节覆盖成完整内容），每轮回读前 `await sleep(400)`（macOS 落盘有延迟，立刻读会拿到 0）；抛非 `AbortError` 一律回退到直接下载。
  4. 失败时 `_expSave` 返回 `'fail'`，`_expDo` 的 `finally` **不要**关闭弹窗，让用户改文件名重试；`'cancel'` 则给 toast 提示。
- **回归检查**：真实 Chrome（`channel:'chrome'`，Playwright 缓存版本常与已装版本不匹配）跑 `check_export.js` 三种场景——默认直接下载（`page.on('download')` 断言字节数）、勾选 picker 且首次写 0 字节（断言 `tries>=2 && lastLen≈期望`）、picker 抛错（断言回退下载）。落盘文件再用 openpyxl 只读模式解析，确认 `max_row/max_col` 与 `<dimension>` 一致。
- _xlsx 模板必须带 `<dimension ref="A1:<列字母><行数>"/>`。

`assets/validate_guide.js` 的第 5/6 项检查就是防这两类问题的：分别跑作者作用域与全库作用域，断言字节数、`dimension`、`<row` 数；再静态扫 `_expSave` 里有没有回读校验和 blob 回退。

## 落地通道：内置预览窗口救不回来，必须另开三条路

**前提事实**：WorkBuddy 的内置展示/预览窗口用受限 WebContents + 沙箱策略，页面里的 `a.download` 与 `showSaveFilePicker` **会被静默取消**——不报错、不告警、不回退，用户只看到"没反应"或"0 字节空文件"。同一份 HTML 用外部 Chrome / Edge 双击打开则完全正常。所以别把内置窗口里的失败当成代码 bug 去死磕，要给用户绕开的通道：

1. **`assets/open_external.sh`** —— 依次探测 `/Applications/Google Chrome.app`、`Microsoft Edge.app`、`Chromium.app`、`Brave Browser.app`，命中就 `open -a "$B" "$HTML"`，全都没有则退回 `open "$HTML"`。用法 `sh open_external.sh simple` 开简化版。
2. **`assets/export_excel.py`** —— 命令行直接落盘到 `exports/`，**零第三方依赖**（优先 openpyxl，没装就 `zipfile` 手写最小 OOXML：`[Content_Types].xml` / `xl/workbook.xml` / `xl/worksheets/sheet1.xml`，务必带 `<dimension>`）。直接从生成的 HTML 里正则抠 `const DATA = {...};` / `const AUTHORS = [...];`，保证与页面所见一致。换会议只改 `GUIDE_HTML` / `GUIDE_RSRC` / `GUIDE_OUTDIR` 三个环境变量即可，不用改代码。
   - **字段 key/label 必须从 `render.py` 里解析** `const AUTHOR_FIELDS` / `const PAPER_FIELDS` 的 `k:'x', label:'y'`——手抄 key 必然列错位（踩过：姓名列全空）。
   - 子命令：`authors` / `author <姓名>` / `papers` / `papers <主题id|作者名|搜索词>`。
3. **页面内「📋 复制到剪贴板」**（`#expCopy`）——导出行拼成 TSV，`navigator.clipboard.writeText`，用户粘进 Excel / Numbers 即可。这是唯一在内置预览窗口里可能还活着的一条回答路径。

**排障顺序**（少走弯路）：先问"你是双击外部浏览器打开的，还是从 WorkBuddy 内置预览窗打开的" → 再决定修代码还是换通道。**别信 Playwright/CDP 的 `canceled` 状态**——接管下载时连 `about:blank` 里一个 3 MB 无关 blob 都报 canceled，那是假象。

## 简化版裁剪（`render_simple.py`）

`cp render.py render_simple.py`，在**末尾**追加后处理，**绝不改原版**。两种删除手段叠加：

- **模板级**：删掉数据注入行（`const AUTHORS = __AUTHORS__;`）、删浮动按钮 `<button class="fab" id="exportBtn">`、正则整段删导航项（`const a3 = el(...)` … `spKids.appendChild(a3);`）。
- **输出级**：对生成的 HTML 按锚点切块 —— `<div class="modal-mask" id="expMask">` → `</script>`；`// ---------- authors ----------` → `// ---------- nav ----------`（含 `listField/authorCard/authorStats/viewSpecialAuthors` 与全部 export 函数）；把 export 事件绑定替换成 `showView('overview');`。
- **兜底**：`special-*` 视图分支重定向到 `viewOverview()`，防止深链白屏。
- **残留断言**：末尾扫 `exportBtn` / `expMask` / `a3.dataset.view` / `_expOpen` / `_xlsxBuild` / `PAPER_FIELDS` / `AUTHOR_FIELDS`，有一个就 `SystemExit`。

**删变量必须连带删引用**：漏过 `AUTHORS.length`（`AUTHORS is not defined`）和 `spKids.appendChild(a3)`（`a3 is not defined`）两次，页面看着正常但其实脚本已中断——只有 jsdom 报错能发现。

## 发布到 GitHub Pages

页面必须**零外部依赖**才能"和本地一样"：

```bash
grep -o 'src="http[^"]*"\|href="http[^"]*"\|@import[^;]*' <venue>_simple.html | sort -u
# 应为空
```

流程：

1. 本地准备仓库：`/tmp/pub_gh`，`cp <venue>_simple.html index.html`，`git init -b main` + 一条 commit。
2. 建公开仓库（`gh repo create <repo> --public` 或官方 API）。
3. `git push`；启用 Pages（GitHub Actions 或 Options→Pages→Deploy from branch `main`）。
4. 轮询到 `https://<user>.github.io/<repo>/` 可访问。

常见障碍与对策：

| 障碍 | 表现 | 对策 |
|---|---|---|
| 环境的沙箱/TCC 写不进 `~/.config/gh` | 浏览器已 `✓ Authentication complete.`，但 `gh auth token` 取不到 | 让用户在本机终端跑授权脚本，token 落到 `/tmp/gh_token`（不进项目目录），再用 `gh` + `GH_TOKEN` 环境推 |
| 已连接的 GitHub 集成令牌无写权限 | `403 Resource not accessible by integration` | 同上，走用户本机凭据 |
| 沙箱里没装 gh / 装不进 `/usr/local/bin` | `command not found` / 写被拒 | 装到 `~/bin/gh`；GitHub release 下载若被限速，换 release asset 或镜像 |
