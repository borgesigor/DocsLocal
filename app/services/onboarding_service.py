"""Maintain the protected local guide and its bundled agent skill."""

from pathlib import Path

from app.services import document_service, project_service
from app.services.storage import atomic_write, repository_operation
from app.services.toml_writer import dumps_values

WELCOME_CONTENT = '''# Bem-vindo ao Docs Local

O Docs Local organiza sua documentação em projetos, pastas e arquivos Markdown.
Os documentos ficam no seu computador e você pode trabalhar offline. O login
com GitHub é opcional e serve para manter um backup privado.

## Crie seu primeiro projeto

Clique em **+** ao lado de Projetos e informe um nome e uma descrição.
Selecione o projeto na barra lateral para acessar seus arquivos. Cada projeto
tem um arquivo `index.md`, que funciona como sua página inicial.

Use o menu de contexto (botão direito) para renomear projetos ou excluí-los.
A exclusão de um projeto o arquiva localmente.

## Organize documentos e pastas

Crie um documento pelo botão de novo arquivo. Informe um nome como `introducao.md`
ou `guias/instalacao.md` para organizá-lo em uma pasta. O menu de contexto da
árvore de arquivos permite criar pastas, renomear e excluir documentos.

Documentos usam a extensão `.md`. Arquivos de apoio, como imagens e PDFs, ficam
na pasta `assets` do projeto e podem ser enviados pela API local.

## Escreva em Markdown

Abra um documento e clique em **Editar Markdown**. Salve pelo botão **Salvar**
antes de sair da edição. Depois, volte à visualização para ler o documento
formatado.

```markdown
# Título principal
## Uma seção

Texto com **negrito**, *itálico* e `código`.

- Primeiro item
- Segundo item

[Link para outro documento](docs/introducao.md)
```

Também é possível usar tabelas, listas de tarefas e blocos de código.
Use o campo de busca para localizar conteúdo nos documentos do projeto.

## Conecte ao GitHub para fazer backup

Clique em **Logar com GitHub**, copie o código exibido e informe-o na página
oficial do GitHub que será aberta. Autorize o Docs Local. A conexão será
concluída automaticamente no aplicativo; você não precisa configurar credenciais
de desenvolvedor. Se a janela não abrir, use **Abrir GitHub** no diálogo.
Após a conexão, o aplicativo cria ou verifica um repositório privado
chamado `docs-local-backup` na conta autorizada.

Se já existe um backup, os arquivos do GitHub são restaurados antes do envio.
Se não existe repositório, o aplicativo cria o backup a partir dos seus arquivos
locais. Documentos criados ou editados offline entram em uma fila persistente.
Na próxima conexão, eles são combinados com o backup sem apagar arquivos que
existem apenas no GitHub. Edições simultâneas são preservadas em cópias de
conflito identificadas, e identidades de documentos evitam duplicações.

As alterações locais são enviadas automaticamente quando a integração está
ativada. Com a fila vazia, não há consultas periódicas ao repositório.
Use **Sincronizar** para solicitar um envio imediato e acompanhe o
indicador de estado. Sem internet, continue escrevendo localmente e sincronize
quando a conexão voltar. O backup envia os documentos; ele não substitui uma
rotina própria de recuperação de arquivos.

O menu da sua conta permite abrir seu perfil, acessar o repositório de backup
e sair do GitHub. Sair encerra a sessão de backup e mantém seus arquivos locais.

## Onde ficam meus dados?

No Windows, a versão instalada armazena os dados em `%LOCALAPPDATA%\\DocsLocal`:

- `repository/projetos/`: documentos e arquivos de cada projeto.
- `config.toml`: preferências do aplicativo.
- `state/`: estado local e credenciais protegidas pela conta do Windows.

Ao executar pelo código-fonte, os dados ficam em `data/` dentro do projeto.
O Docs Local funciona no seu computador; não exponha o servidor à internet.
Para automações locais, consulte a documentação da API em
[http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs) na porta padrão.

## Atualizações e este guia

O ícone na área de notificação do Windows permite abrir o aplicativo e
verificar atualizações. Na versão instalada, um modal avisa sobre novas
releases e inicia a atualização automaticamente após 30 segundos. Você pode
atualizar imediatamente ou adiar por uma hora. O documento aberto é salvo,
o executável é verificado por SHA-256 e o aplicativo fecha e reinicia.
Os documentos locais e os arquivos ainda na fila de backup são preservados.

O projeto **Guia do Docs Local** é a documentação padrão do aplicativo.
Ele e todos os seus itens (documentos, pastas e anexos) não podem ser excluídos
ou arquivados, tanto pela interface quanto pela API. Edições são preservadas.

## Endereço interno e skill para agentes

Você pode usar [http://docs.local](http://docs.local) para abrir o aplicativo,
na documentação e em links de automações locais. No Windows, use **Configurar
http://docs.local** no menu do ícone da bandeja e aceite a solicitação de
administrador uma vez. O endereço funciona somente neste computador e requer
o aplicativo em execução. A API está em [http://docs.local/docs](http://docs.local/docs).
O endereço alternativo é [http://127.0.0.1:8765](http://127.0.0.1:8765).

Este guia inclui a [skill Markdown do Docs Local](docs/skill/SKILL.md),
com instruções para qualquer agente consultar, pesquisar e atualizar documentos.
Copie o conteúdo para `docslocal/SKILL.md` no diretório de skills do seu agente,
junto da pasta `references` com os documentos
[HTTP](docs/skill/references/http-workflow.md) e
[contratos de API](docs/skill/references/api-documentation.md).
Consulte a skill antes de automatizar escritas e respeite revisões concorrentes.
'''


