#!/usr/bin/env python3
"""
freellamapi — 本地免费大模型（Ollama）API 路由网关

职责
----
把本地 Ollama（默认 http://127.0.0.1:11434）暴露成一套统一的 API 路由：
  - OpenAI 兼容：`POST /v1/chat/completions`、`GET /v1/models`
  - Ollama 原生：`POST /api/chat`、`POST /api/generate`
  - 模型路由：`POST /route`（按任务类型自动选模型，即「路由」核心）
  - 健康探测：`GET /health`
  - 服务信息：`GET /`

设计原则
--------
- **零新依赖**：仅用 FastAPI + 标准库 urllib 转发到 Ollama；不引入 requests/openai SDK。
- **无状态网关**：本服务不做推理，只做协议转换 + 模型路由 + CORS。
- **localhost 优先**：Ollama 在本地，转发时清空代理（实测环境存在系统代理，会破坏直连）。
- **与 NBACore 后端解耦**：独立端口，不依赖 PostgreSQL / backend.core，可单独启停。

环境变量
--------
- FREELLAMAPI_HOST       监听地址   默认 127.0.0.1
- FREELLAMAPI_PORT       监听端口   默认 8777
- OLLAMA_BASE_URL        Ollama 地址 默认 http://127.0.0.1:11434
- FREELLAMAPI_DEFAULT_MODEL  默认模型 默认 qwen3:8b-nothink
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("freellamapi")

# ── 配置 ───────────────────────────────────────────────
HOST = os.getenv("FREELLAMAPI_HOST", "127.0.0.1")
PORT = int(os.getenv("FREELLAMAPI_PORT", "8777"))
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("FREELLAMAPI_DEFAULT_MODEL", "qwen3:8b-nothink")

# 模型路由表：任务类型 -> 模型。按 Ollama 实际可用模型设定。
MODEL_ROUTES: Dict[str, str] = {
    "chat": "qwen3:8b-nothink",          # 通用对话（无需思维链）
    "reason": "qwen3:8b",                # 需要推理链
    "code": "qwen2.5-coder:7b",          # 代码生成
    "translate": "hy-mt2-7b",            # 翻译
    "fast": "qwen-3b:latest",            # 极速/轻量
    "deep": "deepseek-v4-qwen35-9b:latest",  # 重推理
}


# ── 转发工具 ───────────────────────────────────────────
def _opener():
    """无代理 opener：Ollama 在 localhost，避免 http_proxy 干扰。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _forward(method: str, path: str, body: Optional[bytes] = None,
             stream: bool = False, timeout: float = 120):
    """把请求转发到 Ollama 对应路径，返回 (status, payload_or_iter)。"""
    url = f"{OLLAMA_BASE}{path}"
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        resp = _opener().open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:  # Ollama 返回 4xx/5xx
        raw = exc.read().decode("utf-8", "replace")
        raise HTTPException(status_code=exc.code, detail=raw)
    except Exception as exc:  # 网络层
        raise HTTPException(status_code=502, detail=f"Ollama 不可达: {exc}")
    if stream:
        return resp.status, resp
    raw = resp.read().decode("utf-8", "replace")
    return resp.status, raw


def _ollama_models() -> List[str]:
    try:
        _, raw = _forward("GET", "/api/tags")
        data = json.loads(raw)
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ── Pydantic 模型（请求体）──────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    temperature: float = 0.7
    stream: bool = False
    task: Optional[str] = Field(None, description="路由任务类型: chat/reason/code/translate/fast/deep")


class GenerateRequest(BaseModel):
    model: Optional[str] = None
    prompt: str
    temperature: float = 0.7
    stream: bool = False
    task: Optional[str] = None


class RouteRequest(BaseModel):
    task: str = Field(..., description="任务类型: chat/reason/code/translate/fast/deep")
    prompt: Optional[str] = None
    hint_model: Optional[str] = None


