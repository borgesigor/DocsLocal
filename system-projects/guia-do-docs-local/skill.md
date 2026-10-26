---
name: docslocal
description: Consulte, pesquise e mantenha documentação Markdown de projetos no Docs Local pela API local. Use quando a tarefa mencionar Docs Local ou DocsLocal como destino da documentação. Não se aplica ao desenvolvimento do próprio aplicativo nem a documentos Word.
---

# Docs Local

Use esta skill para trabalhar nos projetos de documentação do usuário. Todas
as instruções estão neste arquivo; não há dependência de `references/`.

## Encontrar a instância e o projeto

Prefira uma ferramenta conectada do Docs Local quando ela atender à tarefa.
Caso contrário, use HTTP local com PowerShell ou Python.

1. Use o endereço informado pelo usuário ou tente `http://127.0.0.1:8765`.
   `http://docs.local` é um alias opcional, disponível somente após configuração.
   Confirme `GET /api/v1/health`: deve retornar `status: ok` e `service: docs-local`.
2. Consulte `/openapi.json` para conferir os contratos da instância; `/docs`
   oferece a interface interativa. A documentação descreve o sistema, mas não
   substitui a confirmação do comportamento implementado.
3. Liste `GET /api/v1/projects` e identifique o projeto pelo nome e pelo `id`
   retornado. Use `include_archived=true` quando necessário. Não adivinhe slugs
   nem crie outro projeto para compensar uma busca incompleta.
4. Liste `GET /api/v1/projects/{project_id}/documents` ou consulte `/tree`
   no mesmo projeto. Localize o `path` e use o `id` retornado para ler ou editar.
   Os documentos podem estar na raiz ou em qualquer subpasta, além de `docs/`.

Se houver mais de um destino plausível, esclareça apenas a identificação
necessária antes de escrever. Se o serviço estiver indisponível, informe o
bloqueio e preserve a proposta localmente; não inicie outra instância nem
altere a instalação para contorná-lo sem autorização.

O projeto `guia-do-docs-local` e outros projetos com `system: true` e
`protected: true` são conteúdo de sistema. Podem ser consultados e pesquisados,
mas a interface e a API rejeitam suas alterações com `403 protected_guide`.
Sua manutenção pertence ao código do aplicativo em `system-projects/`.

## Consultar e pesquisar

Todas as rotas abaixo são relativas a `/api/v1`.

| Operação | Requisição |
| --- | --- |
| Listar projetos | `GET /projects` |
| Consultar projeto | `GET /projects/{project_id}` |
| Listar documentos | `GET /projects/{project_id}/documents` |
| Ler árvore de documentos e pastas | `GET /projects/{project_id}/tree` |
| Ler documento completo | `GET /projects/{project_id}/documents/{document_id}` |
| Pesquisar conteúdo | `GET /search?q=...&project_id=...` |
| Consultar histórico do documento | `GET /projects/{project_id}/documents/{document_id}/history` |
| Consultar sincronização | `GET /sync/status` |

A busca procura um trecho de texto no conteúdo, sem distinguir maiúsculas e
minúsculas. Codifique os parâmetros e restrinja ao projeto relevante. Os
resultados trazem projeto, caminho, título e trecho; para obter o documento
completo, resolva o caminho na listagem e use seu ID.

O GET individual retorna `id`, `path`, `title`, `content`, `revision`, `etag`
e o cabeçalho HTTP `ETag`. `content` exclui o comentário interno `docs-local`,
mas preserva o cabeçalho YAML e o restante do Markdown. Preserve esses metadados
ao editar. O título é extraído do primeiro título Markdown de nível 1 (`# `).

## Criar e atualizar

Leia as instruções do projeto, como `AGENTS.md`, e a documentação existente
para respeitar convenções e a fonte principal dos documentos. Modifique os
documentos do usuário pela API, mantendo o escopo autorizado pela tarefa.

| Operação | Requisição e corpo JSON |
| --- | --- |
| Criar projeto | `POST /projects` com `name` e, opcionalmente, `description` |
| Criar documento | `POST /projects/{project_id}/documents` com `path`, `content` e, opcionalmente, `title` |
| Substituir conteúdo | `PUT /projects/{project_id}/documents/{document_id}` com `content` completo e `revision` lida |
| Renomear ou mover documento | `PATCH /projects/{project_id}/documents/{document_id}` com `path` e/ou `title` |
| Criar pasta | `POST /projects/{project_id}/folders` com `path` |
| Renomear ou mover pasta | `PATCH /projects/{project_id}/folders` com `path` e `new_path` |

