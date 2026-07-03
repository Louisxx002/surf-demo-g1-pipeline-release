import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LlmPromptIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.pop("llm_server", None)
        cls.llm_server = importlib.import_module("llm_server")

    def test_chinese_prompt_sets_xjtlu_embodied_robot_identity(self):
        prompt = self.llm_server.build_prompt("zh")

        self.assertIn("西交利物浦大学校园智能语音机器人助手", prompt)
        self.assertIn("身份回答模板", prompt)
        self.assertIn("挥手", prompt)
        self.assertIn("仅在用户询问动作能力或发出动作请求时提及", prompt)
        self.assertNotIn("我有实体机器人身体", prompt)
        self.assertNotIn("没有实体手臂", prompt)
        self.assertNotIn("elderly companion", prompt)

    def test_english_prompt_sets_xjtlu_embodied_robot_identity(self):
        prompt = self.llm_server.build_prompt("en")

        self.assertIn("embodied campus voice robot assistant", prompt)
        self.assertIn("Xi'an Jiaotong-Liverpool University", prompt)
        self.assertIn("wave, hug, or greet", prompt)
        self.assertIn("Only mention gesture capability", prompt)
        self.assertNotIn("elderly companion", prompt)


if __name__ == "__main__":
    unittest.main()
