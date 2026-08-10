# 贡献与验证

## 变更原则

- 保持改动小且可审查；不要顺手重构无关文件。
- 自动化仍应只通过 UI、OCR、系统音频和常规输入与游戏交互。
- 不要提交用户日志、截图、配置、账号信息、密钥或个人路径。
- 涉及战斗 planner、战斗状态、声音捕获或用户数据兼容性时，补充相应测试并说明风险。

## 文档贡献

- 将面向用户的说明放在“开始使用”“功能”或“指南”。
- 将 API、架构和实现说明放在“开发”。
- 新页面必须添加到根目录 `mkdocs.yml` 的 `nav`，否则不会出现在网站导航中。
- 使用相对 Markdown 链接；提交前运行严格构建检查断链和配置错误。

```powershell
.\.venv\Scripts\python.exe -m mkdocs build --strict
```

## 代码验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "*.py"
```

请在提交说明中写明已运行的验证，以及因环境限制未运行的验证。
