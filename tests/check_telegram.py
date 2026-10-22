"""Exercise real polling and photo handlers through an in-memory Telegram API."""

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from fluent.runtime import FluentResourceLoader
from PIL import Image, ImageDraw
from telegram.ext import ApplicationBuilder
from telegram.request import BaseRequest

from photobot import photo_task
from photobot.cached_localization import Localization
from photobot.config import Config
from photobot.telegram import create_telegram_bot


class FakeTelegram(BaseRequest):
    def __init__(self, photo):
        self.photo = photo
        self.updates = asyncio.Queue()
        self.replies = asyncio.Queue()
        self.calls = []
        self.user = {"id": 42, "is_bot": False, "first_name": "Test", "language_code": "en"}
        self.bot = {"id": 123456, "is_bot": True, "first_name": "Photo", "username": "test_photo_bot"}
        self.chat = {"id": 42, "type": "private"}

    @property
    def read_timeout(self):
        return 1

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    async def do_request(self, url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        self.calls.append((endpoint, params))
        if "/file/bot" in url:
            if endpoint != "input.jpg":
                raise AssertionError(f"Unexpected download: {endpoint}")
            return 200, self.photo
        if endpoint == "getMe":
            result = self.bot
        elif endpoint == "deleteWebhook":
            result = True
        elif endpoint == "getUpdates":
            try:
                result = [await asyncio.wait_for(self.updates.get(), timeout=0.05)]
            except asyncio.TimeoutError:
                result = []
        elif endpoint == "getFile":
            if params["file_id"] != "large-photo":
                raise AssertionError("The largest submitted photo was not selected")
            result = {"file_id": "large-photo", "file_unique_id": "large", "file_path": "input.jpg"}
        elif endpoint in {"sendMessage", "sendDocument"}:
            uploaded = None
            if endpoint == "sendDocument":
                filename, content, _ = next(iter(request_data.multipart_data.values()))
                uploaded = (filename, content if isinstance(content, bytes) else content.read())
            self.replies.put_nowait((endpoint, params, uploaded))
            result = {"message_id": len(self.calls), "date": 1, "chat": self.chat, "from": self.bot}
            if endpoint == "sendMessage":
                result["text"] = params["text"]
            else:
                result["document"] = {"file_id": "result", "file_unique_id": "result"}
        else:
            raise AssertionError(f"Unexpected Telegram method: {endpoint}")
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def submit(self, update_id, **message):
        self.updates.put_nowait({
            "update_id": update_id,
            "message": {"message_id": update_id, "date": 1, "chat": self.chat, "from": self.user, **message},
        })

    async def next_reply(self):
        return await asyncio.wait_for(self.replies.get(), timeout=5)


class TelegramChecks(unittest.IsolatedAsyncioTestCase):
    async def test_start_photo_autocrop_and_document_reply(self):
        photo = io.BytesIO()
        Image.new("RGB", (1200, 1600), "blue").save(photo, "JPEG")
        api = FakeTelegram(photo.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = Image.new("RGBA", (1080, 1080))
            ImageDraw.Draw(frame).rectangle((0, 0, 1079, 1079), outline="red", width=100)
            frame.save(root / "frame.png")
            settings = yaml.safe_load(Path("config/config.template.yaml").read_text())
            settings["telegram"]["token"] = "123456:TEST_ONLY"
            settings["users_db"]["address"] = ""
            settings["photo"].update(storage_path=str(root / "photos"), cpu_threads=1)
            (root / "config.yaml").write_text(yaml.safe_dump(settings))
            config = Config(str(root / "config.yaml"))
            app = SimpleNamespace(bot=None, users_collection=None, localization=Localization(
                FluentResourceLoader(config.localization.path), config.localization.file,
                config.localization.fallbacks,
            ))
            builder = ApplicationBuilder().request(api).get_updates_request(api)
            errors = []

            async def record_error(update, context):
                errors.append(context.error)

            with patch("photobot.telegram.ApplicationBuilder", return_value=builder), \
                    patch.object(photo_task, "files_path", str(root / "photos")), \
                    patch.object(photo_task, "frame_filename", str(root / "frame.png")), \
                    patch.object(photo_task, "main_executor", None):
                photo_task.init_photo_tasker(config)
                try:
                    async with create_telegram_bot(config, app) as application:
                        application.add_error_handler(record_error)
                        api.submit(1, text="/start", entities=[{"type": "bot_command", "offset": 0, "length": 6}])
                        method, params, _ = await api.next_reply()
                        self.assertEqual((method, params["chat_id"], params["parse_mode"]), ("sendMessage", 42, "HTML"))
                        self.assertEqual(params["text"], app.localization("start-message", locale="en"))

                        api.submit(2, photo=[
                            {"file_id": "small-photo", "file_unique_id": "small", "width": 90, "height": 120},
                            {"file_id": "large-photo", "file_unique_id": "large", "width": 1200, "height": 1600},
                        ])
                        _, params, _ = await api.next_reply()
                        self.assertEqual(params["text"], app.localization("select-position-prompt", locale="en"))
                        self.assertIn("reply_markup", params)

                        api.submit(3, text=app.localization("autocrop-command", locale="en"))
                        _, params, _ = await api.next_reply()
                        self.assertEqual(params["text"], app.localization("processing-photo", locale="en"))
                        method, params, uploaded = await api.next_reply()
                        self.assertEqual((method, params["chat_id"], uploaded[0]), ("sendDocument", 42, "avatar.jpg"))
                        with Image.open(io.BytesIO(uploaded[1])) as result:
                            self.assertEqual((result.format, result.size), ("JPEG", (1000, 1000)))
                            self.assertGreater(result.getpixel((500, 500))[2], 240)
                            self.assertGreater(result.getpixel((10, 10))[0], 240)
                        _, params, _ = await api.next_reply()
                        self.assertEqual(params["text"], app.localization("final-message", locale="en"))
                        await application.update_queue.join()
                        self.assertEqual(errors, [])
                        self.assertTrue(api.replies.empty())
                        self.assertEqual(list((root / "photos").iterdir()), [])
                        self.assertNotIn(42, photo_task.tasks_by_user)
                finally:
                    for task in list(photo_task.tasks_by_uuid.values()):
                        task.delete()
                    photo_task.main_executor.shutdown(wait=True)
            self.assertIsNone(app.bot)
            methods = [method for method, _ in api.calls]
            self.assertIn("getUpdates", methods)
            self.assertIn("getFile", methods)
            self.assertIn("input.jpg", methods)


if __name__ == "__main__":
    unittest.main()