As criações retornam `201`. A criação de projeto já inclui `index.md`, `docs/`
e `assets/`. Ao criar um documento, os diretórios pais são criados conforme
necessário. Se enviar `content`, inclua nele o título desejado: o campo `title`
só gera o conteúdo inicial quando `content` é omitido.

Use caminhos relativos ao projeto, com `/` e extensão `.md`. Não use caminhos
absolutos, `..`, `.git`, links simbólicos ou nomes e caracteres reservados pelo
Windows. O `index.md` inicial pode ser editado, mas não movido nem excluído.

Para editar conteúdo, faça GET, prepare a versão completa e envie PUT com a
revisão recebida. Alternativamente, envie `If-Match` com o ETag recebido entre
aspas, usando apenas essa precondição. PUT substitui todo o texto; não envie
somente o trecho alterado e não grave se o conteúdo já estiver correto.

PATCH aceita caminho e título, mas não uma precondição de revisão do cliente.
Use-o para renomeações ou movimentações solicitadas, considerando concorrência
e links afetados. Alterar `title` por PATCH modifica o primeiro `# ` do conteúdo.

Envie JSON em UTF-8 com `Content-Type: application/json; charset=utf-8`.
Após escrever, releia o documento e confira conteúdo, caminho e revisão.
Se houver uma edição concorrente nessa releitura, concilie antes de agir.

### Exemplo de leitura e atualização em PowerShell

Substitua nome e caminho pelos valores da tarefa. No Windows PowerShell,
desserialize explicitamente as listagens para evitar arrays encapsulados.

```powershell
$ErrorActionPreference = 'Stop'
$docsOrigin = 'http://127.0.0.1:8765'
$docsApi = "$docsOrigin/api/v1"
$targetProjectName = 'Nome do projeto solicitado'
$targetDocumentPath = 'docs/api/README.md'

$health = Invoke-RestMethod "$docsApi/health" -TimeoutSec 10
if ($health.service -ne 'docs-local' -or $health.status -ne 'ok') {
    throw 'O endereço não confirmou um Docs Local saudável.'
}
$projects = (Invoke-WebRequest "$docsApi/projects" -UseBasicParsing -TimeoutSec 10).Content | ConvertFrom-Json
$selectedProjects = @($projects | Where-Object { $_.name -eq $targetProjectName })
if ($selectedProjects.Count -ne 1) { throw 'Projeto ausente ou ambíguo.' }
$projectId = [uri]::EscapeDataString($selectedProjects[0].id)
$documents = (Invoke-WebRequest "$docsApi/projects/$projectId/documents" -UseBasicParsing -TimeoutSec 10).Content | ConvertFrom-Json
$selectedDocuments = @($documents | Where-Object { $_.path -eq $targetDocumentPath })
if ($selectedDocuments.Count -ne 1) { throw 'Documento ausente ou ambíguo.' }
$documentId = [uri]::EscapeDataString($selectedDocuments[0].id)
$documentUrl = "$docsApi/projects/$projectId/documents/$documentId"
$current = Invoke-RestMethod $documentUrl -TimeoutSec 10
```

Prepare `$newContent` a partir de `$current.content` com a alteração autorizada.
Só então execute a escrita:

```powershell
if ($newContent -isnot [string]) { throw 'Prepare o conteúdo completo.' }
if ($newContent -cne $current.content) {
    $payload = @{ content = $newContent; revision = $current.revision } | ConvertTo-Json -Depth 10
    $saved = Invoke-RestMethod $documentUrl -Method Put `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 15
    $verified = Invoke-RestMethod $documentUrl -TimeoutSec 10
    if ($verified.id -ne $current.id -or $verified.path -ne $current.path -or
        $verified.content -cne $newContent -or $verified.revision -ne $saved.revision) {
        throw 'A releitura divergiu; examine a versão atual antes de escrever novamente.'
    }
}
```

Se os acentos vierem corrompidos, decodifique a resposta como UTF-8 antes de
preparar a edição. Não grave texto corrompido de volta no serviço.

## Links para leitura

Forneça ao usuário links no formato
`{origem}/{project_id}/{document_path}`, usando o ID e o caminho confirmados.
Exemplo de documento existente: `http://docs.local/guia-do-docs-local/skill.md`.
A URL da API continua usando `document_id`; não substitua esse ID pelo caminho.

