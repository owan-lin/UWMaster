# UWMaster 项目介绍与架构交接

记录日期：2026-10-06，时区 America/Los_Angeles。本文供接手本项目的 agent 阅读；以当前工作区、最新用户指令及 TASK_RULES.md 为准，不用旧对话恢复已经更正的规则。

## 1. 项目目标与用户偏好

UWMaster 是 Owan 的本地 UW 学期课程面板，统一管理需要完成的课业及需要到场的重要事项。原方案使用 Microsoft To Do，已被用户取消，改为独立本地软件。

- 两个面板：待办按时间排序；日历按周／月展示同一批任务。
- 包括 GPA 计分任务、CR/NC 通过要求，以及用户要求纳入的必做课前材料。具体纳入规则先读 TASK_RULES.md。
- 标题必须简短而明确，例如 `Pre-class Material 2`、`HW1`、`Paper Quiz 0`。不要只写泛称 `Participation`，也不要把阅读主题、动作清单和要求塞进标题；详细内容放在任务详情。
- 截止时间、个人上课时间、课前完成提醒、平台显示的截止标签必须区分。不能将个人准备目标伪装成官方提交截止。
- 中文界面；使用西雅图时间，跨夏令时与用户旅行时仍应按 Seattle 显示。
- 不猜测截止、分值、权重或来源状态。来源矛盾、未发布及无法登录的情况要明确标注。
- 保留用户完成状态与备注。已评分不自动等于用户标记完成。
- 用户此前指定：管理协调 GPT-6.1-sol / medium；编码 GPT-5.6-terra。仅在可配置时设置，不虚称切换。日常修改无需扩大为多 agent 工作。

## 2. 工作区和版本状态

当前项目目录：`D:\AcademicProgress&Resources_UniversityofWashington\UWMaster`。实际目录名包含普通 `&`，不是 `&amp;`。PowerShell 使用带引号的路径或 `-LiteralPath`。

GitHub 私有仓库：https://github.com/owan-lin/UWMaster ，默认分支 `main`，remote 为 `origin`。初版提交 `f1ba3ee`；本对话最后一笔应用修改提交为 `c2c73e3`（缩短课前材料标题）。

**交接时本地已经有其他对话的未提交改动**：README、前端、后端静态资源白名单、启动器、测试及快照；还有 TASK_RULES.md 和 assets/。因此远程旧版并不完整代表当前工作区。本次文档提交不代替这些改动的验收与提交。接手先运行 `git status --short` 和 `git diff`，不要 reset、checkout 或覆盖其他对话的工作。

旧初版目录 `C:\Users\owanl\Documents\Codex\2026-10-06\ren\outputs\uw-course-monitor` 仅为历史副本。运行服务和每周更新路径此前已经切换到 UWMaster，不要继续在旧目录开发。

## 3. 当前课程与分类

交接时读取的快照为 Autumn 2026，4 门课程、75 个任务；这是当前文件统计，不是保证学期完整覆盖。快照顶层 `checked_at` 仍为首次核查时间，不能据此声称所有后续来源都重新检查过。

| course_id | 课程／个人 section | 成绩形式 | 主要来源 |
| --- | --- | --- | --- |
| math126 | MATH 126 C / CC | GPA | Canvas 1920200、数学官网 PDF、Gradescope、WebAssign、Ed |
| cse123 | CSE 123 B / BG | GPA | 课程官网、Syllabus、Ed 106640、Canvas 1916719 |
| cse190 | CSE 190 B | CR/NC | 课程 Google Site、Canvas 1916754、Ed 107518 |
| cse391 | CSE 391 A | CR/NC | 课程官网、Syllabus、Gradescope、Ed 107766 |

TASK_RULES.md 记录了另一对话的最新用户更正：CSE 123 lecture 非必到，不纳入必做事项；PreLect / Pre-Class Work 按计分任务纳入，未知分值不推测；section、quiz、project 的规则未变。旧对话曾按公开 Syllabus 把 Pre-class 视为不直接评分并纳入 lecture，两者已经被本地规则修正。**不要基于旧聊天或旧远程快照静默恢复旧分类**；新的来源冲突应记录证据并核实。

非必到 lecture 参考数据目前存于忽略的 `data/cse123_optional_lectures.json`；新克隆不会自动拥有这个本地文件。

当前课前材料：

- `ed-106640-preclass-184333` → `Pre-class Material 1`，Ed 曾明确显示整份已完成。
- `ed-106640-preclass-184530` → `Pre-class Material 2`，详情保留编译／运行时阅读、Interfaces 复习、Abstract Classes 阅读、两个概念检查及 Birds! 编程练习。
- 第 2 份的个人 B 班课前提醒为 10/07 11:30；Ed 显示的截止标签为 10/07 13:30，两者在详情分别说明。
- 浏览材料页面可能使 Ed 标记某一页完成；不能把一页完成当作整份材料完成，也不要代用户作答或提交。

## 4. 技术架构

无前端框架、无构建步骤、无数据库。后端仅使用 Python 标准库；前端是静态 HTML / CSS / JavaScript。

