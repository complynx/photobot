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
import hashlib
import hmac
import time
import math
from urllib.parse import parse_qsl
from .telegram import send_avatar_result

logger = logging.getLogger(__name__)

def verify_editor_owner(init_data: str, bot_token: str, user_id: int):
    """Authenticate the inline Mini App before updating a user's Telegram message."""
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Duplicate fields")
        signature = data.pop("hash")
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        age = time.time() - int(data["auth_date"])
        if not hmac.compare_digest(signature, expected) or not -60 <= age <= 86400:
            raise ValueError("Invalid or expired signature")
        if json.loads(data["user"])["id"] != user_id:
            raise ValueError("Wrong owner")
    except (KeyError, ValueError, TypeError):
        raise tornado.web.HTTPError(403)

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
                editor_transform=task.editor_transform,
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

        verify_editor_owner(
            self.request.headers.get("X-Telegram-Init-Data", ""),
            self.app.bot.config.telegram.token.get_secret_value(), task.user.id,
        )
        transform = None
        if self.request.headers.get("X-Photo-Transform"):
            try:
                transform = json.loads(self.request.headers["X-Photo-Transform"])
                if not (isinstance(transform, list) and len(transform) == 2
                        and all(isinstance(row, list) and len(row) == 3 for row in transform)
                        and all(type(v) in (int, float) and math.isfinite(v) for row in transform for v in row)):
                    raise ValueError("Invalid transform")
            except (ValueError, TypeError):
                raise tornado.web.HTTPError(400)
        try:
            async with task.edit_lock:
                # A new photo or timeout may have invalidated this editor while it waited.
                if get_by_uuid(task.id) is not task:
                    raise tornado.web.HTTPError(404)
                task.set_cropped_file_from_upload(binary)
                await task.finalize_avatar()
                if get_by_uuid(task.id) is not task:
                    raise tornado.web.HTTPError(404)
                await send_avatar_result(task, self.app.bot)
                task.editor_transform = transform
        except tornado.web.HTTPError:
            raise
        except KeyError:
            raise tornado.web.HTTPError(404)
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
    ], template_path="templates/", static_path="static/")
    app.listen(config.server.port)
    base_app.server = app

    return app
