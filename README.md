# Docs Local

Aplicativo local-first para organizar documentação Markdown em projetos e pastas. O servidor e a interface são executados no próprio computador. O Docs Local mantém documentos na máquina e só os envia a um serviço externo quando a integração GitHub opcional é configurada e autorizada.

## Windows

Baixe `DocsLocal.exe` na página de [releases](https://github.com/borgesigor/DocsLocal/releases/latest) e execute. Na primeira inicialização, os dados ficam em `%LOCALAPPDATA%\DocsLocal`. O ícone aparece na área de notificação. Dê duplo clique para abrir `http://127.0.0.1:8765`; clique com o botão direito para abrir o menu.

O aplicativo verifica versões ao iniciar e a cada seis horas. Ao encontrar uma versão mais recente, pede confirmação antes de baixar. Confere o arquivo por SHA-256 e reinicia o Docs Local após a atualização. A verificação requer internet; o uso local continua disponível offline.

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

## Criar o executável

No Windows, compile a interface, instale `requirements-build.txt` e execute `scripts/build-windows.ps1`. O executável e seu checksum SHA-256 são criados em `dist/`.

Para publicar outra versão, atualize `app/version.py`, reconstrua o executável e envie o commit para o GitHub. Publique uma release estável com tag `vMAJOR.MINOR.PATCH` e os arquivos `DocsLocal.exe` e `DocsLocal.exe.sha256`, mantendo esses nomes. Exemplo com o GitHub CLI:

```powershell
gh release create v1.0.1 dist/DocsLocal.exe dist/DocsLocal.exe.sha256 --target main --title "Docs Local v1.0.1" --generate-notes
```

## Dados e privacidade

Configuração e documentos ficam localmente em `%LOCALAPPDATA%\DocsLocal` para o `.exe`, ou em `data/` quando executado a partir do código. O cofre OAuth usa Windows DPAPI.

Cada instalação começa vazia e cada usuário configura seu próprio login e backup. Consulte [PRIVACY.md](PRIVACY.md) para os detalhes do isolamento por conta do Windows.

## Desenvolvimento

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Licença

MIT. Consulte [LICENSE](LICENSE).