# ── App ────────────────────────────────────────────────
app = FastAPI(title="freellamapi", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 复用 Ollama 已加载模型状态
_AVAILABLE = _ollama_models()


def _resolve_model(req_model: Optional[str], task: Optional[str]) -> str:
    if req_model:
        return req_model
    if task and task in MODEL_ROUTES:
        return MODEL_ROUTES[task]
    # 若默认模型不可用，回退到 Ollama 任一可用模型
    if _AVAILABLE and DEFAULT_MODEL not in _AVAILABLE:
        return _AVAILABLE[0]
    return DEFAULT_MODEL


# ── 路由 ───────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "freellamapi",
        "version": "1.0.0",
        "ollama_base": OLLAMA_BASE,
        "available_models": _AVAILABLE,
        "default_model": _resolve_model(None, None),
        "routes": {
            "POST /v1/chat/completions": "OpenAI 兼容对话",
            "GET  /v1/models": "OpenAI 兼容模型列表",
            "POST /api/chat": "Ollama 原生 chat",
            "POST /api/generate": "Ollama 原生 generate",
            "POST /route": "按任务类型路由到最合适模型",
            "GET  /health": "健康检查",
        },
    }


@app.get("/health")
def health():
    reachable = bool(_AVAILABLE) or _forward("GET", "/api/tags")[0] == 200
    return {
        "status": "ok" if reachable else "degraded",
        "ollama_reachable": reachable,
        "ollama_base": OLLAMA_BASE,
        "available_models": _AVAILABLE,
    }


@app.get("/v1/models")
def openai_models():
    models = _ollama_models()
    return {
        "object": "list",
        "data": [
            {
                "id": m,
                "object": "model",
                "owned_by": "ollama",
                "created": 0,
            }
            for m in models
        ],
    }


@app.post("/route")
def route(req: RouteRequest):
    """核心「路由」：按任务类型选模型，可附带可用模型白名单校验。"""
    chosen = req.hint_model or MODEL_ROUTES.get(req.task, DEFAULT_MODEL)
    if _AVAILABLE and chosen not in _AVAILABLE and req.hint_model:
        # hint 给的模型不可用，回退到该任务的默认路由
        chosen = MODEL_ROUTES.get(req.task, _AVAILABLE[0] if _AVAILABLE else DEFAULT_MODEL)
    return {
        "task": req.task,
        "model": chosen,
        "available_models": _AVAILABLE,
        "note": "路由已将请求导向该模型",
    }


@app.post("/v1/chat/completions")
def openai_chat(req: ChatRequest):
    """OpenAI 兼容 chat/completions —— 协议转换为 Ollama /api/chat。"""
    model = _resolve_model(req.model, req.task)
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    payload = {
        "model": model,
        "messages": messages,
        "stream": req.stream,
        "options": {"temperature": req.temperature},
    }
    body = json.dumps(payload).encode("utf-8")

    if req.stream:
        status, resp = _forward("POST", "/api/chat", body, stream=True)
        def gen():
            for line in resp:
                try:
                    chunk = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                content = chunk.get("message", {}).get("content", "")
                out = {
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"delta": {"content": content}, "index": 0}],
                }
                yield f"data: {json.dumps(out, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    status, raw = _forward("POST", "/api/chat", body)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Ollama 返回非 JSON")
    content = data.get("message", {}).get("content", "")
    return {
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": data.get("prompt_eval_count", 0) and {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        },
    }


@app.post("/api/chat")
async def ollama_chat(request: Request):
    """Ollama 原生 chat 透传（保留完整 Ollama 语义）。"""
    body = await request.body()
    status, raw = _forward("POST", "/api/chat", body if body else None)
    return JSONResponse(content=_try_json(raw), status_code=status)


@app.post("/api/generate")
async def ollama_generate(request: Request):
    """Ollama 原生 generate 透传。"""
    body = await request.body()
    status, raw = _forward("POST", "/api/generate", body if body else None)
    return JSONResponse(content=_try_json(raw), status_code=status)


def _try_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}


if __name__ == "__main__":
    import uvicorn
    logger.info("freellamapi 启动 | host=%s port=%s ollama=%s models=%s",
                HOST, PORT, OLLAMA_BASE, _AVAILABLE)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
