"""
文献索引器
- PDF/DOCX 解析
- text-embedding-3-large 向量化
- ChromaDB 存储（手动传向量，避免 embedding_function 冲突）
- AI 摘要生成（独立 collection）
- SSE 进度推送
"""

import os
import re
import time
import hashlib
from pathlib import Path
from typing import Callable, Optional

import fitz  # pymupdf
from docx import Document
import chromadb
import requests

from config import (
    LEVOLINK_API_BASE, LEVOLINK_API_KEY,
    EMBEDDING_MODEL, EMBEDDING_DIMENSIONS,
    CHAT_MODEL, CHAT_MAX_TOKENS,
    CHROMA_PERSIST_DIR, PAPERS_DIR,
    CHUNK_SIZE, CHUNK_OVERLAP,
    SUMMARY_COLLECTION_SUFFIX, SUMMARY_SYSTEM_PROMPT
)


# ===== ChromaDB 客户端 =====
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def get_collection(lib_name: str):
    """获取或创建向量块 collection（不传 embedding_function 避免冲突）"""
    try:
        return chroma_client.get_collection(name=lib_name)
    except Exception:
        return chroma_client.create_collection(
            name=lib_name,
            metadata={"hnsw:space": "cosine"}
        )


def get_summary_collection(lib_name: str):
    """获取或创建摘要 collection"""
    name = f"{lib_name}{SUMMARY_COLLECTION_SUFFIX}"
    try:
        return chroma_client.get_collection(name=name)
    except Exception:
        return chroma_client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"}
        )


# ===== 文件解析 =====
def extract_text_from_pdf(filepath: str) -> str:
    """从 PDF 提取文本"""
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_text_from_docx(filepath: str) -> str:
    """从 DOCX 提取文本"""
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])


def extract_text(filepath: str) -> str:
    """根据文件类型提取文本"""
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext == ".docx":
        return extract_text_from_docx(filepath)
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


# ===== 分块 =====
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: float = CHUNK_OVERLAP) -> list:
    """
    按词数分块，支持中英文混合
    中文按字符计数，英文按空格分词
    """
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    tokens = []
    current_word = ""
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            if current_word:
                tokens.append(current_word)
                current_word = ""
            tokens.append(char)
        elif char in (' ', '\t'):
            if current_word:
                tokens.append(current_word)
                current_word = ""
            tokens.append(char)
        elif char == '\n':
            if current_word:
                tokens.append(current_word)
                current_word = ""
            tokens.append(char)
        else:
            current_word += char
    if current_word:
        tokens.append(current_word)

    overlap_size = int(chunk_size * overlap)
    step = chunk_size - overlap_size
    chunks = []

    i = 0
    while i < len(tokens):
        chunk_tokens = tokens[i:i + chunk_size]
        chunk_str = "".join(chunk_tokens).strip()
        if chunk_str:
            # 截断保护：避免超出 embedding API token 限制
            if len(chunk_str) > 8000:
                chunk_str = chunk_str[:8000]
            chunks.append(chunk_str)
        i += step

    return chunks


