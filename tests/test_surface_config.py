import unittest

from core import adapter


class SurfaceConfigTests(unittest.TestCase):
    def test_reads_chatgpt_web_surface(self) -> None:
        config = {"surfaces": {"chatgpt_web": {"input_box": {"click_x": 5}}}}

        self.assertEqual(
            adapter.resolve_target(config, "input_box")["click_x"], 5
        )

    def test_does_not_expose_executor_products_as_a_side_surfaces(self) -> None:
        self.assertEqual(adapter.endpoints(), ["chatgpt_web"])
        self.assertEqual(adapter.resolve_targets({}, "reasonix"), {})


if __name__ == "__main__":
    unittest.main()
