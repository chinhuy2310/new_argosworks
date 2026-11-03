import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from utils.image_optimizer import ImageTooLargeError, optimize_and_save_file


class TestImageOptimizerSafety(unittest.TestCase):
    def test_rejects_images_over_pixel_budget(self):
        fake_image = MagicMock()
        fake_image.size = (10000, 10000)
        image_context = MagicMock()
        image_context.__enter__.return_value = fake_image
        image_context.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, "oversized.png")
            with patch("utils.image_optimizer.Image.open", return_value=image_context):
                with self.assertRaises(ImageTooLargeError):
                    optimize_and_save_file(b"not-a-real-image", target, max_pixels=1_000_000)
            self.assertFalse(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
