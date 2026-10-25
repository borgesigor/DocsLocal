const api = '/api/v1';
const $ = (selector) => document.querySelector(selector);

const state = {
    projects: [],
    project: null,
    document: null,
    revision: null,
    dirty: false,
    saveTimer: null,
    autosaveDelay: 1000,
};

async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(api + path, { ...options, headers });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(result?.error?.message || `Erro ${response.status}`);
    }
    return result;
}

function showToast(message) {
    const toast = $('#toast');
    toast.textContent = message;
    toast.classList.add('visible');
    setTimeout(() => toast.classList.remove('visible'), 2600);
}

function formatDate(value) {
    if (!value) return '—';
    return new Intl.DateTimeFormat('pt-BR', {
        day: '2-digit',
        month: 'short',
    }).format(new Date(value));
}

async function loadProjects() {
    state.projects = await request('/projects');
    $('#project-total').textContent = `${state.projects.length} ${state.projects.length === 1 ? 'projeto' : 'projetos'}`;

    const grid = $('#project-grid');
    grid.replaceChildren();
    if (state.projects.length === 0) {
        grid.innerHTML = '<div class="empty-projects">Ainda não há projetos. Crie um para começar a organizar seus documentos.</div>';
        return;
    }

    for (const project of state.projects) {
        const card = document.createElement('article');
        card.className = 'project-card';
        card.tabIndex = 0;
        card.innerHTML = '<div class="folder-icon">▱</div><h3></h3><p></p><div class="card-meta"><span></span><span></span></div>';
        card.querySelector('h3').textContent = project.name;
        card.querySelector('p').textContent = project.description || 'Sem descrição';
        const documentLabel = project.document_count === 1 ? 'documento' : 'documentos';
        card.querySelector('.card-meta span:first-child').textContent = (
            `${project.document_count} ${documentLabel}`
        );
        card.querySelector('.card-meta span:last-child').textContent = formatDate(project.updated_at);
        card.addEventListener('click', () => openProject(project.id));
        card.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') openProject(project.id);
        });
        grid.append(card);
    }
}

async function openProject(projectId) {
    state.project = await request(`/projects/${projectId}`);
    $('#home').hidden = true;
    $('#workspace').hidden = false;
    $('#project-name').textContent = state.project.name;
    $('#project-description').textContent = state.project.description;
    $('#crumbs').textContent = state.project.name;
    $('#history').hidden = false;
    await refreshTree();
}

function appendTree(nodes, container, depth = 0) {
    for (const node of nodes) {
        const row = document.createElement('div');
        row.className = 'tree-row';
        row.style.paddingLeft = `${7 + depth * 12}px`;
        row.innerHTML = `<span class="glyph">${node.type === 'folder' ? '▱' : '▤'}</span><span></span>`;
        row.lastElementChild.textContent = node.type === 'folder' ? node.name : node.title;
        container.append(row);

        if (node.type === 'folder') {
            const children = document.createElement('div');
            children.className = 'tree-children';
            row.addEventListener('click', () => children.classList.toggle('hidden'));
            appendTree(node.children, children, depth + 1);
            container.append(children);
            continue;
        }

        row.dataset.id = node.id;
        row.addEventListener('click', () => openDocument(node.id));
        if (state.document?.id === node.id) row.classList.add('active');
    }
}

async function refreshTree() {
    const tree = await request(`/projects/${state.project.id}/tree`);
    const container = $('#tree');
    container.replaceChildren();
    appendTree(tree, container);
}

async function openDocument(documentId) {
    if (state.dirty) {
        clearTimeout(state.saveTimer);
        if (!(await saveDocument())) return;
    }

    state.document = await request(`/projects/${state.project.id}/documents/${documentId}`);
    state.revision = state.document.revision;
    state.dirty = false;
    $('#editor').value = state.document.content;
    $('#editor').disabled = false;
    $('#doc-title').textContent = state.document.title;
    $('#doc-path').textContent = state.document.path;
    $('#doc-menu').hidden = false;
    $('#save-state').textContent = 'Salvo localmente';
    renderPreview();
    await refreshTree();
}

