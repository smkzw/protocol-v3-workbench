"""WP6 browser proxy: legacy reads from 5301, Protocol v3 writes from 5302."""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response


app = FastAPI(title="WP6 split acceptance proxy")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(path: str, request: Request) -> Response:
    full_path = "/" + path
    target = 5302 if "/protocol-workflow" in full_path else 5301
    url = f"http://127.0.0.1:{target}{full_path}"
    if request.url.query:
        url += "?" + request.url.query
    headers = {
        key: value for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        upstream = await client.request(
            request.method, url, content=await request.body(), headers=headers
        )
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key.lower() not in {
            "content-length", "content-encoding", "transfer-encoding", "connection"
        }
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
