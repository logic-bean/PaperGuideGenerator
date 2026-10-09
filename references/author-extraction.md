# PDF 作者信息抽取方法论（extract_authors.py）

把会议论文 PDF **首页**的"作者 / 机构 / 邮箱"题头，解析成结构化字段，最终喂给
`render.py` 生成可检索、可按机构分类的作者卡片。本文固化了 Interspeech 2026（1379 篇）
生产跑中踩过的全部坑与最终修复——**单位/国家/邮箱提取失败率从 30 篇不匹配降到 1 篇**。

## 1. 目标与产物链

```
pdfs/pNNNN.pdf  ──extract_authors.py──▶  _batches/paper_meta.json
                                              │  {idx:{authors,affs,sym_affs,default_affs,emails}}
                                              ▼
                                  attribute_authors.py   作者聚合（{名:{papers,affs,countries}}）
                                  classify_inst.py      机构归类 company/university/others
                                  second_pass.py        手审 C 规则补类
                                              │  _batches/inst_class_final.json
                                              ▼
                                  render.py  →  interspeech2026_authors.html  （作者卡片）
```

- **上标→机构** 是一一对应的核心：作者名后的小数字（上标）指向机构块里同号的那一行。
- **邮箱** 多数只属于通讯作者；普通作者 `email: null` 是**正确**的（如 p0699 的 Pablo Gómez）。
- **国家** 从机构文本里靠关键词（universit/research/国名）推断，不单列解析通道。

## 2. 字体尺寸约定（Interspeech 模板，pymupdf `get_text('dict')`）

| 元素 | 字号 | 判定 |
|------|------|------|
| 论文标题 | ~14pt | `maxsz > 12.6` 直接跳过，防止被当作者 |
| 作者名 / 机构正文 | 12pt | 作者/机构带：`10.4 <= maxsz <= 12.6` |
| 上标（数字 / `*` / `†‡♢§¶`） | ~8pt | `is_sup(sp): sp['size'] < 10.0` |
| 邮箱行 | ~9pt | `maxsz < 10.5` 走邮箱分支 |
| ORCID 图标渲染成的假文本 "ID" | 5pt | 源头过滤 `size<7` 的 "ID" |

> **尺寸带边界**：作者带上限必须 ≤ 12.6，否则 13pt 标题（如 p277）会被当成第一个"作者"，
> 把位置匹配整体右移一位。下限 10.4 排除页眉等小字。

## 3. 两阶段抽取（parse_paper）

### Phase A — 视觉行重建 + 三块分类
`page1_lines(doc)` 先把 pymupdf 的 `blocks→lines→spans` 重建成**视觉行**，再逐行分类为
作者块 / 机构块 / 邮箱块，每块合并成一条逻辑流（保留 `(text, is_sup)` 段，便于 Phase B）。

**为什么不能信 pymupdf 的块/行顺序**：一个视觉行会被拆成多个独立块（如斜体首作者名单独成行），
纯 y 排序会把名字排到它**自己的上标之后** → 误触 marker-first（ORCID）解析，作者↔上标归属全乱
（p0699 即此坑）。

行合并规则（关键，缺一不可）：
- 两行同属一行 ⇔ **垂直重叠 > 50% 较小行高** `AND` **水平不相交**
 （`L.x0 >= best.x1-1.0 or best.x0 >= L.x1-1.0`）。
- 水平不相交约束是救 p972/422/250/60/111/1021 的：页眉 9pt 行与居中标题 14pt 行**垂直重叠**
  但水平重叠 → 不能合并，否则页眉小字成"行首上标"吞掉作者块。
- 行内 span 按 `bbox.x0` 排序（修顺序翻转 1018/513/1367）。
- 源头过滤 5pt "ID" 假文本（修 p186 `sup='†ID3,5'`）。
- 相邻同尺寸纯文本 span 间隙 `0.3<gap<8.0` 且首尾无空格 → 补空格合并（修 `JingdongChen` 粘连）。

### Phase B — 解析
- **作者两种版式**：
  - `normal`：上标**跟在**名字后 `"Name¹, Name²"`
  - `marker-first`（ORCID）：上标**在**名字前 `"ID¹, Name¹"` —— 错位会误触发，靠
    `first_text.startswith(',')` 判定。
  - 边界规则：待定上标遇新文本段先 `nm_flush()`（修名字+单位粘连 p681）；`and` 仅用
    `re.sub(r'\s+and\s+',', ')` 与行首 `re.sub(r'^(\s*)and\s+',r'\1, ')` —— **绝不**用
    `(?<=[a-zA-Z])and (?=[A-Z])` 切断真名（Saurabhch**and** Bhati 等 6 处被切过）。
- **机构按标记拆分**：数字组 `digit_groups`、符号组 `sym_groups`（`†‡♢§¶`）、无编号
  `default_affs`；`aff_flush()` 加 `re.sub(r',(?=\S)',', ')` 修 `EECS,Gwangju`。
- **邮箱展开**：`{a,b}@x.com` / `locals{@domain}` / `<a,b>@x.com` 三类括号形式 → 个体邮箱
  （`expand_emails` + `BRACE_EMAIL_RE` + `TAIL_BRACE_EMAIL_RE`）。
