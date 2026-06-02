# Unitree G1 Reply Action Classifier Package

这是一个可分发给他人的独立项目包，用于演示：

```text
机器人 reply 文本
-> 通义千问 / Hugging Face / 本地规则分类
-> 映射到宇树 G1 官方手臂动作 action id
-> dry-run 展示未来要调用的官方 SDK 命令
```

## 目录结构

```text
arm_action_classifier/     动作分类器代码
docs/                      reply 文本与动作映射参考
unitree_sdk2/              宇树官方 SDK2
requirements.txt           Python 依赖
```

## 快速开始

```bash
cd unitree_g1_action_classifier_package
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

默认使用通义千问，需要设置 DashScope API Key：

```bash
export DASHSCOPE_API_KEY="你的APIKey"
```

运行分类：

```bash
cd arm_action_classifier
../.venv/bin/python arm_action_classifier.py "西交利物浦大学非常棒"
```

示例结果：

```text
鼓掌 clap -> action_id 17
```

## 后端说明

默认后端是通义千问：

```bash
../.venv/bin/python arm_action_classifier.py "你好，很高兴见到你"
```

也可以显式指定其他后端。本地关键词 / 规则后端不需要联网或 API Key：

```bash
../.venv/bin/python arm_action_classifier.py "你好，很高兴见到你" --backend qwen
../.venv/bin/python arm_action_classifier.py "你好，很高兴见到你" --backend hf
../.venv/bin/python arm_action_classifier.py "你好，很高兴见到你" --backend keyword
```

## 当前状态

- 已支持 16 个宇树官方 G1 手臂动作。
- 已支持 1 个 `无动作` 兜底。
- 默认 dry-run，不会连接或控制真机。
- 真机执行接口已预留：`--execute --network <网卡> --runner <官方示例程序路径>`。

## 真机说明

macOS arm64 本机不能直接编译当前 SDK 中的官方 runner，因为 SDK 包内只有：

```text
unitree_sdk2/lib/aarch64/libunitree_sdk2.a
unitree_sdk2/lib/x86_64/libunitree_sdk2.a
```

真机执行建议在官方支持的 Linux `x86_64` 或 `aarch64` 环境中编译 `unitree_sdk2/example/g1/high_level/g1_arm_action_example.cpp`。
