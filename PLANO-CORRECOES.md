# Plano de correções (o que o João achou testando no PC)

Anotado em 15/10/2026, à noite. **Nada de código ainda**: este arquivo é a lista do que corrigir na próxima
sessão (Claude ou Codex). Cada item diz o que aconteceu, o que deveria acontecer, a causa provável e o teste
de pronto. Quem corrigir marca `[x]` no mesmo commit.

As regras do `AGENTS.md` continuam valendo: teste automático para cada bug corrigido, tudo em português e
nada pesado para o i3.

---

## 1. Print pelo WhatsApp: demora, diz que mandou e não manda

- [ ] **O que aconteceu:** "manda um print pro (amigo)". O Bolha demorou muito, falou que tinha enviado, e o
  print não chegou. Antes funcionava.
- **O que deveria acontecer:** o print chega em poucos segundos e o Bolha só diz "enviei" quando o WhatsApp
  confirmar a entrega.
- **Causas prováveis (no código de hoje):**
  - O print pega **todas as telas juntas** (`sct.monitors[0]` em `_new_screenshot`, no `windows/jarvis_ai.py`).
    Com duas telas sai um PNG enorme, que vai em base64 dentro do JSON para o WAHA. Isso deixa o envio lento e
    pode fazer o WhatsApp recusar a imagem.
  - O Bolha diz "enviei" assim que o WAHA responde "ok" (`W.send_file` no `windows/waha.py`), sem conferir se a
    mensagem saiu de verdade.
  - Achar o contato pode cair na lista inteira de contatos (`/api/contacts/all`, até 60 s), o que explica a
    demora antes de perguntar.
- **Como corrigir:**
  1. Print só da **tela principal** (`monitors[1]`), convertido em **JPG** de no máximo uns 1920 px e uns 300 KB.
  2. Depois de enviar, conferir a mensagem pelo id que o WAHA devolve: o "ack" de enviado ou entregue, por até
     uns 15 s. Se não confirmar, dizer a verdade: "o WhatsApp não confirmou o envio".
  3. Guardar em cache (memória do programa) os contatos já achados, para a segunda vez ser na hora.
  4. Cronometrar cada parte (achar o contato, tirar o print, enviar) no diário, para ver o que demora.
- **Teste de pronto:** "manda um print pro Erick" chega no WhatsApp dele em menos de 10 s, e com o WAHA desligado
  o Bolha diz que não conseguiu (nunca "enviei").

## 2. Confirmação: para arquivo e print, confirmar só o CONTATO

- [ ] **O que o João quer:**
  - **Mensagem de texto:** continua como hoje: "Posso enviar 'tal mensagem' para Fulano?".
  - **Print, foto e arquivo:** não perguntar "posso enviar?". O pedido já diz o que mandar. Só mostrar o contato
    achado e confirmar se é ele: **"É esse contato: Erick Cuba?"** (com nome e foto ou número no card). O
    "sim" é o OK para mandar.
- **Onde mexer:** `whatsapp_send_file` no `windows/jarvis_ai.py`, que hoje pergunta "Mando arquivo.png para Fulano?",
  e o card "Confirmar" do `reator.html`, que precisa de um tipo "contato" com avatar e nome.
- **Regra de segurança (AGENTS.md):** mandar continua pedindo um "sim". Só muda a pergunta: em vez do conteúdo,
  confirma o contato.
- **Teste de pronto:** "manda um print pro Erick", ele responde "É esse contato: Erick Cuba?", o João diz "sim"
  e o print vai.

## 3. Reconhecimento de voz precisa melhorar muito

- [ ] **O que aconteceu:** ele entende errado muitos pedidos falados. Hoje o João está no microfone do próprio
  PC; vai trocar de microfone, o que já deve ajudar.
