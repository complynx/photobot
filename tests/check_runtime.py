"""Run in the built image without credentials or network access."""

import ssl
import unittest

import certifi
from PIL import Image

import photobot.main
from photobot.pipeline import pipeline


class RuntimeChecks(unittest.TestCase):
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
