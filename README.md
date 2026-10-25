# Docs Local

Aplicativo local-first para organizar documentação Markdown em projetos e pastas. O servidor e a interface são executados no próprio computador. O Docs Local mantém documentos na máquina e só os envia a um serviço externo quando a integração GitHub opcional é configurada e autorizada.

## Windows

Baixe `DocsLocal.exe` na página de [releases](https://github.com/borgesigor/DocsLocal/releases/latest) e execute. Na primeira inicialização, os dados ficam em `%LOCALAPPDATA%\DocsLocal`. O ícone aparece na área de notificação. Dê duplo clique para abrir `http://127.0.0.1:8765`; clique com o botão direito para abrir o menu.

O aplicativo verifica versões ao iniciar e a cada seis horas. Ao encontrar uma versão mais recente, abre um modal com uma contagem de 30 segundos para atualizar automaticamente; é possível atualizar imediatamente ou adiar por uma hora. O documento aberto é salvo antes do download. O executável é verificado por SHA-256, o programa fecha e reinicia após a substituição. Documentos não salvos em outra janela bloqueiam a instalação até serem salvos. A verificação requer internet; o uso local continua disponível offline.

## Executar a partir do código

Requer Python 3.12 ou superior, Git e, para reconstruir a interface, Node.js/npm.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Set-Location frontend
npm ci
npm run build
Set-Location ..
python -m app.tray
```

O servidor aceita somente loopback (`127.0.0.1`, `localhost` ou `::1`) e não oferece autenticação multiusuário. Não o exponha diretamente à internet.

## Login com GitHub

Clique em **Logar com GitHub**, copie o código mostrado pelo Docs Local e informe-o na página oficial do GitHub que será aberta. Autorize o aplicativo; o Docs Local detecta a autorização automaticamente e conecta sua conta. Se o navegador bloquear a janela, use **Abrir GitHub** no diálogo. O código expira em até 15 minutos e o login pode ser cancelado no aplicativo.

O Client ID público do OAuth App do Docs Local é fixo no código. Nenhum usuário precisa registrar outro OAuth App, informar credenciais de desenvolvedor ou fornecer um Client Secret. O Device Flow não requer serviço web intermediário. Os tokens da sessão ficam protegidos pelo Windows DPAPI.

Para manter uma distribuição própria, o responsável pelo aplicativo precisa registrar seu OAuth App no GitHub, habilitar **Enable Device Flow** em suas configurações e definir o Client ID em `app/services/github_service.py`. A opção é habilitada uma vez pelo responsável; não há configuração OAuth na interface do usuário. A integração solicita `repo` para criar e atualizar o backup privado e `read:user` para exibir a conta conectada.

## Sincronização e recuperação do backup

Ao conectar a conta ou iniciar o aplicativo autenticado, o Docs Local consulta o backup uma vez. Se o repositório já contém um backup válido, restaura os arquivos antes de publicar mudanças. Se o repositório não existe, cria um repositório privado e envia os arquivos locais.

A instalação vazia nunca é usada como ordem para apagar os arquivos remotos. O aplicativo compara os hashes de cada arquivo com a última versão sincronizada, vinculada ao repositório, à branch e à pasta local. Novos documentos e edições locais pendentes são preservados e enviados. Exclusões locais só são publicadas quando o arquivo era conhecido pela sincronização anterior e não recebeu uma edição remota concorrente.

Em alterações concorrentes no mesmo documento, a versão do GitHub permanece no caminho original e a versão local é preservada em um arquivo `*.conflito-local-<hash>.md`, com uma identidade distinta. Renomeações e novas tentativas usam as identidades e hashes para evitar duplicações. O guia genérico de uma instalação nova não duplica um guia já existente no backup.

A fila fica gravada em `state/github-sync/` e sobrevive a falhas, atualizações e reinicializações. As verificações periódicas comparam arquivos locais; uma fila vazia não gera consultas ao repositório. Durante uma sincronização real, somente blobs alterados ou ausentes são transferidos. Falhas são repetidas com intervalo crescente. Alterações feitas em outro computador são verificadas na próxima abertura ou conexão da conta.

## Atualizar a partir da v1.0.0

A v1.1.1 corrige um arquivo auxiliar de TLS omitido nos executáveis v1.0.0 e v1.1.0. Se a consulta de versões falhar com `[Errno 2] No such file or directory`, mantenha o Docs Local aberto, extraia o pacote `Reparar-Atualizacao-DocsLocal.zip` da release v1.1.1 e execute `repair-update-tls.ps1` no PowerShell. O script recompõe somente o recurso ausente na pasta temporária da instância em execução, mantendo a validação TLS original. Em seguida, use **Verificar atualizações** na bandeja. Alternativamente, encerre o aplicativo e substitua o executável pelo `DocsLocal.exe` da release; a pasta de dados é preservada.

A v1.0.0 reconhece releases estáveis com os assets `DocsLocal.exe` e `DocsLocal.exe.sha256`, e usa um helper `--apply-update` compatível com a v1.1.0. A primeira transição usa a confirmação nativa da v1.0.0; o modal com atualização automática passa a funcionar na versão nova. A pasta `%LOCALAPPDATA%\\DocsLocal` é preservada. Sessões registradas por outro OAuth App podem exigir um novo login pelo Device Flow.

## Criar o executável

No Windows, compile a interface, instale `requirements-build.txt` e execute `scripts/build-windows.ps1`. O executável e seu checksum SHA-256 são criados em `dist/`.

A build inclui os recursos TLS exigidos pela distribuição do Python e executa um teste TLS no próprio `.exe` antes de gerar o checksum. Para conferir também a consulta HTTPS ao GitHub, execute `DocsLocal.exe --check-update-network C:\caminho\relatorio.json`; o relatório registra se a conexão e a validação dos certificados funcionaram.

Para publicar outra versão, atualize `app/version.py`, reconstrua o executável e envie o commit para o GitHub. Publique uma release estável com tag `vMAJOR.MINOR.PATCH` e os arquivos `DocsLocal.exe` e `DocsLocal.exe.sha256`, mantendo esses nomes. Exemplo com o GitHub CLI:

```powershell
gh release create v1.1.0 dist/DocsLocal.exe dist/DocsLocal.exe.sha256 --target main --title "Docs Local v1.1.0" --generate-notes
```

## Dados e privacidade

Configuração e documentos ficam localmente em `%LOCALAPPDATA%\DocsLocal` para o `.exe`, ou em `data/` quando executado a partir do código. O cofre OAuth usa Windows DPAPI.

Na primeira inicialização, cada instalação recebe o projeto **Guia do Docs Local**, com instruções de uso que funcionam offline. O guia pode ser editado ou arquivado e não é recriado ao reiniciar. Cada usuário configura seu próprio login e backup. Consulte [PRIVACY.md](PRIVACY.md) para os detalhes do isolamento por conta do Windows.

## Desenvolvimento

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Licença

MIT. Consulte [LICENSE](LICENSE).
