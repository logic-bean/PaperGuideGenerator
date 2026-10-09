---
name: conference-guide-site
description: 把一场学术会议（如 Interspeech / ICASSP / ACL）的官网论文列表做成**单文件离线中文导读站**（一个 .html，双击即开，可搜索、可按研究方向/分会场浏览、可收藏、有七维解读与热点统计）。适用于"帮我整理某会议的论文导读/速览/navigate 页面"。覆盖抓取→结构化→LLM 抽取→可视化→校验→发布全链路，并固化了热点短语挖掘、计数口径、jsdom 校验、简化版裁剪等已踩过的坑。
agent_created: true
---

# 会议论文导读站生成

把一个会议的**论文列表页**变成一个自包含的中文导读网站。目标产物是一个 `.html`，无外部依赖（无 CDN、无字体外链、无后端），本机双击打开和放到 GitHub Pages 上行为完全一致。

## When to Use

- 用户要整理某一会议/ workshop / 论坛的全部论文，做成"导读 / 速览 / navigate 页面"
- 需要按**研究方向 + 分会场**两级浏览、关键词搜索、收藏、导出
- 需要每篇论文的**七维解读**（一句话总结 / 研究动机 / 拟解决问题 / 主要方法 / 数据集 / 实验结果 / 主要贡献）

## 一、总体管线（5 个阶段）

```
① 抓原始页   会议官网 HTML 快照  → interspeech2026.html
② 结构化     build_guide.py      → guide_data.json   （papers / themes / sessions / hotspots / dataset）
③ 富化（可选）LLM 本地抽取         → _batches/llm_enrich.json  （summary + datasets，七维另走 out_*.json）
④ 渲染       render.py           → interspeech2026_authors.html
⑤ 校验/发布   validate_guide.js / render_simple.py / gh CLI
```

**关键设计：③④ 的富化结果在 render 阶段注入，不在 build 阶段。** 所以抽完 LLM 只需要重跑 `render.py`，不必重建 `guide_data.json`（1379 篇重建要分钟级，渲染只要几秒）。

## 二、目录约定（照抄这套命名，脚本不用改）

```
<workdir>/
  <venue>2026.html                 # ① 官网原始页快照（必留，是唯一真源）
  build_guide.py                   # ② 解析 + 分类 + 热点 → guide_data.json
  guide_data.json                  # ② 产物
  llm_enrich.py                    # ③ 本地 Ollama 多线程可续跑抽取   → assets/
  render.py                        # ④ 注入 → 最终 HTML
  render_simple.py                 # ④ 变体：去掉某些模块 → 简化版 HTML
  _batches/                        # 中间产物（全部在此，可 gitignore）
    abs_text.json      摘要（index → 英文 abstract）
    isca_index.html    会议索引（DOI 推导用）
    llm_enrich.json    LLM 抽取结果（index → {summary, datasets}）
    llm_enrich.log     抽取进度日志（含 DONE total= 哨兵）
    out_*.json         七维（index → {motivation, problem, method, ...}）
    paper_meta.json    每篇 PDF 首页解析出的作者机构/邮箱
    author_enrich.json / inst_pool.json / inst_class_final.json   作者富化
  <venue>2026_authors.html         # ④ 完整版（产物）
```

## 三、各阶段要点

### ① 抓取 + 解析

先落一份原始 HTML 快照再解析，别边抓边解析（抓挂了就全丢）。

`build_guide.py` 里的解析器结构（Interspeech 的 ISCA 页面）：

- 用 `re.split(r'(?=<h4[^>]*>)', RAW)` 按 session 分块；`h4` 文本 = 分会场名
- 每块内用 `<a class="w3-text" href="X_interspeech.html">…` 抽论文条目
- 条目内的 `<br>` 是 **标题 | 作者列表** 的分隔符，先替换成 ` | ` 再 split
- `slug = href.replace('_interspeech.html','')`；`url` 拼 ISCA archive 域名

不同会议只需改这两行正则 + 域名常量。

### ② 分类与热点

- **研究方向（theme）**：先写 `THEMES = {id: (中文名, emoji)}`，再写 `MAP = {'分会场名(精确)': 'theme id'}`。**结尾必须有 `assert not unmapped`**，宁可崩掉也不要漏分类——漏一个就静默少一批论文。
- **热点短语**：直接复用 `assets/hotspots.py`（`from hotspots import hotspots`），喂该分组的标题列表，得到 `[[短语, 涉及论文数], ...]`。
  唯一需要换的是模块顶部的 `LEX_TEXT`（领域词表），换 venue 就换这一张表。

