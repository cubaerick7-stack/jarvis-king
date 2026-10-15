# Bolha 3.0: plano dos 100+ recursos

Plano montado com o João em 14/10/2026 para a "mega atualização". Quem pegar um item (Claude ou Codex)
marca `[x]` aqui no mesmo commit. As regras de sempre continuam: grátis, leve no i3 de 8 GB, tudo em
português, e **sempre pergunta antes de apagar, mandar, publicar, instalar ou gastar dinheiro**.

## Situação (15/10/2026, Claude)

Tudo abaixo marcado com `[x]` está **no código, com teste automático passando no Linux e no Windows** (o CI do
GitHub roda os testes no Windows, inclusive um que mexe de verdade no Bloco de Notas pela UI Automation).
Pela regra de ouro, cada item só conta como pronto de verdade depois do **teste de pronto no PC** do João:
a lista para testar está no fim do `TESTES.txt`. Como usar cada coisa: seção "BOLHA 3.0" do `LEIA-ME.txt`.

- `[x]` feito (código + teste) · `[~]` feito em parte (o que falta está ao lado) · `[ ]` não feito (o motivo ao lado)
- Coisas que dependem de uma configuração única do senhor (Google, Home Assistant, Linketrack, pacotes opcionais)
  estão marcadas `[x]` com a observação; sem a configuração, o Bolha explica o setx que falta.

## O que vem primeiro (a ordem de verdade)

A lista grande mais abaixo é o **cardápio**. Esta aqui é a **fila**: só coisas úteis no dia a dia do João,
na ordem em que fazem o Bolha melhorar mais. Cada item tem um **teste de pronto**: só conta como feito
quando passar nele no PC de verdade.

### O motor que faz ele melhorar sozinho (antes de tudo)
| # | O quê | Por que importa | Pronto quando | Feito |
|---|---|---|---|---|
| M1 | **Diário de cada pedido**: o que o senhor disse, o que ele entendeu, o que fez, quanto demorou, se deu erro | Sem isso, ninguém sabe onde ele falha | "o que deu errado hoje?" lista os pedidos que falharam | ✓ código e teste |
| M2 | **"Errou" e "boa"** por voz ou botão no card | O senhor ensina sem configurar nada | depois de "errou, era o Chrome", o mesmo pedido acerta | ✓ código e teste |
| M3 | **Acertos viram exemplos** para a IA nos pedidos parecidos | Ele erra menos o mesmo tipo de pedido | um pedido que falhou 2x passa a acertar sem mexer no código | ✓ código e teste |
| M4 | **Relatório da semana** (`G:\Jarvis\config\relatorio.md`): as 10 falhas mais comuns, o que está lento | É a lista de trabalho do Claude e do Codex | o arquivo sai todo domingo e o senhor manda para nós | ✓ código e teste |
| M5 | **Cronômetro** em cada pedido (ouvir, pensar, fazer, falar) | Saber o que deixa ele lento | aparece no console e no relatório | ✓ código e teste |

### Fase 1: ouvir, entender e responder rápido
| # | O quê | Pronto quando | Feito |
|---|---|---|---|
| 1 | Calibração do microfone ("diga Bolha 3 vezes") | some o "Não ouvi o pedido (precisa de 350)" | ✓ código e teste |
| 2 | "Bolha, para" corta a fala na hora | testado com uma resposta longa | ✓ código e teste |
| 3 | Escuta mais 8 s depois de responder, sem chamar o nome | "e amanhã?" depois do clima funciona | ✓ código e teste |
| 4 | Vocabulário pessoal (contatos, jogos, pastas) para o Whisper | "abre o Omori" e "manda pro Erick Cuba" acertam por voz | ✓ código e teste |
| 5 | Roteador: Groq decide o simples, Gemini o pesado | pedido simples responde em menos de 2 s | ✓ código e teste |
| 6 | Começa a falar na 1ª frase ("Verificando, senhor") | a voz começa em até 1,5 s | ✓ código e teste |
| 7 | Vários pedidos numa frase | "abre o Spotify, toca lofi e baixa o volume" faz os três | ✓ código e teste |
| 8 | Autoteste ao abrir (mic, voz, IA, WAHA, internet) num card | o card mostra o que está fora e como arrumar | ✓ código e teste |

