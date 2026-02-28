# 飞书文档 Skill — 架构文档

## 项目结构

```
skills/feishu-docs/
├── SKILL.md                    # Skill 入口（nanobot 加载）
├── docs/
│   ├── REQUIREMENTS.md         # 需求文档
│   ├── ARCHITECTURE.md         # 架构文档（本文件）
│   └── DEVLOG.md               # 开发日志
├── scripts/
│   ├── feishu_doc.py           # 核心 Python 脚本（统一入口）
│   └── md_to_blocks.py         # Markdown → 飞书 Block 转换器
└── tests/
    └── test_md_to_blocks.py    # Markdown 转换器单元测试
```

## 架构设计

### 整体方案

采用 **Python CLI 脚本** 作为 Skill 实现方式：
- Agent 通过 `exec` 工具调用 Python 脚本
- 脚本自行从 `~/.nanobot/config.json` 读取飞书凭证
- 脚本使用 `lark-oapi` SDK 调用飞书 API
- 输出结果到 stdout，供 agent 解析

### 核心组件

#### 1. `feishu_doc.py` — 统一 CLI 入口

```
用法:
  python3 feishu_doc.py create --title "标题" [--folder TOKEN]
  python3 feishu_doc.py write --doc DOC_ID --markdown "# 内容"
  python3 feishu_doc.py write --doc DOC_ID --markdown-file path/to/file.md
  python3 feishu_doc.py read --doc DOC_ID [--format raw|blocks]
  python3 feishu_doc.py create-and-write --title "标题" --markdown "# 内容" [--folder TOKEN]
  python3 feishu_doc.py create-and-write --title "标题" --markdown-file path/to/file.md [--folder TOKEN]
  python3 feishu_doc.py list-comments --doc DOC_ID [--status all|solved|unsolved]
  python3 feishu_doc.py reply-comment --doc DOC_ID --comment COMMENT_ID --text "回复内容"
  python3 feishu_doc.py resolve-comment --doc DOC_ID --comment COMMENT_ID
  python3 feishu_doc.py add-comment --doc DOC_ID --quote "引用文本" --text "批注内容"
  python3 feishu_doc.py add-member --doc DOC_ID --open-id OPEN_ID [--perm full_access|edit|view]
```

子命令:
- `create` — 创建空白文档
- `write` — 向已有文档追加内容
- `read` — 读取文档内容
- `create-and-write` — 创建文档并写入内容（组合命令）
- `list-comments` — 列出文档批注
- `reply-comment` — 回复指定批注
- `resolve-comment` — 标记批注为已解决
- `add-comment` — 在文档上创建新批注
- `add-member` — 为文档添加协作者

#### 2. `md_to_blocks.py` — Markdown → 飞书 Block 转换器

将 Markdown 文本解析为飞书 Block 数据结构（JSON），支持：

| Markdown 语法 | 飞书 Block 类型 | block_type 值 |
|---|---|---|
| 普通段落 | text | 2 |
| `# H1` | heading1 | 3 |
| `## H2` | heading2 | 4 |
| `### H3` | heading3 | 5 |
| `#### H4` ~ `######### H9` | heading4~9 | 6~11 |
| `- item` | bullet | 12 |
| `1. item` | ordered | 13 |
| `` ```code``` `` | code | 14 |
| `> quote` | quote | 15 |
| `- [ ] todo` / `- [x] todo` | todo | 17 |
| `---` | divider | 22 |

文本内联样式支持：
| Markdown | 飞书 TextElementStyle |
|---|---|
| `**bold**` | bold: true |
| `*italic*` | italic: true |
| `~~strike~~` | strikethrough: true |
| `` `code` `` | inline_code: true |
| `[text](url)` | link.url |

### 数据流

```
Agent (exec)
  → python3 feishu_doc.py <command> <args>
    → 读取 ~/.nanobot/config.json 获取 appId/appSecret
    → 初始化 lark.Client (tenant_access_token)
    → [如果有 markdown] md_to_blocks.py 转换
    → 调用飞书 API
    → 输出 JSON 结果到 stdout
  ← Agent 解析结果
```

### 凭证管理

```python
# feishu_doc.py 内部
config = json.load(open(os.path.expanduser("~/.nanobot/config.json")))
feishu_apps = config["channels"]["feishu"]
# 找到 name="ST" 的应用
st_app = next(app for app in feishu_apps if app.get("name") == "ST")
app_id = st_app["appId"]
app_secret = st_app["appSecret"]
```

**安全保证**：
- appSecret 仅在脚本进程内使用，不输出到 stdout
- Agent 不直接接触密钥，只调用脚本命令

### 飞书 API 调用链

#### 创建文档
```
POST /open-apis/docx/v1/documents
Body: { "title": "...", "folder_token": "..." }
Response: { "document": { "document_id": "...", "title": "...", "revision_id": 1 } }
```

#### 写入 Block
```
POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children
Body: { "children": [ Block, Block, ... ] }
```
- `block_id` = `document_id`（根 Block = 文档本身）

#### 读取文档
```
GET /open-apis/docx/v1/documents/{document_id}/raw_content
Response: { "content": "纯文本内容" }
```

```
GET /open-apis/docx/v1/documents/{document_id}/blocks
Response: { "items": [ Block, Block, ... ] }
```

#### 列出批注
```
GET /open-apis/drive/v1/files/{file_token}/comments?file_type=docx
Response: { "items": [ { "comment_id", "reply_list": { "replies": [...] }, "is_solved" } ] }
```

#### 回复批注
```
POST /open-apis/drive/v1/files/{file_token}/comments/{comment_id}/replies?file_type=docx
Body: { "content": { "elements": [{ "type": "text_run", "text_run": { "text": "..." } }] } }
```
- SDK 中无 CreateFileCommentReply，使用 requests 直接调用 HTTP API

#### 解决批注
```
PATCH /open-apis/drive/v1/files/{file_token}/comments/{comment_id}?file_type=docx
Body: { "is_solved": true }
```

#### 创建批注
```
POST /open-apis/drive/v1/files/{file_token}/comments?file_type=docx
Body: { "content": { "elements": [...] }, "quote": "引用文本" }
```
- SDK 中 CreateFileComment 需要 quote（引用的文档原文）和 content（批注正文）

#### 添加协作者
```
POST /open-apis/drive/v1/permissions/{token}/members?type=docx
Body: { "member_type": "openid", "member_id": "ou_xxx", "perm": "full_access" }
```

## 设计决策

### 为什么用 Python 脚本而不是 Shell 脚本？
- 飞书 Block 数据结构复杂（嵌套 JSON），Shell 处理困难
- `lark-oapi` 是 Python SDK，直接调用最方便
- Markdown 解析需要正则/状态机，Python 更合适

### 为什么用 CLI 而不是 HTTP 服务？
- Skill 是 agent 按需调用，不需要常驻进程
- CLI 更简单，无需管理服务生命周期
- 每次调用独立初始化 Client，无状态，无冲突

### 为什么选择 ST 应用？
- ST 应用已开通文档权限
- 可通过 `--app` 参数扩展支持其他应用

---

*创建日期: 2026-02-28*