- **O que fazer no Bolha:**
  1. Depois de trocar o microfone, rodar "calibra o microfone" de novo.
  2. Ligar o modo de depuração (`$env:JARVIS_VOZ_DEBUG=1`) e anotar no diário o texto que o Whisper devolveu e
     o que o senhor quis dizer. Isso vira a lista de palavras mais erradas no relatório da semana.
  3. Vocabulário pessoal automático: nomes dos contatos do WhatsApp, jogos instalados (Steam, Epic e atalhos da
     área de trabalho) e músicas mais pedidas vão para o Whisper sozinhos.
  4. Quando a transcrição vier estranha (palavras soltas sem verbo), a IA reescreve a frase antes de agir
     ("abre o o mori" -> "abre o Omori"). Hoje só existe a troca por vocabulário.
  5. Filtro de ruído do microfone e o detector de voz (webrtcvad) instalados por padrão, se não pesarem no i3.
- **Teste de pronto:** 20 pedidos falados do `TESTES.txt` seguidos, no microfone novo: pelo menos 18 entendidos certo.

## 4. "Abre tal jogo": procurar de verdade antes de dizer que não tem

- [ ] **O que aconteceu:** "abre pra mim tal jogo". Ele não achou, ou jogou a frase inteira na pesquisa do
  Windows.
- **O que deveria acontecer:** procurar em todo lugar, achar o nome mais parecido e só então abrir. Se não achar
  em lugar nenhum, dizer onde procurou.
- **Ordem de busca:**
  1. Atalhos da área de trabalho (a do usuário, a pública e a do OneDrive) e do Menu Iniciar.
  2. Jogos da Steam e da Epic.
  3. Apps da Microsoft Store e Xbox.
  4. Everything (.exe e .lnk em todos os discos, inclusive o G:).
  5. Pastas comuns de jogos (G:\Jogos, G:\Games, Program Files...).
- **Como acertar o nome:**
  - Limpar a frase antes de procurar: tirar "pra mim", "o jogo", "aquele", "abre"...
  - Comparar sem acento, sem espaço e por parecença ("omori" ~ "OMORI.exe" ~ "Omori - Atalho").
  - Se achar mais de um: card "Qual deles, senhor?" com as opções.
- **Pesquisa do Windows:** só como último recurso, com o nome limpo (nunca a frase inteira). Depois, conferir se
  abriu uma janela nova; se não abriu, avisar.
- **Caso real, o Minecraft:** ele nem reconheceu o nome e, quando reconheceu, não abriu. O Minecraft não é um
  .exe comum: vem pelo **Minecraft Launcher**, que é app da Microsoft Store/Xbox (abre por `shell:AppsFolder`) ou
  o launcher antigo (`MinecraftLauncher.exe`). Precisa de apelidos conhecidos ("minecraft" -> Minecraft Launcher),
  da busca nos apps da Store por parte do nome e de conferir se o launcher abriu de verdade.
- **Teste de pronto:** "abre pra mim o omori", "abre o minecraft", "abre aquele jogo do minecraft" e "joga hollow
  knight" abrem o jogo certo; um nome que não existe responde "não achei X na área de trabalho, Steam, Epic nem
  no Everything".

## 5. "Abre X" não pode ir direto para a pesquisa do Windows

- [ ] **O que aconteceu:** o atalho rápido pega tudo o que vem depois de "abre" e digita na pesquisa do Windows,
  mesmo quando não faz sentido.
- **Como corrigir:**
  - Primeiro entender o que é X: um programa, um jogo, um site, uma pasta, um arquivo ou outra coisa.
  - Frase comprida ou estranha, ou X que não bate com nada conhecido: vai para a IA formular o pedido certo,
    em vez de ir para a pesquisa do Windows.
  - A pesquisa do Windows só entra com um nome curto e limpo, depois de tudo do item 4.
- **Teste de pronto:** "abre pra mim aquele negócio de editar foto" pergunta ou sugere (ex.: Paint, Fotos) em vez
  de digitar a frase na pesquisa do Windows.

## 6. Música descrita: "coloca aquela música que fala tal coisa"