### Fase 2: as mãos e as utilidades que o senhor pediu
| # | O quê | Pronto quando | Feito |
|---|---|---|---|
| 9 | **Área de integrações**: cada serviço liga sozinho com `setx CHAVE` e "quais integrações eu tenho?" mostra o que falta | ligar uma integração nova é só o setx e reabrir | ✓ código e teste |
| 10 | **Leitor de PDF em voz alta** com "continua", "para", "volta" | lê um PDF de 10 páginas em partes | ✓ código e teste |
| 11 | **Limpador de memória do Windows** (libera RAM sem fechar nada) e diz quanto liberou | "limpa a memória" mostra antes e depois | ✓ código e teste |
| 12 | Clicar em qualquer botão de qualquer programa pelo nome | "clica em Salvar" no Bloco de Notas e no Word | ✓ código e teste |
| 13 | Modos prontos: aula, estudo, jogo, dormir | cada modo faz tudo de uma vez e desfaz com "sai do modo" | ✓ código e teste |
| 14 | "Aprende uma habilidade: quando eu disser X, faça Y" | a habilidade criada por voz funciona no dia seguinte | ✓ código e teste |
| 15 | Responder o WhatsApp por voz e resumo dos não lidos | "responde que já vou" (com "sim") | ✓ código e teste |
| 16 | Janelas: lado a lado, 2ª tela, layouts salvos | "modo trabalho" arruma as janelas | ✓ código e teste |
| 17 | Saúde do PC: disco, RAM, temperatura, o que está pesando | "por que tá lento?" diz o culpado e oferece fechar | ✓ código e teste |
| 18 | Instalar e atualizar programas pelo winget (com "sim") | "instala o VLC" funciona | ✓ código e teste |

### Fase 3: o resto do cardápio, em blocos pequenos
Escolhido pelo relatório da semana (M4): primeiro o que mais falha ou o que o senhor mais pede.

### Regra de ouro
Nada entra sem teste automático e sem o teste de pronto no PC. É melhor 10 coisas que funcionam sempre
do que 100 que funcionam às vezes.

---

## Como ele "aprende" de verdade

O Bolha não treina um modelo de IA no PC (o i3 não aguenta e não precisa). Ele aprende como um bom
mordomo: **guarda** o que o senhor ensina, corrige e repete, e **usa** isso nas próximas vezes.

- **Ensinado:** "aprende: quando eu disser *modo aula*, abre o Teams e silencia o WhatsApp".
- **Corrigido:** "não, era o Chrome": a próxima vez já abre o Chrome.
- **Observado:** os hábitos (o que o senhor faz toda segunda às 8h) viram sugestões e depois rotinas.
- **Mostrado:** "observa o que eu faço": grava os cliques e teclas e depois repete sozinho.

Tudo fica na memória (`G:\Jarvis\config`), visível e apagável pela tela.

## Os 4 alicerces (fazer primeiro: o resto depende deles)

1. **Ouvido**: ouvir certo, rápido, e saber quando o senhor terminou de falar.
2. **Cérebro**: entender a conversa, decidir rápido e falar sem demora.
3. **Memória que aprende**: ensinar, corrigir, apelidos, macros.
4. **Mãos**: mexer em qualquer botão de qualquer programa, não só nos que têm atalho pronto.

---

## 1. Ouvido (audição)
- [x] 1. Cronômetro de cada pedido: quanto levou para ouvir, pensar, fazer e falar (mostra no console e num card).
- [x] 2. Calibração guiada do microfone: "diga Bolha 3 vezes" e ele acerta o volume mínimo sozinho (hoje aparece "precisa de 350").
- [x] 3. Limite de volume que se ajusta ao barulho do quarto ao longo do dia.
- [x] 4. Saber quando o senhor terminou de falar (detector de voz leve), sem cortar no meio nem esperar demais. (corte de fala adaptativo; o detector de voz completo usa o webrtcvad, opcional)
- [x] 5. Interromper: "Bolha, para" corta a fala dele na hora.
- [x] 6. Conversa contínua: depois de responder, escuta mais 8 s sem precisar dizer "Bolha".
- [x] 7. Vocabulário pessoal para o Whisper: nomes de contatos, jogos e pastas (acerta "Omori", "Erick Cuba").
- [x] 8. A IA corrige a frase quando a transcrição vem estranha ("abre o o mori" -> "abre o Omori").
- [x] 9. Nome "Bolha" sem falso alarme com "bola", "olha" (lista de palavras parecidas por contexto).
- [x] 10. Abaixar a música e o jogo enquanto ouve (melhorar o que já existe).
- [x] 11. Usar o microfone do celular como microfone do PC (pelo celular.py). (já existia: o microfone do celular manda o pedido para o PC)
- [ ] 12. (Talvez) Reconhecer só a voz do João: só se ficar leve no i3. — não feito: reconhecer a voz pesaria no i3 de 8 GB; volta se o relatório da semana mostrar falsos alarmes de outras vozes