```text
用户浏览器（localhost）
    │ fetch /api/data、状态保存、导入、ICS
    ▼
server.py / ThreadingHTTPServer（127.0.0.1:8765）
    ├── snapshot.json              课程来源快照
    ├── data/user_state.json       用户完成状态与备注
    └── data/history.json          导入变更记录

Codex 浏览器核查 → work/新快照.json → import_snapshot.py
                                      └→ 合并写入 snapshot.json
```

| 文件 | 职责 |
| --- | --- |
| index.html | 页面结构、工具按钮、任务详情和历史 dialog 容器 |
| app.js | 数据读取、筛选／搜索、课程切换、待办、周／月日历、详情、备注与完成保存、导入／备份／ICS |
| style.css | 布局、响应式样式和当前 UW 品牌风格 |
| assets/ | 本地校园图、logo、字体；来源记录见 assets/SOURCES.md；个人项目不是 UW 官方应用 |
| server.py | 静态文件、HTTP API、校验、快照合并、状态覆盖、原子写入、变更比较、ICS |
| snapshot.json | 唯一课程核查快照，已纳入 Git；不要把凭证写入其中 |
| import_snapshot.py | 命令行校验及合并新快照，与 HTTP 导入复用后端函数 |
| start.cmd / start.ps1 | 寻找 Python、启动隐藏服务、健康检查、打开浏览器、保存日志 |
| tests.py | 临时端口后端测试；当前还包含静态资源白名单检查 |
| TASK_RULES.md | 最新课程纳入／分类规则，更新快照前必读 |

后端每次读取 `/api/data` 时重新读取磁盘快照，再叠加用户状态；修改数据后刷新页面即可。修改 Python 后端代码则要重启服务，前端没有自动热更新。

## 5. 数据模型

Schema 当前为 `schema_version: 1`。完整样例直接查看 snapshot.json。

| 层级／字段 | 含义 |
| --- | --- |
| term | id、name、start、end、timezone、owner |
| courses[] | id、code、section、title、grading、policy、url、canvas_url、status、coverage[] |
| courses[].coverage[] | 来源 name / url，verified / blocked / pending 等状态与核查 note |
| tasks[].id | 稳定来源 ID；重复核查继续用相同 ID，避免丢失个人状态 |
| course_id / title / original_title | 关联课程、简短显示标题、来源原始标题 |
| kind | homework / quiz / exam / project / participation / class / extra_credit / preparation |
| due / end | ISO 时间含 UTC offset，或只有日期的 YYYY-MM-DD；未知截止用 null，不补造时间 |
| available_from | 发布／开放日期；不是截止 |
| time_basis / platform_due_label | 区分个人课前完成目标和平台原始时间标签 |
| certainty | verified / tentative / needs_confirmation |
| grade_impact / points / weight | 计分／通过影响与已知分值权重 |
| source_url / source_note / description | 证据入口、核查说明、具体要完成的内容 |
| source_status / score / checked_at | 来源状态、已返回分数、核查时间，不代替用户状态 |
| user_completed / user_note | GET /api/data 叠加生成，真正保存在 data/user_state.json |

当前校验检查学期必要字段、唯一 ID、课程关联、标题及 due 格式；并未完整校验所有扩展字段、end、时区或业务规则。核查 agent 仍需验证来源和时间精度；带时刻的数据应明确包含 offset。

## 6. API 与持久化

| 方法／路径 | 行为 |
| --- | --- |
| GET /api/data | 快照叠加个人完成状态与备注 |
| GET /api/history | 导入变更历史 |
| GET /api/ics | 下载已核实、未完成、具有日期的事项；排除来源明确 completed 的项目 |
| POST /api/task-state | `{id, completed: bool, note: string}`，备注上限 4000 字符 |
| POST /api/import | `{snapshot: ...}`，校验、合并、保存、记录变更 |

写请求需要 `Content-Type: application/json` 和 `X-UW-Course-Panel: local-ui`，并通过 localhost Host / Origin 检查；请求体上限 2 MiB。服务仅监听 127.0.0.1，当前静态访问采用文件白名单，包括已列出的 assets。没有 UW / Ed / Canvas 凭证存储或登录 API。

写文件使用临时文件和 `os.replace`，并保存前一份 `.bak`。线程内操作有 RLock；它不是跨进程文件锁，避免同时进行 CLI 导入和 HTTP 导入。

**合并规则特别重要**：同学期按 ID 更新，新快照遗漏的旧任务仍保留；不同 term.id 则换学期。因此“新快照不列某任务”不等于删除。移除不应纳入的任务时，需要明确的数据迁移／移除方案，不能仅依靠普通导入，也不能无差别清空用户状态。

历史比较目前只跟踪新增／移除以及 due、title、certainty、points、weight 的变化；description、source_status 等变化不一定产生 history 记录。状态按 task ID 保存，换学期 ID 应防止碰撞。

ICS 有时刻的事件转为 UTC；有 end 时写 DTEND；日期型事项为全天；包含课程代码、标题、来源 URL。待确认、暂定、无日期和用户已完成项目不导出。源码仍是轻量实现，后续增加字段或复杂文本时要实际检查生成文件。

