# 飞书文档 Skill — 开发日志

## Phase 1: MVP — 核心文档操作

### 2026-02-28 Session 1: 项目初始化 + 核心实现 ✅

#### 任务拆解
- [x] 创建项目目录结构
- [x] 编写需求文档 (REQUIREMENTS.md)
- [x] 编写架构文档 (ARCHITECTURE.md)
- [x] 编写开发日志 (DEVLOG.md)
- [x] 实现 `md_to_blocks.py` — Markdown → 飞书 Block 转换器
- [x] 编写 `md_to_blocks` 单元测试 — 29 项全部通过
- [x] 实现 `feishu_doc.py` — 统一 CLI 入口
- [x] 编写 SKILL.md
- [x] 端到端测试
- [x] Git 初始化 + 首次提交 (3f0c81a)

#### 端到端测试结果

| 命令 | 结果 | 详情 |
|---|---|---|
| `create` | ✅ | 创建文档 `MVd5dJAmto0vuDxVEjvcxIBRnsg` |
| `write` | ✅ | 写入 14 个 blocks (标题/列表/代码/引用/分割线/待办) |
| `read --format raw` | ✅ | 正确读取纯文本内容 |
| `create-and-write` | ✅ | 一步创建 `WSrPds2S3ovK6BxvJ8xcwVMmn3c` + 写入 7 blocks |

#### 技术细节
- `lark-oapi` SDK 的 `from lark_oapi.api.docx.v1 import *` 可导入所有需要的模型类
- Block 写入使用 `document_block_children.create()`，block_id = document_id（根节点）
- 批量写入限制：每次最多 50 个 blocks
- 凭证加载：从 `~/.nanobot/config.json` 的 `channels.feishu` 数组中查找 `name="ST"` 的条目

---

## Phase 2: 批注（Comment）操作

### 2026-02-28 Session 2: 批注功能实现 ✅

#### 任务拆解
- [x] 更新需求文档 (REQUIREMENTS.md) — 新增 Phase 2 批注需求
- [x] 更新架构文档 (ARCHITECTURE.md) — 新增批注相关 API 和子命令
- [x] 实现 `list-comments` 子命令 — 列出文档批注
- [x] 实现 `reply-comment` 子命令 — 回复批注（HTTP API，SDK 缺 CreateReply）
- [x] 实现 `resolve-comment` 子命令 — 标记批注已解决
- [x] 实现 `add-comment` 子命令 — 创建新批注（HTTP API）
- [x] 实现 `add-member` 子命令 — 添加协作者
- [x] 更新 SKILL.md — 新增命令文档
- [x] 端到端测试：全部 5 个新命令测试通过
- [x] Git 提交

#### 端到端测试结果

| 命令 | 结果 | 详情 |
|---|---|---|
| `list-comments` | ✅ | 读取到 2 条批注，含回复内容和解决状态 |
| `reply-comment` | ✅ | 成功回复批注 7611786999179054038 |
| `resolve-comment` | ✅ | 成功标记批注为已解决 |
| `add-comment` | ✅ | 成功创建新批注 7611788674048527305 |
| `add-member` | (已在 session 前手动验证) | 通过 SDK CreatePermissionMember |

#### 技术细节
- `lark-oapi` SDK 缺少 `CreateFileCommentReply`，reply-comment 和 add-comment 使用 `requests` 直接调用 HTTP API
- 批注 API 均在 `drive.v1` 模块下，与文档内容 API（`docx.v1`）分属不同模块
- add-comment 需要 `reply_list.replies` 结构包裹批注正文，`quote` 为引用文本
- list-comments 返回的 reply content 是嵌套对象：`reply.content.elements[].text_run.text`

#### Bug Fix: md_to_blocks 段落间空行 (commit a822714)
- **问题**：Markdown 中两段纯文本之间的空行被忽略，飞书文档中两段紧贴
- **原因**：`markdown_to_blocks()` 中空行被直接 `continue` 跳过
- **修复**：空行在两个 text block 之间生成空 text block（前瞻判断下一个非空行是否为普通段落）
- **验证**：29 项单元测试全部通过 + 飞书文档端到端验证

---

## Phase 3: 覆盖写入 + 表格支持

### 2026-03-04 Session 1: 修复 write 覆盖 + 表格渲染

#### 问题背景
- 飞书 session `feishu.ST.1772584826` 中，AI 尝试 `--mode overwrite` 参数但不存在，每次失败后 fallback 到追加，导致文档内容重复 3 遍
- Markdown 表格语法被当作普通文本段落写入，飞书文档中无法渲染为表格