## 2. Cérebro e conversa
- [x] 13. Contexto de verdade: atalhos não pegam frases com "esse/isso/ele/lá"; a IA resolve pela conversa.
- [x] 14. Groq decide rápido; Gemini só para o pesado (tela, textos longos). Ferramentas por chamada nativa, não JSON no texto.
- [x] 15. Falar em pedaços: começa a falar a 1ª frase enquanto o resto ainda chega.
- [x] 16. Frases prontas gravadas ("Verificando, senhor") para resposta instantânea.
- [x] 17. Vários pedidos numa frase: "abre o Spotify, toca lofi e baixa o volume".
- [x] 18. Perguntar quando estiver em dúvida, com as opções num card ("qual dos dois, senhor?").
- [x] 19. Não repetir sempre as mesmas frases (variar "Às suas ordens").
- [x] 20. Personalidade ajustável: mais sério, mais humor seco, mais curto.
- [x] 21. Modo papo: conversa livre, ele pergunta de volta e lembra do assunto.
- [x] 22. "Por que você fez isso?": explica o que fez e por quê.
- [x] 23. Ver a tela: "o que é isso?", "qual o erro aqui?" (print + IA).
- [x] 24. Boa noite: resumo do dia, lembretes de amanhã, e desliga a tela.

## 3. Memória que aprende
- [x] 25. "Aprende: quando eu disser X, faça Y": atalhos pessoais por voz.
- [x] 26. Aprender com correção: "não, era o Chrome" vira preferência guardada.
- [x] 27. Apelidos: "o patrão" = contato tal; "meu jogo" = Omori; "o contrato" = tal arquivo.
- [x] 28. Hábitos viram rotinas: "toda segunda 8h o senhor abre o Teams; quer que eu faça sozinho?"
- [x] 29. "Observa o que eu faço": grava cliques e teclas e repete como macro (com botão PARAR).
- [x] 30. Memória de pessoas: aniversários, quem é quem, o que cada um gosta.
- [x] 31. Preferências automáticas: música por hora do dia, volume preferido por app.
- [x] 32. Nota do senhor: "bom trabalho" / "errou" ajusta as próximas escolhas.
- [x] 33. "O que você aprendeu essa semana?": ele conta.
- [x] 34. Painel da memória na tela: ver, editar e apagar o que ele sabe.
- [x] 35. Backup da memória (pendrive ou outra pasta).

## 4. Mãos: mexer em cada pedacinho do PC
- [x] 36. Clicar em qualquer botão de qualquer programa pelo nome (UI Automation do Windows).
- [x] 37. Ler o que está escrito numa janela (para a IA entender o programa aberto).
- [x] 38. Visão de reserva: print + IA acha o botão quando o Windows não informa (pede confirmação).
- [x] 39. Modo agente: "faz X no programa Y" em vários passos, mostrando cada passo num card, com botão PARAR.
- [x] 40. Preencher formulários e campos de qualquer programa.
- [x] 41. Janelas: lado a lado, mandar para a 2ª tela, maximizar, layouts salvos ("modo trabalho").
- [x] 42. Windows: Wi-Fi, Bluetooth, modo escuro, não perturbe, saída de som (fone/caixa), resolução.
- [x] 43. Instalar e atualizar programas pelo winget (confirmação).
- [x] 44. Desinstalar programa (confirmação).
- [x] 45. Limpeza: temporários, lixeira, downloads velhos (confirmação + relatório do que liberou).
- [x] 46. "O que está pesando?" e fechar o culpado (confirmação se não for programa comum).
- [x] 47. Imprimir arquivo.
- [x] 48. Histórico da área de transferência ("cola o que eu copiei antes").
- [x] 49. Atalhos de qualquer app por voz: "salva", "desfaz", "nova aba".
- [x] 50. Organizar pasta (por tipo/data), renomear em lote, compactar/descompactar.
- [x] 51. Converter arquivos: imagem para PDF, vídeo para MP3 (ffmpeg).
- [x] 52. Volume por programa (Discord mais alto, jogo mais baixo).

