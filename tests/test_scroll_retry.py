import ast
import unittest
from pathlib import Path


MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"


class ScrollRetryTests(unittest.TestCase):
    def test_scrolls_up_to_reveal_bottom_button(self) -> None:
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "scroll_up_once"
        )

        calls = [
            node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        ]
        call = next(call for call in calls if ast.unparse(call.func) == "pyautogui.scroll")
        self.assertEqual(ast.unparse(call.func), "pyautogui.scroll")
        self.assertEqual(ast.literal_eval(call.args[0]), 1)

        source = MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn('class_name != "Chrome_WidgetWin_1"', source)
        self.assertIn("win32gui.SetForegroundWindow(root)", source)
        self.assertIn('diag("A: 页面已向上滚动"', source)

    def test_interaction_step_delay_defaults_to_half_second(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('config.get("interaction_step_delay", 0.5)', source)

    def test_execution_requires_trigger_transition(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('state = "WAIT_EXECUTION_START"', source)
        self.assertIn('event="回复完成图标已变化，确认开始执行"', source)
        self.assertIn('event="回复完成图标未变化，重新执行发送"', source)
        self.assertIn('pyautogui.press("enter")', source)

    def test_starts_execution_check_without_ready_delay(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertNotIn("time.sleep(ready_delay)", source)
        self.assertNotIn("ready_deadline", source)
        self.assertIn('state="持续检测 ChatGPT 执行状态"', source)

    def test_round_limit_does_not_stop_automatic_relay(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn("current_round + 1", source)
        self.assertNotIn('event="达到安全轮次上限，自动联动停止"', source)
        self.assertNotIn("if current_round >= max_rounds", source)

    def test_bottom_button_is_detected_before_clicking(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('event="找到到底按钮"', source)
        self.assertIn('event="点击到底按钮"', source)
        self.assertIn('event="持续10秒未找到到底按钮，向上滚动一格后重试"', source)
        self.assertIn('scroll_up_once(targets["bottom"], interaction_step_delay)', source)
        self.assertNotIn('event="盲点到底"', source)

    def test_copy_retries_when_clipboard_does_not_change(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('event="点击后剪贴板未变化，重新识别并点击"', source)
        self.assertIn('state = "CHECK_COPY"', source)
        self.assertNotIn('error_code="CHATGPT_COPY_FAILED"', source)

    def test_missing_copy_button_scrolls_up_before_retry(self) -> None:
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('event="复制按钮未找到，向上滚动一格后继续检测"', source)
        self.assertIn('scroll_up_once(targets["copy"], interaction_step_delay)', source)


if __name__ == "__main__":
    unittest.main()
