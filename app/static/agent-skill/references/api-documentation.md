A documentação da API deve seguir uma estrutura centralizada por serviço ou domínio funcional, com contratos completos, exemplos práticos e organização consistente. O objetivo é permitir que desenvolvedores compreendam e utilizem a API sem precisar consultar o código-fonte.
Toda a documentação deve ficar em docs/api/, com um único arquivo Markdown por serviço ou domínio funcional, reunindo seus endpoints, recursos, operações e comportamentos.
Exemplo de estrutura:
```text
docs/
└── api/
    ├── README.md
    ├── authentication.md
    ├── billing.md
    ├── checkout.md
    ├── customers.md
    └── tax.md

```
- README.md: ponto de entrada, contendo visão geral da API, índice dos serviços e convenções compartilhadas.
- billing.md: documentação completa do serviço Billing, incluindo todos os seus recursos e endpoints.
- checkout.md: documentação completa do serviço Checkout.
- Demais arquivos: seguem os serviços e domínios realmente existentes no projeto.
Não crie arquivos individuais por endpoint, método HTTP ou operação. Endpoints relacionados devem permanecer agrupados no arquivo do respectivo serviço. Não crie arquivos para serviços inexistentes.
Cada arquivo deve funcionar como uma referência técnica autossuficiente, permitindo compreender os recursos, contratos e comportamentos do serviço.
Utilize a seguinte estrutura como modelo, adaptando as seções ao que realmente se aplica:
```markdown
# Billing

## Visão geral
Responsabilidades, recursos e comportamento do serviço.

## Autenticação e permissões
Credenciais, escopos e permissões exigidas.

## Endpoints
Tabela com métodos HTTP, rotas e descrições.

## Invoices

### Criar invoice
POST /billing/invoices

Descrição da operação.

#### Parâmetros
Campos, tipos, obrigatoriedade, valores aceitos e padrões.

#### Exemplo de requisição
Exemplo HTTP ou cURL com payload válido.

#### Validações
Regras e condições de rejeição.

#### Resposta de sucesso
Status HTTP, estrutura e exemplo do JSON retornado.

#### Erros
Status HTTP, códigos, condições e exemplos de resposta.

#### Observações
Idempotência, efeitos colaterais e demais comportamentos.

### Consultar invoice
GET /billing/invoices/{id}
...

### Listar invoices
GET /billing/invoices
...

## Paginação e limites
Regras compartilhadas pelo serviço.

## Webhooks e eventos
Eventos produzidos ou consumidos, quando aplicável.

```
Para cada endpoint, documente, quando aplicável:
- Método e rota: método HTTP, caminho e finalidade.
- Autenticação e autorização: credenciais, permissões e restrições.
- Parâmetros: path, query, headers e body, com tipos, obrigatoriedade, valores permitidos e padrões.
- Requisição: formato, estrutura e exemplo válido.
- Validações: regras de negócio, restrições e condições de rejeição.
- Respostas de sucesso: status HTTP, campos retornados e exemplos JSON.
- Erros: status HTTP, códigos, causas e exemplos de resposta.
- Comportamentos adicionais: paginação, filtros, ordenação, idempotência, limites, efeitos colaterais e eventos relevantes.
Evite duplicar convenções globais em cada endpoint. Centralize-as em docs/api/README.md e referencie-as internamente quando necessário.
A documentação deve representar o comportamento efetivamente implementado, nunca suposições sobre o funcionamento da API.
Antes de criar ou atualizar qualquer contrato:
1. Consulte as rotas, controllers, handlers, schemas, DTOs, validações e componentes relevantes.
2. Confirme métodos HTTP, caminhos, parâmetros, permissões, status codes e formatos das respostas.
3. Verifique fluxos de erro, regras de negócio e comportamentos relevantes.
4. Produza exemplos compatíveis com os contratos reais, preservando nomes e tipos dos campos.
5. Identifique explicitamente funcionalidades planejadas ou ainda não implementadas.
Nunca invente endpoints, parâmetros, respostas, códigos de erro, valores padrão ou comportamentos. Quando uma informação não puder ser confirmada, sinalize a lacuna em vez de apresentá-la como fato.
Toda alteração que afete o contrato público ou o comportamento observável da API deve atualizar a documentação na mesma tarefa.
Isso inclui alterações em rotas, métodos HTTP, schemas, DTOs, parâmetros, validações, permissões, respostas, erros, paginação, filtros, limites e demais comportamentos relevantes.
Revise sempre:
1. docs/api/<serviço>.md: contrato completo do serviço afetado.
2. docs/api/README.md: índice, visão geral e convenções compartilhadas.
3. backend/README.md: informações e instruções da API no contexto do backend.
Atualize o conteúdo que tiver sido afetado. Se determinado arquivo continuar correto, não faça alterações artificiais.
Uma alteração da API não está concluída enquanto a documentação correspondente estiver inconsistente com a implementação.
A documentação deve ser:
- Completa: cobrir todos os endpoints públicos existentes e seus contratos relevantes.
- Precisa: refletir fielmente a implementação, incluindo erros e restrições.
- Consistente: manter nomenclatura, estrutura e formatação uniformes entre serviços.
- Navegável: facilitar a localização de serviços, recursos e operações.
- Prática: fornecer exemplos válidos de requisições e respostas para facilitar integrações.
- Atualizada: evoluir junto com o código, sem contratos obsoletos.
Princípio central: docs/api/ é a referência principal dos contratos da API para consumidores e integrações. A implementação determina o comportamento real; a documentação deve representá-lo fielmente, de forma clara, completa e suficiente para utilizar a API sem consultar o código-fonte.
Este padrão é autossuficiente. Não é necessário consultar referências externas para interpretá-lo ou aplicá-lo.