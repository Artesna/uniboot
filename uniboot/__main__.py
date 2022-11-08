import os
import json
import asyncio
import logging
from aiohttp.web import Application, _run_app

from .api.v1 import core
from .api import frontend

loop = asyncio.new_event_loop()


async def main():
    app = Application(client_max_size=256 * 1024 * 1024)

    with open(os.environ.get("CONFIG", "config.json"), "r") as f:
        app["config"] = json.load(f)

    app["config"]["bin"] = app["config"]["bin"].replace("{cwd}", "/".join(__file__.split("/")[:-2]))
    app["pages"] = {}

    for k, v in app["config"]["pages"].items():
        with open(v, "rb") as f:
            app["pages"][k] = f.read()

    logging.basicConfig(level=logging.getLevelName(app["config"]["log"]))

    app.add_routes(core.routes)
    app.add_routes(frontend.routes)

    await _run_app(app, port=app["config"]["port"])

loop.run_until_complete(main())
