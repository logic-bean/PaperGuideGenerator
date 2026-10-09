# 会议论文导读站生成 Skill · conference-guide-site

English: A WorkBuddy skill that turns a conference's paper list into a single-file, offline, Chinese-language guide site.

把一场学术会议（Interspeech / ICASSP / ACL …）的官网论文列表，做成一个**自包含的单文件中文导读网站**。本仓库即 WorkBuddy 技能 `conference-guide-site` 的完整源码与方法论文档。

## 它解决什么问题

会议官网的论文列表难检索、难按方向浏览、没有中文解读。本技能产出**一个 `.html`**（无 CDN、无字体外链、无后端），双击即开，也可直接丢到 GitHub Pages。具备：

- 按**研究方向 + 分会场**两级浏览、关键词搜索、收藏
- 每篇论文的**七维解读**（一句话总结 / 动机 / 问题 / 方法 / 数据集 / 实验 / 贡献）
- 热点短语挖掘与统计
- **作者卡片**：从 PDF 首页解析作者 / 机构 / 邮箱 / 国家，可检索、可按机构类型（企业 / 高校 / 其他）分类
- Excel 导出（含零依赖兜底通道）
- 7 语种（zh/en/ja/fr/de/ko/es）i18n（需配合 `html-i18n-pipeline` 技能）

## 安装到 WorkBuddy

```bash
git clone https://github.com/logic-bean/PaperGuideGenerator.git
mkdir -p ~/.workbuddy/skills/conference-guide-site
cp -r PaperGuideGenerator/. ~/.workbuddy/skills/conference-guide-site/
```

重启 WorkBuddy 后即可在对话中触发（触发词见下节）。

---

## 在 WorkBuddy 中如何使用本技能（端到端）

本技能不是"一条命令跑完"，而是**一段由你与 AI 协作的多阶段流水线**。下面按"真实使用顺序"把每一阶段讲清楚：怎么触发、要准备什么、改哪里、产物落在哪、怎么验证。

### 1. 触发方式

在 WorkBuddy 对话里用自然语言描述需求即可，常用触发词：

- 「帮我整理 Interspeech 2026 的论文导读 / 速览 / navigate 页面」
- 「把 ACL 2026 官网论文列表做成可搜索的中文导读站」
- 「做一个能按研究方向浏览、能收藏、有七维解读的会议论文站」

AI 加载 `conference-guide-site` 技能后，会按下方 5 阶段推进。**建议先说清**：会议名/年份、官网论文列表 URL、是否需要七维解读（要本地跑 LLM）、是否需要作者卡片（要放 PDF）、要不要多语种。

### 2. 端到端流程总览

```
① 抓取官网 HTML 快照      → <venue>2026.html   （唯一真源，先落盘再解析）
② build_guide.py 结构化   → guide_data.json     （papers / themes / sessions / hotspots / dataset）
③-a 作者抽取（PDF 首页）  → _batches/paper_meta.json + 机构分类
③ LLM 富化（本地 Ollama） → _batches/out_*.json + llm_enrich.json
④ render.py 渲染注入      → <venue>2026_authors.html
⑤ validate_guide.js 校验 / 推 GitHub Pages
```

**关键设计**：③④ 的富化结果在 **render 阶段注入**，不在 build 阶段。抽完一次 LLM / 作者数据只需重跑 `render.py`（几秒），不必重建 `guide_data.json`（千篇级重建要分钟级）。

### 3. 阶段一：抓取官网论文列表快照

- 让 AI 用 WebFetch / 浏览器把会议官网的论文列表页**整页存成 `<venue>2026.html`**。
- **务必先落快照再解析**（别边抓边解析，抓挂了就全丢）。这份 HTML 是后续唯一真源，必须保留。
- 不同会议的列表页结构不同，但都属于"一次性解析"，见下阶段。

### 4. 阶段二：结构化（build_guide.py → guide_data.json）

AI 会基于 `build_guide.py` 写针对本会议的解析器。需要你/AI 确认或改动的点：

- **两条正则 + 域名常量**：按 `<h4>` 分会场分块、在块内按 `<a class=...>` 抽论文条目；`slug` / `url` / DOI 域名随会议变。
- **研究方向（theme）**：先写 `THEMES = {id: (中文名, emoji)}`，再写 `MAP = {'分会场名(精确)': 'theme id'}`。
- **必加哨兵**：`MAP` 结尾要有 `assert not unmapped` —— 宁可崩掉也不要漏分类（漏一个就静默少一批论文）。
- **热点短语**：直接复用 `assets/hotspots.py`（`from hotspots import hotspots`），唯一要换的是模块顶部的 `LEX_TEXT`（领域词表）。

产物：`guide_data.json`（含 papers / themes / sessions / hotspots / dataset）。

### 5. 阶段三-a：作者与机构抽取（可选，需要论文 PDF）

