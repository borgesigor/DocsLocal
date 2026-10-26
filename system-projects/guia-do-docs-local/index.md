<!-- docs-local: id=a0dacc01-64b9-4c9e-b22d-f4c4ed75b984 revision=7 updated=2026-10-26T02:24:03+00:00 -->
# Bem-vindo ao Docs Local

O Docs Local organiza documentação Markdown em projetos. Você consulta e edita
os arquivos no próprio computador, inclusive offline. A conexão com o GitHub
é opcional e serve para backup e recuperação dos documentos.

## Acessar o aplicativo

Com o aplicativo em execução, abra [http://127.0.0.1:8765](http://127.0.0.1:8765).
No Windows, o ícone na área de notificação permite abrir a interface, verificar
atualizações e encerrar o programa.

Para usar [http://docs.local](http://docs.local), escolha **Configurar
http://docs.local** no menu da bandeja e aceite a solicitação de administrador.
A configuração associa o nome ao computador e encaminha a porta local 80 para
a porta do servidor, 8765 por padrão. A porta 80 precisa estar disponível.
O endereço permanece configurado após reiniciar o Windows, mas o Docs Local
precisa estar aberto para responder.

Ao executar pelo código, a mesma configuração pode ser feita com
`app/static/configure-local-url.ps1` no PowerShell como administrador. Se mudar
a porta do servidor, ajuste também o encaminhamento do endereço.

## Criar e organizar documentos

1. Clique em **+** ao lado de **Projetos** e informe o nome e a descrição.
2. Selecione o projeto. Ele começa com `index.md` e as pastas `docs/` e `assets/`.
3. Em **Arquivos**, use **Criar documento**. O botão principal cria em `docs/`;
   o menu de contexto de uma pasta permite criar dentro dela. Um nome como
   `guias/instalacao.md` cria também as subpastas necessárias.
4. Abra o arquivo, clique em **Editar Markdown** e depois em **Salvar**.
   **Cancelar** descarta a edição ainda não salva.

A árvore reflete as pastas reais do projeto, inclusive as vazias, e encontra
Markdown na raiz ou em qualquer subpasta. **Filtrar arquivos...** procura por
nome, título ou caminho na árvore; a API também permite pesquisar no conteúdo.

Use os menus de contexto para criar pastas, renomear ou excluir itens. Ao
renomear um documento pela interface, seu título principal também é atualizado.
O documento inicial `index.md` pode ser editado, mas não movido nem excluído.
Excluir uma pasta remove também seu conteúdo. A opção de excluir um projeto
o **arquiva**: ele sai da lista, mas seus dados permanecem no armazenamento local.

O leitor apresenta títulos, listas, tabelas, links e blocos de código. Quando
o Markdown começa com um cabeçalho YAML, os campos aparecem em um bloco de
metadados; o texto original continua disponível no editor.

## Compartilhar links locais

Copie o endereço do documento aberto. O formato é
`http://docs.local/{project_id}/{document_path}`, como neste
[documento de instruções para agentes](/guia-do-docs-local/skill.md).
Com o endereço alternativo, use a mesma rota após `http://127.0.0.1:8765`.

O caminho inclui o nome do arquivo e sua extensão `.md`. Após mover ou renomear
um arquivo ou pasta, revise os links que apontam para ele; as referências não
são reescritas automaticamente. Se fizer alterações diretamente nos arquivos,
atualize a página para recarregar a árvore e o conteúdo.

Esses endereços abrem o Docs Local no computador de quem acessa. Para usar os
documentos em outra instalação, conecte o backup nessa instalação.

## Conectar o backup no GitHub

Clique em **Logar com GitHub**, copie o código exibido e use **Abrir GitHub**
para informá-lo na página oficial. Autorize o aplicativo e volte ao Docs Local;
a conexão é detectada automaticamente. Você pode cancelar a tentativa pelo
diálogo ou iniciar outra se o código expirar.

Não é necessário criar um OAuth App, fornecer Client Secret ou configurar
credenciais de desenvolvedor. O login usa o Device Flow do aplicativo e solicita
`repo` para o backup privado e `read:user` para identificar a conta. No Windows,
os tokens ficam protegidos pelo DPAPI da conta do usuário.

O repositório padrão se chama `docs-local-backup`. O aplicativo verifica se
ele pertence à conta conectada e se é privado antes de enviar documentos.

### Sincronização e recuperação

- Ao conectar a conta ou iniciar o aplicativo autenticado, o Docs Local consulta
  o backup. Se houver um backup válido, recupera os arquivos conciliando as
  mudanças locais antes de publicar. Se o repositório não existir, cria um
  repositório privado e envia os dados locais.
- Salvamentos e outras alterações entram na fila de sincronização. Use
  **Sincronizar** para solicitar o processamento e acompanhe o estado na interface.
  O arquivo salvo localmente continua disponível mesmo se o envio falhar.
- A fila persiste em disco e é retomada após reinicializações e atualizações.
  Sem internet, continue trabalhando e sincronize quando a conexão voltar.
- A sincronização compara arquivos com a última versão conhecida. Uma instalação
  vazia não apaga o backup remoto; exclusões locais só são enviadas para arquivos
  já conhecidos, sem edição remota concorrente.
- Se o mesmo documento tiver mudanças incompatíveis, a versão do GitHub fica
  no caminho original e a versão local é preservada em
  `*.conflito-local-<hash>.md`. Revise as duas antes de resolver a duplicidade.

As verificações periódicas examinam alterações locais. Após a recuperação inicial,
uma fila vazia não consulta o repositório, inclusive ao clicar em **Sincronizar**.
Mudanças feitas em outro computador são consultadas na próxima abertura do
aplicativo ou conexão da conta, ou durante uma sincronização com pendências locais.

## Atualizar o aplicativo

Na versão Windows instalada, o Docs Local verifica versões ao iniciar e a cada
seis horas. Uma atualização disponível abre um aviso com contagem de 30 segundos.
Você pode atualizar imediatamente ou **Adiar por 1 hora**. Também pode usar
**Verificar atualizações** no menu da bandeja.

Antes de instalar, o aplicativo tenta salvar o documento aberto, baixa o
executável, verifica seu SHA-256 e reinicia. Se o salvamento falhar ou houver
alterações não salvas em outra aba ou janela, a instalação fica bloqueada.
Os documentos e a fila de backup são preservados.

## Onde ficam os dados

| Instalação | Pasta padrão dos dados |
| --- | --- |
| Executável Windows | `%LOCALAPPDATA%\DocsLocal` |
| Execução pelo código | `data/` dentro do checkout |

Nessa pasta ficam `config.toml`, `repository/` e `state/`. Por padrão, os projetos
do usuário ficam em `repository/projetos/`; o destino é definido por
`storage.repository_path`. A configuração é acessível pela API, sem uma tela
de configurações gerais na interface atual.

O servidor aceita apenas endereços de loopback e oferece um perfil local por
conta do Windows. Pessoas que usam a mesma conta compartilham os dados desse
perfil. A consulta pública de atualizações não envia documentos nem usa os
tokens do backup.

## Este guia e a integração com agentes

O **Guia do Docs Local** é um projeto de sistema, somente leitura na interface
e na API. Não é possível adicionar, editar, renomear, mover ou excluir seus
itens, nem arquivar o projeto. Crie outro projeto para sua documentação.

Os arquivos fonte ficam em `system-projects/guia-do-docs-local/` no repositório
do software e são incluídos no executável. Para manter o guia, edite esses
arquivos no código e distribua uma nova versão. A inicialização apenas os lê:
não gera, restaura nem sobrescreve o guia. Ele não participa do backup pessoal.
Cópias legadas na pasta de projetos do usuário são ignoradas; a sincronização
remove cópias antigas da árvore atual do backup, preservando o histórico do Git.

A [Skill do Docs Local](/guia-do-docs-local/skill.md) contém as instruções para
agentes consultarem, pesquisarem e manterem documentação pela API. Para
instalá-la, copie o conteúdo completo de `skill.md`, incluindo o cabeçalho YAML,
para `docslocal/SKILL.md` no diretório de skills do agente. Ela é autossuficiente,
sem arquivos de referência adicionais.

Consulte a [API interativa](/docs) e o [contrato OpenAPI](/openapi.json) da
instância em execução para conferir as operações e os formatos disponíveis.
