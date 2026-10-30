# Telegram AI Bot

Telegram AI 聊天机器人，自有品牌版本，支持 Agent 工具调用和每用户沙盒。

## 功能

- /start 邀请码、强制订阅频道（可关）、AI 对话、每日免费额度、邀请奖励
- /model 模型设置：用户自己切换模型，每用户单独保存，切换后自动新对话
- /new 新对话、/balance 我的额度
- Agent 工具：沙盒文件读写/列出/运行命令（每用户 users/<id>/ 目录，30 秒超时，禁危险命令）
- Agent 工具：只读查哪吒服务器（需在 config.yaml 里配 nezha.api_key）
- 输入 /model 后自动删除命令消息，点击切换模型后自动删除模型菜单消息

## 部署

1. cp config.example.yaml config.yaml，填 bot.token 和 ai.*
2. python3 -m venv venv && venv/bin/pip install -r requirements.txt
3. venv/bin/python bot.py
4. systemd 见 tg-ai-bot.service

## 配置

config.yaml 里只改 ai.base_url / ai.api_key / ai.model，不用改代码。
config.yaml、bot.db、users/ 不要提交到公开仓库，见 .gitignore。