## 5. Arquivos e documentos
- [x] 53. Buscar dentro dos arquivos (texto de PDF e Word), não só pelo nome.
- [x] 54. Perguntas sobre um documento ("qual o prazo nesse contrato?").
- [x] 55. Ditar um documento (Word ou txt).
- [x] 56. Ler PDF em voz alta.
- [x] 57. Planilha: abrir, somar uma coluna, criar uma simples.
- [x] 58. Fotos por data ("fotos de julho").
- [x] 59. Backup automático de uma pasta.
- [x] 60. Aviso de disco quase cheio.

## 6. Internet e navegador
- [x] 61. Abas: "fecha as abas do YouTube", "volta para a aba do Gmail". (nas abas do navegador do Bolha)
- [x] 62. Resumir ou ler em voz alta a página aberta.
- [x] 63. Acompanhar preço de produto e avisar quando baixar.
- [x] 64. Rastrear encomenda dos Correios. (com a conta grátis do Linketrack: setx LINKETRACK_USER e LINKETRACK_TOKEN)
- [x] 65. Traduzir o texto da tela.
- [x] 66. "Abre o último arquivo baixado."
- [x] 67. Favoritos por voz.
- [x] 68. Pesquisa comparando opções (preço, avaliação) num card lado a lado.

## 7. Comunicação
- [x] 69. WhatsApp: "responde que já vou" (para a última mensagem).
- [x] 70. Resumo das mensagens não lidas.
- [x] 71. Transcrever e ler os áudios recebidos no WhatsApp.
- [x] 72. Mandar áudio gravado pelo WhatsApp.
- [x] 73. Gmail: ler, resumir, responder (API oficial, confirmação). (depois da configuração do Google, uma vez)
- [x] 74. Google Agenda: eventos do dia, criar evento. (depois da configuração do Google, uma vez)
- [x] 75. Contatos VIP: avisa na hora; os outros só no resumo.
- [x] 76. Não perturbe: segura os avisos e conta depois.

## 8. Rotina e casa
- [x] 77. Modos: jogo, estudo, trabalho, dormir (cada um mexe em várias coisas de uma vez).
- [x] 78. Pomodoro com foco (bloqueia distração, avisa a pausa).
- [x] 79. Lista de tarefas e de compras por voz, num card.
- [x] 80. Lembrete de água e de postura (opcional).
- [x] 81. Contas a pagar com vencimento.
- [x] 82. Aviso de chuva antes de sair.
- [x] 83. Música por humor ("algo para animar").
- [x] 84. (Se tiver) lâmpadas e tomadas inteligentes. (pelo Home Assistant: setx HA_URL e HA_TOKEN)
- [x] 85. Contagem regressiva para datas ("quantos dias para a prova?").
- [x] 86. Despertador com soneca ("mais 10 minutos").

## 9. Jogos e mídia
- [x] 87. Modo jogo: fecha o que pesa, não perturbe, prioridade para o jogo.
- [x] 88. Abrir jogo da Steam pelo nome.
- [~] 89. FPS e temperatura no HUD. — FPS pelo painel do Xbox Game Bar ("mostra o fps"); a temperatura aparece no HUD e na saúde do PC só quando o Windows informa (muitos notebooks só informam como administrador)
- [x] 90. "Grava os últimos 30 segundos" (Xbox Game Bar).
- [x] 91. "Onde assisto tal filme?"
- [x] 92. Retomar a música ou o vídeo de onde parou.

## 10. Saúde e segurança do PC
- [x] 93. Relatório de saúde: disco, RAM, temperatura, atualizações pendentes.
- [x] 94. Aviso de programa novo que começou a abrir com o Windows.
- [x] 95. Bloquear o PC por voz. (já existia)
- [x] 96. Senha falada para ações perigosas (apagar, desinstalar).
- [x] 97. Desfazer a última ação de arquivo (mover, renomear).
- [x] 98. Modo visita: esconde notificações e cards pessoais.

## 11. Tela e celular
- [x] 99. HUD fixo: CPU, RAM, clima, hora, próxima tarefa.
- [x] 100. Notificações do Windows viram card do Bolha. (com os pacotes winrt opcionais; veja TELA E CELULAR no LEIA-ME)
- [x] 101. Temas do reator (azul, vermelho e dourado do Homem de Ferro).
- [x] 102. Celular: mandar arquivo do celular para o PC e do PC para o celular.
- [x] 103. Celular avisa quando o PC termina algo (download, render).
- [x] 104. Celular: botões rápidos (modos, despertador, volume).

