# Dados de cada instalação

O executável distribuído inclui somente um guia genérico de uso, criado localmente na primeira inicialização, sem documentos pessoais ou credenciais GitHub.

Cada conta do Windows usa sua própria pasta `%LOCALAPPDATA%\DocsLocal`: configuração em `config.toml`, documentos em `repository/` e estado local em `state/`. O projeto Guia do Docs Local pode ser editado ou arquivado; outros projetos e pastas são criados pelo próprio usuário. Executar o código-fonte usa `data/` dentro do checkout; essa pasta de dados deve permanecer privada.

O login GitHub pertence ao usuário conectado nessa instalação. O backup opcional usa um repositório privado da conta retornada pelo GitHub; o software valida a propriedade e a visibilidade antes de enviar dados. Os tokens ficam no cofre DPAPI da conta do Windows e não são incluídos na distribuição.

A integração usa o OAuth App do Docs Local com Client ID público fixo e Device Flow. Cada pessoa confirma um código e autoriza o aplicativo diretamente no GitHub; não precisa registrar um OAuth App. Não há Client Secret no executável nem um servidor intermediário de autenticação. O código privado do dispositivo existe somente na memória durante o login e não é enviado à interface. Ao sair ou cancelar o login, a tentativa pendente é descartada.

O endereço `borgesigor/DocsLocal` é a origem pública das atualizações do software. A consulta de versões não utiliza os tokens de backup e não envia documentos. Documentos de usuários não são enviados a esse repositório público.

O aplicativo oferece um perfil local por conta do Windows. Não é um servidor web com contas multiusuário. Contas diferentes do Windows têm diretórios e cofres distintos; pessoas que usam a mesma conta do Windows compartilham esse perfil local.