- [ ] **O que aconteceu:** ele pesquisou a descrição literal no YouTube, o que não faz sentido.
- **O que deveria acontecer:** a IA descobre qual é a música pela descrição (letra, cantor, filme, época) e
  monta a busca com nome e artista. Exemplos:
  - "aquela do Henrique e Juliano que fala de..." -> o nome da música + "Henrique e Juliano"
  - "a música do filme do Homem de Ferro do começo" -> "Back in Black AC/DC"
- **Como corrigir:**
  - Pedido de música sem nome claro ("aquela que", "a que fala", "a do filme") não vai pelo atalho do "toca":
    vai para a IA.
  - A IA usa a pesquisa (research) para identificar a música, e só então chama o play_youtube com o nome certo.
  - Se ficar em dúvida entre duas, pergunta com opções no card.
- **Teste de pronto:** três descrições diferentes tocam a música certa.

## 7. Despertador dentro do Bolha (sem abrir o navegador)

- [ ] **O que aconteceu:** na hora do alarme ele pesquisa a música, abre a página do YouTube e ela fica na frente.
  O PC é fraco, o navegador demora, e a página cobre o Bolha.
- **O que o João quer:**
  1. Na hora do alarme, o Bolha vem para a frente e abre um **card grande dentro dele** (pop-up do reator) com a
     hora, o botão **ACORDEI** e o nome da música. A música toca **dentro do Bolha**: nada de abrir o navegador.
  2. Ao clicar em ACORDEI (ou dizer "acordei"), a música para e começa o bom dia, falado e mostrado em cards:
     - "Bom dia, senhor. O mundo não parou enquanto o senhor dormia."
     - **Principais notícias**, cada uma num card **com imagem** (a foto da notícia, quando houver).
     - **Previsão do tempo** do dia (agora, máxima e mínima, chance de chuva) e a **roupa recomendada**.
     - **Lembretes e compromissos de hoje** (os lembretes do Bolha e a Agenda do Google, se estiver ligada).
     - No fim: "Por hoje é isso. Tenha um bom dia, senhor." e toca a **música final**, que o senhor escolhe.
- **Como fazer (ideia):**
  - Tocar o áudio no próprio reator: baixar só o áudio da música uma vez (o yt-dlp, guardado em
    `G:\Jarvis\cache\musicas`) e tocar com o player da página (`<audio>`). O despertador e a música final já
    ficam baixados na véspera, para tocar mesmo sem internet ou com o PC lento.
  - O card do despertador já existe (`despertador` no `reator.html`): ganha o player, a capa da música e o
    botão ACORDEI grande.
  - O bom dia vira uma sequência de cards (notícias com imagem, clima com ícone, roupa, lembretes) que trocam
    sozinhos enquanto ele fala. As imagens vêm do RSS das notícias, com o texto sempre por `textContent`.
  - Configurar: "a música do despertador é X" e "a música do bom dia é Y" (hoje é por setx
    `BOLHA_MUSICA_DESPERTAR` e `BOLHA_MUSICA_BOM_DIA`).
- **Teste de pronto:** "me acorda daqui a 2 minutos": na hora, o card abre dentro do Bolha com a música tocando
  e nenhum navegador abre. No ACORDEI, ele fala o bom dia com notícias (com imagem), clima, roupa e lembretes, e
  termina com "Tenha um bom dia" e a música final.

## 8. Falar como um assistente de verdade (menos "senhor", menos robô)

- [ ] **O que aconteceu:** ele fala "senhor" em quase toda frase ("Pronto, senhor", "Verificando, senhor", "Às
  suas ordens, senhor"). Fica robótico, com cara de frase programada.
- **O que o João quer:** falar natural, como um assistente de verdade. O "senhor" só quando cabe: no
  cumprimento, num aviso importante, numa confirmação. Nada de repetir em toda resposta.
- **Onde mexer:**
  - O prompt da IA (`build_ai_prompt`, `ANSWER_PROMPT`, `MORNING_PROMPT`, `GREETING_PROMPT`, `CHAT_PROMPT`):
    trocar "chama o usuário de senhor" por "use 'senhor' só de vez em quando, quando soar natural (no máximo
    uma vez a cada várias respostas)".
  - As frases prontas fixas no código: as listas `FILLERS`, `THANKS`, o `SMALL_TALK`, os avisos e as respostas
    das ferramentas. A maioria perde o "senhor" ("Pronto.", "Um instante.", "Abrindo o Chrome."), e as listas
    ganham mais variedade.
  - Respostas mais curtas e diretas, com o jeito de conversa e não de relatório.
  - Uma trava simples: se a última resposta já teve "senhor", a próxima frase pronta vem sem.