如果你要"作者卡片"（按机构检索、按企业/高校分类），把论文 PDF 放进 `pdfs/`：

```bash
python3 extract_authors.py        # → _batches/paper_meta.json
python3 attribute_authors.py
python3 classify_inst.py
python3 second_pass.py            # → _batches/inst_class_final.json（覆盖须 100%）
```

- 这是生成 `<venue>2026_authors.html` 作者卡片的**上游核心步骤**（发生在 i18n 之前）。
- 完整方法论与七类真实踩坑见 **`references/author-extraction.md`**（首作者上标错位 / 页眉吞作者块 / ORCID "ID" 假文本 / 裸城市名误命中人名 / 无编号单位行变作者 / 折行续行以上标开头 / 名字粘连 + `and` 切断真名）。
- **经验**：先用 3~5 篇"作者多 + 上标复杂 + 有 ORCID"的论文做黄金样本，修一版跑一版再全量，别盲跑全量。

### 6. 阶段三：LLM 富化（可选，需要本地 Ollama）

如果你要七维解读 / 一句话总结 / 数据集，让 AI 用本地 Ollama 抽取（qwen3:14b 这类 4B~14B 即可，M3 24G 无压力）：

```bash
OLLAMA_BASE=http://localhost:11434/api/chat \
  python3 llm_enrich.py --workers 8 --trunc 1600 --predict 256 --flush 25
```

- 换会议时改 `--sys` 指向你自己的抽取提示词文件。
- 默认 8 workers + 每 25 条落盘 = **可续跑**，中途杀掉最多丢一个 flush。
- 1379 篇 ≈ 3.5 h（串行 15 s/篇）。
- **坑**：脚本内 `urllib` 必须绕开系统代理，否则 localhost 请求返 502。

### 7. 阶段四：渲染（render.py → HTML）

```bash
python3 render.py          # → <venue>2026_authors.html（完整版，含作者卡片）
python3 render_simple.py   # → 简化版 HTML（去掉作者视图等）
```

- `render.py` = HTML 模板（Python 字符串）+ 注入逻辑，把 `guide_data.json` 与富化结果拼进 `__DATA__`/`__AUTHORS__`。
- 数据注入前会 `json.replace('</', '<\\/')`，防止标题里的 `</` 提前闭合 `<script>`。
- 改完 LLM / 作者数据只需重跑这一步，秒级。

### 8. 阶段五：校验与发布

```bash
# 校验（jsdom 探针，零外部依赖全家桶）
NODE_PATH=/path/to/jsdom/node_modules \
NODE_OPTIONS=--max-old-space-size=4096 \
node assets/validate_guide.js <venue>2026_authors.html
# 退出码非 0 即有问题，errors 数组必须有内容
```

- jsdom 校验是**唯一靠得住的运行时校验**（静态 grep 抓不到运行时渲染内容，`DATA`/`PAPERS` 是 `const`，要用 `window.eval('PAPERS.length')`）。
- 发布到 GitHub Pages：**先确认页面零外部依赖**（grep 无 `src="http` / `href="http` / `@import`），再把 HTML 存成仓库根目录 `index.html` 推上去，与本地打开完全一致。
- 本机若缺少 `gh` 或 token，可用 `~/.config/gh/hosts.yml` 缓存的 OAuth token 直连 GitHub REST API 推送（注意 `api.github.com` 走系统代理会 502，需 `env -u http_proxy … NO_PROXY='*'` 绕开）。

### 9. 典型对话示例

> **你**：帮我做 Interspeech 2026 的论文导读站，要七维解读和作者卡片，先抓官网列表。
> **AI**：好的，我先拉取官网论文列表存为 `interspeech2026.html`（阶段①）。完成后我会写 `build_guide.py` 结构化出 `guide_data.json`（阶段②）。作者卡片需要论文 PDF，请提供 `pdfs/` 目录；七维解读我会用本地 Ollama 跑（阶段③）。你希望先跑结构化确认分类，还是先把 PDF 和 Ollama 准备好？
>
> **你**：先结构化，确认分会场分类对不对。
> **AI**：（写 `THEMES`/`MAP` + `assert not unmapped`，跑 `build_guide.py`）已生成 `guide_data.json`，共 N 篇、M 个分会场，研究方向映射如下……请核对有没有漏分/错分的会场。
>
> **你**：分类没问题，PDF 放好了，Ollama 也开着，跑吧。
> **AI**：（阶段③-a 作者抽取 + 阶段③ LLM 富化后台跑）→ 阶段④ `render.py` → 阶段⑤ `validate_guide.js` 通过后，交付 `<venue>2026_authors.html`，并给出 GitHub Pages 上线选项。

---

## 目录约定

照抄 `SKILL.md` 第二节的命名，脚本即可零改动运行：

