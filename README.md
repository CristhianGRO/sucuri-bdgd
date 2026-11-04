# SUCURI · Redes BDGD

Explore redes de distribuição em um mapa, selecione alimentadores e exporte GeoJSON, KMZ e arquivos de entrada para fluxo de potência.

**[Abrir o site](https://cristhiangro.github.io/sucuri-bdgd/)** · **[Baixar SUCURI Local para Windows](https://github.com/CristhianGRO/sucuri-bdgd/releases/latest/download/SUCURI-Local-Windows.zip)**

## Começar

O site funciona como visualizador sem instalar nada: experimente a rede fictícia ou abra um GeoJSON. Para baixar e converter BDGD, conecte o aplicativo local:

1. Baixe o ZIP acima e **extraia toda a pasta**. Abra `SUCURI Local.exe` (Windows x64). Extraia o aplicativo em uma pasta Windows, como Downloads ou `D:\Aplicativos\SUCURI`, fora de pastas de rede/WSL.
2. Escolha a pasta dos dados. Se houver disco D, a sugestão é `D:\SUCURI`; você pode escolher outro disco. Clique em **Iniciar serviço**.
3. Clique em **Copiar código**, depois **Abrir site**. Cole o código em **Conectar meu computador** e clique em **Conectar computador**.
4. Quando o navegador pedir acesso à rede local, permita. Mantenha o aplicativo aberto enquanto usar o processamento.
5. Em **Obter base da ANEEL**, busque a distribuidora, selecione a base e clique em **Baixar e importar**. O download e a conversão podem levar vários minutos e ocupar vários GB.
6. Em **Processar BDGD**, selecione a base e o alimentador e clique em **Carregar ou processar e adicionar**.

A versão portátil ainda não tem assinatura digital. Distribuímos o código e o processo de compilação neste repositório. O Python e suas dependências acompanham o ZIP; não é necessário instalá-los separadamente.

### Depois do primeiro uso

Abra novamente o SUCURI Local e inicie o serviço. As bases e os resultados anteriores permanecem no disco. Um alimentador com resultado compatível é carregado do cache; marque **Reprocessar** apenas quando quiser recalcular.

Para comparar alimentadores, mantenha **Adicionar sem substituir o mapa** marcado e carregue outros alimentadores. Use **Redes carregadas** para ocultar ou remover redes da visualização; isso não apaga os arquivos salvos. Selecione um alimentador em **Alimentador no mapa** para exportar seu GeoJSON ou KMZ; **Fluxo ↓** baixa os arquivos de entrada daquele processamento.

### Onde ficam os arquivos?

Na pasta escolhida no aplicativo:

```text
SUCURI/
  bases/              bases importadas da ANEEL (CSV e GDB)
  runtime/downloads/  arquivos de origem baixados
  runtime/jobs/       redes, relatórios, logs e exportações
  runtime/cache/      índice dos resultados reutilizáveis
```

A preferência de pasta fica em `%LOCALAPPDATA%/SUCURI/settings.json` no Windows ou `~/.config/SUCURI/settings.json` no Linux. Trocar a pasta não move arquivos existentes: selecione novamente a pasta antiga para reencontrar seus dados. Faça backup da pasta inteira para preservar bases e resultados.

## Se não conectar

- **Failed to fetch / sem resposta:** confirme que o aplicativo mostra “Serviço ativo”. Autorize o acesso à rede local nas permissões do site no navegador. Atualize a página e tente novamente.
- **Navegador bloqueia a conexão:** no aplicativo, clique em **Abrir versão local**. A mesma interface abre em `http://127.0.0.1:8081/` e usa o mesmo armazenamento, sem precisar de código. Esse é também o caminho recomendado para navegadores sem suporte à conexão entre site público e localhost.
- **Código incorreto ou expirado:** clique em **Novo código** no aplicativo. Cada código dura 10 minutos, pode ser usado uma vez e bloqueia após cinco tentativas. Reiniciar o aplicativo invalida conexões anteriores.
- **Erro de DLL ao abrir pela pasta do WSL:** extraia o aplicativo em uma pasta Windows local (C: ou D:). As bibliotecas nativas podem não carregar por caminhos `\\wsl.localhost`.
- **Porta 8081 ocupada:** feche outra instância do aplicativo ou o servidor SUCURI iniciado no terminal. O aplicativo não encerra automaticamente programas de terceiros.
- **Sem bases disponíveis:** importe uma no painel ANEEL. Para CSVs já preparados, coloque cada base em `bases/NOME_DA_BASE/`, incluindo `CTMT.csv` e as demais tabelas necessárias.
- **Elementos sem coordenadas:** consulte o relatório. A topologia pode conter nós sem posição; não inventamos coordenadas para exibi-los no mapa.

## Linux, WSL e desenvolvimento

Use Python 3.12. No Linux, instale os pacotes de sistema `python3-venv` e `python3-tk` se necessário.

```bash
git clone https://github.com/CristhianGRO/sucuri-bdgd.git
cd sucuri-bdgd
python3 -m venv .venv
.venv/bin/python -m pip install -r web_backend/requirements.txt
.venv/bin/python sucuri_local.py
```

Sem interface gráfica:

```bash
.venv/bin/python -m web_backend.server --port 8081
```

O terminal exibe um código para conectar o site. Mantenha-o aberto. Para definir o armazenamento explicitamente:

```bash
.venv/bin/python -m web_backend.server --data /mnt/d/SUCURI/bases --runtime /mnt/d/SUCURI/runtime
```

No WSL, o redirecionamento de localhost para o navegador Windows depende da configuração da máquina. Se falhar, prefira executar o aplicativo Windows diretamente. A alternativa local abre na mesma porta informada no terminal. O site publicado conecta à porta padrão 8081.

No Windows, para executar a partir do código:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r web_backend/requirements.txt
.\.venv\Scripts\python.exe sucuri_local.py
```

## Arquitetura e privacidade

O GitHub Pages hospeda apenas HTML, CSS e JavaScript. O navegador desenha o mapa e chama o serviço Python no próprio computador. O Python consulta o catálogo oficial da ANEEL, baixa a base, forma a rede e salva os resultados. Não existe servidor de processamento SUCURI na nuvem.

O serviço escuta somente em `127.0.0.1`. A conexão do Pages aceita apenas a origem `https://cristhiangro.github.io` e requer pareamento; o token fica na sessão da aba e não vai em URLs. CORS reconhece a origem, não o caminho do repositório: outros sites sob essa mesma origem compartilham o limite de confiança do navegador. A interface local pode acessar o serviço diretamente.

Os arquivos BDGD não são enviados ao GitHub. O navegador ainda solicita bibliotecas a CDNs e imagens do mapa ao OpenStreetMap (que recebe as coordenadas das áreas consultadas). O mapa não requer chave de API, exige atribuição e respeita o uso normal de tiles; não há download em massa de mapas.

## Limites atuais

- As exportações de fluxo são **arquivos de entrada**, não resultados de simulação. Valide o relatório, ilhas, coordenadas e parâmetros elétricos antes do uso técnico.
- A qualidade e a completude dependem da base BDGD. Geometrias CSV podem ligar nós por segmentos retos.
- O cache verifica metadados dos arquivos, versão do motor e dependências. Alterações na base ou no motor podem exigir novo processamento.
- A execução padrão usa um processo de trabalho; o servidor por terminal aceita `--workers 1` a `--workers 4`. Bases grandes exigem memória e espaço de disco compatíveis.
- A visualização tem limite de 100 mil elementos e a importação manual de GeoJSON, 25 MB.
- O aplicativo precisa de internet para baixar bases e carregar mapas/bibliotecas da interface.

## Publicação e manutenção

- `.github/workflows/pages.yml` publica somente os arquivos estáticos de `web/` a cada push em `main`.
- `.github/workflows/checks.yml` executa os testes em Windows e Linux.
- `.github/workflows/release.yml` compila e verifica o aplicativo Windows e publica o ZIP quando uma tag `v*` é enviada.
- Dados, ambientes Python e resultados estão excluídos do Git. Não adicione bases ou dados de consumidores ao repositório.
- Para um fork, ajuste a origem em `web_backend/access.py` e os links do site, launcher e README. Habilite **Settings → Pages → GitHub Actions**.

Testes locais:

```bash
python -m unittest discover -s web_backend/tests -v
node --test web/tests/model.test.mjs web/tests/symbology.test.mjs web/tests/networks.test.mjs
```