## 7. 启动与验证

在项目根目录运行：

```powershell
.\start.cmd
# 或直接启动
& 'D:\DevTools\Python\pythoncore-3.14-64\python.exe' server.py
```

打开 http://127.0.0.1:8765/ 。start.ps1 会检查服务响应，已有服务正常时直接打开页面；启动失败查看 data/server-error.log。固定生产端口 8765，CLI 不支持另一个生产端口。

注意已有监听进程可能仍运行旧 Python 代码。先确认进程身份／命令，再重启自己的服务；不要因为端口被占就杀未知进程。

后端验证：

```powershell
& 'D:\DevTools\Python\pythoncore-3.14-64\python.exe' -X utf8 tests.py
```

从项目根目录执行。测试用随机本机端口和 `_test_runtime/`，不要指向生产 data/；运行前确认临时路径位于项目内。沙箱可能阻止本机 socket，需要按工具权限流程执行，不能把网络限制当成应用故障。

初版曾验收备注刷新保留、完成勾选持久化、月历导航、Seattle 日期和 ICS 下载。交接时的新 UI／assets／测试改动来自其他对话，本文没有重新运行这些改动的测试，不将旧验收冒充新验收。

## 8. 每周核查与聊天自动化

软件本身没有定时爬虫。现有 Codex heartbeat 自动化 ID 为 `uw`，名称“每周更新 UW 课程监控面板”，读取时仍 ACTIVE：每周一 Seattle 09:00，从 2026-10-12 开始，项目路径已指向 UWMaster。

它仍绑定本旧对话 `01a112eb-fde8-7043-95e0-562f6e07c119`，不是随仓库安装的 Windows 定时任务。用户已说明本对话到此结束，剩余工作在其他项目对话完成；**接手需要安排自动化归属的迁移／更新，不能假定新对话自动继承**。本次文档工作未改变自动化启停状态。

读取时自动化 prompt 还含旧的 Pre-class“不计分”等历史分类，未引用最新 TASK_RULES.md。后续维护应先读取最新规则并同步自动化 prompt，避免周一恢复旧分类；不要新建重复任务来绕开迁移。

每次核查流程：

1. 先读 TASK_RULES.md、当前 snapshot.json 和本地个人状态；核实当学期 MyUW 课程／section。
2. 逐课读 Syllabus、官网、Canvas assignments / quizzes / modules / announcements，并沿真实课程链接核查 Ed Lessons / Discussion、Gradescope、WebAssign。
3. 收录真正已发布的任务和已知日历；任务标题简短，内容、分值、原始时区、链接和证据放详情。无日期事项明确待确认。
4. 记录每个来源覆盖状态；无法登录或访问的源标部分核查。不索取密码、验证码，不替用户提交课业。
5. 生成新快照到 work/，然后从项目根目录运行 `python import_snapshot.py --input work/新快照.json`。保留稳定 ID、完成状态、备注与历史。
6. 刷新面板核对待办与日历、来源说明、重要截止变更。没有变化或可行动结果时保持安静，仅通知重要变化、失败或用户需要处理的事项。

## 9. 已知限制与后续注意事项

- WebAssign / Cengage 曾显示 PAYMENT REQUIRED，未购买或开通，数学平台截止仍只能部分核查。
- MATH 126 的 12.4：Canvas 为 10/13 23:00，打印日历列在 10/08；待确认，不强行选一个当真。
- CSE 123 官网仍提示 under development；Projects / Computer Quizzes 正式截止或预约时段未完整核实，不能从跨行日历块推断截止。
- 当前 app.js 存在重复函数定义、后置覆盖和捕获阶段事件处理器；最后生效的定义才决定行为。重构前读完整文件，避免只改旧定义而实际页面不变。
- 日历以 Seattle 的日期加 UTC noon 作为日期载体；不要重新引入本地时区月首／日期偏移错误。前端“未来 7 天”还采用当前时刻窗口，并保留某些逾期作业；它不是纯七个自然日列表。
- 列表与日历共用筛选结果，未来 7 天筛选下导航到远期会缺少事件；先用全部学期查看远期。
- 已完成筛选主要按 user_completed；来源 completed / scored 的处理不同。不要混同“已评分”“Ed 已完成”“用户已勾选”。
- 尚无任务删除／归档 API、独立采集器、跨设备同步、可靠离线调度或完整状态迁移机制。
- 后端改动重启，数据／前端改动刷新；确认看到实际结果再报告完成。

## 10. 接手顺序与 Git 边界

先读 AGENTS.md → 本文 → TASK_RULES.md → README.md，再检查 git status / diff 和当前快照。根据用户在新对话的请求推进，不把本文的已知限制自动扩展为未经请求的大改造。

Git 可保存代码、文档和课程快照；data/、work/、日志、.bak、缓存和 .env 被忽略。私有仓库的 snapshot.json 含个人课程信息，不改为公开，不提交登录凭证、个人笔记或运行日志。

存在其他对话并行改动时，只提交自己的文件／改动，不使用 `git add .`、不代别的 agent 验收或重置。用户已把后续任务交给其他项目对话，本旧对话不再承担后续开发。