## 12. Ele se cuidando
- [x] 105. Autoteste ao abrir: microfone, voz, IA, WAHA, internet, num card de status.
- [x] 106. Atualizar sozinho (git pull) com confirmação.
- [x] 107. Relatório de erro pronto para mandar ao Claude ou ao Codex.
- [x] 108. Modo sem internet: só os atalhos locais, e avisa o que não dá.

---

## Ordem sugerida

**Fase 1: alicerces (primeiro, porque melhora tudo que vem depois)**
1, 2, 4, 5, 6, 7, 13, 14, 15, 16, 17, 25, 26, 27, 36, 37, 39, 105

**Fase 2: o dia a dia**
3, 8, 18, 23, 24, 28, 41, 42, 46, 49, 61, 62, 69, 70, 77, 79, 86, 99, 100

**Fase 3: o resto**, em blocos por grupo, conforme o senhor for pedindo.

## Limites honestos
- **Gmail e Agenda** precisam de uma configuração de acesso no Google, uma vez só (a API oficial e gratuita).
- **Mexer em qualquer programa**: a maioria dos programas do Windows informa seus botões; jogos e alguns apps
  não. Nesses, ele usa a visão (print + IA), que é mais lenta e sempre pede confirmação antes de clicar.
- **Cota grátis da IA**: com 100 recursos usando IA, a cota acaba mais rápido. Por isso o cronômetro (1) e o
  "Groq decide, Gemini só no pesado" (14) vêm primeiro.

---

## 13. Skills: 70 receitas prontas (cardápio, depois da Fase 2)

