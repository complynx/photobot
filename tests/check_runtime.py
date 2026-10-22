"""Run in the built image without credentials or network access."""

import ssl
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import certifi
import yaml
from PIL import Image

import photobot.main
from photobot.pipeline import pipeline
from photobot.config import Config


class RuntimeChecks(unittest.TestCase):
    def test_settings_keep_yaml_names_and_environment_aliases(self):
        settings = yaml.safe_load(Path("config/config.template.yaml").read_text())
        settings["telegram"] = {}
        settings["server"].pop("port")
        settings["users_db"] = {}
        environment = {"TELEGRAM_TOKEN": "123456:TEST_ONLY", "SERVER_PORT": "8099",
                       "BOT_MONGODB_ADDRESS": "mongodb://test.invalid/test_db",
                       "BOT_MONGODB_COLLECTION": "test_users"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment, clear=True):
            path = Path(directory) / "config.yaml"
            path.write_text(yaml.safe_dump(settings))
            config = Config(str(path))
        self.assertEqual(config.telegram.token.get_secret_value(), "123456:TEST_ONLY")
        self.assertEqual(config.server.port, 8099)
        self.assertEqual(config.server.base, "https://example.com/bot")
        self.assertEqual(config.users_db.address, "mongodb://test.invalid/test_db")
        self.assertEqual(config.users_db.collection, "test_users")

    def test_ca_bundles_distrust_compromised_hierarchies(self):
        blocked = {"emSign ECC Root CA - G3", "AAA Certificate Services"}
        for bundle in (ssl.get_default_verify_paths().cafile, certifi.where()):
            with self.subTest(bundle=bundle):
                self.assertIsNotNone(bundle)
                roots = ssl.create_default_context(cafile=bundle).get_ca_certs()
                self.assertTrue(roots)
                names = {
                    value
                    for root in roots
                    for rdn in root["subject"]
                    for name, value in rdn
                    if name == "commonName"
                }
                self.assertFalse(blocked & names)

    def test_photo_composition(self):
        source = Image.new("RGB", (8, 8), "white")
        frame = Image.new("RGBA", source.size, (255, 0, 0, 128))
        result = pipeline(source, frame)
        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.size, source.size)
        self.assertEqual(result.getpixel((0, 0)), (255, 127, 127, 255))


if __name__ == "__main__":
    unittest.main()
