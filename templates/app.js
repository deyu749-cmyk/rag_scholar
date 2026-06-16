// ===== 全局状态 =====
let currentWritingStyle = "polish";
let currentWritingOutput = "";
let writingHistory = [];
let conversationHistory = [];
let searchHistory = [];
let lastSearchResults = null;
let lastAnalysis = "";
let lastQuery = "";
let currentWritingMode = "rewrite";     // 写作子模式: rewrite | review | annotate
let currentReviewScope = "review";      // 综述类型: review | overview
let currentReviewOutput = "";
let currentAnnotateOutput = "";

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    loadLibs();
    loadHistory();
    initTabs();
});

// ===== Tab 切换 =====
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });
}

// ===== 加载文献库 =====
async function loadLibs() {
    try {
        const res = await fetch('/api/libs');
        const data = await res.json();
        const containers = ['lib-checkboxes-search', 'lib-checkboxes-writing', 'lib-checkboxes-index'];

        containers.forEach(containerId => {
            const container = document.getElementById(containerId);
            container.innerHTML = '';
            data.libs.forEach(lib => {
                const label = document.createElement('label');
                label.className = 'lib-checkbox';
                label.innerHTML = `
                    <input type="checkbox" value="${lib.name}" checked>
                    <span>
                        <span class="lib-name">${lib.name}</span>
                        <span class="lib-info">${lib.file_count}篇 · ${lib.indexed_chunks}块 · ${lib.summary_count}摘要</span>
                    </span>
                `;
                container.appendChild(label);
            });
        });
    } catch (e) {
        console.error('加载文献库失败:', e);
    }
}

// ===== 获取选中的库 =====
function getSelectedLibs(containerId) {
    const boxes = document.querySelectorAll(`#${containerId} input[type="checkbox"]:checked`);
    return Array.from(boxes).map(cb => cb.value);
}

// ===== 工具函数 =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime() {
    const now = new Date();
    return now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// ===== 检索 =====