- **Teste de pronto:** 10 pedidos seguidos e o "senhor" aparece no máximo 2 ou 3 vezes; as respostas soam
  naturais.

## 9. Sem internet, a IA local entra sozinha

- [ ] **O que o João quer:** quando a internet cair, o Bolha usa sozinho a IA local que já está baixada (o
  Qwen 1.7B pelo Ollama, que é leve), sem precisar do `setx JARVIS_LOCAL 1`. Quando a internet voltar, ele volta
  para o Gemini e o Groq.
- **Como fazer:** no `ai_backends()`, se `autoteste.internet()` for falso e o Ollama estiver aberto com o
  modelo, colocar o Qwen na lista. Avisar uma vez: "Estou sem internet; sigo com a IA local, mais simples."
- **Decidido:** não usar o Gemma de 7,2 GB no PC (8 GB de RAM não aguentam). Fica o Qwen leve como reserva.
- **Teste de pronto:** com o Wi-Fi desligado, "me explica o que é fotossíntese" responde pela IA local; com o Wi-Fi
  ligado de novo, volta para a nuvem.

## 10. Slides da faculdade: "faz um slide sobre X e manda no zap"

- [ ] **O que o João quer:** "faz um slide sobre (tema) para a faculdade, com (tantos) slides, e manda pro
  (contato)" ou "...e manda pra mim no zap". O WhatsApp do Bolha (WAHA) é outro número, então mandar para o
  próprio João funciona igual a mandar para qualquer contato.
- **Como funcionaria:**
  1. **Conteúdo:** o Gemini pesquisa o tema (research, com as fontes) e monta o roteiro em JSON: título,
     de 6 a 12 slides com título e 3 a 5 tópicos curtos cada, notas do apresentador e um slide final de
     referências. O tom e o nível seguem o pedido (ex.: "para a aula de Direito Civil", "nível de faculdade").
  2. **Visual de verdade, nível profissional** (o João ainda não ligou nenhum app; decidido assim, pela regra do
     "grátis"):
     - **Padrão, grátis:** o Bolha monta o .pptx com o `python-pptx` num modelo caprichado (capa forte, ícones,
       uma imagem de fonte livre por slide, cores combinando, layouts variados). Não precisa de conta.
     - **Com o Google conectado** (o mesmo "conecta o Google" do Gmail e da Agenda), grátis: cria direto no
       Google Slides a partir de um modelo bonito e manda o **link** pelo WhatsApp. Isso também resolve o limite
       do WAHA para mandar arquivo.
     - **Gamma (opcional, pago):** é o que fica mais bonito, mas a API é dos planos pagos (confirmar o preço
       antes). Só se o João quiser pagar; a chave fica no `setx GAMMA_API_KEY` e o Bolha pergunta antes de gastar.
     - **Canva:** descartado. A API não gera slides sozinha.
  3. **Salvar e mostrar:** salva em `Documentos\Slides\<tema>.pptx`, abre para o João ver e diz quantos slides
     fez. O "muda o slide 3" ou "acrescenta um slide sobre Y" edita o mesmo arquivo.
  4. **Mandar:** pergunta "É esse contato: Fulano?" (item 2) e envia pelo WhatsApp. Também manda um **PDF**
     junto (abre em qualquer celular, sem PowerPoint).