### ③-a 作者与机构抽取（PDF 首页 → 作者卡片）

`extract_authors.py` 把 `pdfs/pNNNN.pdf` 首页题头解析成 `{作者名, 上标归属, 机构, 邮箱, 国家}`，
是生成 `interspeech2026_authors.html` 作者卡片的上游核心步骤（发生在 i18n 之前）。

- **两阶段**：Phase A 视觉行重建（`page1_lines`，垂直重叠>50% **且**水平不相交才合并，行内按 x0 排序）+ 三块分类；Phase B 解析作者名+上标、机构按标记拆分、邮箱展开。
- **字体尺寸约定**：上标 `size<10.0`；作者/机构带 `[10.4,12.6]`（上限 12.6 排除 13pt 标题被当作者）；邮箱 `maxsz<10.5`。
- **七类已踩坑**（首作者上标错位 / 页眉吞作者块 / ORCID "ID" 假文本 / 裸城市名误命中人名 / 无编号单位行变作者 / 折行续行以上标开头 / 名字粘连+`and` 切断真名）—— 完整根因+修复见 **`references/author-extraction.md`**。
- **官方名单门控**：`main()` 读 `guide_data.json` 的 `p['a']` 作 `official_names`，用 `_matches_official()`（去变音符+小写 token 集合包含匹配）区分"无编号单位行"与作者行。
- **富化链**：`attribute_authors.py` → `classify_inst.py` → `second_pass.py` 归类 company/university/others，覆盖率须 100%。
- **渲染层兜底**：`render.py`/`render_simple.py` 作者名匹配加"唯一互相包含"兜底（§5），把作者数不匹配从 30 篇压到 1 篇。
- **校验**：交付前 `validate_guide.js` 必 PASS；作者名/机构/邮箱保留原文，i18n 阶段不翻译。

> 经验：先用 3~5 篇"作者多+上标复杂+有 ORCID"的论文（如 p0699/p186/p1273）做黄金样本，
> 修一版跑一版再全量，别一上来盲跑全量。

### ③ LLM 富化（工作量最大，务必后台跑）

```bash
OLLAMA_BASE=http://localhost:11434/api/chat \
  python3 llm_enrich.py --workers 8 --trunc 1600 --predict 256 --flush 25
```

- 用**本地** Ollama（qwen3:14b 这类 4B~14B 即可，M3 24G 无压力）；换 venue 时改 `--sys` 指向你自己的抽取提示词文件。
- 默认 8 workers + 每 25 条落盘 = 可续跑，中途杀掉最多丢一个 flush。
- 跑完：1379 篇 ≈ 3.5 h（串行是 15 s/篇）。
- **坑**：`urllib` 必须绕开系统代理，否则 localhost 请求返 502：
  `urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))`

### ④ 渲染

`render.py` = 一份 HTML 模板（Python 字符串）+ 注入逻辑，末尾：

```python
out = HTML.replace('__DATA__', safe).replace('__AUTHORS__', safe_auth).replace('__ASTATS__', author_stats_json)
open('<venue>2026_authors.html','w',encoding='utf-8').write(out)
```

数据注入前必须 `json.replace('</', '<\\/')`，否则标题里出现 `</` 会提前闭合 `<script>`。

### ⑤ 简化版裁剪（按需）

复制一份 `render_simple.py`，在末尾追加"输出级后处理"：按锚点整段删除（导出模态、某个 view 的函数块、事件绑定），再做**残留断言**——发现 `id="exportBtn"`、`_expOpen` 之类残留直接 `SystemExit`。删除变量定义时必须连带删掉所有引用点（`AUTHORS` / `a3` / `spKids.appendChild(a3)` 都漏过一次，表面渲染正常但脚本已中断，只有 jsdom 探针能抓出来）。

## 四、必踩的坑（都是真实代价换来的）

