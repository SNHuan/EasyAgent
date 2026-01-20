# Changelog

All notable changes to EasyAgent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] - 2026-01-20

### Added

- **`Message.reasoning_content` 字段**: `Message` 模型新增 `reasoning_content` 可选字段，用于存储 LLM 的推理/思考内容（如 Claude 的 `<think>` 块）。这使得 agent 的 memory 能够完整保留模型输出的所有信息。

- **`Message.from_response()` 类方法**: 新增从 `LLMResponse` 直接创建 `Message` 的便捷方法。自动将 response 中的 `content`、`reasoning_content` 和 `tool_calls` 映射到 Message 对应字段。

- **`Message.to_api_dict()` 方法**: 新增将 Message 渲染为 LLM API 所需 dict 格式的方法。在发送给 LLM 时，自动将 `reasoning_content` 以 `<think>...</think>` 格式合并到 `content` 中，确保对话上下文的完整性。

### Changed

- **`BaseAgent._build_messages()`**: 改用 `Message.to_api_dict()` 构建 API 请求消息，确保 `reasoning_content` 被正确渲染到对话历史中。

### Why This Matters

现代 LLM（如 Claude、DeepSeek）支持 "思考" 模式，会在 `reasoning_content` 字段返回推理过程。之前的实现只存储 `content`，导致：

1. 对话历史丢失了模型的推理上下文
2. 多轮对话时模型无法"回忆"之前的思考过程
3. 日志和 trajectory 无法完整记录模型行为

此次更新确保：

- ✅ Memory 完整存储 `content` + `reasoning_content`
- ✅ 发送给 LLM 时正确合并为完整上下文
- ✅ 支持 trajectory 导出完整的 thinking 记录

### Migration Guide

**无破坏性变更**。现有代码无需修改即可继续工作。

如需利用新功能：

```python
# 之前的写法（仍然有效）
msg = Message.assistant(content="Hello")

# 新写法：从 LLMResponse 直接创建（推荐）
response = await model.call_with_history(msgs)
msg = Message.from_response(response)

# 或者手动指定 reasoning_content
msg = Message.assistant(
    content="The answer is 42",
    reasoning_content="Let me think step by step..."
)
```

## [0.1.3] - 2026-01-15

### Added

- Auto-discover tools feature
- Tests for tool discovery

### Changed

- Updated README with sandbox and new features

## [0.1.2] - Previous releases

See git history for earlier changes.