@repository_operation
def ensure_welcome_documentation(state_folder: Path) -> None:
    marker = state_folder / 'welcome-documentation-v1'
    project = None
    if marker.exists():
        project_id = marker.read_text(encoding='utf-8').strip()
        project = next((item for item in project_service.list_projects(include_archived=True)
                        if item['id'] == project_id), None)
    if project is None:
        project = next((item for item in project_service.list_projects(include_archived=True)
                        if item.get('protected')), None)
    if project is None:
        project = project_service.create_project(
            'Guia do Docs Local',
            'Primeiros passos, edição em Markdown, API e skill para agentes.',
            initial_content=WELCOME_CONTENT,
        )
    folder, metadata = project_service.get_folder(project['id'], include_archived=True)
    if not metadata.get('protected') or metadata.get('archived'):
        metadata.update(protected=True, archived=False)
        atomic_write(folder / 'project.toml', dumps_values(metadata))

    if not (folder / 'index.md').exists():
        document_service.create_document(project['id'], 'index.md', content=WELCOME_CONTENT)
    welcome = next(doc for doc in document_service.list_documents(project['id'])
                   if doc['path'] == 'index.md')
    upgrade_marker = state_folder / 'welcome-documentation-v2'
    migration_key = project['id'] + ':' + welcome['id'] + '\n'
    if not upgrade_marker.exists() or upgrade_marker.read_text(encoding='utf-8') != migration_key:
        document = document_service.read_document(project['id'], welcome['id'])
        if '## Endereço interno e skill para agentes' not in document['content']:
            content = document['content'].replace(
                'Este guia é um documento local comum: você pode editar, renomear ou excluir.',
                'Este guia e todos os seus itens são protegidos contra exclusão e arquivamento.')
            content += '\n\n' + WELCOME_CONTENT[WELCOME_CONTENT.index('O projeto **Guia do Docs Local**'):]
            document_service.update_document(project['id'], document['id'], content, document['revision'])
        atomic_write(upgrade_marker, migration_key)

    resources = Path(__file__).parents[1] / 'static' / 'agent-skill'
    for source in sorted(resources.rglob('*.md')):
        path = 'docs/skill/' + source.relative_to(resources).as_posix()
        if not (folder / path).exists():
            document_service.create_document(project['id'], path, content=source.read_text(encoding='utf-8'))
    atomic_write(marker, project['id'] + '\n')
