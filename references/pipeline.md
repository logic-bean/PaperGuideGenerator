# 管线数据契约（逐阶段）

## ① 原始页 → `guide_data.json`

`build_guide.py` 读 `<venue>2026.html`（官网快照），产出：

```jsonc
{
  "meta":   { "total": 1379, "n_sessions": 188, "n_themes": 18,
              "venue": "Sydney, Australia · 27 Sep – 1 Oct 2026",
              "doi": "10.21437/Interspeech.2026", "n_dataset": 82 },
  "themes": [ { "id": "asr", "zh": "语音识别 (ASR)", "emoji": "🎙️",
                "count": 187, "n_sessions": 14, "pids": [0, 3, 11, ...],
                "hot_uni": [["speech recognition", 53], ...],
                "hot_bi":  [["keyword spotting", 12], ...] } ],
  "sessions":[ { "name": "ASR Under Real-World Constraints...", "idx": 0,
                "count": 12, "pids": [...], "hot_uni": [...], "hot_bi": [...] } ],
  "papers": [ { "t": "标题", "a": "作者串", "s": "分会场名", "u": "全文链接",
                "th": "theme id", "d": true/false, "six": {...} } ],
  "dataset": { "pids": [...], "stats": { "hot_uni": [["data augmentation", 12], ...] } },
  "global_hot": { "uni": [...], "bi": [...] },
  "lex": ["acoustic model", "asr", ...]     // 策展词表，前端用来区分真短语
}
```

要点：

- `papers[].t/a/s/u/th/d` 是缩写字段名（`title/authors/session/url/theme/is_datacur`），`render.py` 按此读。
- `six` 七维：**在 `build_guide.py` 里从 `_batches/out_*.json` 合并**（`_load_six()` glob 所有 `out_*.json`，逐字段「先到先得」），不属于 LLM 抽取产物。
- `guide_data.json` 不写 `abs` 字段（页面不需要），但**必须能从 `_batches/abs_text.json` 回填**，否则 LLM 抽取全程 `KeyError` 假失败。快照文件留一份 `guide_data.pre_merge.bak` 很有用。

## ② 摘要与 PDF 富化

| 产物 | 来源脚本 | 内容 |
|---|---|---|
| `_batches/abs_text.json` | `fetch_abstracts.py`（并发抓 ISCA / 出版社） | `{"0": "...abstract..."}` |
| `_batches/paper_meta.json` | `extract_authors.py`（解析 `pdfs/` 首页） | 每篇作者的机构 / 邮箱 / 国家 |
| `_batches/author_enrich.json` | `attribute_authors.py` | `{作者名: {papers, affs, emails, countries}}` |
| `_batches/inst_pool.json` → `inst_class_rules.json` → `inst_class_final.json` | `classify_inst.py` → `second_pass.py` | 机构归类 company / university / others |
| `_batches/isca_index.html` | 手工/脚本存索引页 | DOI 推导用 |

**DOI 推导**：`10.21437/Interspeech.2026-<n>`，`n` = 该 slug 在索引页 `_interspeech.html` 出现的位置（1-based）。guide 的 1379 个 slug 与索引 1:1，所以能全命中。

## ③ LLM 抽取

`_batches/llm_enrich.json`：`{"0": {"summary":"一句中文…", "datasets":["LibriSpeech"]}}`

- 只有 `summary` + `datasets` 两个字段走 LLM；**七维的其余 6 维来自 `out_*.json`（人工/第二轮整理产物）**。
- `render.py` 里做兜底：LLM 没给 summary 就用摘要首句截断（90 字）;`datasets` 空则用已知语料表 + 正则启发式兜底（`_KNOWN_DS` + `X dataset/corpus/benchmark` 只读专有名词形态）。

## ④ 渲染注入顺序

`render.py` 顶部按此顺序把外部数据缝进 `DATA`：

1. `_batches/isca_index.html` → DOI（`_slugof` + `_ISCA_MAP`）
2. `_batches/llm_enrich.json` → `summary` / `datasets` / `dataset`（字符串兼容字段）
3. `_batches/paper_meta.json` + `_batches/inst_class_final.json` → 作者机构/邮箱/机构类型
4. 数据集聚合 `_build_dataset_usage()`（同名数据集大小写归一合并）
5. `__DATA__` / `__AUTHORS__` / `__ASTATS__` 三处模板占位替换

## ⑤ 输出

- `interspeech2026_authors.html` — 完整版（含作者分析 + Excel 导出），~4.2 MB
- `interspeech2026_simple.html` — 简化版（`render_simple.py` 生成），~2.1 MB
- 两者都是**零外部依赖**：`grep -o 'src="http` / `@import` 应为空。
