// ===== RAG Scholar Index Admin =====

document.addEventListener('DOMContentLoaded', () => {
    loadLibs();
});

function formatTime() {
    const now = new Date();
    return now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function getSelectedLibs() {
    const boxes = document.querySelectorAll('#lib-checkboxes-index input[type="checkbox"]:checked');
    return Array.from(boxes).map(cb => cb.value);
}

// ===== Load Libraries =====
async function loadLibs() {
    try {
        const res = await fetch('/api/libs');
        const data = await res.json();
        const container = document.getElementById('lib-checkboxes-index');
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
    } catch (e) {
        console.error('加载文献库失败:', e);
    }
}

// ===== Start Indexing =====
function startIndexing() {
    const libs = getSelectedLibs();
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
                buffer = lines.pop();

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
        const pct = Math.round((data.current / data.total) * 100);
        document.getElementById('progress-bar').style.width = pct + '%';
        if (message) addProgressLine(message, '');
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
    loadLibs();
}

// ===== Delete Index =====
async function deleteSelectedIndex() {
    const libs = getSelectedLibs();
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
