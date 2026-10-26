# API local e PowerShell

Contratos conferidos no código e na OpenAPI local em 25/10/2026. Confirme-os novamente se a versão instalada divergir. No Windows PowerShell, desserialize explicitamente as listagens para evitar arrays encapsulados por `Invoke-RestMethod`.

## Descobrir e ler (somente consulta)

Defina `$targetProjectName` e `$targetDocumentPath` a partir da tarefa e da listagem do projeto. Os valores abaixo são ilustrativos; substitua-os antes de executar.

```powershell
$ErrorActionPreference = 'Stop'
$targetProjectName = 'Nome do projeto solicitado'
$targetDocumentPath = 'docs/api/README.md'
$docsOrigin = 'http://127.0.0.1:8765'
$docsApi = "$docsOrigin/api/v1"
$health = Invoke-RestMethod "$docsApi/health" -TimeoutSec 10
if ($health.service -ne 'docs-local' -or $health.status -ne 'ok') {
    throw 'O endereço não confirmou um Docs Local saudável.'
}
$projectsResponse = Invoke-WebRequest "$docsApi/projects" -UseBasicParsing -TimeoutSec 10
$projects = $projectsResponse.Content | ConvertFrom-Json
$matches = @($projects | Where-Object { $_.name -eq $targetProjectName })
if ($matches.Count -ne 1) { throw 'Projeto ausente ou ambíguo.' }
$projectId = [uri]::EscapeDataString($matches[0].id)
$documentsResponse = Invoke-WebRequest "$docsApi/projects/$projectId/documents" -UseBasicParsing -TimeoutSec 10
$documents = $documentsResponse.Content | ConvertFrom-Json
$selected = @($documents | Where-Object { $_.path -eq $targetDocumentPath })
if ($selected.Count -ne 1) { throw 'Documento ausente ou ambíguo; examine a listagem.' }
$documentId = [uri]::EscapeDataString($selected[0].id)
$documentUrl = "$docsApi/projects/$projectId/documents/$documentId"
$current = Invoke-RestMethod $documentUrl -TimeoutSec 10
```

O GET individual retorna `id`, `path`, `title`, `content`, `revision`, `etag` e o cabeçalho HTTP `ETag`. O conteúdo exclui o comentário interno de metadados. Se o PowerShell mostrar acentos corrompidos, decodifique os bytes da resposta como UTF-8 com `Invoke-WebRequest` antes de editar; não grave de volta texto corrompido.

## URL de leitura no navegador

O `$documentUrl` acima é a rota da API e continua usando ID. Para fornecer um link de leitura ao usuário, componha a URL com o ID do projeto e o caminho confirmado no documento:

```powershell
$encodedDocumentPath = (($current.path -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
$documentViewUrl = "$docsOrigin/$projectId/$encodedDocumentPath"
```

Exemplo: `http://127.0.0.1:8765/project-x/docs/regras-para-agentes.md`. Para referências internas, use `/project-x/docs/regras-para-agentes.md`, substituindo projeto e caminho pelos valores reais. O índice é `/{project_id}/index.md`. Não publique novos links com query `project`/`document`. Após renomear/mover, confira as referências; links de seção exigem um título correspondente no destino. Referências a arquivos que só existem no repositório devem ser identificadas como referências do repositório, sem inventar um destino no Docs Local.

## Atualizar após preparar o conteúdo

O trecho abaixo escreve no serviço. Use apenas depois de preparar `$newContent` com a alteração autorizada sobre `$current.content`.

```powershell
if ($newContent -isnot [string] -or [string]::IsNullOrWhiteSpace($newContent)) {
    throw 'Prepare o conteúdo completo antes de salvar.'
}
if ($newContent -cne $current.content) {
    $payload = @{ content = $newContent; revision = $current.revision } | ConvertTo-Json -Depth 10
    $saved = Invoke-RestMethod $documentUrl -Method Put `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 15
    $verified = Invoke-RestMethod $documentUrl -TimeoutSec 10
    if ($verified.id -ne $current.id -or $verified.path -ne $current.path -or
        $verified.content -cne $newContent -or $verified.revision -ne $saved.revision) {
        throw 'A releitura divergiu do salvamento; revise antes de qualquer nova escrita.'
    }
}
```

Uma atualização bem-sucedida aumenta a revisão. Se outro agente escrever entre PUT e GET, examine a versão atual; não reverta automaticamente.

## Payloads e outras operações

Todos os caminhos abaixo são relativos a `/api/v1`.

| Finalidade | Requisição | Contrato |
| --- | --- | --- |
| Criar documento | `POST /projects/{project_id}/documents` | JSON com `path`, `title`, `content`; retorna `201` e cria diretórios pais necessários |
| Atualizar conteúdo | `PUT /projects/{project_id}/documents/{document_id}` | JSON com `content` completo e `revision` real do GET; retorna `200` |
| Atualizar com ETag | Mesmo PUT | JSON com `content` e cabeçalho `If-Match` com ETag recebido entre aspas; prefira uma única precondição |
| Pesquisar | `GET /search` | Query `q` e `project_id`, codificados separadamente |
| Ler histórico | `GET /projects/{project_id}/documents/{document_id}/history` | Sem corpo |
| Consultar sincronização | `GET /sync/status` | Sem corpo |

Existe PATCH individual com `path` e/ou `title`, mas sem precondição de revisão fornecida pelo cliente. Não o use como atalho para editar conteúdo. Para movimentações ou renomeações solicitadas, confirme o contrato atual, avalie concorrência e confira links afetados.
