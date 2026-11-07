"""Exercise real polling and photo handlers through an in-memory Telegram API."""

import asyncio
import io
import json
import tempfile
import unittest
import hashlib
import hmac
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import yaml
from fluent.runtime import FluentResourceLoader
from PIL import Image, ImageDraw
from telegram.ext import ApplicationBuilder
from telegram.request import BaseRequest
from tornado.httpclient import AsyncHTTPClient, HTTPRequest
from tornado.httpserver import HTTPServer
from tornado.netutil import bind_sockets
from tornado.web import Application as WebApplication

from photobot import photo_task
from photobot.cached_localization import Localization
from photobot.config import Config
from photobot.telegram import create_telegram_bot, avatar_cancel_inner
from photobot.server import FitFrameHandler


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
        elif endpoint in {"sendMessage", "sendDocument", "editMessageMedia"}:
            uploaded = None
            if endpoint in {"sendDocument", "editMessageMedia"}:
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
    async def test_completed_task_cleanup_is_not_a_cancellation(self):
        collection = SimpleNamespace(update_one=AsyncMock())
        context = SimpleNamespace(application=SimpleNamespace(base_app=SimpleNamespace(users_collection=collection)),
                                  bot=SimpleNamespace(id=123456, edit_message_reply_markup=AsyncMock()))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
        task = SimpleNamespace(result_message_id=10, chat=SimpleNamespace(id=42), discard=AsyncMock(return_value=True))
        with patch("photobot.telegram.get_by_user", return_value=task):
            self.assertTrue(await avatar_cancel_inner(update, context))
            collection.update_one.assert_not_awaited()
            context.bot.edit_message_reply_markup.assert_awaited_once_with(chat_id=42, message_id=10, reply_markup=None)
            task.result_message_id = None
            self.assertTrue(await avatar_cancel_inner(update, context))
            collection.update_one.assert_awaited_once()

    async def test_start_automatic_frame_and_inline_edit(self):
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
                        self.assertEqual(params["text"], app.localization("processing-photo", locale="en"))
                        method, params, uploaded = await api.next_reply()
                        self.assertEqual((method, params["chat_id"], uploaded[0]), ("sendDocument", 42, "avatar.jpg"))
                        button = params["reply_markup"]["inline_keyboard"][0][0]
                        self.assertEqual(button["text"], app.localization("select-position-command", locale="en"))
                        task_id = parse_qs(urlsplit(button["web_app"]["url"]).query)["id"][0]
                        with Image.open(io.BytesIO(uploaded[1])) as result:
                            self.assertEqual((result.format, result.size), ("JPEG", (1000, 1000)))
                            self.assertGreater(result.getpixel((500, 500))[2], 240)
                            self.assertGreater(result.getpixel((10, 10))[0], 240)
                        _, params, _ = await api.next_reply()
                        self.assertEqual(params["text"], app.localization("final-message", locale="en"))
                        await application.update_queue.join()
                        self.assertEqual(errors, [])
                        self.assertTrue(api.replies.empty())
                        task = photo_task.get_by_user(42)
                        self.assertEqual(task.id.hex, task_id)
                        self.assertTrue(Path(task.file).is_file())

                        sockets = bind_sockets(0, "127.0.0.1")
                        port = sockets[0].getsockname()[1]
                        http = HTTPServer(WebApplication([(r"/fit_frame", FitFrameHandler, {"app": app})], template_path="templates/"))
                        http.add_sockets(sockets)
                        client = AsyncHTTPClient(force_instance=True)
                        edited = io.BytesIO()
                        Image.new("RGBA", (1080, 1080), "green").save(edited, "PNG")

                        def signed_data(user_id):
                            data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id})}
                            secret = hmac.new(b"WebAppData", b"123456:TEST_ONLY", hashlib.sha256).digest()
                            check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
                            data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
                            return urlencode(data)

                        async def upload(init_data, transform=None):
                            headers = {"Content-Type": "image/png", "X-Telegram-Init-Data": init_data}
                            if transform is not None:
                                headers["X-Photo-Transform"] = json.dumps(transform)
                            return await client.fetch(HTTPRequest(
                                f"http://127.0.0.1:{port}/fit_frame?id={task_id}", method="POST",
                                headers=headers,
                                body=edited.getvalue(),
                            ), raise_error=False)

                        try:
                            self.assertEqual((await upload("")).code, 403)
                            self.assertEqual((await upload(signed_data(43))).code, 403)
                            self.assertEqual((await upload(signed_data(42).replace("hash=", "hash=00"))).code, 403)
                            self.assertEqual((await upload(signed_data(42), [[float("nan")]])).code, 400)
                            self.assertTrue(api.replies.empty())
                            transform = [[0.9, 0, 10], [0, 0.9, 20]]
                            self.assertEqual((await upload(signed_data(42), transform)).code, 200)
                            method, params, uploaded = await api.next_reply()
                            self.assertEqual((method, params["message_id"]), ("editMessageMedia", task.result_message_id))
                            with Image.open(io.BytesIO(uploaded[1])) as result:
                                self.assertEqual(result.size, (1000, 1000))
                                self.assertGreater(result.getpixel((500, 500))[1], 100)
                                self.assertLess(result.getpixel((500, 500))[2], 20)
                            self.assertTrue(Path(task.file).is_file())
                            self.assertEqual(task.editor_transform, transform)
                            page = await client.fetch(f"http://127.0.0.1:{port}/fit_frame?id={task_id}")
                            self.assertIn(b'name="viewport"', page.body)
                            self.assertIn(b'data-editor-transform=', page.body)

                            started, release = asyncio.Event(), asyncio.Event()
                            finalize = task.finalize_avatar
                            async def delayed_finalize():
                                started.set()
                                await release.wait()
                                await finalize()
                            with patch.object(task, "finalize_avatar", delayed_finalize):
                                saving = asyncio.create_task(upload(signed_data(42)))
                                await asyncio.wait_for(started.wait(), 5)
                                discard = asyncio.create_task(task.discard())
                                await asyncio.sleep(0)
                                self.assertFalse(discard.done())
                                release.set()
                                self.assertEqual((await saving).code, 200)
                                self.assertTrue(await discard)
                                self.assertEqual((await api.next_reply())[0], "editMessageMedia")
                        finally:
                            http.stop()
                            await http.close_all_connections()
                            client.close()

                        api.submit(3, text="/cancel", entities=[{"type": "bot_command", "offset": 0, "length": 7}])
                        await api.next_reply()
                        await application.update_queue.join()
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