async function doSearch() {
    const query = document.getElementById('search-input').value.trim();
    if (!query) return;

    const libs = getSelectedLibs('lib-checkboxes-search');
    if (libs.length === 0) {
        alert('请选择至少一个文献库');
        return;
    }

    document.getElementById('search-loading').classList.add('show');
    document.getElementById('results-panel').classList.remove('show');
    document.getElementById('btn-search').disabled = true;

    try {
        const res = await fetch('/api/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, libs })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        lastSearchResults = data.results;
        lastAnalysis = data.analysis;
        lastQuery = query;

        conversationHistory.push({ role: 'user', content: query });
        conversationHistory.push({ role: 'assistant', content: data.analysis });

        displayResults(data);
        addToHistory(query, data.mode);
    } catch (e) {
        alert('检索失败: ' + e.message);
    } finally {
        document.getElementById('search-loading').classList.remove('show');
        document.getElementById('btn-search').disabled = false;
    }
}

// ===== 显示结果 =====
function displayResults(data) {
    const panel = document.getElementById('results-panel');
    const badge = document.getElementById('mode-badge');
    const content = document.getElementById('analysis-content');

    badge.textContent = data.mode === 'summaries' ? '全局分析' : '精准检索';
    badge.className = 'mode-badge ' + data.mode;

    let html = escapeHtml(data.analysis);

    // 解析 [段落N]
    html = html.replace(/\[段落(\d+)\]/g, (match, num) => {
        const idx = parseInt(num) - 1;
        if (idx >= 0 && idx < data.results.length) {
            const r = data.results[idx];
            const doc = escapeHtml(r.document.substring(0, 500)) + (r.document.length > 500 ? '...' : '');
            return `<span class="ref-toggle" onclick="toggleRef(this)">[段落${num}]</span><div class="ref-block">${doc}<div class="ref-source">来源: ${escapeHtml(r.source)} | 相关度: ${r.score}</div></div>`;
        }
        return match;
    });

    // 解析 [文献N]
    html = html.replace(/\[文献(\d+)\]/g, (match, num) => {
        const idx = parseInt(num) - 1;
        if (idx >= 0 && idx < data.results.length) {
            const r = data.results[idx];
            const doc = escapeHtml(r.document.substring(0, 500)) + (r.document.length > 500 ? '...' : '');
            return `<span class="ref-toggle" onclick="toggleRef(this)">[文献${num}]</span><div class="ref-block">${doc}<div class="ref-source">来源: ${escapeHtml(r.source)} | 相关度: ${r.score}</div></div>`;
        }
        return match;
    });

    content.innerHTML = html;
    panel.classList.add('show');
}

// ===== 折叠引用 =====
function toggleRef(el) {
    const block = el.nextElementSibling;
    if (block && block.classList.contains('ref-block')) {
        block.classList.toggle('show');
    }
}

// ===== 总结 =====
async function doSummarize() {
    if (conversationHistory.length === 0) {
        alert('暂无对话内容可总结');
        return;
    }

    document.getElementById('search-loading').classList.add('show');
    document.getElementById('btn-summarize').disabled = true;

    try {
        const res = await fetch('/api/summarize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ history: conversationHistory })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        const badge = document.getElementById('mode-badge');
        const content = document.getElementById('analysis-content');
        badge.textContent = '对话总结';
        badge.className = 'mode-badge summaries';
        content.innerHTML = escapeHtml(data.summary);
        document.getElementById('results-panel').classList.add('show');
    } catch (e) {
        alert('总结失败: ' + e.message);
    } finally {
        document.getElementById('search-loading').classList.remove('show');
        document.getElementById('btn-summarize').disabled = false;
    }
}

// ===== 审查（审稿人模式）=====
async function doRecheck() {
    if (!lastAnalysis || !lastSearchResults) {
        alert('请先进行一次检索');
        return;
    }

    document.getElementById('search-loading').classList.add('show');
    document.getElementById('btn-recheck').disabled = true;

    try {
        const res = await fetch('/api/recheck', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: lastQuery,
                analysis: lastAnalysis,
                results: lastSearchResults
            })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        const badge = document.getElementById('mode-badge');
        const content = document.getElementById('analysis-content');
        badge.textContent = '审稿意见';
        badge.className = 'mode-badge summaries';
        content.innerHTML = escapeHtml(data.review);
        document.getElementById('results-panel').classList.add('show');
    } catch (e) {
        alert('审查失败: ' + e.message);
    } finally {
        document.getElementById('search-loading').classList.remove('show');
        document.getElementById('btn-recheck').disabled = false;
    }
}

// ===== 复制分析结果 =====
function copyAnalysis() {
    const content = document.getElementById('analysis-content').innerText;
    navigator.clipboard.writeText(content).then(() => {
        alert('已复制到剪贴板');
    }).catch(() => {
        // fallback
        const ta = document.createElement('textarea');
        ta.value = content;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('已复制到剪贴板');
    });
}

// ===== 清空结果 =====
function clearResults() {
    document.getElementById('results-panel').classList.remove('show');
    document.getElementById('analysis-content').innerHTML = '';
    lastSearchResults = null;
    lastAnalysis = "";
    lastQuery = "";
}

// ===== 历史记录 =====
function addToHistory(query, mode) {
    searchHistory.unshift({
        query: query,
        mode: mode,
        time: formatTime()
    });
    // 最多保留 20 条
    if (searchHistory.length > 20) {
        searchHistory = searchHistory.slice(0, 20);
    }
    saveHistory();
    renderHistory();
}

function renderHistory() {
    const list = document.getElementById('history-list');
    list.innerHTML = '';
    searchHistory.forEach((item, idx) => {
        const div = document.createElement('div');
        div.className = 'history-item';
        div.innerHTML = `
            <div class="history-query">${escapeHtml(item.query.substring(0, 60))}${item.query.length > 60 ? '...' : ''}</div>
            <div class="history-time">${item.time} · ${item.mode === 'summaries' ? '全局' : '精准'}</div>
        `;
        div.onclick = () => {
            document.getElementById('search-input').value = item.query;
        };
        list.appendChild(div);
    });
}

function saveHistory() {
    try {
        localStorage.setItem('rag_search_history', JSON.stringify(searchHistory));
    } catch (e) {}
}

function loadHistory() {
    try {
        const saved = localStorage.getItem('rag_search_history');
        if (saved) {
            searchHistory = JSON.parse(saved);
            renderHistory();
        }
    } catch (e) {}
}

// ===== 写作模式 =====
function setWritingStyle(style, btn) {
    currentWritingStyle = style;
    document.querySelectorAll('.style-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

async function doWrite() {
    const text = document.getElementById('writing-input').value.trim();
    if (!text) {
        alert('请输入需要处理的文本');
        return;
    }

    const libs = getSelectedLibs('lib-checkboxes-writing');

    document.getElementById('writing-loading').classList.add('show');
    document.getElementById('btn-write').disabled = true;

    try {
        const res = await fetch('/api/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                libs: libs,
                style: currentWritingStyle
            })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        currentWritingOutput = data.rewritten_text;
        document.getElementById('writing-output').textContent = currentWritingOutput;

        // 重置写作对话历史
        writingHistory = [
            { role: 'user', content: '原文：' + text },
            { role: 'assistant', content: currentWritingOutput }
        ];
    } catch (e) {
        alert('处理失败: ' + e.message);
    } finally {
        document.getElementById('writing-loading').classList.remove('show');
        document.getElementById('btn-write').disabled = false;
    }
}

async function doWritingChat() {
    const instruction = document.getElementById('writing-chat-input').value.trim();
    if (!instruction) return;
    if (!currentWritingOutput) {
        alert('请先进行一次写作处理');
        return;
    }

    const libs = getSelectedLibs('lib-checkboxes-writing');

    document.getElementById('writing-loading').classList.add('show');

    try {
        const res = await fetch('/api/write/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: currentWritingOutput,
                instruction: instruction,
                libs: libs,
                history: writingHistory
            })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        currentWritingOutput = data.result;
        document.getElementById('writing-output').textContent = currentWritingOutput;
        document.getElementById('writing-chat-input').value = '';

        // 更新对话历史
        writingHistory.push({ role: 'user', content: instruction });
        writingHistory.push({ role: 'assistant', content: currentWritingOutput });
    } catch (e) {
        alert('修改失败: ' + e.message);
    } finally {
        document.getElementById('writing-loading').classList.remove('show');
    }
}

function copyWritingOutput() {
    if (!currentWritingOutput) return;
    navigator.clipboard.writeText(currentWritingOutput).then(() => {
        alert('已复制到剪贴板');
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = currentWritingOutput;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('已复制到剪贴板');
    });
}

// ===== 索引管理 =====
function startIndexing() {
    const libs = getSelectedLibs('lib-checkboxes-index');
    if (libs.length === 0) {
        alert('请选择至少一个文献库');
        return;
    }

    const forceRebuild = document.getElementById('opt-force-rebuild').checked;
    const genSummaries = document.getElementById('opt-gen-summaries').checked;

    document.getElementById('btn-start-index').disabled = true;
    document.getElementById('btn-delete-index').disabled = true;

    const progressPanel = document.getElementById('progress-panel');
    const progressLog = document.getElementById('progress-log');
    const progressBar = document.getElementById('progress-bar');

    progressPanel.classList.add('show');
    progressLog.innerHTML = '';
    progressBar.style.width = '0%';

    addProgressLine('开始索引任务...', 'info');

    // SSE 连接
    fetch('/api/index', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            libs: libs,
            force_rebuild: forceRebuild,
            generate_summaries: genSummaries
        })
    }).then(response => {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        function read() {
            reader.read().then(({ done, value }) => {
                if (done) {
                    onIndexingDone();
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // 保留未完成的行

                lines.forEach(line => {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            handleProgressMessage(data);
                        } catch (e) {}
                    } else if (line.startsWith('event: done')) {
                        onIndexingDone();
                    }
                });

                read();
            });
        }

        read();
    }).catch(e => {
        addProgressLine('连接失败: ' + e.message, 'error');
        onIndexingDone();
    });
}