Uma skill é uma pasta `G:\Jarvis\skills\<nome>\` com um `SKILL.md` (a receita em texto). A IA vê só o nome e
uma linha de cada uma; quando o pedido combina, carrega a receita e segue usando as ferramentas que já existem.
Ações perigosas continuam pedindo "sim". Skills importadas da internet entram só com o texto; script só depois
do senhor aprovar. Antes delas: **o sistema de skills** (pasta, lista na IA, "aprende uma habilidade" por voz,
importar só o texto).

### Rotina e modos
- [x] S1. **modo-aula**: abre Teams/Meet, silencia o WhatsApp, volume em 30, abre o caderno.
- [x] S2. **modo-estudo**: Pomodoro de 25 min, lofi baixo, bloqueia YouTube e redes.
- [x] S3. **modo-trabalho**: abre e-mail, agenda e as pastas do dia, lado a lado.
- [x] S4. **modo-jogo**: fecha o que pesa, não perturbe, Discord aberto, prioridade para o jogo.
- [x] S5. **modo-dormir**: boa noite, lembretes de amanhã, despertador, apaga a tela e baixa o volume.
- [x] S6. **modo-filme**: tela cheia, som alto, notificações desligadas, luz do HUD apagada.
- [x] S7. **modo-visita**: esconde notificações e cards pessoais.
- [x] S8. **cheguei-em-casa**: o "papai chegou" com resumo e o que ficou pendente.
- [x] S9. **saindo-de-casa**: clima e chuva, o que levar, bloqueia o PC.
- [x] S10. **pausa-agora**: 5 minutos de alongamento guiado com contagem.

### Dia a dia
- [x] S11. **lista-de-compras**: anota por voz, organiza por seção e manda no zap na hora de sair.
- [x] S12. **contas-do-mes**: lista as contas com vencimento e avisa 2 dias antes.
- [x] S13. **receita-com-o-que-tem**: "tenho ovo e arroz": pesquisa receita e mostra os passos num card.
- [x] S14. **cozinhando**: lê a receita passo a passo, espera o "próximo", com timers.
- [x] S15. **aniversarios**: avisa o aniversário e sugere a mensagem (manda só com "sim").
- [x] S16. **agua-e-postura**: lembretes ao longo do dia, só com o PC em uso.
- [x] S17. **resumo-da-semana**: o que o senhor fez, ouviu e pediu na semana.
- [x] S18. **planejar-o-dia**: monta o dia com lembretes, agenda e tarefas, e pergunta o que falta.
- [x] S19. **tarefas**: lista de tarefas com prioridade, riscar por voz.
- [x] S20. **contagem-regressiva**: "quantos dias para a prova/viagem?" com card.

### Estudo
- [x] S21. **explica-simples**: explica um assunto como para uma criança e depois como prova.
- [x] S22. **quiz**: faz perguntas sobre um assunto e corrige as respostas faladas.
- [x] S23. **resumo-de-pdf**: resume o PDF por capítulos num card com tópicos.
- [x] S24. **flashcards**: cria cartões de estudo de um texto e revisa por voz.
- [x] S25. **trabalho-escolar**: pesquisa com fontes, monta o esqueleto do trabalho no Word.
- [x] S26. **corrige-texto**: corrige o texto copiado (ortografia e clareza) e cola de volta.
- [x] S27. **traduz-tela**: traduz o texto selecionado ou da tela.
- [x] S28. **conta-explicada**: resolve uma conta mostrando o passo a passo.
- [x] S29. **idioma-do-dia**: uma frase em inglês por dia, com pronúncia.
- [x] S30. **leitura-em-voz**: lê o artigo ou PDF em voz alta, com pausa e "continua".

### Arquivos e PC
- [x] S31. **arrumar-downloads**: separa por tipo, apaga instalador velho (pergunta antes).
- [x] S32. **limpeza-do-pc**: temporários, lixeira, cache; diz quanto liberou.
- [x] S33. **backup-rapido**: copia uma pasta para o pendrive/outro disco.
- [x] S34. **renomear-fotos**: renomeia por data, em lote.
- [x] S35. **pdf-de-imagens**: junta prints/fotos num PDF.
- [x] S36. **comprimir-para-enviar**: compacta e diminui arquivos grandes para mandar no zap.
- [x] S37. **achar-arquivo-perdido**: procura por nome, conteúdo e data aproximada.
- [x] S38. **saude-do-pc**: disco, RAM, temperatura, atualizações pendentes, num card.
- [x] S39. **por-que-ta-lento**: acha o que está pesando e sugere o que fechar.
- [x] S40. **instalar-programa**: instala pelo winget (pergunta antes).
- [x] S41. **atualizar-tudo**: atualiza os programas pelo winget (pergunta antes).
- [x] S42. **wifi-com-problema**: testa a internet, reinicia o adaptador, mostra o resultado.
- [x] S43. **fone-ou-caixa**: troca a saída de som.
- [x] S44. **print-e-manda**: print da tela e manda para alguém (pergunta antes).
- [x] S45. **gravar-tela**: grava a tela por X minutos e salva.

### Comunicação
- [x] S46. **responde-zap**: responde a última mensagem pelo que o senhor ditar (pergunta antes).
- [x] S47. **resumo-do-zap**: resume as conversas não lidas, por pessoa.
- [x] S48. **ouvir-audios**: transcreve e lê os áudios recebidos.
- [x] S49. **avisa-que-atrasei**: manda "vou atrasar X minutos" para quem o senhor disser.
- [x] S50. **mensagem-bonita**: escreve parabéns/agradecimento no tom do senhor.
- [x] S51. **email-rapido**: dita e manda e-mail (pergunta antes).
- [x] S52. **resumo-do-email**: lê e resume os e-mails importantes.
- [x] S53. **marcar-compromisso**: cria evento na agenda e lembra antes.
- [x] S54. **vip**: mensagem de quem é VIP avisa na hora; o resto só no resumo.
- [x] S55. **nao-perturbe-ate**: segura avisos até um horário e conta tudo depois.

### Internet e compras
- [x] S56. **comparar-precos**: compara um produto em várias lojas num card.
- [x] S57. **vigiar-preco**: avisa quando o preço cair.
- [x] S58. **rastrear-encomenda**: acompanha o código dos Correios e avisa mudanças.
- [x] S59. **noticias-de**: notícias de um assunto (time, jogo, cidade) num card.
- [x] S60. **placar**: placar e próximo jogo do time do senhor.
- [x] S61. **cotacoes**: dólar, euro, bitcoin, com variação do dia.
- [x] S62. **onde-assistir**: em qual streaming está o filme/série.
- [x] S63. **resumo-de-video**: resume um vídeo do YouTube pela legenda.
- [x] S64. **pesquisa-profunda**: pesquisa em várias fontes e monta um relatório com links.

### Diversão e jogos
- [x] S65. **playlist-do-humor**: música pelo humor ("algo para animar", "para focar").
- [x] S66. **abrir-jogo**: abre jogo da Steam/Epic pelo nome e entra no modo jogo.
- [x] S67. **dica-do-jogo**: pesquisa dica/guia da parte em que o senhor travou.
- [x] S68. **clipe**: salva os últimos 30 s do jogo (Xbox Game Bar).
- [x] S69. **piada-e-curiosidade**: uma curiosidade ou piada seca de mordomo.
- [x] S70. **contar-historia**: conta uma história curta (para dormir ou passar o tempo).
