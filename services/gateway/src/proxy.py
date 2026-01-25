import httpx
from fastapi import Request, HTTPException
from fastapi.responses import Response, StreamingResponse
from loguru import logger

async def reverse_proxy(request: Request, path: str, target_url: str, target_path: str, client: httpx.AsyncClient):
    url = f"{target_url}{target_path}"
    
    # Copy query params
    params = dict(request.query_params)
    
    # Copy headers (exclude host to avoid conflicts)
    # Also exclude Hop-by-Hop headers that might conflict with StreamingResponse
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() not in ('host', 'content-length', 'transfer-encoding', 'connection')
    }
    
    logger.trace(f"Proxying {request.method} {request.url} -> {url}")
    
    try:
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
            
        # Special handling for 204 No Content (no body allowed, no chunked encoding)
        if r.status_code == 204:
            return Response(
                status_code=204,
                headers=dict(r.headers)
            )

        # Filter response headers
        response_headers = {
            k: v for k, v in r.headers.items()
            if k.lower() not in ('content-length', 'transfer-encoding', 'connection')
        }

        return StreamingResponse(
            r.aiter_raw(),
            status_code=r.status_code,
            headers=response_headers,
            background=None
        )
            
    except httpx.ConnectError:
        logger.error(f"Failed to connect to upstream service: {target_url}")
        raise HTTPException(status_code=503, detail="Upstream service unavailable")
    except Exception as e:
        logger.error(f"Proxy error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