- **Type1 字体修复** `fix_text()`：间距重音 `´` + 字母 → 组合重音 NFC（`Gómez` 不乱码）；
  `ﬁ/ﬂ/ﬀ/ﬃ` 连字拆开。

## 4. 七类根因与修复（真实代价换来）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | 首作者上标丢失/错位（p0699） | 斜体名拆块 + y 排序使名排到上标后 | `page1_lines` 视觉行聚类（垂直重叠>50% **且**水平不相交）+ 行内 x 排序 |
| 2 | 6 篇整块作者被吞 | 页眉 9pt 与标题 14pt 垂直重叠被合并，小字成"行首上标" | 聚类加"水平不相交"约束（页眉与标题水平重叠故不并） |
| 3 | `sup='†ID3,5'`（p186） | ORCID 图标渲染成 5pt 假文本 "ID" | `page1_lines` 源头过滤 `size<7` 的 "ID" |
| 4 | 作者被当机构（p370 Berlin Chen） | `AFF_KW` 裸城市名 `berlin` 误命中人名 | 删裸城市名（`beijing/shanghai/seoul/tokyo/london/paris/berlin`），真实机构行总有更强关键词兜底 |
| 5 | 无编号单位行变作者（"Factored AI, Mountain View, CA"） | 无数字/无机构关键词的单位行被当成作者 | `parse_paper` 加 `official_names` 门控：`_matches_official()` 做去变音符+小写 token 集合的包含/被包含匹配，命中官方名单才认作作者 |
| 6 | 折行续行以上标开头被误判机构（p18/214/478） | `lead_is_digit` 把"续行首字符是上标"当机构标记 | `lead_is_digit` 加作者续行例外：非机构关键词 `AND` 命中官方名 → 仍作作者块 |
| 7 | 名字+单位粘连 / `and` 连写切断真名 | 文本层丢空格 + 激进 `and` 正则 | 渲染层"包含匹配"兜底（见 §5）+ 收激进 `and` 正则 |

**AFF_KW 守门原则**：只放强关键词（`universit|research|institut|department|corp|gmbh|ltd|`
国名、`project|society|foundation|organi[sz]ation|ventures|studio|partners|committee` 等）。
**绝不**放裸城市名——它们会误命中人名（p370 的教训）。

## 5. 渲染层兜底匹配（render.py / render_simple.py）

`paper_meta.json` 的键是作者名原文；渲染时若精确匹配不到（作者名+单位粘连 token、
如 `"Emanüel A. P. Habets International Audio Laboratories Erlangen"`，p1273），加**包含匹配**：

```python
if rec is None:
    cands = {k for k in info if min(len(k), len(key)) >= 10
             and (key in k or k in key)}
    if len(cands) == 1:
        rec = info.get(next(iter(cands))); name_m = 'positional'
```

即：两个串都 ≥10 字符且**唯一互相包含**即匹配。这把"作者数 vs 官方名单不匹配"从 30 篇压到 1 篇。

## 6. 机构分类链（company / university / others）

`attribute_authors.py` 聚合 → `classify_inst.py` 规则链初分 → `second_pass.py` 手审 C 规则表补类。
覆盖率须达 100%（Interspeech 2026：2124/2124）。碰到未分类串：
1. 先重跑 classify 链（多半是新增机构串）；
2. 仍剩的少量手工补 `inst_class_final.json`（如 `ic['Intron']='company'`、
   `ic['NXP Semiconductors, ...']='company'`、`ic['ia CODA - ...']='others'`、
   `ic['Verth, Copenhagen, Denmark']='others'`）。

## 7. 校验指标（交付前必查）

- 解析成功 `ok` / 失败：Interspeech 2026 = **1375 / 4**。4 个失败多为相对路径 `pdfs/pNNNN.pdf`
  未找到（跑批 cwd 不同），非解析错误，作者数据本身无问题。
- 作者数 vs 官方名单不匹配：旧版 30 篇 → 修复后 **1 篇**（已由渲染层兜底）。
- 作者卡片字段覆盖：单位 ~4567、国家 ~3932、邮箱 ~3226（4592 作者总量）。
- `validate_guide.js`（jsdom）必须 PASS：作者数组长度、卡片字段、`window.eval('AUTHORS.length')` 探针。
- 作者名/机构/邮箱 **保留原文**，i18n 阶段不翻译（见 html-i18n-pipeline Skill）。

## 8. 换一场会议要改什么（checklist）

- [ ] `PDFDIR` / 字号带 `[10.4,12.6]` / `is_sup` 阈值（模板不同需实测）
- [ ] `AFF_KW`：增删该会议高频机构关键词、国名
- [ ] `AFF_SYM`：该会议用的相等贡献/通讯符号集（`†‡♢§¶♡♠`）
- [ ] 邮箱括号形式（`{}/<>/()` 三种已覆盖，罕见形式加正则）
- [ ] 官方名单来源：`main()` 读 `guide_data.json` 的 `p['a']` 作 `official_names` 门控
- [ ] 渲染层"包含匹配"兜底（§5）务必同步到 `render.py` 与 `render_simple.py`

> 经验：先拿 3~5 篇"作者多 + 上标复杂 + 有 ORCID"的论文（如 p0699/p186/p1273）做黄金样本，
> 修一版跑一版，再全量；不要一上来就全量盲跑。
