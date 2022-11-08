from aiohttp import web

routes = web.RouteTableDef()


@routes.get("/")
async def get_frontend_default(request: web.Request):
    return web.Response(body=request.app["pages"]["en"], content_type="text/html")


@routes.get("/{tail:.*}")
async def get_frontend(request: web.Request):
    try:
        return web.Response(body=request.app["pages"][request.path[1:]], content_type="text/html")
    except:
        return web.Response(text="Not found", status=404)
