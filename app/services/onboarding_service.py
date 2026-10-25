"""Create an editable local guide once for each installation."""

from pathlib import Path

from app.services import project_service
from app.services.storage import atomic_write, repository_operation

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

Este guia é um documento local comum: você pode editar, renomear ou excluir.
Ele é criado apenas uma vez e suas alterações são preservadas ao reiniciar.
'''


@repository_operation
def ensure_welcome_documentation(state_folder: Path) -> None:
    marker = state_folder / 'welcome-documentation-v1'
    if marker.exists():
        return

    project = project_service.create_project(
        'Guia do Docs Local',
        'Primeiros passos, edição em Markdown e backup no GitHub.',
        initial_content=WELCOME_CONTENT,
    )
    atomic_write(marker, project['id'] + '\n')
