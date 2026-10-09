# -*- coding: utf-8 -*-
"""Resumable, multi-worker LLM enrichment for a conference guide.

Reads ``guide_data.json`` (papers) + ``_batches/abs_text.json`` (abstracts),
calls a **local** Ollama model per paper and writes ``_batches/llm_enrich.json``
keyed by paper index: ``{"summary": "...", "datasets": [...]}``.

Measured on an Apple M3 (8 cores, model served on 11434):
  * serial loop          ~15 s/paper
  * --workers 8          ~4  paper/min  (1379 papers ≈ 3.5 h, resumable)

The job is **resumable**: already-written indices are skipped, and results are
flushed every N records, so killing it halfway costs at most one flush.

Usage
-----
    OLLAMA_BASE=http://localhost:11434/api/chat \
      python3 llm_enrich.py --workers 8 --trunc 1600 --predict 256 --flush 25

    # override the extraction prompt for another venue
    python3 llm_enrich.py --sys prompt.zh.txt
"""
import json, time, urllib.request, os, re, sys, threading, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434/api/chat")
# Never route localhost inference through the system HTTP proxy (it returns 502).
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

GD = "guide_data.json"
ABS = "_batches/abs_text.json"
OUT = "_batches/llm_enrich.json"
LOG = "_batches/llm_enrich.log"
MODEL = "qwen3:14b"

SYS = ("你是学术文献分析助手。根据论文标题与英文摘要，输出一个 JSON 对象："
       "{\"summary\":\"用一句中文凝练总结该论文的核心方法/主要贡献/结论，必须是摘要的凝练，"
       "不要简单照抄摘要首句\",\"datasets\":[\"论文实验中使用的所有数据集/语料/基准的英文名"
       "（训练集、测试集、验证集、评测基准均可），若摘要未明确提及则返回空列表\"]}。"
       "只输出 JSON，不要任何解释或推理过程。")

_lock = threading.Lock()
_flush_every = 25


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    print(msg, flush=True)


def extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            pass
    s, e = text.find("["), text.rfind("]")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            pass
    return None


# OLLAMA_BASE is the full base URL. For a llama.cpp native server on another
# port, either point OLLAMA_BASE at it and set OLLAMA_ENDPOINT=/v1/chat/completions,
# or set OLLAMA_CHAT_URL directly (it always wins).
ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "")
CHAT_URL = os.environ.get("OLLAMA_CHAT_URL") or (BASE.rstrip("/") + ENDPOINT)


def call_one(title, abstract, opts, model=MODEL):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": f"TITLE: {title}\nABSTRACT: {abstract[:3000]}"},
        ],
        "options": dict({"temperature": 0.0}, **opts),
        "stream": False,
        "think": False,
    }
    if ENDPOINT.startswith("/v1/"):
        payload = {  # llama.cpp OpenAI-compatible shape
            "model": model,
            "messages": payload["messages"],
            "temperature": 0.0,
            "max_tokens": (opts or {}).get("num_predict", 256),
            "stream": False,
        }
    req = urllib.request.Request(
        CHAT_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=300))
    if "/v1/chat/completions" in CHAT_URL:
        ch = r.get("choices") or [{}]
        m = ch[0].get("message") or {}
        return m.get("content") or ch[0].get("text") or r.get("content") or ""
    return r["message"]["content"]


def norm(j):
    if isinstance(j, list):
        j = j[0] if j else None
    if not isinstance(j, dict):
        return None
    s = str(j.get("summary", "")).strip()
    if not s:
        return None
    ds = j.get("datasets") or []
    if not isinstance(ds, list):
        ds = [ds]
    return {"summary": s, "datasets": [str(x).strip() for x in ds if str(x).strip()]}


def work(idx, title, abstract, opts, model=MODEL):
    for attempt in range(3):
        try:
            raw = call_one(title, abstract, opts, model)
            rec = norm(extract_json(raw))
            if rec:
                return idx, rec, ""
            log(f"  [{idx}] parse-fail a{attempt}: {raw[:140]!r}")
        except Exception as ex:
            log(f"  [{idx}] err a{attempt}: {ex}")
            time.sleep(2 + 2 * attempt)
    return idx, None, "GAVE_UP"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8, help="python-side worker threads")
    ap.add_argument("--par", type=int, default=0, help="server num_parallel (0 = keep)")
    ap.add_argument("--ctx", type=int, default=0, help="server num_ctx (0 = keep)")
    ap.add_argument("--predict", type=int, default=0, help="num_predict cap (0 = keep)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new records (0 = all)")
    ap.add_argument("--shard", type=str, default="", help="e.g. 2/4 -> shard 2 of 4")
    ap.add_argument("--start", type=int, default=0, help="skip indices below this")
    ap.add_argument("--model", default=os.environ.get("ENRICH_MODEL", MODEL))
    ap.add_argument("--trunc", type=int, default=2000, help="abstract chars sent to the model")
    ap.add_argument("--flush", type=int, default=25, help="save results every N new records")
    ap.add_argument("--sys", type=str, default="", help="file overriding the extraction prompt")
    args = ap.parse_args()

    global SYS, OUT, LOG
    if args.sys:
        SYS = open(args.sys, encoding="utf-8").read().strip()
    OUT = os.environ.get("ENRICH_OUT", OUT)
    LOG = os.environ.get("ENRICH_LOG", LOG)

    opts = {}
    if args.par:
        opts["num_parallel"] = args.par
    if args.ctx:
        opts["num_ctx"] = args.ctx
    if args.predict:
        opts["num_predict"] = args.predict

    d = json.load(open(GD, encoding="utf-8"))
    papers = d["papers"]
    abs_map = json.load(open(ABS, encoding="utf-8")) if os.path.exists(ABS) else {}
    done = {}
    if os.path.exists(OUT):
        done = json.load(open(OUT, encoding="utf-8"))
    log(f"start total={len(papers)} already_done={len(done)} workers={args.workers} "
        f"model={args.model} opts={opts} shard={args.shard or '-'}")

    total = len(papers)
    shard_a, shard_n = 0, 1
    if "/" in args.shard:
        shard_a, shard_n = (int(x) for x in args.shard.split("/"))

    pending = []
    for i in range(args.start, total):
        if str(i) in done:
            continue
        if i % shard_n != shard_a:
            continue
        title = papers[i].get("t", "")
        abstract = (papers[i].get("abs") or abs_map.get(str(i), "")).strip()
        if not abstract:
            log(f"  [{i}] no-abstract, skipped")
            continue
        pending.append((i, title, abstract))

    log(f"pending={len(pending)}")
    n_new = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, i, t, a, opts, args.model) for (i, t, a) in pending]
        for k, fut in enumerate(as_completed(futs), 1):
            try:
                idx, rec, note = fut.result()
            except Exception as ex2:
                log(f"  [?] crash {ex2}")
                continue
            if rec is None:
                rec = {"summary": "", "datasets": []}
                log(f"  [{idx}] {note or 'failed'}")
            with _lock:
                done[str(idx)] = rec
            n_new += 1
            if n_new % 10 == 0 or n_new % args.flush == 0:
                el = time.time() - t0
                rate = n_new / el * 60
                eta = (len(pending) - n_new) / rate if rate > 0 else 0
                log(f"progress {len(done)}/{total} new={n_new} {rate:.1f}/min eta={eta:.0f}min")
                json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            if args.limit and n_new >= args.limit:
                log(f"limit reached ({args.limit}), stopping early")
                for f in futs:
                    f.cancel()
                break
    json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    log(f"DONE total={len(done)} new={n_new} elapsed={(time.time()-t0)/60:.1f}min")
    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()