1. **热点数字全是 1**：后端返回的是纯字符串列表 `['speech recognition']`，前端 `countedSorted()` 对非数组项兜底 `count=1`，于是每颗 chip 都印 1。**输出必须是 `[[phrase, n]]` 配对**。
2. **前端重排会毁掉后端排序**：`countedSorted()` 若按数字降序重排，裸词 `detection (116)` 会压过 `speech recognition (53)`。改成**保序归一化**（只做格式转换，不 sort）。
3. **"研究焦点"不是词组**：焦点取词要先取**多词短语**，不足再补，最后才允许 1–2 个裸词兜底；不要一上来就取 bigram（会出 `balancing hearing` 这种碎片）。
4. **重音把词切碎**：`māori` 不去重音会被切成 `ori` 碎片 → `_deacc()` 先 NFKD 折叠。
5. **连字符术语被滑窗拆开**：`text-to-speech` 会出 `text speech` 空壳邻接 → 允许跳过 1 个功能词 + 策展别名（`text speech` → `text to speech`，**别名表必须按"长者优先"建**，否则自己映射自己）。
6. **改分类名要一次改全**：导航项 / 面包屑 / `<h2>` / 区块标题 / 导出范围标签是同一个分类的五种叫法，只改一处就会三种名字并存。用户若只要改导航，就只改导航。
7. **jsdom 探针是唯一靠得住的校验**：静态 grep 查不到运行时渲染的内容；页面里 `DATA`/`PAPERS` 是 `const`，`window.DATA` 取不到，要用 `window.eval('PAPERS.length')`。
8. **导出的 xlsx 是 0 字节 / 根本不落盘**（真实事故，同一个现象复现三次：作者分析 4592 人导出，用户保存下来是 0 字节，甚至下载目录里压根没文件）——**先分清用户是在哪儿打开的**（见坑 12），再动手改，否则会改错方向。若确认是外部浏览器：根因是 `showSaveFilePicker` 在 **macOS 上会先把文件占位成 0 字节、再异步落盘**，落盘失败或延迟就留下可见的空文件，页面还照常关弹窗。此时**把默认路径改成浏览器直接下载**：`URL.createObjectURL` + `a.download`，Chrome 原子落盘（先写 `.crdownload` 再改名），不会出现 0 字节孤儿文件，且默认就落到访达「下载」。系统「存储为」对话框降级成弹窗里的**可选勾选框**（默认不勾），只有勾选才走，且必须带：回读 `handle.getFile().size` + **同一 handle 重写覆盖**（`createWritable()` 每次都截断，能把已落盘的 0 字节文件覆盖成完整内容）+ 最多 3 轮、每轮回读前等 400 ms（落盘有延迟）；抛非 AbortError 一律回退下载。下载后用 `_toast()` 提示文件名与保存位置，失败时保留弹窗让用户改文件名重试。
9. **xlsx 模板必须有 `<dimension ref="A1:XXn"/>`**：缺了它 openpyxl 只读模式会报 "Worksheet is unsized"，WPS/在线表格一类也可能整表显示为空（数据其实是对的）。
10. **字段取值要包 try/catch**：`{k:'papers', get:a=>a.pids.map(...)}` 一旦某条数据缺字段就整个导出抛异常、一行都存不下来；统一走 `_expCell(f, item)` 兜底，且 `pids` 前加 `Array.isArray()` 判断。
11. **两层弹窗别认错**：macOS Chrome 的 `showSaveFilePicker` 弹的是**原生 NSSavePanel**（自带「标签：」「位置：」下拉与「取消 / 保存」按钮），它盖在自定义 `expMask` 之上，截图看起来像页面自己做了个二级保存框。排查前先分清哪层是原生的——原生那层参数你改不到，要改的是 `_expSave` 的分支逻辑。
12. **排"下载落不了盘"必须先问"在哪打开的"**：用户实测——**外部浏览器（Chrome / Edge）双击打开一切正常，用 WorkBuddy 自带的展示/预览窗口打开必然落不了盘**。内置预览用的是受限 WebContents + 沙箱策略，页面里的 `a.download` 与 `showSaveFilePicker` 会被**静默取消**（不报错、不告警、不回退，用户只看到"没反应 / 空文件"）。这不是页面 bug、不是磁盘满、不是权限问题。**排查顺序：先确认打开方式 → 再用外部浏览器复现；如果连 Playwright/CDP 都复现 `inProgress:0 → canceled`，很可能是被内置容器污染，别急着改本机 Chrome 配置。** 顺带：Playwright 接管下载时的 `canceled` 状态是假象（连 `about:blank` 里一个 3 MB 无关 blob 都报 canceled），不能据此判定用户环境。
13. **导出类页面必须自带"非浏览器下载"落地通道**：既然内置预览窗口救不回来，就要给用户绕开这条路的选择——① 一个 `open_external.sh`（依次探测 Chrome / Edge / Chromium / Brave，`open -a` 打开 HTML）；② 一个 `export_excel.py` **零第三方依赖**（优先 openpyxl，没装就手写最小 xlsx：`zipfile` + 手写 `[Content_Types].xml`/`xl/workbook.xml`/`xl/worksheets/sheet1.xml`，务必带 `<dimension>`），直接从生成的 HTML 里正则抠出 `const DATA` / `const AUTHORS` 落盘到 `exports/`；③ 页面内再留一条「📋 复制到剪贴板」（TSV，`navigator.clipboard.writeText`）供粘进 Excel。字段 key/label 统一从 `render.py` 里解析 `const AUTHOR_FIELDS / PAPER_FIELDS`，别手抄（手抄必然对不上列）。