async function saveDocument() {
    if (!state.document || !state.dirty) return true;
    $('#save-state').textContent = 'Salvando…';

    try {
        const saved = await request(`/projects/${state.project.id}/documents/${state.document.id}`, {
            method: 'PUT',
            body: JSON.stringify({ content: $('#editor').value, revision: state.revision }),
        });
        state.document = saved;
        state.revision = saved.revision;
        state.dirty = false;
        $('#save-state').textContent = 'Salvo localmente';
        renderPreview();
        await refreshTree();
        await updateSyncStatus();
        return true;
    } catch (error) {
        $('#save-state').textContent = 'Falha ao salvar';
        showToast(error.message);
        return false;
    }
}

function escapeHtml(text) {
    const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return text.replace(/[&<>"']/g, (character) => entities[character]);
}

function renderInlineMarkdown(text) {
    return escapeHtml(text)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function renderMarkdown(source) {
    const output = [];
    let insideCodeBlock = false;
    let insideList = false;

    for (const line of source.split('\n')) {
        if (line.startsWith('```')) {
            if (insideList) {
                output.push('</ul>');
                insideList = false;
            }
            output.push(insideCodeBlock ? '</code></pre>' : '<pre><code>');
            insideCodeBlock = !insideCodeBlock;
            continue;
        }
        if (insideCodeBlock) {
            output.push(escapeHtml(line));
            continue;
        }

        const heading = line.match(/^(#{1,6})\s+(.*)$/);
        const listItem = line.match(/^[-*+]\s+(.*)$/);
        if (heading) {
            if (insideList) output.push('</ul>');
            insideList = false;
            const level = heading[1].length;
            output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
        } else if (listItem) {
            if (!insideList) output.push('<ul>');
            insideList = true;
            const checkbox = listItem[1].match(/^\[([ xX])\]\s+(.*)$/);
            if (checkbox) {
                const checked = checkbox[1].toLowerCase() === 'x' ? ' checked' : '';
                output.push(`<li><input type="checkbox" disabled${checked}> ${renderInlineMarkdown(checkbox[2])}</li>`);
            } else {
                output.push(`<li>${renderInlineMarkdown(listItem[1])}</li>`);
            }
        } else if (line.startsWith('> ')) {
            output.push(`<blockquote>${renderInlineMarkdown(line.slice(2))}</blockquote>`);
        } else if (line.trim()) {
            output.push(`<p>${renderInlineMarkdown(line)}</p>`);
        } else if (insideList) {
            output.push('</ul>');
            insideList = false;
        }
    }

    if (insideList) output.push('</ul>');
    if (insideCodeBlock) output.push('</code></pre>');
    return output.join('') || '<div class="empty-note">A visualização do documento aparece aqui.</div>';
}

function renderPreview() {
    $('#preview').innerHTML = renderMarkdown($('#editor').value);
}

function setEditorMode(mode) {
    const editorLayout = $('#editor-layout');
    editorLayout.style.gridTemplateColumns = mode === 'edit' ? '1fr 0' : mode === 'preview' ? '0 1fr' : '1fr 1fr';
    $('.editor-pane').classList.toggle('hidden', mode === 'preview');
    $('.preview-pane').classList.toggle('hidden', mode === 'edit');
    document.querySelectorAll('.mode-switch button').forEach((button) => {
        button.classList.toggle('selected', button.dataset.mode === mode);
    });
}

document.querySelectorAll('.mode-switch button').forEach((button) => {
    button.addEventListener('click', () => setEditorMode(button.dataset.mode));
});

function showModal(title, description, fields, onSubmit, submitLabel = 'Continuar') {
    const dialog = $('#modal');
    const form = $('#modal-form');
    const content = $('#modal-content');
    content.replaceChildren();

    const heading = document.createElement('h2');
    heading.textContent = title;
    content.append(heading);
    const details = document.createElement('p');
    details.textContent = description;
    content.append(details);

    for (const field of fields) {
        const label = document.createElement('label');
        label.textContent = field.label;
        const input = document.createElement(field.multiline ? 'textarea' : 'input');
        input.name = field.name;
        input.placeholder = field.placeholder || '';
        input.required = Boolean(field.required);
        if (field.value) input.value = field.value;
        content.append(label, input);
    }

    $('#modal-submit').textContent = submitLabel;
    form.onsubmit = async (event) => {
        event.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries());
        try {
            await onSubmit(values);
            form.onsubmit = null;
            dialog.close();
        } catch (error) {
            showToast(error.message);
        }
    };
    dialog.showModal();
}

$('#new-project').addEventListener('click', () => showModal(
    'Novo projeto',
    'Um espaço independente para reunir seus documentos.',
    [
        { name: 'name', label: 'Nome do projeto', placeholder: 'Ex.: Caderno de pesquisa', required: true },
        { name: 'description', label: 'Descrição', placeholder: 'Do que trata este projeto?', multiline: true },
    ],
    async (values) => {
        await request('/projects', { method: 'POST', body: JSON.stringify(values) });
        await loadProjects();
        await updateSyncStatus();
        showToast('Projeto criado');
    },
    'Criar projeto',
));

$('#new-document').addEventListener('click', () => showModal(
    'Novo documento',
    'O arquivo será salvo como Markdown dentro deste projeto.',
    [
        { name: 'title', label: 'Título', placeholder: 'Ex.: Notas da reunião', required: true },
        { name: 'path', label: 'Caminho', placeholder: 'docs/notas-da-reuniao.md', required: true },
    ],
    async (values) => {
        const document = await request(`/projects/${state.project.id}/documents`, {
            method: 'POST',
            body: JSON.stringify({ title: values.title, path: values.path }),
        });
        await refreshTree();
        await openDocument(document.id);
        await updateSyncStatus();
    },
    'Criar documento',
));

$('#new-folder').addEventListener('click', () => showModal(
    'Nova pasta',
    'Organize documentos em uma pasta do projeto.',
    [{ name: 'path', label: 'Caminho da pasta', placeholder: 'docs/referencias', required: true }],
    async (values) => {
        await request(`/projects/${state.project.id}/folders`, {
            method: 'POST',
            body: JSON.stringify(values),
        });
        await refreshTree();
        await updateSyncStatus();
    },
    'Criar pasta',
));

$('#rename-document').addEventListener('click', () => showModal(
    'Renomear ou mover',
    'Informe o novo caminho do arquivo Markdown.',
    [{ name: 'path', label: 'Caminho', value: state.document.path, required: true }],
    async (values) => {
        const updated = await request(`/projects/${state.project.id}/documents/${state.document.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ path: values.path }),
        });
        state.document = updated;
        state.revision = updated.revision;
        $('#doc-title').textContent = updated.title;
        $('#doc-path').textContent = updated.path;
        await refreshTree();
        await updateSyncStatus();
    },
    'Salvar caminho',
));

$('#delete-document').addEventListener('click', async () => {
    if (!state.document || !confirm(`Excluir permanentemente “${state.document.title}”?`)) return;
    try {
        if (state.dirty) {
            clearTimeout(state.saveTimer);
            if (!(await saveDocument())) return;
        }
        await request(`/projects/${state.project.id}/documents/${state.document.id}`, { method: 'DELETE' });
        state.document = null;
        state.dirty = false;
        $('#editor').value = '';
        $('#editor').disabled = true;
        $('#preview').innerHTML = '<div class="empty-note">Escolha um documento ou crie um novo.</div>';
        $('#doc-title').textContent = 'Selecione um documento';
        $('#doc-path').textContent = '';
        $('#doc-menu').hidden = true;
        await refreshTree();
        await updateSyncStatus();
        showToast('Documento excluído');
    } catch (error) {
        showToast(error.message);
    }
});

$('#back-home').addEventListener('click', async () => {
    if (state.dirty) {
        clearTimeout(state.saveTimer);
        if (!(await saveDocument())) return;
    }
    state.project = null;
    state.document = null;
    $('#workspace').hidden = true;
    $('#home').hidden = false;
    $('#crumbs').textContent = 'Seus projetos';
    $('#history').hidden = true;
    await loadProjects();
});

$('#project-settings').addEventListener('click', async () => {
    const action = prompt('Digite “editar” para alterar o projeto ou “arquivar” para arquivá-lo.');
    if (action?.toLowerCase() === 'arquivar') {
        if (state.dirty) {
            clearTimeout(state.saveTimer);
            if (!(await saveDocument())) return;
        }
        if (!confirm(`Arquivar “${state.project.name}”? Os arquivos permanecem no repositório.`)) return;
        try {
            await request(`/projects/${state.project.id}?confirm=true`, { method: 'DELETE' });
            state.project = null;
            state.document = null;
            $('#workspace').hidden = true;
            $('#home').hidden = false;
            await loadProjects();
            await updateSyncStatus();
        } catch (error) {
            showToast(error.message);
        }
        return;
    }
    if (action?.toLowerCase() !== 'editar') return;

    showModal(
        'Configurações do projeto',
        'Altere o nome ou a descrição.',
        [
            { name: 'name', label: 'Nome', value: state.project.name, required: true },
            { name: 'description', label: 'Descrição', value: state.project.description, multiline: true },
        ],
        async (values) => {
            state.project = await request(`/projects/${state.project.id}`, {
                method: 'PATCH',
                body: JSON.stringify(values),
            });
            $('#project-name').textContent = state.project.name;
            $('#project-description').textContent = state.project.description;
            $('#crumbs').textContent = state.project.name;
            await loadProjects();
        },
        'Salvar',
    );
});

$('#history').addEventListener('click', async () => {
    const commits = await request('/sync/history');
    showToast(commits.length ? commits.map((commit) => `${commit.commit} ${commit.message}`).join(' · ') : 'Ainda não há commits locais.');
});

$('#sync-now').addEventListener('click', async () => {
    await request('/sync/trigger', { method: 'POST' });
    showToast('Sincronização solicitada');
    await updateSyncStatus();
});

$('#project-search').addEventListener('input', async (event) => {
    const query = event.target.value.trim();
    if (query.length < 2) {
        $('#project-results').hidden = true;
        $('#tree').hidden = false;
        return;
    }

    try {
        const results = await request(`/search?q=${encodeURIComponent(query)}&project_id=${state.project.id}`);
        const container = $('#project-results');
        container.replaceChildren();
        container.hidden = false;
        $('#tree').hidden = true;
        if (results.length === 0) {
            container.innerHTML = '<div class="results-empty">Nenhum documento encontrado.</div>';
            return;
        }

        for (const result of results) {
            const item = document.createElement('div');
            item.className = 'result-card';
            item.innerHTML = '<h3></h3><span class="result-path"></span><p></p>';
            item.querySelector('h3').textContent = result.title;
            item.querySelector('.result-path').textContent = result.path;
            item.querySelector('p').textContent = result.snippet;
            item.addEventListener('click', async () => {
                const documents = await request(`/projects/${state.project.id}/documents`);
                const match = documents.find((document) => document.path === result.path);
                if (match) await openDocument(match.id);
                container.hidden = true;
                $('#tree').hidden = false;
            });
            container.append(item);
        }
    } catch (error) {
        showToast(error.message);
    }
});

$('#editor').addEventListener('input', () => {
    state.dirty = true;
    $('#save-state').textContent = 'Alterações não salvas';
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(saveDocument, state.autosaveDelay);
    renderPreview();
});

$('#editor').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        clearTimeout(state.saveTimer);
        saveDocument();
    }
    if (event.key === 'Tab') {
        event.preventDefault();
        const editor = event.target;
        editor.setRangeText('  ', editor.selectionStart, editor.selectionEnd, 'end');
        editor.dispatchEvent(new Event('input'));
    }
});

document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !$('#workspace').hidden) {
        event.preventDefault();
        $('#project-search').focus();
    }
    if (event.key === 'Escape' && state.dirty) {
        clearTimeout(state.saveTimer);
        saveDocument();
    }
});

async function updateSyncStatus() {
    try {
        const status = await request('/sync/status');
        const pill = $('#sync-pill');
        pill.classList.toggle('error', ['error', 'conflict'].includes(status.state));
        pill.classList.toggle('syncing', ['syncing', 'queued'].includes(status.state));

        const labels = {
            synced: 'Sincronizado',
            syncing: 'Sincronizando',
            queued: 'Na fila',
            error: 'Falha na sincronização',
            conflict: 'Conflito Git',
            idle: 'Backup pendente',
            disabled: 'Git desativado',
        };
        pill.querySelector('span').textContent = labels[status.state] || 'Backup pendente';
        if (state.document && !state.dirty) {
            const message = status.state === 'synced'
                ? 'Sincronizado com GitHub'
                : status.state === 'error'
                    ? 'Falha na sincronização'
                    : 'Aguardando sincronização';
            $('#save-state').textContent = message;
        }
    } catch {
        // The local editor remains usable while the status endpoint is unavailable.
    }
}

async function initialize() {
    try {
        const config = await request('/system/config');
        state.autosaveDelay = config.editor.autosave_debounce_ms;
        await loadProjects();
        await updateSyncStatus();
    } catch (error) {
        showToast(error.message);
    }
}

initialize();
setInterval(updateSyncStatus, 5000);
