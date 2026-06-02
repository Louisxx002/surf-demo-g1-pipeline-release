# G1 Arm Action Classifier

这个小目录用于把大模型或语音识别得到的文本，分类到宇树 G1 官方手臂预置动作，并可调用官方 `g1_arm_action_example` 执行。

默认分类后端现在是通义千问 DashScope OpenAI-compatible API。Hugging Face 和关键词规则保留为备用后端。

当前输入按“机器人回复文本”理解，而不是只按用户命令理解。例如：

- `你好，很高兴见到你` -> 高位挥手
- `谢谢你，我很喜欢这个礼物` -> 比心
- `太棒了，你做得很好` -> 鼓掌
- `抱歉，这个我不能做` -> 拒绝摆手
- `我可以帮你查询天气信息` -> 无动作

官方动作来自：

- `unitree_sdk2/include/unitree/robot/g1/arm/g1_arm_action_client.hpp`
- `unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`

## 动作映射

| 分类标签 | 官方 action id | 官方动作名 |
|---|---:|---|
| 无动作 | -1 | `none` |
| 释放手臂 | 99 | `release arm` |
| 双手飞吻 | 11 | `two-hand kiss` |
| 左手飞吻 | 12 | `left kiss` |
| 右手飞吻 | 13 | `right kiss` |
| 举双手 | 15 | `hands up` |
| 鼓掌 | 17 | `clap` |
| 击掌 | 18 | `high five` |
| 拥抱 | 19 | `hug` |
| 比心 | 20 | `heart` |
| 右手比心 | 21 | `right heart` |
| 拒绝摆手 | 22 | `reject` |
| 举右手 | 23 | `right hand up` |
| x-ray | 24 | `x-ray` |
| 面前挥手 | 25 | `face wave` |
| 高位挥手 | 26 | `high wave` |
| 握手 | 27 | `shake hand` |

备注：

- `left kiss` 对应官方预置动作 `action id 12`，`right kiss` 对应官方预置动作 `action id 13`。
- `右手飞吻`、`右边飞吻`、`右侧飞吻`、`单手飞吻` 会命中 `right kiss`；未指定方向的 `飞吻`、`亲吻`、`亲亲`、`么么`、`么么哒`、`kiss`、`mua` 默认命中 `right kiss`。
- 只有明确说 `双手飞吻` 时，才会命中 `action id 11`。
- 日语和英语的常见别名也会命中对应动作，例如 `こんにちは`、`ハグ`、`ハイタッチ`、`握手しましょう`。

## 安装 Hugging Face 依赖

```bash
cd <repo-root>/deps/unitree_g1_action_classifier_package
python3 -m venv .venv
.venv/bin/python -m pip install transformers torch sentencepiece protobuf
```

## 使用通义千问分类

先设置百炼 / DashScope API Key：

```bash
export DASHSCOPE_API_KEY="你的APIKey"
```

然后运行：

```bash
cd <repo-root>/deps/unitree_g1_action_classifier_package/arm_action_classifier
../.venv/bin/python arm_action_classifier.py "西交利物浦大学非常棒"
```

默认会调用：

```text
model: qwen-plus
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
```

也可以显式指定：

```bash
../.venv/bin/python arm_action_classifier.py "你好，很高兴见到你" \
  --backend qwen \
  --qwen-model qwen-plus
```

程序会要求通义千问只从动作白名单里选择一个标签，并返回 JSON：

```json
{
  "label": "鼓掌",
  "confidence": 0.95,
  "reason": "这是一句赞美和认可的回复，适合搭配鼓掌。"
}
```

第一次使用 Hugging Face 后端会下载模型。中文 zero-shot 可先用默认模型 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`：

```bash
../.venv/bin/python arm_action_classifier.py "给我鼓个掌" --backend hf
../.venv/bin/python arm_action_classifier.py "抱一下" --backend hf
../.venv/bin/python arm_action_classifier.py "和我击个掌" --backend hf
```

如果本机暂时没有模型或网络，可以先用关键词后端验证：

```bash
../.venv/bin/python arm_action_classifier.py "抱一下" --backend keyword
```

## 真机执行

先编译官方 SDK 示例，生成 `g1_arm_action_example`。然后执行：

```bash
../.venv/bin/python arm_action_classifier.py "给我鼓个掌" \
  --backend hf \
  --execute \
  --network eth0 \
  --runner ../unitree_sdk2/build/bin/g1_arm_action_example
```

执行命令等价于：

```bash
../unitree_sdk2/build/bin/g1_arm_action_example --network eth0 --id 17
```

## 当前本机验证状态

当前 macOS `arm64` 本机已经验证：

- Hugging Face / Torch 依赖已安装到项目 `.venv`。
- `--backend hf` 可以实际加载模型并完成分类。
- 对常见明确口令，会使用 `hf+keyword` 或 `keyword_after_low_confidence_hf` 保证安全命中。
- 默认不执行真机动作，只输出将要执行的官方命令。

官方 C++ runner 尚未在这台 Mac 上编译成功，因为 SDK 当前只包含：

```text
unitree_sdk2/lib/aarch64/libunitree_sdk2.a
unitree_sdk2/lib/x86_64/libunitree_sdk2.a
```

没有 macOS `arm64` 对应的 `libunitree_sdk2.a`。真机执行建议在官方支持的 Linux `x86_64` 或 `aarch64` 环境编译 `g1_arm_action_example`。

## 安全建议

- 未连接真机时不要加 `--execute`，默认只 dry-run。
- `release arm`、`reject`、`hug`、`high five` 等动作要保证机器人周围没有人和障碍物。
- 如果分类置信度低于阈值，程序不会执行动作。
- 默认执行阈值是 `0.8`；`release arm` 只允许明确“释放/复位/放松/收回”等口令触发。
- `无动作` 的 action id 是 `-1`，不会调用官方 SDK，用来处理“不应该动”或无法表达的文本。