function handleProgressMessage(data) {
    const stage = data.stage || '';
    const message = data.message || '';

    if (stage === 'error') {
        addProgressLine(message, 'error');
    } else if (stage === 'lib_start') {
        addProgressLine(message, 'info');
    } else if (stage === 'lib_index_done' || stage === 'lib_summary_done' || stage === 'all_done') {
        addProgressLine(message, 'success');
    } else if (data.current && data.total) {
        // 进度更新
        const pct = Math.round((data.current / data.total) * 100);
        document.getElementById('progress-bar').style.width = pct + '%';
        if (message) {
            addProgressLine(message, '');
        }
    } else if (message) {
        addProgressLine(message, '');
    }
}

function addProgressLine(text, type) {
    const log = document.getElementById('progress-log');
    const line = document.createElement('div');
    line.className = 'progress-line' + (type ? ' ' + type : '');
    line.textContent = '[' + formatTime() + '] ' + text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
}

function onIndexingDone() {
    document.getElementById('btn-start-index').disabled = false;
    document.getElementById('btn-delete-index').disabled = false;
    document.getElementById('progress-bar').style.width = '100%';
    addProgressLine('任务结束', 'success');
    // 刷新库信息
    loadLibs();
}

async function deleteSelectedIndex() {
    const libs = getSelectedLibs('lib-checkboxes-index');
    if (libs.length === 0) {
        alert('请选择要删除的文献库');
        return;
    }

    if (!confirm(`确定要删除以下库的索引？\n${libs.join(', ')}\n\n此操作不可恢复。`)) {
        return;
    }

    for (const lib of libs) {
        try {
            const res = await fetch(`/api/libs/${lib}/delete_index`, { method: 'POST' });
            const data = await res.json();
            if (data.error) {
                alert(`删除 ${lib} 失败: ${data.error}`);
            }
        } catch (e) {
            alert(`删除 ${lib} 失败: ${e.message}`);
        }
    }

    alert('删除完成');
    loadLibs();
}

