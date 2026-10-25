# Dados de cada instalação

O executável distribuído começa sem projetos, documentos, configuração pessoal ou credenciais GitHub.

Cada conta do Windows usa sua própria pasta `%LOCALAPPDATA%\DocsLocal`: configuração em `config.toml`, documentos em `repository/` e estado local em `state/`. A estrutura de projetos e pastas é criada pelo próprio usuário. Executar o código-fonte usa `data/` dentro do checkout; essa pasta de dados deve permanecer privada.

O login GitHub pertence ao usuário conectado nessa instalação. O backup opcional usa um repositório privado da conta retornada pelo GitHub; o software valida a propriedade e a visibilidade antes de enviar dados. Client Secret e tokens ficam no cofre DPAPI da conta do Windows. Não são incluídos na distribuição.

A integração atual exige que cada usuário configure seu próprio OAuth App do GitHub. Não há um Client Secret compartilhado embutido no executável.

O endereço `borgesigor/DocsLocal` é a origem pública das atualizações do software. A consulta de versões não utiliza os tokens de backup e não envia documentos. Documentos de usuários não são enviados a esse repositório público.

O aplicativo oferece um perfil local por conta do Windows. Não é um servidor web com contas multiusuário. Contas diferentes do Windows têm diretórios e cofres distintos; pessoas que usam a mesma conta do Windows compartilham esse perfil local.