- **Atenção, limite do WAHA:** o WAHA grátis manda imagem, mas PDF e .pptx dependem da versão. Se não mandar:
  - Plano B: transformar os slides em imagens (uma por slide) e mandar como álbum.
  - Plano C: "manda pro celular" (aparece com o botão Baixar).
  - Plano D: com o Google conectado, subir no Drive e mandar o link por texto.
- **Sem habilidade (skill):** é uma ferramenta direta do Bolha ("faz um slide"), ligada ao app por API.
- **Teste de pronto:** "faz um slide sobre a Revolução Francesa com 8 slides e manda pra mim no zap": o .pptx e
  o PDF chegam no WhatsApp do João e abrem certos no celular.

## 11. Textos de verdade: "faz um resumo do livro X no Word e me manda"

- [ ] **O que aconteceu:** os textos dele saem curtos e rasos: ele "só resume", sem escrever bastante.
- **O que o João quer:** "faz um resumo do livro (X) no Word e me manda" (ou "no Bloco de Notas") gera um
  texto **completo e bem escrito**, que é salvo e mandado.
  - O resumo tem introdução, os capítulos ou partes principais, personagens ou conceitos, temas e conclusão.
  - O tamanho segue o pedido ("resumo completo", "2 páginas", "bem detalhado", "só o principal"); o padrão é
    completo, não um parágrafo.
- **Como fazer:**
  - Pesquisa do livro com fontes (research), depois escrever em partes (uma chamada da IA por seção) para não
    sair cortado. O texto é escrito com o Gemini, que aceita textos longos.
  - Salva em `Documentos\Resumos\<título>.docx` (com títulos e parágrafos formatados) ou `.txt` no Bloco de
    Notas, abre para o João ver e manda pelo WhatsApp (confirmando o contato, item 2; com o mesmo limite do
    WAHA do item 10).
  - Hoje o `write_document` já cria o .docx, mas a IA escreve pouco: o prompt e o modo em partes resolvem isso.
- **Teste de pronto:** "faz um resumo completo de Dom Casmurro no Word e me manda no zap" gera um documento de
  pelo menos 2 páginas, bem dividido, que chega no WhatsApp.

## 12. Pesquisar e RESPONDER, não abrir o navegador

- [ ] **O que aconteceu:** "pesquisa tal coisa" abre o navegador do João com a busca. O João quer que o Bolha
  **saiba e fale a resposta**, não que mostre onde procurar.
- **Causa (no código de hoje):** o atalho rápido manda "pesquisa X" direto para o `search_web` (busca no Google
  no navegador), na regra `^(?:pesquisa|pesquise)\\s+(.+)$` do `fast_local_router`.
- **Como corrigir:**
  - "pesquisa X", "procura na internet X", "o que é X", "quem foi X", "como funciona X": vão para o
    **research** (o Gemini pesquisa na internet e responde falando, com o card de resumo e as fontes).
  - Pergunta de conhecimento que não muda com o tempo ("o que é fotossíntese") a IA já responde direto, sem
    pesquisar.
  - O navegador só abre quando o João pedir para ver: "abre no navegador", "me mostra os resultados", "pesquisa
    no Google e abre".
  - A resposta falada é completa (3 a 6 frases, com os números e nomes importantes); o card traz mais detalhes.
- **Teste de pronto:** "pesquisa quem inventou o avião" responde falando (e mostra o card) sem abrir o
  navegador; "pesquisa receita de bolo e abre no navegador" abre.

---

## Ordem sugerida

1. Itens 1 e 2 (WhatsApp): é o que mais irrita, e a correção é pequena.
2. Item 12 (pesquisar e responder): é pequeno e muda muito o dia a dia.
3. Item 8 (falar natural): é rápido.
4. Itens 4 e 5 (abrir programas e jogos, incluindo o Minecraft).
5. Item 11 (textos completos no Word e no Bloco de Notas).
6. Item 7 (despertador dentro do Bolha).
7. Item 6 (música descrita).
8. Item 10 (slides pelo app de slides).
9. Item 9 (IA local sem internet).
10. Item 3 (voz), depois do microfone novo.
