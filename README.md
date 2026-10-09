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
git clone https://github.com/logic-bean/PaperGuideGenrator.git
mkdir -p ~/.workbuddy/skills/conference-guide-site
cp -r PaperGuideGenrator/. ~/.workbuddy/skills/conference-guide-site/
```

重启 WorkBuddy 后即可在对话中触发（触发词：「帮我整理某会议的论文导读 / 速览 / navigate 页面」）。

## 管线总览（5 阶段）

```
① 抓原始页   会议官网 HTML 快照     → <venue>2026.html
② 结构化     build_guide.py         → guide_data.json
③ 富化       LLM 本地抽取 + PDF 作者抽取
④ 渲染       render.py              → <venue>2026_authors.html
⑤ 校验/发布   validate_guide.js / 推 GitHub Pages
```

关键设计：富化结果在**渲染阶段注入**，不在 build 阶段。改完 LLM / 作者数据只需重跑 `render.py`（秒级），不必重建 `guide_data.json`（千篇级重建要分钟级）。

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

## 快速上手

1. 抓官网 HTML 存为 `<venue>2026.html`（**先落快照再解析**，别边抓边解析）。
2. 改 `build_guide.py` 的两条正则 + 域名常量；写 `THEMES` / `MAP`（结尾带 `assert not unmapped`）。
3. `python3 build_guide.py` → `guide_data.json`。
4. （可选）LLM 富化：
   ```bash
   OLLAMA_BASE=http://localhost:11434/api/chat \
     python3 llm_enrich.py --workers 8 --trunc 1600 --predict 256 --flush 25
   ```
5. （可选）作者抽取：把论文 PDF 放到 `pdfs/`，`python3 extract_authors.py` → `_batches/paper_meta.json`，再跑 `attribute_authors.py` / `classify_inst.py` / `second_pass.py`。
6. `python3 render.py` → 完整版 HTML；`render_simple.py` 出简化版。
7. 校验：`node assets/validate_guide.js <venue>2026_authors.html`（需受管 jsdom）。
8. 发布：确认零外部依赖后，存成 `index.html` 推到 GitHub Pages。

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
