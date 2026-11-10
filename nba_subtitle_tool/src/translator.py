"""翻译模块：调用本地 Ollama 运行的 Qwen2.5 等大模型，注入篮球术语表，
将英文/法文解说译为中文。段落级并发，保证 1:1 映射最稳。"""
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed


def load_glossary(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def glossary_to_text(glossary: list, limit: int = 0) -> str:
    items = glossary if not limit else glossary[:limit]
    lines = []
    for g in items:
        s = f"- {g['en']} / {g.get('fr','')} → {g['zh']}"
        if g.get("note"):
            s += f"  （{g['note']}）"
        lines.append(s)
    return "\n".join(lines)


SYSTEM_PROMPT = """你是一名专业的篮球赛事字幕翻译，服务于篮球视频的中文字幕与文稿制作。
任务：将下面的英文（可能夹杂法文）解说翻译为简体中文。

硬性要求：
1. 必须采用术语表中的标准译法。凡原文出现术语表中的英文/法文词，译文须使用对应中文
   （例：screen→掩护、pick and roll→挡拆、fadeaway→后仰跳投、outlet pass→一传/分球、
   catch-and-shoot→接球就投、meneur→控球后卫、contre→盖帽）。术语表含注释时务必遵循注释。
2. 法文术语同样按术语表处理。
3. 不得保留任何英文单词：Great/OK/Nice 等也要译出（如「精彩」「漂亮」「好球」），
   球员名用通用中文译名（Kobe→科比，Nash→纳什）。
4. 保留解说的口语化与现场感，中文通顺自然、专业。
5. 只输出中文译文本身，不要解释、不要重复原文、不要加「中文：」之类前缀或引号。
6. 若一段里同时出现英文和法文，统一译为中文。

术语表（优先采用，含必要注释）：
{glossary}
"""


def _client(base_url: str):
    import ollama
    return ollama.Client(host=base_url)


# ---------- Hy-MT2（腾讯混元翻译模型）适配 ----------
# 与通用 LLM（Qwen 等）的三点差异：
#   1) Hy-MT2 没有默认 system prompt，翻译指令必须写进 prompt；
#   2) 采样参数不同（官方推荐 temp 0.7 / top_p 0.6 / top_k 20 / rep_pen 1.05）；
#   3) 上下文仅 4K，全文注入 189 条术语表（约 3.8K token）会撑爆，
#      因此按「当前段落实际出现的术语」动态裁剪术语表。
_HY_MT_MARKERS = ("hy-mt", "hymt", "hy_mt", "hunyuan-mt", "hunyuan_mt")

HY_MT_PARAMS = {
    "temperature": 0.7,
    "top_p": 0.6,
    "top_k": 20,
    "repeat_penalty": 1.05,
    "num_predict": 512,
}


def is_hy_mt(model: str) -> bool:
    m = (model or "").lower()
    return any(k in m for k in _HY_MT_MARKERS)


def relevant_glossary(text: str, glossary: list, max_items: int = 40) -> list:
    """只保留当前段落里真实出现的术语，避免 4K 上下文被整张术语表占满。"""
    low = (text or "").lower()
    hits = []
    for g in glossary:
        for key in ("en", "fr"):
            t = (g.get(key) or "").strip()
            if len(t) >= 3 and t.lower() in low:
                hits.append(g)
                break
        if len(hits) >= max_items:
            break
    return hits


def _build_hy_mt_prompt(text: str, glossary_text: str) -> str:
    glossary_block = f"\n术语表（命中项，必须采用其标准译法）：\n{glossary_text}\n" if glossary_text else "\n"
    return (
        "你是一名专业的篮球赛事字幕翻译。请将下面的英文（可能夹杂法文）解说翻译成简体中文。\n"
        "硬性要求：\n"
        "1. 必须使用术语表中的标准译法；术语表含注释时务必遵循注释。\n"
        "2. 法文术语同样按术语表处理。\n"
        "3. 不得保留任何英文单词（Great/OK/Nice 等也要译出），球员名用通用中文译名（Kobe→科比）。\n"
        "4. 保留解说的口语化与现场感，中文通顺自然、专业。\n"
        "5. 只输出中文译文本身，不要解释、不要重复原文、不要加任何前缀或引号。\n"
        + glossary_block +
        f"\n原文：{text}\n"
        "译文："
    )


def translate_one(text: str, glossary_text: str, model: str,
                  temperature: float = 0.1, base_url: str = "http://localhost:11434",
                  glossary: list = None) -> str:
    if not text.strip():
        return ""
    client = _client(base_url)
    if is_hy_mt(model):
        # 4K 上下文：按段落裁剪术语表；若未传 glossary 则退回调用方给的文本
        g_text = glossary_text
        if glossary:
            g_text = glossary_to_text(relevant_glossary(text, glossary))
        resp = client.generate(
            model=model,
            prompt=_build_hy_mt_prompt(text, g_text),
            options=dict(HY_MT_PARAMS),
        )
    else:
        resp = client.generate(
            model=model,
            system=SYSTEM_PROMPT.format(glossary=glossary_text),
            prompt=text,
            options={"temperature": temperature, "num_predict": 512},
        )
    out = resp.get("response", "").strip()
    # 去掉可能的前缀噪声
    for pfx in ("中文：", "译文：", "翻译：", "“", "”"):
        if out.startswith(pfx):
            out = out[len(pfx):].strip()
    if out.endswith("”"):
        out = out[:-1].strip()
    return out


def translate_segments(texts: list, glossary: list, model: str,
                       workers: int = 4, temperature: float = 0.1,
                       base_url: str = "http://localhost:11434",
                       glossary_limit: int = 0) -> list:
    """逐段翻译，并发执行。返回与输入等长的中文列表。"""
    glossary_text = glossary_to_text(glossary, glossary_limit)
    results = [None] * len(texts)

    def job(i, t):
        # 传入 glossary 本体，Hy-MT2 会按段落裁剪（4K 上下文），其它模型用全文术语表
        return i, translate_one(t, glossary_text, model, temperature, base_url,
                                glossary=glossary)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(job, i, t) for i, t in enumerate(texts)]
        for fut in as_completed(futs):
            i, zh = fut.result()
            results[i] = zh
    # 兜底：任何 None 用原文占位，避免丢段
    for i, r in enumerate(results):
        if r is None:
            results[i] = texts[i]
    return results


def translate_cached(texts, cache_json, glossary, model, workers=4,
                     temperature=0.1, base_url="http://localhost:11434",
                     glossary_limit=0, resume=True):
    if resume and os.path.exists(cache_json):
        with open(cache_json, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if isinstance(cached, list) and len(cached) == len(texts):
            return cached
    zh = translate_segments(texts, glossary, model, workers, temperature,
                            base_url, glossary_limit)
    os.makedirs(os.path.dirname(cache_json), exist_ok=True)
    with open(cache_json, "w", encoding="utf-8") as f:
        json.dump(zh, f, ensure_ascii=False, indent=2)
    return zh
