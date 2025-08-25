from typing import Any, Optional
import tornado.web
from tornado.httputil import HTTPServerRequest
import tornado.platform.asyncio
import os
from .config import Config
from .photo_task import get_by_uuid, real_frame_size
import base64
import json
import logging

logger = logging.getLogger(__name__)

class FitFrameHandler(tornado.web.RequestHandler):
    def initialize(self, app):
        self.app = app

    async def get(self):
        id_str = self.get_query_argument("id", default="")
        locale_str = self.get_query_argument("locale", default="en")
        def localize(s: str):
            return self.app.localization(s, locale=locale_str)

        try:
            task = get_by_uuid(id_str)

            if self.app.users_collection is not None:
                try:
                    user_agent = self.request.headers.get("User-Agent")
                    await self.app.users_collection.update_one({
                        "user_id": task.user.id,
                        "bot_id": self.app.bot.bot.id,
                    }, {
                        "$set": {
                            "user_agent": user_agent
                        },
                    }, upsert=True)
                except Exception as e:
                    logger.error(f"mongodb update error: {e}", exc_info=1)

            self.render(
                "fit_frame.html",
                task=task,
                id=id_str,
                real_frame_size=real_frame_size,
                help_desktop=localize("frame-mover-help-desktop"),
                help_mobile=localize("frame-mover-help-mobile"),
                frame_mover_help_unified=localize("frame-mover-help-unified"),
                finish_button_text=localize("frame-mover-finish-button-text"),
                help_realign=localize("frame-realign-message"),
            )
        except (KeyError, ValueError):
            raise tornado.web.HTTPError(404)

    async def post(self):
        """Accept cropped PNG (data URL or raw bytes) from canvas and store as cropped file.
        Body formats supported:
        - JSON { id: <uuid>, image: 'data:image/png;base64,...' }
        - form-data / x-www-form-urlencoded with fields id, image
        - raw binary with query param ?id=...
        Returns JSON {status:"ok"} or error.
        """
        try:
            content_type = self.request.headers.get('Content-Type','')
            if content_type.startswith('image/png'):
                # Raw binary with ?id= param
                id_str = self.get_query_argument('id','')
                image_data = self.request.body
            elif 'application/json' in content_type:
                payload = json.loads(self.request.body.decode('utf-8'))
                id_str = payload.get('id','')
                image_data = payload.get('image','')
            elif 'application/x-www-form-urlencoded' in content_type or 'multipart/form-data' in content_type:
                id_str = self.get_body_argument('id','')
                image_data = self.get_body_argument('image','')
            else:
                # Fallback treat as raw binary
                id_str = self.get_query_argument('id','')
                image_data = self.request.body
            task = get_by_uuid(id_str)
        except Exception:
            logger.error("bad upload request", exc_info=1)
            raise tornado.web.HTTPError(400)

        # Expect a data URL or bytes
        binary: bytes
        if isinstance(image_data, str):
            if image_data.startswith('data:image'):
                try:
                    header, b64data = image_data.split(',',1)
                    binary = base64.b64decode(b64data)
                except Exception:
                    raise tornado.web.HTTPError(400)
            else:
                # assume base64 without header
                try:
                    binary = base64.b64decode(image_data)
                except Exception:
                    raise tornado.web.HTTPError(400)
        else:
            binary = image_data

        try:
            task.set_cropped_file_from_upload(binary)
        except Exception as e:
            logger.error("error writing uploaded cropped image: %s", e, exc_info=1)
            raise tornado.web.HTTPError(500)
        self.set_header('Content-Type','application/json')
        self.write({'status':'ok'})



class PhotoHandler(tornado.web.StaticFileHandler):
    def __init__(self, application: tornado.web.Application, request: HTTPServerRequest, **kwargs: Any) -> None:
        super().__init__(application, request, path="", **kwargs)
    
    @classmethod
    def get_absolute_path(cls, root: str, path: str) -> str:
        try:
            task = get_by_uuid(path)
            if task.file is None:
                return ""
            return task.file
        except (KeyError, ValueError):
            return ""
    
    def validate_absolute_path(self, root: str, absolute_path: str) -> Optional[str]:
        if absolute_path == "" or not os.path.isfile(absolute_path):
            raise tornado.web.HTTPError(404)
        return absolute_path



async def create_server(config: Config, base_app):
    tornado.platform.asyncio.AsyncIOMainLoop().install()
    app = tornado.web.Application([
        (r"/fit_frame", FitFrameHandler, {"app": base_app}),
        (r"/photos/(.*)", PhotoHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static/"}),
    ], template_path="templates/")
    app.listen(config.server.port)
    base_app.server = app

    return app
