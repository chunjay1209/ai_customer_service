# AI 智能客服查价系统

基于 FastAPI + Streamlit 的智能报价查询系统，支持多租户管理、AI 关键词拆分、模糊匹配和实时价格查询。

## 功能特性

- **AI 智能批量查价**：输入自然语言商品描述，LLM 自动拆分关键词（品牌/型号/颜色/容量），在报价表中精确匹配价格
- **多租户管理**：平台级多商户管理，每个租户独立配置 LLM 模型、数据源
- **双数据源支持**：支持 DB 直连（MySQL）和飞书多维表格两种数据源模式
- **角色权限控制**：角色级别的功能权限管理，控制运营后台各页面访问
- **报价看板**：实时展示报价数据，支持按商品搜索、价格排序
- **审计日志**：完整的操作审计记录，可追溯所有用户操作
- **动态轮询**：自动检测数据源变更，实时同步价格数据

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 前端框架 | Streamlit |
| 数据库 | MySQL（生产）/ SQLite（开发） |
| ORM | SQLAlchemy |
| 认证 | JWT (python-jose) |
| AI/LLM | DeepSeek / Gemini |
| 缓存 | Redis（可选）/ 内存缓存 |
| 定时任务 | APScheduler |

## 项目结构

```
ai_customer_service/
├── backend/                    # 后端服务
│   ├── main.py                 # FastAPI 应用入口，API 路由定义
│   ├── models.py               # 数据库模型（Tenant/User/Role/PriceCache 等）
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── config.py               # 配置管理（环境变量加载）
│   ├── database.py             # 数据库连接与自动迁移
│   ├── auth.py                 # JWT 认证与密码处理
│   ├── audit.py                # 审计日志记录
│   ├── feishu_api.py           # 商品匹配核心逻辑（关键词分类/模糊匹配）
│   ├── llm_service.py          # LLM 调用服务（DeepSeek/Gemini 关键词提取）
│   ├── price_service.py        # 价格查询服务（缓存/同步/匹配）
│   ├── polling.py              # 动态轮询（数据源变更检测）
│   ├── init_db.py              # 数据库初始化脚本
│   ├── test_match_e2e.py       # 端到端匹配测试
│   └── datasource/             # 数据源策略
│       ├── base.py             # 数据源抽象基类
│       ├── db_strategy.py      # DB 直连策略
│       └── feishu_strategy.py  # 飞书多维表格策略
├── frontend/
│   └── app.py                  # Streamlit 前端（9 个功能页面）
├── data/
│   └── app.db                  # SQLite 数据库文件（开发模式）
├── requirements.txt            # Python 依赖
├── restart.sh                  # 服务重启脚本
├── .env                        # 环境变量配置
└── .env.example                # 环境变量示例
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- MySQL 5.7+（生产环境）或 SQLite（开发环境）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，按需修改：

```bash
# 数据库（MySQL 生产 / SQLite 开发）
DB_URL=mysql+pymysql://root:password@host:port/db_name
# DB_URL=sqlite:///./data/app.db

# JWT 密钥（生产环境务必修改为强随机字符串）
JWT_SECRET=change-me-to-a-long-random-string

# 服务端口
BACKEND_PORT=8502

# LLM 配置（DeepSeek 或 Gemini）
GEMINI_API_KEY=your_api_key_here
```

### 4. 初始化数据库

```bash
cd backend
python init_db.py
```

### 5. 启动服务

**后端：**

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8502 --reload
```

**前端：**

```bash
cd frontend
streamlit run app.py --server.port 8501
```

### 6. 访问系统

- 前端页面：`http://localhost:8501`
- 后端 API 文档：`http://localhost:8502/docs`
- 默认管理员：公司代码 `admin`，用户名 `admin`，密码 `admin123`

## API 接口

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/change-password` | 修改密码 |
| GET | `/api/auth/me` | 获取当前用户信息 |

### 平台管理（超级管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/platform/tenants` | 商户列表/创建 |
| PUT/DELETE | `/api/platform/tenants/{id}` | 商户编辑/删除 |
| GET/PUT | `/api/platform/tenants/{id}/config` | 商户配置（数据源/LLM） |
| POST | `/api/platform/tenants/{id}/validate-db` | 验证 DB 连接 |
| POST | `/api/platform/tenants/{code}/refresh-cache` | 刷新数据缓存 |
| POST | `/api/platform/tenants/{code}/check-price` | 单条查价 |
| GET | `/api/platform/tenants/{code}/rows` | 获取报价数据 |

### 运营后台（租户管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/admin/users` | 员工列表/创建 |
| PUT/DELETE | `/api/admin/users/{id}` | 员工编辑/删除 |
| POST | `/api/admin/users/reset-password` | 重置密码 |
| GET/POST | `/api/admin/roles` | 角色列表/创建 |
| PUT/DELETE | `/api/admin/roles/{id}` | 角色编辑/删除 |
| GET | `/api/admin/audit-logs` | 审计日志 |
| GET/PUT | `/api/admin/config` | 租户配置 |

### 价格查询

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/price/check` | **AI 智能批量查价**（核心接口） |
| GET | `/api/feishu/rows` | 获取报价数据 |
| GET | `/health` | 健康检查 |

## 功能页面

| 页面 | 访问角色 | 说明 |
|------|---------|------|
| 报价看板 | 所有用户 | 报价数据查看与搜索 |
| AI 智能批量查价 | 所有用户 | 自然语言输入，AI 拆分关键词匹配价格 |
| 员工管理 | 管理员 | 员工账号增删改查 |
| 角色管理 | 管理员 | 角色权限配置 |
| 后台配置 | 管理员 | 租户级 LLM/数据源配置 |
| 审计日志 | 管理员 | 操作记录查询 |
| 修改密码 | 所有用户 | 个人密码修改 |
| 平台商户管理 | 超级管理员 | 商户增删改查 |
| 平台监控 | 超级管理员 | 数据同步状态监控 |

## AI 查价流程

```
用户输入 "iPhone 16 Pro 256GB 沙漠金"
        ↓
[1] LLM 关键词提取（DeepSeek/Gemini）
        → ["iPhone", "16", "Pro", "沙漠金", "256"]
        ↓
[2] 关键词分类
        → 型号: iPhone 16 Pro | 颜色: 沙漠金 | 容量: 256
        ↓
[3] 模型 token 索引过滤（9899 行 → 5-50 行候选）
        ↓
[4] 三阶段匹配（严格 AND → 放宽容量 → 放宽颜色）
        ↓
[5] 返回匹配结果 + 价格
```

## 生产部署

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /api {
        proxy_pass http://127.0.0.1:8502;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
    }
}
```

### systemd 服务

```ini
[Unit]
Description=AI Customer Service Backend
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/ai_customer_service
ExecStart=/path/to/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8502
Restart=always

[Install]
WantedBy=multi-user.target
```

## 注意事项

1. **JWT_SECRET** 生产环境务必修改为强随机字符串（32 字符以上）
2. **API_BASE_URL** 需设置为服务器实际 IP/域名，确保前后端通信正常
3. **LLM 配置** 为租户级配置，需在后台管理页面为每个租户单独设置 API Key 和模型
4. **数据源** 支持 DB 直连和飞书两种模式，切换时需清空缓存并重新同步
5. **缓存** 默认使用内存缓存（5 分钟 TTL），生产环境建议配置 Redis 以支持多 worker 共享

## License

Internal use only.