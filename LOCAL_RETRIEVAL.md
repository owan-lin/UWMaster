# 本地课程检索 · 第一阶段

开发分支：`codex/local-course-retrieval`。本阶段使用本机 Codex 批处理接口，模型默认 `gpt-6.1-sol`，reasoning 为 medium。不依赖当前桌面聊天，也不继承聊天的浏览器工具。服务器阶段可替换 `local_codex.run` 适配器。

## 使用

1. 首次运行 `powershell -ExecutionPolicy Bypass -File .\setup_retrieval.ps1`。依赖安装到项目忽略的 `work/runtime-packages`；需要 Microsoft Edge。
2. 重启本地 UWMaster 服务，进入“课程检索”。本机 Codex 应已登录；可用性以实际执行结果为准。
3. 编辑并保存每门课的要求与 HTTPS 来源。选择来源，点击“连接课程浏览器”，在独立 Edge 会话中自行完成登录与 MFA。分别连接需要登录的平台；会话保存在忽略的 `data/course-browser`。
4. 点击“更新检索 · 本地 Codex”。先采集证据，再调用 Codex；有效变更自动应用，冲突暂缓。没有连接浏览器的来源明确显示未核查。
5. 在“检索助手”查看新增、字段变更、证据、失败来源与冲突。可选择来源值，或保留当前记录；保留争议日期不自动将其标成已核实。状态差异可标记已复核。历史记录刷新后仍可查询。
6. 可继续询问本次检索。对话只解释结果；规则修改需在编辑器保存后重新检索，不通过聊天直接改正式任务。

## 合并规则

### Gmail 邮件来源

进入课程检索页的“邮件检索”连接页（`/gmail.html`）。运行 `setup_gmail.ps1` 安装可选授权依赖并重启服务，然后按 [Google 官方说明](https://developers.google.com/workspace/gmail/api/quickstart/python) 启用 Gmail API、配置同意页面及自己的测试用户、创建桌面应用 OAuth 客户端，下载 JSON 并在连接页导入。点击授权，在 Google 页面选择自己的 Gmail 账号，最后勾选“更新课程时包含 Gmail 邮件”并保存。Google 测试模式下授权可能过期，失败时页面要求重新授权。

这是本地程序自己的 `gmail.readonly` 授权，不继承桌面聊天的 Gmail 连接。授权及客户端在忽略的 `data/gmail_*.json`；移除本地连接删除本地 token，在 Google 账号授权管理可进一步撤销。邮件原文、查询及读取状态保存在本地检索 SQLite，识别出来的任务、引用和来源链接会进入课程快照；匹配的正文交给本地 Codex 所用模型分析。

默认只匹配当前课程代码，可逐课设置 Gmail 搜索条件。每次重查学期开始前 30 天至今（含归档、不含垃圾箱及垃圾邮件），因此旧邮件中的未来任务能被发现。这个窗口之外、代码未匹配的邮件不保证覆盖；不自动扩大到整个邮箱。每门课最多 100 封，超过时明确部分核查；正文最多 40,000 字符，附件不读取并明确标注。网站与邮件共享证据校验、三方合并及冲突流程。不同邮件可能提到相同事项，AI 必须先匹配已有任务；无法确定身份暂缓。不会把已读或星标当作课业完成。没有邮件匹配与读取失败分别记录；未授权不冒充完成核查。检索期间修改范围或重新授权则拒绝本次应用。

- 发现新增任务从检索开始时间向后；日期型任务包含 Seattle 当日。未知截止的已发布任务可纳入待确认。
- 定向复核未来任务、未完成旧任务与待复核任务。既有未来任务的截止移到过去仍能合并。
- 已有任务用原 ID；新增任务用“学期＋课程＋稳定来源标识”生成 ID。疑似同名重复暂缓，不仅凭标题合并。
- 字段仅在有本次原文证据时修改。缺失、unknown、未明确撤销的 null 不清空已有数据。源码限制字段和日期格式，日期时间必须带时区。
- 不修改 `data/user_state.json`：个人完成状态与备注持续保留。来源完成、提交与评分分开保存；已评分不自动表示个人已完成。
- 比较开始时快照、提交时快照与新证据。期间同字段发生其他更新则暂缓该字段；规则版本变化则拒绝本次应用。
- 遗漏任务继续保留。来源明确取消或规则排除用 lifecycle 保存历史并退出默认待办与 ICS。手动任务／删除记录保持独立。
- 已完成任务内容变化或来源明确未完成时增加复核提醒，不取消勾选。冲突与提醒跨检索保留，已处理的相同提醒不重复打开。

## 数据与执行

- `retrieval_merge.py`：纯合并逻辑。
- `retrieval_flow.py`：持久任务、范围、证据、调用、三方合并、恢复与对话。
- `course_collector.py`：公开 HTML／PDF 与独立 Edge 会话。
- `local_codex.py`：stdin 输入、JSON Schema 输出、只读 sandbox、取消和超时。
- `retrieval_assistant.js/css`：进度、变更、冲突处理、历史、后续对话；待办页在无编辑／保存时刷新。
- `data/retrieval.sqlite`：运行证据、要求版本、合并报告与对话。`work/codex-retrieval`：调用输出及诊断。均不提交 Git。
- 持久保存写入意图后再替换快照，启动时恢复未完成保存；历史按事件 ID 去重。重启中断的采集／AI 调用不自动冒充完成。
- 每次只运行一个 AI 检索或对话。来源逐个读取；在课程路径内额外跟进最多 24 个相关页面，不能视为全站完整爬取。PDF 提取最多前 80 页；单来源上限 8 MB、文字上限 100,000 字符；总文字超过 500,000 字符时停止 AI 应用，要求缩小范围。达到上限明确标为部分读取。
- 连接浏览器仅表示会话可操作，不保证每个平台登录有效。浏览材料可能触发阅读标记，不替用户作答或提交。UW 学生 Canvas API token 限制仍适用，不通过复制 cookie 绕过 API 限制。

## 验证

`python -X utf8 tests_retrieval_merge.py`；`python -X utf8 tests_retrieval.py`；原 `tests.py`、`tests_beta.py` 和 `node tests_frontend.cjs`。

Gmail：`python -X utf8 tests_gmail.py --http` 使用隔离文件与模拟邮件，覆盖正文／附件标记、零匹配与失败、上限、网站与邮件冲突、个人状态保护、范围变更拒绝应用、OAuth 工作线程及本地接口；不连接真实邮箱。真实 Gmail 客户端配置与首次 Google 授权尚待用户完成。

本次实测：真实 Codex 结构化输出及隔离证据的 DDL 更新／个人状态保护、公开 CSE 391 页面与独立 Edge 读取、隔离网页的冲突采用和对话。未将测试结果写入正式课程快照；首次私人平台登录仍需用户完成。

官方接口参考：[Codex 非交互执行](https://learn.chatgpt.com/docs/non-interactive-mode)、[Playwright 持久浏览器](https://playwright.dev/python/docs/api/class-browsertype)。
