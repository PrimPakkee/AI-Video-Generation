# AI Video Prompt Generator - Web Interface

网页版 NotebookLM Prompt 生成器，无需终端命令，通过浏览器界面生成教育视频 Prompt。

## 功能特性

- 🎯 简洁的网页界面，无需终端操作
- 🚀 一键生成 NotebookLM Prompt
- 📋 一键复制生成的 Prompt
- ✅ 实时生成状态和错误提示
- 🔒 安全设计，防止命令注入

## 技术栈

- **后端**: FastAPI
- **前端**: HTML/CSS/JavaScript
- **部署**: 本地运行

## 安装依赖

```bash
# 安装 FastAPI 和 uvicorn
pip install fastapi uvicorn python-dotenv

# 或者如果有 requirements.txt
pip install -r requirements.txt
```

## 启动服务

### 方法 1: 使用 uvicorn 命令（推荐）

```bash
# 在项目根目录运行
uvicorn web.app:app --reload --port 8000
```

### 方法 2: 直接运行 Python 文件

```bash
# 在项目根目录运行
python3 web/app.py
```

### 启动参数说明

- `--reload`: 开发模式，代码修改后自动重启（生产环境不要使用）
- `--port 8000`: 指定端口号（默认 8000）
- `--host 0.0.0.0`: 允许外部访问（默认仅本地）

## 使用方式

1. **启动服务**
   ```bash
   uvicorn web.app:app --reload --port 8000
   ```

2. **打开浏览器**
   ```
   http://localhost:8000
   ```

3. **输入视频题目**
   - 例如："为什么盲盒越到最后越难集齐"
   - 例如："两个骰子为什么最容易掷出 7"

4. **点击生成按钮**
   - 等待生成完成（通常需要 30-60 秒）

5. **复制生成的 Prompt**
   - 点击 "📋 复制到剪贴板" 按钮
   - 或手动选择文本复制

6. **使用 Prompt**
   - 将复制的 Prompt 粘贴到 NotebookLM
   - 生成教育视频

## API 接口

### GET /

返回主页面

### POST /api/generate

生成 NotebookLM Prompt

**请求体:**
```json
{
  "title": "视频题目"
}
```

**成功响应:**
```json
{
  "success": true,
  "slug": "output_slug",
  "prompt": "生成的 Prompt 内容",
  "output_dir": "outputs/output_slug"
}
```

**失败响应:**
```json
{
  "success": false,
  "error": "错误信息",
  "stdout": "命令输出",
  "stderr": "错误输出"
}
```

### GET /api/health

健康检查

**响应:**
```json
{
  "status": "ok",
  "project_root": "/path/to/project",
  "env_loaded": true
}
```

## 文件结构

```
web/
├── app.py              # FastAPI 后端
├── README.md           # 本文档
└── static/
    ├── index.html      # 主页面
    ├── style.css       # 样式文件
    └── main.js         # 前端逻辑
```

## 安全设计

1. **输入验证**
   - 题目长度限制 1-200 字符
   - slug 仅允许字母数字下划线横线

2. **命令注入防护**
   - 使用 subprocess list 参数，不拼接 shell 字符串
   - slug 严格过滤特殊字符

3. **环境变量保护**
   - API key 和敏感信息不返回给前端
   - .env 文件不暴露为静态文件

4. **超时控制**
   - 生成命令超时时间：10 分钟
   - 防止长时间占用资源

## 故障排除

### 问题：启动失败 - "No module named 'fastapi'"

**解决方案:**
```bash
pip install fastapi uvicorn python-dotenv
```

### 问题：生成失败 - "Script not found"

**解决方案:**
- 确保在项目根目录运行 uvicorn 命令
- 检查 `scripts/generate_video_package.py` 是否存在

### 问题：生成失败 - "Missing API key"

**解决方案:**
- 确保 `.env` 文件存在于项目根目录
- 确保配置了 `AI_VIDEO_LLM_API_KEY`

### 问题：端口被占用

**解决方案:**
```bash
# 使用其他端口
uvicorn web.app:app --reload --port 8001
```

或者杀死占用端口的进程：
```bash
# macOS/Linux
lsof -ti:8000 | xargs kill -9

# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

## 开发建议

### 本地开发

```bash
# 使用 --reload 自动重启
uvicorn web.app:app --reload --port 8000
```

### 生产部署

```bash
# 不使用 --reload，指定 workers
uvicorn web.app:app --host 0.0.0.0 --port 8000 --workers 4
```

### 日志查看

启动时会在终端显示请求日志：
```
INFO:     127.0.0.1:50123 - "POST /api/generate HTTP/1.1" 200 OK
```

## 限制和注意事项

1. **不支持并发生成**
   - 每次只能生成一个 Prompt
   - 多用户同时使用可能冲突

2. **不保存历史记录**
   - 关闭页面后结果丢失
   - 建议及时复制保存

3. **依赖 LLM API**
   - 需要配置有效的 API key
   - 受 API 速率限制影响

4. **本地运行**
   - 仅适合本地或内网使用
   - 公网部署需要额外安全措施

## 未来改进

- [ ] 支持历史记录查看
- [ ] 支持多用户队列
- [ ] 添加生成进度显示
- [ ] 支持批量生成
- [ ] 添加 Prompt 预览
- [ ] 支持导出为文件

## 联系方式

有问题或建议请联系 Think Academy AI Team。
