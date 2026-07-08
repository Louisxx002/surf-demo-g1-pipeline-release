import unittest

from text_command_policy import matches_command, normalize_command_text


class TextCommandPolicyTest(unittest.TestCase):
    def test_normalizes_spaces_and_punctuation(self):
        self.assertEqual(normalize_command_text("我 没 有 问 题 了。"), "我没有问题了")
        self.assertEqual(normalize_command_text("Bye, bye!"), "byebye")

    def test_matches_exact_chinese_terminate_command(self):
        self.assertTrue(matches_command("我 没 有 问 题 了", ["我没有问题了"]))

    def test_matches_terminate_command_inside_chinese_sentence(self):
        self.assertTrue(matches_command("小浦 我没有问题了 拜拜", ["我没有问题了"]))

    def test_matches_terminate_command_inside_english_sentence(self):
        commands = ["bye", "no more problems", "nothing else"]
        self.assertTrue(matches_command("i have no more problems bye bye", commands))
        self.assertTrue(matches_command("nothing else to ask i have nothing else to ask", commands))

    def test_does_not_match_unrelated_user_question(self):
        commands = ["bye", "没有问题了", "no more questions"]
        self.assertFalse(matches_command("介绍一下西交利物浦大学", commands))
        self.assertFalse(matches_command("can you introduce xjtlu", commands))


if __name__ == "__main__":
    unittest.main()
