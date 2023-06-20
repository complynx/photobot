from typing import Any, Optional
import tornado.web
from tornado.httputil import HTTPServerRequest
import tornado.platform.asyncio
import os
from .config import Config
from .photo_task import get_by_uuid, real_frame_size
import logging

logger = logging.getLogger(__name__)

class FitFrameHandler(tornado.web.RequestHandler):
    def initialize(self, app):
        self.app = app

    async def get(self):
        id_str = self.get_query_argument("id", default="")
        locale_str = self.get_query_argument("locale", default="en")
        l = lambda s: self.app.localization(s, locale=locale_str)

        try:
            task = get_by_uuid(id_str)
            self.render(
                "fit_frame.html",
                task=task,
                id=id_str,
                real_frame_size=real_frame_size,
                help_desktop=l("frame-mover-help-desktop"),
                help_mobile=l("frame-mover-help-mobile"),
                frame_mover_help_unified=l("frame-mover-help-unified"),
                finish_button_text=l("frame-mover-finish-button-text"),
            )
        except (KeyError, ValueError):
            raise tornado.web.HTTPError(404)



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