#### 任务拆解
- [x] 更新需求文档 (REQUIREMENTS.md) — 新增 Phase 3 需求
- [x] `feishu_doc.py` write 命令增加 `--mode` 参数（overwrite/append）
- [x] 实现 overwrite 逻辑：先获取文档子 block 列表，再批量删除，最后写入新内容
- [x] `md_to_blocks.py` 增加 Markdown 表格解析
- [x] `feishu_doc.py` 增加 table block 创建支持（两步：SDK创建空表格 → HTTP API填充cell）
- [x] 编写表格相关单元测试 — 9 项全部通过
- [x] 端到端测试：overwrite 模式 + 表格渲染
- [x] 更新 SKILL.md 文档
- [x] 更新 ARCHITECTURE.md（Phase 4 补齐时一并完成）
- [x] Git 提交 (6e425f8)

#### 端到端测试结果

| 命令 | 结果 | 详情 |
|---|---|---|
| `create-and-write` (含表格) | ✅ | 创建文档 `T4wrdlMsGo45y0x8FIscUAXGnyc`，5行3列表格正确渲染 |
| `write --mode overwrite` | ✅ | 清空原内容 + 写入新表格，内容完全替换 |
| `write --mode append` (默认) | ✅ | 向已有文档追加内容，不影响原内容 |

#### 技术细节
- 飞书表格 block_type=31，table_cell block_type=32
- 创建表格后 API 返回 `response.data.children[0].table.cells` 包含所有 cell block ID（flat 数组，行优先）
- SDK 的 `document_block_children.create` 写入 cell 时有 JSON 解析 bug（空响应），改用 HTTP API
- `_clear_document()` 使用 `BatchDeleteDocumentBlockChildren` API，start_index=0, end_index=N
- 代码重构：`_write_blocks_to_doc()` 统一处理 regular blocks 和 table blocks

---

## Phase 4: 局部编辑（Block 级别操作）

### 2026-03-04 Session 2: 局部编辑命令实现 ✅

#### 问题背景
- 用户反馈：对文档做 overwrite 不方便查看飞书历史编辑记录
- 需要 block 级别的局部编辑能力：原地更新、删除范围、指定位置插入
- 飞书 API 支持三种局部操作：PATCH block、BatchDelete children、CreateChildren at index

#### 任务拆解
- [x] 调研飞书 API 局部编辑能力（PATCH / BatchUpdate / BatchDelete）
- [x] 验证 HTTP PATCH API 可行性（SDK PatchDocumentBlock 参数格式不兼容）
- [x] 实现 `patch-block` 子命令 — 原地更新 block 文本
- [x] 实现 `delete-blocks` 子命令 — 删除指定 index 范围
- [x] 实现 `insert-blocks` 子命令 — 在指定位置插入 Markdown 内容
- [x] 端到端测试：3 个新命令全部通过
- [x] 运行单元测试：38/38 全部通过
- [x] 更新 SKILL.md — 优先强调局部编辑，overwrite 标注慎用
- [x] 更新 REQUIREMENTS.md — Phase 4 需求细化 + 标注已完成
- [x] 更新 ARCHITECTURE.md — 新增局部编辑 API 说明 + 子命令 + 设计决策
- [x] 更新 DEVLOG.md — 本章节 + 补全 Phase 3 遗留
- [x] Git 提交 + 推送 (12efb29 代码, 文档补齐另行提交)

#### 端到端测试结果

| 命令 | 结果 | 详情 |
|---|---|---|
| `patch-block` | ✅ | 更新 block `doxcnHMnIZi2ss4AU4SBtm28DCg` 文本，支持 **加粗** 格式 |
| `insert-blocks` | ✅ | 在 index 1 位置插入新段落，原有 block 后移 |
| `delete-blocks` | ✅ | 删除 index [1, 2) 范围的 block |
| 单元测试 | ✅ | 38/38 全部通过 |

#### 技术细节

##### SDK vs HTTP API 选型
- **SDK `PatchDocumentBlockRequest`**：接受 `Block` 对象作为 `request_body`，但飞书服务端实际期望 `update_text_elements` 结构 → 返回 `[1770001] invalid param`
- **HTTP PATCH API**：直接构造 `{"update_text_elements": {"elements": [...]}}` body → 成功
- 结论：patch-block 使用 HTTP API，delete-blocks 和 insert-blocks 使用 SDK

##### `_get_tenant_token()` 复用
- Phase 2 为 reply-comment / add-comment 创建的 helper
- Phase 4 的 patch-block 复用此 helper 获取 tenant_access_token
- 支持 `app_name` 参数，与 `--app` CLI 参数联动

##### insert-blocks 的 index 参数
- SDK `CreateDocumentBlockChildrenRequestBody.index()` 接受 0-based 位置
- 追加模式（write 命令）使用 `index=-1`（末尾）
- 局部插入使用具体 index 值
- 表格插入暂不支持指定 index（两步创建流程限制），会追加到文档末尾

##### ⚠️ 流程合规性反思
- 本次开发**未遵循 dev-workflow 规范**：直接跳到编码，未先更新需求/架构/DEVLOG
- 事后补齐了所有文档（REQUIREMENTS / ARCHITECTURE / DEVLOG）
- 教训：即使是"小改动"也应先记录任务清单，再编码

---

*开始日期: 2026-02-28*
