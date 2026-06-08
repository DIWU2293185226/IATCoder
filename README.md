<div align="center">

# iatcoder

**轻量、本地、有记忆的终端 coding agent**

iatcoder 跑在本地仓库里，接上一个模型 provider，就能读代码、跑命令、改文件、
保留运行证据，并把有价值的上下文沉淀成本地记忆。


---

## iatcoder 是什么

iatcoder 是一个本地终端里的 coding agent，运行在你的仓库上下文里。一次 agent 运行会被拆成几个可观察的部分：

- **provider profile**：决定调用哪个模型、哪个 endpoint、用什么协议。
- **context**：把系统提示、仓库信息、skills、记忆和最近对话装进 prompt。
- **tools**：文件读取、搜索、shell、写文件、patch、子 agent 都走统一工具协议。
- **approval / sandbox**：写操作和 shell 命令可以被审批或沙箱限制。
- **session / run evidence**：对话、事件流、trace、report 都写到本地 `.iatcoder/`。
- **memory / dream**：把 daily log 整理成长期 topic，下次 session 可以继续用。

iatcoder 关注本地 coding agent 的工程边界：配置清楚、任务能续接、结果能复盘。
