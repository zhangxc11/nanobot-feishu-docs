---
name: feishu-docs
description: "飞书文档操作：创建、读取、写入飞书文档，批注管理（列出/回复/解决/创建），权限管理。支持 Markdown 内容自动转换为飞书文档格式。当用户要求创建文档、写报告、整理内容到飞书、处理批注时使用。"
---

# 飞书文档 Skill

通过飞书开放平台 API 操作飞书文档。支持创建文档、写入 Markdown 内容、读取文档、批注管理、权限管理。

## 脚本位置

```
skills/feishu-docs/scripts/feishu_doc.py
```

## 命令

### 创建空白文档

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py create --title "文档标题"
```

可选参数：
- `--folder TOKEN` — 指定目标文件夹 token（不指定则创建在应用根目录）

### 创建文档并写入内容（最常用）

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py create-and-write --title "文档标题" --markdown "# 内容标题\n\n正文内容"
```

从文件读取内容：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py create-and-write --title "文档标题" --markdown-file /path/to/content.md
```

### 向已有文档追加内容

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py write --doc DOCUMENT_ID --markdown "追加的内容"
```

从文件读取：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py write --doc DOCUMENT_ID --markdown-file /path/to/content.md
```

### 读取文档内容

纯文本格式：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py read --doc DOCUMENT_ID
```

Block 结构格式：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py read --doc DOCUMENT_ID --format blocks
```

### 列出文档批注

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py list-comments --doc DOCUMENT_ID
```

可选参数：
- `--status all|solved|unsolved` — 过滤批注状态（默认 all）

### 回复批注

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py reply-comment --doc DOCUMENT_ID --comment COMMENT_ID --text "回复内容"
```

### 解决批注

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py resolve-comment --doc DOCUMENT_ID --comment COMMENT_ID
```

### 创建批注

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py add-comment --doc DOCUMENT_ID --quote "引用的文档文本" --text "批注内容"
```

对整个文档添加批注（无需引用特定文本）：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py add-comment --doc DOCUMENT_ID --text "批注内容" --is-whole
```

### 添加协作者

```bash
python3 skills/feishu-docs/scripts/feishu_doc.py add-member --doc DOCUMENT_ID --open-id ou_xxx --perm full_access
```

可选参数：
- `--perm full_access|edit|view` — 权限级别（默认 full_access）

## 输出格式

所有命令输出 JSON，包含 `success` 字段：

成功示例：
```json
{
  "success": true,
  "document_id": "doxcnXXXXXX",
  "title": "文档标题",
  "blocks_written": 15,
  "url": "https://feishu.cn/docx/doxcnXXXXXX"
}
```

失败示例：
```json
{
  "success": false,
  "error": "[99991663] No permission"
}
```

## 支持的 Markdown 语法

| Markdown | 飞书效果 |
|---|---|
| `# H1` ~ `######### H9` | 标题 1-9 |
| 普通段落 | 文本 |
| `- item` | 无序列表 |
| `1. item` | 有序列表 |
| `` ```lang ... ``` `` | 代码块（支持语言高亮） |
| `> quote` | 引用 |
| `- [ ] todo` / `- [x] done` | 待办事项 |
| `---` | 分割线 |
| `**bold**` | 加粗 |
| `*italic*` | 斜体 |
| `` `code` `` | 行内代码 |
| `~~strike~~` | 删除线 |
| `[text](url)` | 链接 |

## 使用技巧

### 长内容建议用文件方式

当 Markdown 内容较长时，先写入临时文件再用 `--markdown-file` 传入：

```bash
# 1. 将内容写入临时文件
# 2. 调用命令
python3 skills/feishu-docs/scripts/feishu_doc.py create-and-write \
  --title "周报" \
  --markdown-file /tmp/weekly_report.md
```

### 批注工作流

典型的批注处理流程：
```bash
# 1. 列出未解决的批注
python3 skills/feishu-docs/scripts/feishu_doc.py list-comments --doc DOC_ID --status unsolved

# 2. 根据批注内容更新文档
python3 skills/feishu-docs/scripts/feishu_doc.py write --doc DOC_ID --markdown "更新内容"

# 3. 回复批注说明已处理
python3 skills/feishu-docs/scripts/feishu_doc.py reply-comment --doc DOC_ID --comment COMMENT_ID --text "已处理"

# 4. 标记批注为已解决
python3 skills/feishu-docs/scripts/feishu_doc.py resolve-comment --doc DOC_ID --comment COMMENT_ID
```

### 指定飞书应用

默认使用 ST 应用，可通过 `--app` 切换：
```bash
python3 skills/feishu-docs/scripts/feishu_doc.py --app lab create --title "测试"
```

## 安全说明

- 脚本从 `~/.nanobot/config.json` 自动加载飞书应用凭证
- **appSecret 不会输出到 stdout**，仅在脚本进程内使用
- Agent 不直接接触密钥

## 权限要求

飞书应用需开通以下权限：
- `docx:document:create` — 创建文档
- `docx:document:write_only` — 写入文档
- `docx:document:readonly` — 读取文档
- `drive:drive:comment` — 批注操作（读取/创建/回复/解决）
- `drive:drive:permission` — 权限管理（添加协作者）

## 项目文档

- 需求文档: `skills/feishu-docs/docs/REQUIREMENTS.md`
- 架构文档: `skills/feishu-docs/docs/ARCHITECTURE.md`
- 开发日志: `skills/feishu-docs/docs/DEVLOG.md`
