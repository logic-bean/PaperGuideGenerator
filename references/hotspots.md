# 热点短语挖掘（hotspots）

模块：`assets/hotspots.py`。输入一组标题，输出 `(([[短语, 篇数], ...]), [[补充短语, 篇数], ...])`。

## 口径（必须写进页面说明，否则读者会误读）

- 数字 = **涉及论文数（文档频次 DF）**，不是词频、不是分组总篇数。
- 只统计**标题**（摘要有噪音，且口径要简单可解释）。
- 短语长度 1–3 词。

## 算法

1. `_norm_text`：小写 → NFKD 去重音（`māori`→`maori`）→ 非字母数字替成空格。`_deacc` 是必须的，否则重音词被切出 `ori` 这类碎片。
2. `tokens`：去标点后保留 `len>=3` 且不在 `STOP` 的词。
3. `_spans`：滑窗产出 1–3 词窗口，**允许跳过恰好 1 个功能词**（`FUNC = to/of/and/for/in/with/or/the/a`），这样 `text-to-speech` 不会退化成空壳邻接 `text speech`。
4. `_mine`：**按短语字符串计数 DF**（`df[' '.join(tk[i:j])] += 1`）。
   ⚠️ 早期版本按 token 位置跨度归并，`occ[s].add((ti,i,n))` 后按 `(i,n)` 归并 ⇒ 每个短语 DF 都等于分组篇数（10/1379 这种）。**必须按字符串 DF。**
5. `_condense` 冗余剪枝：若某短语的所有出现都落在更长的短语里，且更长者 DF 严格更大（或同频但更长且原 DF≥2），则丢弃原短语。
6. `ALIAS` 别名：`text speech` → `text to speech`。建立时**必须按 `(-词数, 短语)` 长者优先排序后 `setdefault`**，否则集合迭代顺序会让 `text to speech` 自己把自己映射成 `text speech`。
7. `hotspots()` 四段填充 + 排序键：

```python
rank = (0 if 多词 else 1,      # 完整短语永远优先
        0 if 在策展词表 else 1, # 然后是策展术语
        -n_papers, -词数, 短语)
```

   填充顺序：多词且 ≥2 篇 → 策展词（单篇仅当还没有多词可展示时）→ 未被已选短语覆盖的重复裸词 → 兜底裸词（最多 1–2 个）。

8. 输出前按 alias 去重（`text speech` 和 `text speech synthesis` 都归到 `text to speech`）。

## 前端两条铁律

1. **数据必须是 `[[phrase, count]]` 配对**。返回纯字符串列表时，前端 `countedSorted()` 兜底 `count = 1`，页面上每颗 chip 都显示「1」。
2. **`countedSorted()` 只做格式归一化，不能 sort**。否则前端会按数字再排一次，把后端精心排好的顺序打回原形，高频裸词（如 `detection` 116）会蹿到 `speech recognition`（53）前面。

## 「研究焦点」如何取

`focusFrom(uni, bi)`：优先取 `hot_uni` 里的**多词短语**（3 个），不足再补 `hot_bi` 的多词短语，最后才允许最多 2 个裸词兜底。绝不能先取 bigram —— 那会产出 `balancing hearing` 这种读不通的碎片。

## 调参提示

- 极小分组（如 8 篇的 Paralinguistics、单篇 Keynote）标题同质度低，挖不出多词短语属正常；靠 `LEX_TEXT` 的策展短语兜底即可（`speech language`、`data` 这类）。
- `top_k=12` / `top_combo=6` 是总览尺度；小分组自动缩短。
- 分组篇数 ≤3 时，页面要给一句「篇数少，统计不显著」的提示，别让 1 和 5 看起来是同一量级。
