import unittest

from text_command_policy import select_terminate_ack_text


class TerminateAckLanguageTest(unittest.TestCase):
    def test_english_terminate_command_uses_english_ack(self):
        self.assertEqual(
            select_terminate_ack_text(
                "i have no more problems bye bye",
                "小浦退下了，有问题随时叫小浦。",
                "Xiaopu is standing by. Call me anytime.",
            ),
            "Xiaopu is standing by. Call me anytime.",
        )

    def test_chinese_terminate_command_uses_chinese_ack(self):
        self.assertEqual(
            select_terminate_ack_text(
                "我没有问题了拜拜",
                "小浦退下了，有问题随时叫小浦。",
                "Xiaopu is standing by. Call me anytime.",
            ),
            "小浦退下了，有问题随时叫小浦。",
        )


if __name__ == "__main__":
    unittest.main()