# ===== Embedding API =====
def get_embeddings(texts: list, batch_size: int = 20) -> list:
    """调用乐沃联 API 生成 embedding，支持批量处理"""
    all_embeddings = []
    headers = {
        "Authorization": f"Bearer {LEVOLINK_API_KEY}",
        "Content-Type": "application/json"
    }

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = {
            "model": EMBEDDING_MODEL,
            "input": batch,
            "dimensions": EMBEDDING_DIMENSIONS
        }

        response = requests.post(
            f"{LEVOLINK_API_BASE}/embeddings",
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        data = response.json()

        sorted_data = sorted(data["data"], key=lambda x: x["index"])
        all_embeddings.extend([item["embedding"] for item in sorted_data])

        if i + batch_size < len(texts):
            time.sleep(0.5)

    return all_embeddings


def get_single_embedding(text: str) -> list:
    """单条文本 embedding"""
    return get_embeddings([text])[0]


# ===== Claude API 调用 =====
def call_claude(system_prompt: str, user_content: str,
                max_tokens: int = CHAT_MAX_TOKENS) -> str:
    """调用乐沃联的 Claude 模型（OpenAI 兼容格式）"""
    headers = {
        "Authorization": f"Bearer {LEVOLINK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": CHAT_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content}
        ]
    }

    response = requests.post(
        f"{LEVOLINK_API_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=120
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


# ===== 文件哈希（增量更新用）=====
def file_hash(filepath: str) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ===== 核心索引函数 =====
def index_library(lib_name: str, force_rebuild: bool = False,
                  progress_callback: Optional[Callable] = None) -> dict:
    """
    索引一个文献库

    Args:
        lib_name: 库名
        force_rebuild: 是否强制重建
        progress_callback: 进度回调函数，接收 dict 参数

    Returns:
        统计信息 dict
    """
    lib_path = os.path.join(PAPERS_DIR, lib_name)
    if not os.path.exists(lib_path):
        raise FileNotFoundError(f"文献库目录不存在: {lib_path}")

    files = []
    for f in os.listdir(lib_path):
        if f.lower().endswith(('.pdf', '.docx')) and not f.startswith('.'):
            files.append(os.path.join(lib_path, f))

    total_files = len(files)
    if total_files == 0:
        return {"status": "empty", "message": f"{lib_name} 目录下没有文献文件"}

    def emit(data):
        if progress_callback:
            progress_callback(data)

    emit({
        "stage": "start",
        "lib": lib_name,
        "total_files": total_files,
        "message": f"开始索引 {lib_name}，共 {total_files} 篇文献"
    })

    # 强制重建：删除旧 collection
    if force_rebuild:
        try:
            chroma_client.delete_collection(lib_name)
        except Exception:
            pass
        try:
            chroma_client.delete_collection(f"{lib_name}{SUMMARY_COLLECTION_SUFFIX}")
        except Exception:
            pass
        emit({"stage": "info", "message": "已清除旧索引，开始全量重建"})

    collection = get_collection(lib_name)

    # 获取已索引文件（增量更新）
    existing_ids = set()
    if not force_rebuild:
        try:
            existing = collection.get()
            if existing and existing["ids"]:
                existing_ids = set(existing["ids"])
        except Exception:
            pass

    stats = {
        "indexed_files": 0,
        "skipped_files": 0,
        "total_chunks": 0,
        "errors": []
    }

    for file_idx, filepath in enumerate(sorted(files)):
        filename = os.path.basename(filepath)
        safe_name = re.sub(r'[^\w\-.]', '_', filename)
        file_id_prefix = f"{lib_name}_{safe_name}"

        emit({
            "stage": "file_start",
            "file_index": file_idx + 1,
            "total_files": total_files,
            "filename": filename,
            "message": f"[{file_idx + 1}/{total_files}] 处理: {filename}"
        })

        current_hash = file_hash(filepath)
        hash_id = f"{file_id_prefix}_hash"

        if not force_rebuild and hash_id in existing_ids:
            try:
                result = collection.get(ids=[hash_id])
                if result and result["documents"] and result["documents"][0] == current_hash:
                    # 额外检查：该文件的第一个 chunk 是否存在
                    first_chunk_id = f"{file_id_prefix}_chunk_0"
                    chunk_check = collection.get(ids=[first_chunk_id])
                    if (chunk_check and chunk_check["documents"] and 
                        chunk_check["documents"][0] is not None and 
                        chunk_check["documents"][0] != ""):
                        stats["skipped_files"] += 1
                        emit({
                            "stage": "file_skip",
                            "filename": filename,
                            "message": f"  跳过（未修改）: {filename}"
                        })
                        continue
                    else:
                        # 哈希存在但向量缺失，重新索引
                        emit({
                            "stage": "file_reindex",
                            "filename": filename,
                            "message": f"  检测到向量缺失，重新索引: {filename}"
                        })
                        # 不 continue，继续执行后续索引流程
            except Exception:
                # 获取失败，也继续正常索引流程
                pass

        # 提取文本
        try:
            text = extract_text(filepath)
            if not text.strip():
                stats["errors"].append(f"{filename}: 提取文本为空（可能是扫描版PDF）")
                emit({"stage": "file_error", "filename": filename,
                      "message": f"  跳过: {filename} 文本为空（扫描版？）"})
                continue
        except Exception as e:
            stats["errors"].append(f"{filename}: {str(e)}")
            emit({"stage": "file_error", "filename": filename,
                  "message": f"  错误: {filename} - {str(e)}"})
            continue

        # 分块
        chunks = chunk_text(text)
        num_chunks = len(chunks)

        emit({
            "stage": "chunking_done",
            "filename": filename,
            "num_chunks": num_chunks,
            "message": f"  分块完成: {num_chunks} 个块"
        })

        if num_chunks == 0:
            stats["errors"].append(f"{filename}: 分块结果为空")
            continue

        # 生成 embedding
        emit({
            "stage": "embedding_start",
            "filename": filename,
            "num_chunks": num_chunks,
            "message": f"  生成向量中... ({num_chunks} 个块)"
        })

        try:
            embeddings = get_embeddings(chunks)
        except Exception as e:
            stats["errors"].append(f"{filename}: embedding 失败 - {str(e)}")
            emit({"stage": "file_error", "filename": filename,
                  "message": f"  Embedding 错误: {str(e)}"})
            continue

        emit({"stage": "embedding_done", "filename": filename,
              "message": "  向量生成完成"})

        # 写入 ChromaDB（手动传 embedding）
        ids = [f"{file_id_prefix}_chunk_{i}" for i in range(num_chunks)]
        metadatas = [
            {
                "source":       filename,
                "library":      lib_name,
                "chunk_index":  i,
                "total_chunks": num_chunks,
                "type":         "chunk",
            }
            for i in range(num_chunks)
        ]

        batch_size = 100
        for i in range(0, num_chunks, batch_size):
            end = min(i + batch_size, num_chunks)
            collection.upsert(
                ids=ids[i:end],
                embeddings=embeddings[i:end],
                documents=chunks[i:end],
                metadatas=metadatas[i:end]
            )

        # 存储文件哈希（用零向量占位，type=file_hash 供 retriever 过滤）
        hash_embedding = [0.0] * EMBEDDING_DIMENSIONS
        collection.upsert(
            ids=[hash_id],
            embeddings=[hash_embedding],
            documents=[current_hash],
            metadatas=[{"type": "file_hash", "source": filename, "library": lib_name}]
        )

        stats["indexed_files"] += 1
        stats["total_chunks"] += num_chunks

        emit({
            "stage": "file_done",
            "file_index": file_idx + 1,
            "total_files": total_files,
            "filename": filename,
            "num_chunks": num_chunks,
            "message": f"  ✓ 完成: {filename} ({num_chunks} 块)"
        })

    emit({
        "stage": "chunks_complete",
        "message": (
            f"向量索引完成。已索引 {stats['indexed_files']} 篇，"
            f"跳过 {stats['skipped_files']} 篇，共 {stats['total_chunks']} 个块"
        )
    })

    return stats


# ===== 摘要生成 =====
def generate_summaries(lib_name: str,
                       progress_callback: Optional[Callable] = None) -> dict:
    """为文献库生成 AI 摘要"""
    lib_path = os.path.join(PAPERS_DIR, lib_name)
    summary_collection = get_summary_collection(lib_name)

    files = []
    for f in os.listdir(lib_path):
        if f.lower().endswith(('.pdf', '.docx')) and not f.startswith('.'):
            files.append(os.path.join(lib_path, f))

    total_files = len(files)

    def emit(data):
        if progress_callback:
            progress_callback(data)

    emit({
        "stage": "summary_start",
        "lib": lib_name,
        "total_files": total_files,
        "message": f"开始生成 {lib_name} 的 AI 摘要，共 {total_files} 篇"
    })

    existing_summaries = set()
    try:
        existing = summary_collection.get()
        if existing and existing["ids"]:
            existing_summaries = set(existing["ids"])
    except Exception:
        pass

    stats = {"generated": 0, "skipped": 0, "errors": []}

    for file_idx, filepath in enumerate(sorted(files)):
        filename = os.path.basename(filepath)
        summary_id = f"{lib_name}_{filename}_summary"

        if summary_id in existing_summaries:
            stats["skipped"] += 1
            emit({
                "stage": "summary_skip",
                "file_index": file_idx + 1,
                "total_files": total_files,
                "filename": filename,
                "message": f"  [{file_idx + 1}/{total_files}] 跳过（已有摘要）: {filename}"
            })
            continue

        emit({
            "stage": "summary_generating",
            "file_index": file_idx + 1,
            "total_files": total_files,
            "filename": filename,
            "message": f"  [{file_idx + 1}/{total_files}] 生成摘要: {filename}"
        })

        try:
            text = extract_text(filepath)
            if not text.strip():
                stats["errors"].append(f"{filename}: 文本为空")
                continue
        except Exception as e:
            stats["errors"].append(f"{filename}: {str(e)}")
            continue

        # 限制输入长度（前15000词）
        words = text.split()
        if len(words) > 15000:
            text = " ".join(words[:15000])

        try:
            summary = call_claude(
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_content=f"文献标题: {filename}\n\n文献内容:\n{text}",
                max_tokens=2048
            )
        except Exception as e:
            stats["errors"].append(f"{filename}: Claude 调用失败 - {str(e)}")
            emit({
                "stage": "summary_error",
                "filename": filename,
                "message": f"  ✗ 摘要生成失败: {filename} - {str(e)}"
            })
            time.sleep(5)
            try:
                summary = call_claude(
                    system_prompt=SUMMARY_SYSTEM_PROMPT,
                    user_content=f"文献标题: {filename}\n\n文献内容:\n{text}",
                    max_tokens=2048
                )
            except Exception as e2:
                stats["errors"].append(f"{filename}: 重试失败 - {str(e2)}")
                continue

        try:
            summary_embedding = get_single_embedding(summary)
        except Exception as e:
            stats["errors"].append(f"{filename}: 摘要 embedding 失败 - {str(e)}")
            continue

        summary_collection.upsert(
            ids=[summary_id],
            embeddings=[summary_embedding],
            documents=[summary],
            metadatas=[{
                "source":  filename,
                "library": lib_name,
                "type":    "summary"
            }]
        )

        stats["generated"] += 1
        emit({
            "stage": "summary_done",
            "file_index": file_idx + 1,
            "total_files": total_files,
            "filename": filename,
            "message": f"  ✓ [{file_idx + 1}/{total_files}] 摘要完成: {filename}"
        })

        time.sleep(1)  # 控制速率

    emit({
        "stage": "summary_complete",
        "message": f"摘要生成完成。新生成 {stats['generated']} 篇，跳过 {stats['skipped']} 篇"
    })

    return stats