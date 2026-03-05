# 飞书文档 Skill — 需求文档

## 概述

为 nanobot 提供飞书文档的创建和编辑能力。通过 `lark-oapi` SDK 调用飞书开放平台 API，实现在飞书上创建、读取、编辑文档。

## 背景

- nanobot gateway 已接入飞书（ST / lab 两个应用），具备 IM 聊天能力
- ST 应用已开通文档相关权限（docx、drive、sheets、bitable、wiki）
- `lark-oapi` SDK 已安装，包含完整的 docx API 模块
- 以独立 Skill 形式实现，不修改 nanobot 核心代码

## 已开通权限（ST 应用）

### 文档类
- `docx:document` — 文档管理
- `docx:document:create` — 创建文档
- `docx:document:readonly` — 读取文档
- `docx:document:write_only` — 写入文档
- `docx:document.block:convert` — Block 转换
- `docs:document.content:read` — 读取文档内容

### 云盘类
- `drive:drive.metadata:readonly` — 云盘元数据只读
- `drive:drive:version` — 版本管理
- `drive:drive:version:readonly` — 版本只读

### 表格类
- `sheets:spreadsheet` — 电子表格读写
- `sheets:spreadsheet:create` — 创建电子表格
- `sheets:spreadsheet:readonly` — 只读电子表格
- `sheets:spreadsheet.meta:read` — 表格元数据读取
- `sheets:spreadsheet.meta:write_only` — 表格元数据写入

### 多维表格
- `bitable:app` — 多维表格读写
- `bitable:app:readonly` — 多维表格只读

### 知识库
- `wiki:wiki:readonly` — 知识库只读

## 功能需求

### Phase 1: 核心文档操作（MVP）

#### F1.1 创建文档
- 创建空白飞书文档，支持指定标题
- 支持指定目标文件夹（folder_token）
- 返回文档 URL 和 document_id

#### F1.2 写入文档内容
- 向文档追加内容（Markdown → 飞书 Block）
- 支持的 Block 类型：
  - 文本段落（text）
  - 标题（heading1 ~ heading9）
  - 无序列表（bullet）
  - 有序列表（ordered）
  - 代码块（code）
  - 引用（quote）
  - 待办事项（todo）
  - 分割线（divider）
- Markdown 到 Block 的自动转换

#### F1.3 读取文档内容
- 读取文档纯文本内容（raw_content）
- 读取文档 Block 结构（list blocks）

#### F1.4 创建并写入（一步到位）
- 创建文档 + 写入 Markdown 内容的组合命令
- 最常用的场景：一句话生成一篇文档

### Phase 2: 批注（Comment）操作

#### F2.1 列出文档批注
- 列出指定文档的所有批注（含回复内容）
- 支持过滤已解决/未解决的批注
- 返回批注 ID、内容、回复列表、解决状态

#### F2.2 回复批注
- 对指定批注添加回复
- 支持纯文本内容

#### F2.3 解决批注
- 将指定批注标记为已解决

#### F2.4 创建批注
- 在文档上创建新批注
- 需要指定 quote（引用的文档内容）和批注正文

#### F2.5 权限管理（协作者）
- 为文档添加协作者（通过 open_id）
- 支持设置权限级别（full_access / edit / view）

### Phase 3: 覆盖写入 + 表格支持

#### F3.1 write 命令覆盖模式
- `write --doc DOC_ID --mode overwrite` — 先清空文档所有子 block，再写入新内容
- 默认行为（`--mode append`）保持不变：追加到文档末尾
- `create-and-write` 命令不需要 mode 参数（新文档本身为空）
- 清空逻辑：调用 `BatchDeleteDocumentBlockChildren` API，传入 `start_index=0, end_index=子block数量`

#### F3.2 Markdown 表格 → 飞书 Table Block
- 解析标准 Markdown 表格语法（`| col1 | col2 |` + `|---|---|`）
- 生成飞书 `table` block（block_type=31）
- 表格属性：row_size, column_size, header_row=true
- 单元格内容支持 inline 样式（bold, italic, code, link）
- 飞书表格创建方式：先创建空 table block，再向每个 cell 写入内容

#### F3.3 文档说明完善
- SKILL.md 明确标注 write 命令默认为追加模式
- SKILL.md 明确列出支持和不支持的 Markdown 语法
- ARCHITECTURE.md 更新表格相关 API 说明

### Phase 4: 局部编辑（Block 级别操作） ✅

> **设计原则**：修改已有文档时优先使用局部编辑，避免 overwrite 全量覆盖。overwrite 会丢失飞书编辑历史，无法查看修改前后对比。

#### F4.1 原地更新 Block 内容（patch-block） ✅
- 通过 block_id 定位目标 block，原地更新其文本内容
- 支持行内 Markdown 格式（bold, italic, code, link, strikethrough）
- 适用于 text / heading / bullet / ordered 等文本类 block
- 使用飞书 HTTP PATCH API（`update_text_elements`），SDK 的 PatchDocumentBlock 参数格式不兼容
- 保留飞书完整编辑历史

#### F4.2 删除指定范围的 Block（delete-blocks） ✅
- 按 index 范围删除 page block 的子 block（start_index inclusive, end_index exclusive）
- 支持指定 parent block（默认为 page block = doc_id）
- 使用 SDK `BatchDeleteDocumentBlockChildren` API

#### F4.3 在指定位置插入内容（insert-blocks） ✅
- 在指定 index 位置插入 Markdown 内容（0-based，插入到该 index 之前）
- 支持完整 Markdown 语法（含表格）
- 支持 `--markdown` 和 `--markdown-file` 两种输入方式
- 支持指定 parent block
- 使用 SDK `CreateDocumentBlockChildren` 的 `index` 参数

#### F4.4 推荐编辑工作流
- 编辑前必须先 `read --format blocks` 获取文档结构（block ID + index）
- 优先 patch-block（修改）→ delete-blocks（删除）→ insert-blocks（插入）
- 仅在需要彻底重写整个文档时才使用 `write --mode overwrite`

### Phase 5: 高级功能（后续）

#### F5.1 表格列宽自动计算 ✅
- 创建表格时自动根据单元格内容计算合适的列宽
- CJK 字符按 2 宽度单位计算，ASCII 按 1 宽度单位
- 使用平方根比例分配（压缩长短列差异，视觉更均衡）
- 默认总宽 600px，单列最小 80px，最大 400px
- 创建表格后通过 PATCH API（`update_table_property`）逐列设置宽度
- 解决之前所有列默认 100px 导致表格过窄、内容换行过多的问题

#### F5.2 表格 Cell 写入健壮性 ✅
- 表格 cell 写入增加 HTTP 429 指数退避重试（最多 5 次）
- 写入 cell 内容后删除飞书自动生成的默认空 text block（避免多余空行）
- insert-blocks 命令支持表格的 index 定位（之前硬编码为追加到末尾）

#### F5.3 电子表格操作（后续）
- 创建电子表格
- 读写单元格数据

#### F5.4 多维表格操作（后续）
- 读写多维表格记录

## 技术约束

### 安全性
- **appSecret 不得暴露给 LLM** — 脚本从 config.json 加载凭证，agent 不直接接触密钥
- 脚本中硬编码 config.json 路径，自行读取 appId/appSecret

### 兼容性
- 使用 ST 应用的凭证（config.json 中 feishu 数组第一个 name="ST" 的条目）
- 与 gateway 的 WebSocket 连接无冲突（独立 HTTP Client）

### 依赖
- Python 3.11+
- lark-oapi（已安装在 nanobot venv311 中）

## Issues

（开发过程中发现的问题记录在此）

---

*创建日期: 2026-02-28*