## 五、校验与发布

```bash
# 校验（jsdom，零外部依赖全家桶）
NODE_PATH=/Users/haoyufeng/.workbuddy/binaries/node/workspace/node_modules \
NODE_OPTIONS=--max-old-space-size=4096 \
/Users/haoyufeng/.workbuddy/binaries/node/versions/22.12.0/bin/node \
assets/validate_guide.js <venue>2026_authors.html
# 退出码非 0 即有问题，errors 数组必须有内容
```

- jsdom 在受管 workspace：`/Users/haoyufeng/.workbuddy/binaries/node/workspace/node_modules`（需先 `npm i jsdom`）。
- 发布到 GitHub Pages：**先确认页面零外部依赖**（grep 无 `src="http` / `href="http` / `@import`），再把 HTML 存成仓库根目录 `index.html` 推上去，与本地打开完全一致。
- 发布通道的常见障碍：本执行环境的沙箱与 macOS TCC 写不进 `~/.config/gh` 凭据，已连接的 GitHub 集成令牌又常无写权限（`403 Resource not accessible by integration`）。此时让用户在本机终端跑一段授权脚本把 token 落到 `/tmp`（不进项目目录），再用 `gh` / `git` 推。详见 `references/render-layer.md`。

## 六、换一场会议要改什么（checklist）

- [ ] `build_guide.py`：`RAW` 读取路径、`h4` / `<a class=...>` 两条正则、ISCA 域名（DOI 用 `10.21437/<Venue>.2026-<n>`）
- [ ] `THEMES`（研究方向 id / 中文名 / emoji）与 `MAP`（分会场名 → theme），补上 `assert not unmapped`
- [ ] `hotspots.py` 的 `LEX_TEXT`（换领域词表）
- [ ] `llm_enrich.py` 的 `--sys` 提示词（抽取字段随导读模板变）
- [ ] `extract_authors.py`：`PDFDIR` / 字号带 `[10.4,12.6]` / `is_sup` 阈值 / `AFF_KW` / `AFF_SYM` / 邮箱括号形式（详见 `references/author-extraction.md` 第 8 节）
- [ ] 渲染层"作者名包含匹配兜底"须同步到 `render.py` 与 `render_simple.py`
- [ ] `render.py` 的视图清单、侧边栏导航、导出字段、分类展示名
- [ ] 数据契约：`guide_data.json` 里 `global_hot / themes[].hot_uni / sessions[].hot_uni / dataset.stats.hot_uni` **一律 `[[短语, 篇数]]`**，并带一份 `lex`（策展词表）供前端区分真短语与滑窗碎片

## Reference

- `references/pipeline.md` — 各阶段输入/输出/产物字段的详细契约
- `references/author-extraction.md` — PDF 首页作者/机构/邮箱抽取方法论（两阶段、七类坑、官方名单门控、渲染层兜底、换会议清单）
- `references/hotspots.md` — 热点挖掘算法与计数口径的完整说明
- `references/render-layer.md` — 渲染层、校验、简化版裁剪与发布
- `assets/hotspots.py` — 可直接 import 的热点挖掘模块（换 venue 只改 `LEX_TEXT`）
- `assets/llm_enrich.py` — 可直接跑的本地 LLM 抽取脚本
- `assets/validate_guide.js` — 可直接跑的 jsdom 校验/探针
- `assets/finalize.sh` — 等抽取跑完 → 重渲染 → 校验
