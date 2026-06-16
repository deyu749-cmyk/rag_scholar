# RAG Scholar — 文献语义检索系统

//Welcome!  My first reader----MXC 
//Don't forget to star my project❤️
基于 RAG（检索增强生成）架构的学术文献语义检索与智能分析系统，专为后殖民文学与文化研究领域设计。

## 核心功能

### 文档索引
- 支持 **PDF** 和 **DOCX** 文献解析
- 中英文混合智能分块（中文按字符、英文按单词，20% 重叠）
- `text-embedding-3-large` 向量化（3072 维）
- ChromaDB 持久化存储，支持增量更新

### 智能检索
- **双层检索架构**：向量块检索 + 摘要检索
- AI 自动路由：根据查询类型自动选择检索模式（具体问题 → chunks，宏观分析 → summaries）
- **Cohere Rerank v3.5** 重排序，初检 50 条精选至 Top 10
- 支持按文献库和单篇文献过滤

### AI 分析
- 文献摘要自动生成（四维度结构化：研究问题、方法、结果、意义）
- 深度学术分析（区分西方/非洲本土/中国学者视角，标注学术共识与分歧）
- 研究空白分析（基于摘要集合发现学术趋势）
- 对话总结与事实核查

### 学术写作助手
- **润色**：保持原意，提升学术表达规范性
- **改写**：重新组织语言，降低查重风险
- **扩写**：结合文献库扩展论述
- **压缩**：精简表达
- 文献综述/概论自动生成
- 引用标注建议

### 桌面应用
- PyInstaller 打包为独立 exe，双击即用
- SSE 实时进度推送
- 本地 ChromaDB 存储，无需数据库服务

## 项目结构

```
rag_scholar/
├── app.py              # Flask 主应用，API 路由
├── config.py           # 集中配置管理
├── indexer.py          # 文献索引器（解析、分块、向量化、摘要生成）
├── retriever.py        # 检索器（路由、Rerank、双层检索、深度分析）
├── writer.py           # 写作助手（润色、改写、综述生成、引用标注）
├── launch.py           # 打包入口（加载 .env、启动 Flask、打开浏览器）
├── rag_scholar.spec    # PyInstaller 打包配置
├── requirements.txt    # Python 依赖
├── .env                # 环境变量（API Key 等敏感配置，不提交 Git）
├── templates/          # 前端静态文件
│   ├── index.html
│   ├── app.js
│   └── style.css
├── papers/             # 文献库目录（按库分子文件夹）
│   ├── Coetzee/
│   ├── Gurnah/
│   ├── Gordimer/
│   ├── Mahfouz/
│   ├── Soyinka/
│   └── Introduction/
└── chroma_db/          # ChromaDB 持久化向量数据
```

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 安装

```bash
# 克隆仓库
git clone <repo-url>
cd rag_scholar

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```env
LEVOLINK_API_KEY=your_levolink_api_key
LEVOLINK_API_BASE=https://ai.levolink.com/v1
COHERE_API_KEY=your_cohere_api_key
```

### 运行

```bash
# 直接运行（开发模式）
python app.py

# 或通过 launch.py 启动（自动打开浏览器）
python launch.py
```

浏览器访问 `http://127.0.0.1:5000`

### 打包为 exe

```bash
pyinstaller rag_scholar.spec
```

打包后的文件在 `dist/文献语义检索系统/`，将 `papers/` 目录和 `.env` 文件放在 exe 同级目录即可。

## 使用流程

1. **准备文献**：将 PDF/DOCX 文件放入 `papers/<库名>/` 目录
2. **索引文献**：在 Web 界面选择文献库，点击"开始索引"，等待向量化和摘要生成完成
3. **检索分析**：输入研究问题，选择检索库，获取 AI 深度分析
4. **学术写作**：在写作模式中粘贴文本，选择润色/改写风格，获取结合文献的写作建议

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask + Flask-CORS |
| 向量数据库 | ChromaDB (HNSW, cosine) |
| Embedding | text-embedding-3-large (3072d) |
| 重排序 | Cohere Rerank v3.5 |
| AI 分析 | Claude (via Levolink OpenAI-compatible API) |
| 文档解析 | PyMuPDF (PDF) + python-docx (DOCX) |
| 前端 | 原生 HTML/CSS/JS + SSE |
| 打包 | PyInstaller |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/libs` | GET | 获取文献库列表及索引状态 |
| `/api/libs/<name>/files` | GET | 获取库中文件列表 |
| `/api/index` | POST | 开始索引（SSE 进度推送） |
| `/api/search` | POST | 检索 + AI 分析 |
| `/api/summarize` | POST | 对话总结 |
| `/api/recheck` | POST | 事实核查 |
| `/api/write` | POST | 学术写作（润色/改写/扩写/压缩） |
| `/api/write/chat` | POST | 对话式写作修改 |
| `/api/write/review` | POST | 文献综述/概论生成 |
| `/api/write/annotate` | POST | 引用标注 |
| `/api/libs/<name>/delete_index` | POST | 删除索引 |
| `/api/status` | GET | 系统状态 |

## 文献库

预置六个后殖民文学研究文献库：

- **Coetzee** — J.M. 库切
- **Gurnah** — 阿卜杜勒拉扎克·古尔纳
- **Gordimer** — 纳丁·戈迪默
- **Mahfouz** — 纳吉布·马哈福兹
- **Soyinka** — 沃莱·索因卡
- **Introduction** — 非洲文学导论

可在 `config.py` 的 `LIBRARIES` 中自定义。

## License

MIT