// ===== 写作子模式切换 =====
function switchWritingMode(mode, btn) {
    currentWritingMode = mode;
    document.querySelectorAll('.writing-mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.writing-mode-content').forEach(c => c.classList.remove('active'));
    document.getElementById('wmode-' + mode).classList.add('active');
}

// ===== 文献综述范围切换 =====
function setReviewScope(scope, btn) {
    currentReviewScope = scope;
    document.querySelectorAll('#wmode-review .style-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

// ===== 生成文献综述 =====
async function doReview() {
    const topic = document.getElementById('review-topic-input').value.trim();
    if (!topic) {
        alert('请输入研究主题');
        return;
    }

    const libs = getSelectedLibs('lib-checkboxes-writing');
    if (libs.length === 0) {
        alert('请选择至少一个文献库');
        return;
    }

    document.getElementById('writing-loading').classList.add('show');
    document.getElementById('btn-review').disabled = true;

    try {
        const res = await fetch('/api/write/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                topic: topic,
                libs: libs,
                scope: currentReviewScope
            })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        currentReviewOutput = data.text;
        document.getElementById('review-output').textContent = currentReviewOutput;

        // 显示参考文献列表
        const refList = document.getElementById('review-refs');
        if (data.references_used && data.references_used.length > 0) {
            refList.style.display = 'block';
            refList.innerHTML = '<h4>引用的文献来源</h4>' +
                data.references_used.map(r =>
                    `<div class="ref-item"><span class="ref-source-name">${escapeHtml(r.source)}</span><span class="ref-score">相关度: ${r.score.toFixed(3)}</span></div>`
                ).join('');
        } else {
            refList.style.display = 'none';
        }
    } catch (e) {
        alert('生成失败: ' + e.message);
    } finally {
        document.getElementById('writing-loading').classList.remove('show');
        document.getElementById('btn-review').disabled = false;
    }
}

function copyReviewOutput() {
    if (!currentReviewOutput) return;
    navigator.clipboard.writeText(currentReviewOutput).then(() => {
        alert('已复制到剪贴板');
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = currentReviewOutput;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('已复制到剪贴板');
    });
}

// ===== 引用标注 =====
async function doAnnotate() {
    const text = document.getElementById('annotate-input').value.trim();
    if (!text) {
        alert('请粘贴需要标注的文章');
        return;
    }

    const libs = getSelectedLibs('lib-checkboxes-writing');
    if (libs.length === 0) {
        alert('请选择至少一个文献库');
        return;
    }

    document.getElementById('writing-loading').classList.add('show');
    document.getElementById('btn-annotate').disabled = true;

    try {
        const res = await fetch('/api/write/annotate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                libs: libs
            })
        });
        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        currentAnnotateOutput = data.annotated_text;
        const outputEl = document.getElementById('annotate-output');
        outputEl.innerHTML = escapeHtml(currentAnnotateOutput);

        // 显示可引用文献列表
        const refList = document.getElementById('annotate-refs');
        if (data.citations && data.citations.length > 0) {
            refList.style.display = 'block';
            refList.innerHTML = `<h4>可引用的文献段落（共 ${data.total_suggestions} 篇）</h4>` +
                data.citations.map(r =>
                    `<div class="ref-item">
                        <div class="ref-source-name">[参考${r.ref_id}] ${escapeHtml(r.source)}</div>
                        <div class="ref-preview">${escapeHtml(r.text_preview)}</div>
                        <span class="ref-score">相关度: ${r.score.toFixed(3)}</span>
                    </div>`
                ).join('');
        } else {
            refList.style.display = 'none';
        }
    } catch (e) {
        alert('标注失败: ' + e.message);
    } finally {
        document.getElementById('writing-loading').classList.remove('show');
        document.getElementById('btn-annotate').disabled = false;
    }
}

function copyAnnotateOutput() {
    if (!currentAnnotateOutput) return;
    navigator.clipboard.writeText(currentAnnotateOutput).then(() => {
        alert('已复制到剪贴板');
    }).catch(() => {
        const ta = document.createElement('textarea');
        ta.value = currentAnnotateOutput;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        alert('已复制到剪贴板');
    });
}

// ===== 键盘快捷键 =====
document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') {
        const activeTab = document.querySelector('.tab-content.active');
        if (activeTab.id === 'tab-search') {
            doSearch();
        } else if (activeTab.id === 'tab-writing') {
            if (currentWritingMode === 'rewrite') {
                doWrite();
            } else if (currentWritingMode === 'review') {
                doReview();
            } else if (currentWritingMode === 'annotate') {
                doAnnotate();
            }
        }
    }
});