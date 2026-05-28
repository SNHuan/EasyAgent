---
name: demo-workflow
description: 使用项目名工具和沙箱工具检查环境。
allowed-tools:
  - get_project_name
  - bash
  - write_file
  - read_file
---

# Demo Workflow

加载本 skill 后：

1. 调用 `get_project_name` 获取当前项目名。
2. 使用 `read_skill_file` 读取 `templates/note-template.txt`。
3. 使用 `write_file` 创建一个简短的 note.txt。
4. 使用 `read_file` 验证文件内容。
5. 如需格式化项目名，可以运行 `scripts/format_name.py`。
6. 简洁总结最终结果。