```
<workdir>/
  <venue>2026.html      # ① 官网原始页快照（必留，是唯一真源）
  build_guide.py        # ② 解析 + 分类 + 热点 → guide_data.json
  guide_data.json       # ② 产物
  llm_enrich.py         # ③ 本地 Ollama 可续跑抽取
  render.py             # ④ 注入 → 最终 HTML（完整版）
  render_simple.py      # ④ 变体：简化版 HTML
  _batches/             # 中间产物（全部在此）
  <venue>2026_authors.html  # ④ 产物
```

## 快速上手（命令速查）

```bash
# ① 抓官网 HTML 存为 <venue>2026.html（先落快照再解析）
# ② 改 build_guide.py 两条正则 + 域名；写 THEMES / MAP（结尾 assert not unmapped）
python3 build_guide.py                       # → guide_data.json

# ③-a 作者抽取（可选，PDF 放 pdfs/）
python3 extract_authors.py                   # → _batches/paper_meta.json
python3 attribute_authors.py; python3 classify_inst.py; python3 second_pass.py

# ③ LLM 富化（可选，本地 Ollama）
OLLAMA_BASE=http://localhost:11434/api/chat python3 llm_enrich.py --workers 8 --trunc 1600 --predict 256 --flush 25

# ④ 渲染
python3 render.py                            # → 完整版 HTML
python3 render_simple.py                     # → 简化版

# ⑤ 校验
node assets/validate_guide.js <venue>2026_authors.html
```

## 作者信息抽取（本技能重点沉淀）

PDF 首页题头的「作者名 ↔ 上标 ↔ 机构」是一一对应的。完整方法论见 **`references/author-extraction.md`**，涵盖：

- 两阶段抽取（Phase A 视觉行重建 + 三块分类；Phase B 解析）
- 字体尺寸约定与上标判定（`is_sup(sp): sp['size'] < 10.0`）
- **七类真实踩坑与修复**（首作者上标错位 / 页眉吞作者块 / ORCID "ID" 假文本 / 裸城市名误命中人名 / 无编号单位行变作者 / 折行续行以上标开头 / 名字粘连 + `and` 切断真名）
- 官方名单门控 `_matches_official`、渲染层「包含匹配」兜底、机构分类链、校验指标、换会议 checklist

> 经验：先用 3~5 篇「作者多 + 上标复杂 + 有 ORCID」的论文做黄金样本，修一版跑一版再全量。

## 必踩的坑（速览）

13 条真实代价换来的教训，详见 `SKILL.md` 第四节与 `references/render-layer.md`：

- 热点数字全是 1（后端返回了裸字符串列表，前端兜底成 1）→ 必须返回 `[[短语, 篇数]]` 配对
- 前端重排会毁掉后端精心排好的顺序 → `countedSorted()` 只做格式归一化，不 sort
- 重音把词切碎（`māori` → `ori`）→ 先 NFKD 去重音
- **导出的 xlsx 是 0 字节 / 根本不落盘** → 先问「在哪儿打开的」：WorkBuddy 内置预览窗口会静默取消下载，外部 Chrome/Edge 正常；改用 `URL.createObjectURL` + `a.download` 原子落盘
- **jsdom 探针是唯一靠得住的校验**：页面数据是 `const`，`window.DATA` 取不到，要用 `window.eval('PAPERS.length')`
- **改分类名要一次改全**：导航项 / 面包屑 / `<h2>` / 区块标题 / 导出范围标签是同一分类的五种叫法

## 仓库结构

```
SKILL.md                      技能主文档
references/
  pipeline.md                 各阶段数据契约
  author-extraction.md        PDF 作者抽取方法论（重点）
  hotspots.md                 热点挖掘算法与口径
  render-layer.md             渲染 / 校验 / 裁剪 / 发布
assets/
  hotspots.py                 可直接 import 的热点挖掘模块（换 venue 只改 LEX_TEXT）
  llm_enrich.py               本地 Ollama 可续跑抽取脚本
  export_excel.py             零依赖命令行导出 xlsx
  validate_guide.js           jsdom 校验 / 探针
  finalize.sh                 等抽取完 → 重渲染 → 校验
  open_external.sh            用外部浏览器打开（绕过内置预览窗口禁下载）
```

> 注：`assets/finalize.sh`、`assets/validate_guide.js` 里写死了作者本机的受管二进制绝对路径（node / python3），换机器时按需替换为 `which node` / `which python3` 的结果即可。

## 换一场会议要改什么

见 `SKILL.md` 第六节 checklist：`build_guide.py` 正则 / 域名、`THEMES` / `MAP`、`hotspots.py` 的 `LEX_TEXT`、`llm_enrich.py` 提示词、`extract_authors.py` 字号带 / `AFF_KW` / `AFF_SYM`、渲染层兜底。

## License

MIT