Codifique cada segmento do caminho separadamente, preservando as barras:

```powershell
$encodedDocumentPath = (($current.path -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
$documentViewUrl = "$docsOrigin/$projectId/$encodedDocumentPath"
```

Para links internos, prefira `/{project_id}/{document_path}`. Evite criar novos
links no formato legado `?project=...&document=...`. Após mover ou renomear,
revise as referências e âncoras afetadas; elas não são atualizadas automaticamente.
Um caminho virtual do Docs Local não implica um arquivo no workspace.

## Tratar falhas e concorrência

| Resposta | Conduta |
| --- | --- |
| `409 revision_conflict` | Releia e concilie a mudança com a versão atual. Faça no máximo uma nova tentativa automática; se houver conflito semântico ou nova concorrência, preserve a proposta e informe o bloqueio. |
| `409 path_exists` | Localize e leia o item existente antes de decidir se precisa atualizá-lo. |
| `428 revision_required` | Obtenha a revisão ou o ETag atual antes de salvar. |
| `403 protected_guide` | O destino é conteúdo de sistema; escolha o projeto de usuário correto para a tarefa. |
| `404` | Confira projeto, arquivamento e ID nas listagens antes de criar um substituto. |
| `415` ou `422` | Confira o tipo de conteúdo, o schema e as validações retornadas antes de corrigir a requisição. |

Erros da aplicação usam `error.code` e `error.message`; erros de validação podem
usar `detail`. Após timeout ou perda de conexão em uma escrita, consulte o
estado antes de repetir: a operação pode ter sido persistida. Nunca retire a
precondição de revisão para forçar uma atualização.

## Backup e escopo das operações

As escritas solicitam a sincronização do aplicativo. Salvamento local e envio
ao GitHub são resultados distintos. Consulte `GET /sync/status` quando relevante,
observando autenticação, `state`, `pending`, `last_sync` e `last_error`. Não afirme
backup remoto apenas porque o PUT retornou sucesso ou não há pendências locais.

A recuperação remota ocorre ao iniciar autenticado ou conectar a conta. Depois,
uma fila sem alterações locais não consulta o GitHub, mesmo com sincronização
manual. Em conflitos de conteúdo, o backup mantém a versão remota no caminho
original e preserva a local em `*.conflito-local-<hash>.md`.

Não configure GitHub, dispare sincronização manual ou resolva conflitos do
backup como efeito adicional de editar documentação. Exclusões, arquivamento,
autenticação e configuração global precisam estar no escopo autorizado. A API
de exclusão de projeto arquiva os dados; a exclusão de pasta remove seu conteúdo.

## Quando a tarefa envolver contratos de API

Organize a documentação no projeto selecionado em `docs/api/README.md` e um
arquivo por serviço ou domínio real, como `docs/api/customers.md`. O README
reúne visão geral, índice e convenções compartilhadas. Agrupe os endpoints do
domínio no mesmo arquivo, sem criar um documento por método ou operação.

Confira rotas, handlers, schemas, validações e permissões na implementação.
Para cada endpoint, documente o que se aplicar:

- Método, rota, finalidade, autenticação e autorização.
- Parâmetros de caminho, query, headers e corpo, com tipos, obrigatoriedade,
  valores aceitos e padrões.
- Requisições e respostas de sucesso com exemplos válidos e status HTTP.
- Erros confirmados, códigos, causas, validações e regras de negócio.
- Paginação, filtros, ordenação, limites, idempotência, efeitos colaterais e eventos.

Não invente contratos ou funcionalidades. Sinalize lacunas e separe planejamento
de comportamento implementado. Centralize convenções para evitar repetição.
Atualize o domínio afetado, o índice e o README do backend ou equivalente na
mesma tarefa da mudança, somente onde houver impacto. Preserve links úteis e
siga a convenção existente de fonte principal se também houver cópias no
repositório, evitando versões divergentes.

## Entregar o resultado

Informe projeto, caminhos consultados ou alterados, revisões confirmadas e
lacunas. Inclua links de leitura. Distinga conteúdo preparado, salvamento
confirmado e backup remoto efetivamente verificado.
