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

### Phase 2: 高级功能（后续）

#### F2.1 编辑已有文档
- 更新指定 Block 的内容
- 在指定位置插入新 Block
- 删除指定 Block

#### F2.2 电子表格操作
- 创建电子表格
- 读写单元格数据

#### F2.3 多维表格操作
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
