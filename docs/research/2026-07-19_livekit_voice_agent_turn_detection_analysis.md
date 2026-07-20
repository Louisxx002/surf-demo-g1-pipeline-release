# LiveKit Voice Agent 轮次检测与智能打断机制研究（初稿）

日期：2026-07-19  
研究范围：LiveKit Agents 的语音链路、turn detection、VAD、STT endpointing、adaptive interruption、false interruption 及其对 SURF2026 G1 Pipeline 的适用性。  
资料原则：只采用 LiveKit 官方文档、官方 GitHub 源码/README 和官方博客；本文不包含代码改动。

## 1. 结论摘要

附件文章的总体方向是正确的：实时语音 Agent 的难点不只是把 `STT -> LLM -> TTS` 串起来，还包括判断用户何时说完、机器人说话时是否允许用户打断、如何区分真正抢话与“嗯、对、好”等附和，以及误打断后如何恢复。

但文章把不同时期、不同层次的机制混在了一起，不能按文中的“两行配置”直接迁移到当前项目：

1. **当前 LiveKit 推荐的 Turn Detector 是音频模型**，直接分析原始音频中的语义、语调和韵律信号；旧版基于 STT 文本的 semantic turn detector 已被标记为 deprecated，并计划在 SDK 2.0 移除。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)；[旧版插件弃用说明](https://docs.livekit.io/reference/python/livekit/plugins/turn_detector/index.html)
2. **VAD、turn endpointing 和 interruption 是三件不同的事**。VAD 判断当前有没有语音；endpointing 判断用户这一轮是否结束；interruption 判断机器人正在说话时，新出现的用户语音是否应当中止机器人。[Turns 总览](https://docs.livekit.io/agents/logic/turns/)
3. **Adaptive interruption 不是无条件可用的本地功能**。它要求 LiveKit Cloud 部署或 dev mode、启用 VAD、非 realtime LLM，并且 STT 必须提供 aligned transcripts；某些区域缺少模型时会退化为普通 VAD 打断。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)
4. **`resume_false_interruption` 的能力边界较窄**。它是在一次疑似打断后，没有得到有效转写且等待超时，才尝试从中断点恢复；它并不能保证所有被误判的用户语句都自动恢复，也不能替代回声消除。[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)
5. **当前 SURF2026 Pipeline 不应立刻整体迁移到 LiveKit**。项目已有 ROS2、外置麦克风推流、自定义 VAD/ASR、HTTP LLM、Edge TTS、Unitree relay、灯光和机械臂动作链。完整迁移会同时改变媒体传输、会话状态、TTS 播放和动作取消机制。更稳妥的方向是先借鉴 LiveKit 的状态模型、事件与评测方法，再在隔离分支做 shadow prototype。

## 2. 附件文章逐项核验

### 2.1 “VAD -> STT -> LLM -> TTS 是流式链路”

**判断：基本正确，但描述过于简化。**

LiveKit Agents 确实提供实时媒体、STT、LLM、TTS 与 turn handling 的统一框架，Agent 会作为参与者加入 LiveKit room。[LiveKit Agents 概览](https://docs.livekit.io/agents/)；[LiveKit Agents 官方仓库](https://github.com/livekit/agents)

真实链路中还包含：输入音频流、VAD、转写事件、轮次确认、推测式 LLM 生成、语音合成、播放、打断和会话状态。各组件不一定由同一个模型完成，也不一定都在本地运行。

### 2.2 “STT 的 partial transcript 会提前送给 LLM”

**判断：需要修正。**

当前官方文档描述的是 **preemptive generation**：当 STT 已产生 final transcript、但 turn detector 尚未最终确认用户说完时，可以提前启动 LLM，以降低端点确认造成的等待。它不是简单地把任意 partial transcript 持续送进 LLM。[Agent audio 与 preemptive generation](https://docs.livekit.io/agents/multimodality/audio/)；[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)

当前版本中 LLM 的 preemptive generation 默认启用；TTS 默认不会同步提前启动，只有显式设置 `preemptive_tts=True` 才会进行推测式合成。推测输出若因上下文、工具调用或转写变化而失效，可能被丢弃，因此会增加 token 或合成资源消耗。[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)

### 2.3 “Semantic Turn Detector 同时分析 VAD 和 STT 文本”

**判断：符合旧版机制，不符合当前推荐机制。**

LiveKit 2024 年的官方博客介绍过一个基于文本的 end-of-turn transformer：它使用 final STT transcript 和最近对话上下文，动态缩短或延长 VAD 后的等待时间；当时模型约 135M 参数、主要支持英语。[官方博客：Using a transformer to improve end-of-turn detection](https://blog.livekit.io/using-a-transformer-to-improve-end-of-turn-detection)

当前推荐的 Turn Detector 已改为音频模型：直接编码原始音频，同时利用语义与声学/韵律信息，不再依赖 STT 文本来判断用户是否说完。当前 full 模型通过 LiveKit Inference 使用，`v1-mini` 可在本地 CPU 运行。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)

版本边界：

- 当前音频 Turn Detector 要求 Python SDK `>=1.6.1` 或 Node.js SDK `>=1.4.7`。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- 旧文本 detector 已弃用，并计划在 SDK 2.0 移除。[旧版插件弃用说明](https://docs.livekit.io/reference/python/livekit/plugins/turn_detector/index.html)
- 旧文或旧示例中的 `turn_detection="semantic"` 不能视为当前稳定 API。

### 2.4 “Adaptive interruption 能区分抢话和 backchannel”

**判断：机制真实存在，但依赖条件很多。**

Adaptive interruption 在 VAD 发现机器人说话期间出现用户音频后，使用声学信息判断这是明确打断，还是“嗯、对、好”等不应中止机器人的附和。它主要分析音频，而不是靠关键词文本分类。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

它只有在以下条件同时满足时才会按设计启用：

- Agent 部署到 LiveKit Cloud，或运行在有使用限制的 dev mode；
- VAD 已启用；
- 使用的 LLM 不是 realtime model；
- STT 支持 aligned transcripts；
- 当前区域能访问相应的模型。

条件不满足时，系统会回退到普通 VAD interruption。LiveKit Inference 提供的 STT 支持 aligned transcripts；第三方 STT 插件需要检查 `stt.capabilities.aligned_transcript`。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

语言边界：官方称模型面向多语言设计，但也明确提示英语表现可能更好。因此中文的“嗯、对、好、等一下、不对”等必须用真实场景数据验证，不能因为英文演示有效就直接假定中文同样可靠。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

### 2.5 “False interruption 可以自动恢复”

**判断：正确，但仅在特定状态下生效。**

普通 VAD interruption 可能因为短噪声或非语音声音暂停 Agent。若 `false_interruption_timeout` 时间内没有得到有效用户转写，LiveKit 可将其判为 false interruption；`resume_false_interruption=True` 时尝试从暂停处恢复 Agent 的语音。[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)；[Turn tuning 文档](https://docs.livekit.io/agents/logic/turns/tuning/)

边界包括：

- 它需要先等待 timeout，恢复前天然存在一段停顿；
- 用户已经产生可接受转写时，不再属于“没有 transcript 的误打断”这一简单情形；
- 输出系统必须真正支持暂停、取消或恢复，才能达到自然效果；
- 它不会解决扬声器回灌到麦克风造成的全部 self-speech 问题，也不是 AEC 的替代品。

### 2.6 “只需两项配置即可得到自然打断”

**判断：对当前版本具有误导性。**

当前 API 使用嵌套的 `TurnHandlingOptions` 和 interruption 配置。官方 GitHub 源码显示，旧的顶层参数 `min_interruption_duration`、`min_interruption_words`、`resume_false_interruption` 等已进入迁移/弃用路径，会转换到新的 `turn_handling` 配置中。[AgentSession 当前源码](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)

当前形式更接近：

```python
turn_handling=TurnHandlingOptions(
    turn_detection=inference.TurnDetector(),
    interruption={"mode": "adaptive"},
)
```

即使配置正确，模型可用性、SDK 版本、STT 时间戳能力、地区、网络和播放端是否支持暂停恢复，仍会决定实际效果。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

## 3. 关键机制的准确边界

### 3.1 VAD

VAD 只判断某段音频是否像人声。它不知道一句话在语义上是否完成，也不能可靠区分用户抢话、附和、机器人自声、环境广播或附近其他人的讲话。LiveKit 将 VAD 作为多种 turn mode 的基础信号，但不会把它等同于完整的轮次检测。[Turns 总览](https://docs.livekit.io/agents/logic/turns/)

### 3.2 STT endpointing

支持 endpointing 的 STT 可以给出“当前转写可能结束”的信号。LiveKit 允许只使用 STT endpointing 判断轮次结束，同时继续使用 VAD 处理 interruption。[Turns 总览](https://docs.livekit.io/agents/logic/turns/)

它的优点是实现简单，缺点是延迟与准确率受 STT 提供商、final transcript 时机和网络影响。STT endpointing 也不等于理解用户语义是否完整。

### 3.3 Audio Turn Detector

当前推荐的音频 Turn Detector 直接从音频中综合语义、语调、停顿和韵律，目标是比固定静默阈值更自然地判断轮次结束。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)

默认端点等待会随 detector 结果在最短与最长范围内变化。当前文档给出的 detector 默认值是 `min_endpointing_delay=0.3s`、`max_endpointing_delay=2.5s`；不使用该 detector 时常见默认值是 `0.5s` 与 `3.0s`。Silero VAD 的 `min_silence_duration` 建议不低于 `0.25s`，默认约 `0.55s`。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)

`unlikely_threshold` 越低越倾向尽快结束，越高越倾向耐心等待。降低阈值能减少延迟，但会增加长句中间停顿被提前截断的风险。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)

### 3.4 Interruption

Interruption 只发生在 Agent 正在输出时。普通 VAD 模式达到最小时长/词数后即可打断；adaptive 模式则尝试判断这次语音是不是明确抢话。[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)

常用参数的真实含义：

| 当前参数 | 当前默认值 | 作用与代价 |
|---|---:|---|
| `interruption.enabled` | `True` | 是否允许用户中断 Agent |
| `interruption.mode` | 依环境决定 | `adaptive` 受 Cloud、STT 与地区约束；不可用时回退 `vad` |
| `interruption.min_duration` | `0.5s` | 越小越快，但短噪声更容易误触发；Python 用秒，Node.js 用毫秒 |
| `interruption.min_words` | `0` | 只有启用 STT 时有效；提高可过滤短附和，但会等待转写并错过短纠正词 |
| `interruption.false_interruption_timeout` | `2s` | 无有效转写时等待多久判定误打断；设为 `None` 会关闭该检测 |
| `interruption.resume_false_interruption` | `True` | 判定误打断后尝试恢复 Agent 输出 |
| `interruption.discard_audio_if_uninterruptible` | `True` | Agent 不允许打断时是否丢弃期间用户音频 |
| `interruption.backchannel_boundary` | `(1.0, 1.0)`，仅 Python | 为 adaptive 模式补偿回溯音频和 STT 时间戳边界误差 |

参数来源：[Turn handling 参数参考](https://docs.livekit.io/reference/agents/turn-handling-options/)；[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

### 3.5 Realtime model 的特殊情况

如果使用原生音频 realtime model，并由模型服务端负责 turn detection，多数客户端 interruption 配置会被忽略。因此不能把适用于传统 `STT -> LLM -> TTS` pipeline 的参数原样套到 realtime API。[Turns 总览](https://docs.livekit.io/agents/logic/turns/)

## 4. 对当前 SURF2026 G1 Pipeline 的映射

当前项目不是 LiveKit Agent。它大致是：

```text
机器人外置麦克风/beamformer
  -> UDP 单声道音频
  -> 自定义 VAD、录音窗口和 ASR
  -> ROS /audio_msg
  -> 自定义唤醒、连续会话、self-speech 与 session 状态
  -> 本地 HTTP LLM 服务
  -> Edge TTS 生成 WAV
  -> Jetson relay 播放、灯光、机械臂动作
```

项目已经具备部分同类能力：

- VAD 静默收束与最大录音时长保护；
- 唤醒后首轮和连续追问窗口；
- UI 手动打断与再次听取；
- 基于事件日志的 ASR、LLM、TTS、播放和动作耗时；
- self-speech 过滤与会话关闭逻辑。

但它与 LiveKit 的关键差异是：

1. **TTS 是完整 WAV 文件经 relay 播放。** LiveKit 的 false-interruption resume 假设播放端能暂停并从中断位置恢复；当前 relay 是否能从准确采样位置恢复尚未建立。
2. **动作与 TTS 是两个执行对象。** 打断语音时还要停止或收回 Unitree 手臂。LiveKit 不知道机器人动作是否已执行、能否撤销，也不会自动处理 `ret=3102` 等机器人状态错误。
3. **音频有真实回灌和机器人噪声。** Adaptive interruption、VAD 和 turn detector 都不是 AEC。当前外置麦克风、机器人扬声器、beamformer 方向性和环境噪声仍需独立处理。
4. **网络依赖更敏感。** 当前 DeepSeek、WSL、Jetson relay 已存在网络与服务状态变量；引入 Cloud detector 会增加另一条实时网络依赖。
5. **中文 backchannel 必须单独验证。** 当前主要交互是中文，“嗯、对、好、等一下、不对”既可能是附和，也可能是真打断，不能直接采用英文默认行为。

因此，LiveKit 的价值更适合定位为：**状态机设计参考、可观测性参考和候选检测器**，而不是立即替换现有 pipeline。

## 5. 可选接入路线

### 路线 A：只借鉴设计，不引入 LiveKit 运行时（推荐）

保留现有链路，将打断拆成：

- `AGENT_SPEAKING`
- `INTERRUPT_PENDING`
- `TRUE_INTERRUPTION`
- `FALSE_INTERRUPTION`
- `RESUMING` 或 `LISTENING`

同时记录 VAD 起点、转写到达、打断确认、播放停止、动作停止和恢复结果。这条路线改动最小、离线可测、不会增加 Cloud 依赖。

### 路线 B：隔离分支做 LiveKit shadow detector

在不控制真实机器人行为的前提下，将相同音频送入 LiveKit detector，仅记录它认为的 turn end、backchannel 和 interruption，与现有判断对比。推荐实验分支名：`experiment/livekit-turn-taking-shadow`。

注意：

- full audio Turn Detector 依赖 LiveKit Inference；本地可测试 `v1-mini`。[当前 Turn Detector 文档](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- adaptive interruption 仍有 Cloud/dev mode 和 aligned transcript 限制，不能因为 `v1-mini` 可本地运行就推断 adaptive interruption 也完全本地可用。[Adaptive interruption 官方文档](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)

### 路线 C：完整迁移到 LiveKit AgentSession（暂不推荐）

需要重构：音频传输、Agent room、STT/LLM/TTS provider、机器人 relay 输出、动作取消、ROS bridge、UI 控制和部署。其工程量与风险远高于单独改善 turn-taking，而且会影响当前已跑通的真机链路。

## 6. 建议的验证计划（不改代码）

### 阶段 0：建立标注样本

从真机采集以下场景，每类至少包含中文和英文：

- 正常短句、长句、中间自然停顿；
- 机器人话音刚落立即追问；
- 机器人说话中明确抢话：“等一下”“不对”“停”；
- backchannel：“嗯”“对”“好”“我在听”；
- 机器人扬声器回灌；
- 环境谈话、咳嗽、碰撞、机器人风扇/电机噪声；
- 唤醒词重入与 UI 手动打断。

### 阶段 1：确定可量化指标

- end-of-turn 延迟；
- 长句误截断率；
- 首字/首词丢失率；
- 真打断响应延迟与漏检率；
- backchannel 误打断率；
- self-speech 误识别率；
- false interruption 恢复成功率；
- TTS 与机械臂是否均成功停止。

### 阶段 2：Shadow 对比

现有规则、LiveKit 本地 `v1-mini` 和可用时的 full detector 只输出判断与指标，不控制机器人。达到可接受准确率后，才允许 detector 影响真实 session。

### 阶段 3：受控真机试验

- UI 手动打断和唤醒词打断保留为最高优先级硬打断；
- adaptive 判断只在 TTS 播放期间生效；
- Cloud/网络/模型失败时明确回退到现有 VAD 或不打断模式；
- 所有新行为均通过配置开关启用，可一键回到当前验证版本。

## 7. 最终建议

1. **不要现在整体迁移 LiveKit。** 当前项目的核心风险在真实机器人播放、动作、回声和网络，不只在 turn detector。
2. **下一步最有价值的是建立真实中文测试集和 shadow evaluation。** 先证明 detector 能在本项目的机器人噪声、中文附和和快速追问场景中优于现有逻辑。
3. **若启动实验，必须单独分支并默认不控制真机。** 建议先测本地 `v1-mini` 的 turn endpointing；adaptive interruption 另行评估 LiveKit Cloud、数据合规、网络稳定性和 aligned STT 能力。
4. **把“打断”和“误打断恢复”作为两个独立功能。** 当前完整 WAV 播放和机械臂动作使恢复远比暂停一段流式 TTS 更复杂，不能只增加 `resume_false_interruption=True` 就宣称完成。
5. **保留现有 UI 手动打断。** 在自动判断达到足够可靠之前，手动按钮与再次唤醒是最可控的安全兜底。

## 8. 第一方资料索引

- [LiveKit Agents 官方概览](https://docs.livekit.io/agents/)
- [LiveKit Agents 官方 GitHub 仓库](https://github.com/livekit/agents)
- [Turns overview](https://docs.livekit.io/agents/logic/turns/)
- [Audio Turn Detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)
- [Adaptive interruption handling](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/)
- [Turn handling options reference](https://docs.livekit.io/reference/agents/turn-handling-options/)
- [Turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/)
- [Agent audio and preemptive generation](https://docs.livekit.io/agents/multimodality/audio/)
- [Agent events and interruption events](https://docs.livekit.io/reference/agents/events/)
- [旧文本 Turn Detector 弃用说明](https://docs.livekit.io/reference/python/livekit/plugins/turn_detector/index.html)
- [官方博客：Using a transformer to improve end-of-turn detection](https://blog.livekit.io/using-a-transformer-to-improve-end-of-turn-detection)
- [当前 AgentSession 源码与旧参数迁移](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_session.py)

