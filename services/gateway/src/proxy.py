import httpx
from fastapi import Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from loguru import logger

async def reverse_proxy(request: Request, path: str, target_url: str, target_path: str):
    url = f"{target_url}{target_path}"
    
    # Copy query params
    params = dict(request.query_params)
    
    # Copy headers (exclude host to avoid conflicts)
    headers = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
    
    logger.debug(f"Proxying {request.method} {request.url} -> {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            # Handle body for non-GET requests
            content = await request.body()
            
            req = client.build_request(
                request.method,
                url,
                headers=headers,
                params=params,
                content=content
            )
            
            r = await client.send(req, stream=True)
            
            return StreamingResponse(
                r.aiter_raw(),
                status_code=r.status_code,
                headers=dict(r.headers),
                background=None
            )
            
    except httpx.ConnectError:
        logger.error(f"Failed to connect to upstream service: {target_url}")
        raise HTTPException(status_code=503, detail="Upstream service unavailable")
    except Exception as e:
        logger.error(f"Proxy error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
