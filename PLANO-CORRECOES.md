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
- **Teste de pronto:** "abre pra mim o omori", "abre aquele jogo do minecraft" e "joga hollow knight" abrem o
  jogo certo; um nome que não existe responde "não achei X na área de trabalho, Steam, Epic nem no Everything".

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

---

## Ordem sugerida

1, 2 (WhatsApp: é o que mais irrita e a correção é pequena) -> 4 e 5 (abrir programas e jogos) -> 6 (música) -> 3 (voz,
depois do microfone novo).
