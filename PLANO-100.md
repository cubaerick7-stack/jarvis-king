# Bolha 3.0: plano dos 100+ recursos

Plano montado com o João em 14/10/2026 para a "mega atualização". Quem pegar um item (Claude ou Codex)
marca `[x]` aqui no mesmo commit. As regras de sempre continuam: grátis, leve no i3 de 8 GB, tudo em
português, e **sempre pergunta antes de apagar, mandar, publicar, instalar ou gastar dinheiro**.

## O que vem primeiro (a ordem de verdade)

A lista grande mais abaixo é o **cardápio**. Esta aqui é a **fila**: só coisas úteis no dia a dia do João,
na ordem em que fazem o Bolha melhorar mais. Cada item tem um **teste de pronto**: só conta como feito
quando passar nele no PC de verdade.

### O motor que faz ele melhorar sozinho (antes de tudo)
| # | O quê | Por que importa | Pronto quando |
|---|---|---|---|
| M1 | **Diário de cada pedido**: o que o senhor disse, o que ele entendeu, o que fez, quanto demorou, se deu erro | Sem isso, ninguém sabe onde ele falha | "o que deu errado hoje?" lista os pedidos que falharam |
| M2 | **"Errou" e "boa"** por voz ou botão no card | O senhor ensina sem configurar nada | depois de "errou, era o Chrome", o mesmo pedido acerta |
| M3 | **Acertos viram exemplos** para a IA nos pedidos parecidos | Ele erra menos o mesmo tipo de pedido | um pedido que falhou 2x passa a acertar sem mexer no código |
| M4 | **Relatório da semana** (`G:\Jarvis\config\relatorio.md`): as 10 falhas mais comuns, o que está lento | É a lista de trabalho do Claude e do Codex | o arquivo sai todo domingo e o senhor manda para nós |
| M5 | **Cronômetro** em cada pedido (ouvir, pensar, fazer, falar) | Saber o que deixa ele lento | aparece no console e no relatório |

### Fase 1: ouvir, entender e responder rápido
| # | O quê | Pronto quando |
|---|---|---|
| 1 | Calibração do microfone ("diga Bolha 3 vezes") | some o "Não ouvi o pedido (precisa de 350)" |
| 2 | "Bolha, para" corta a fala na hora | testado com uma resposta longa |
| 3 | Escuta mais 8 s depois de responder, sem chamar o nome | "e amanhã?" depois do clima funciona |
| 4 | Vocabulário pessoal (contatos, jogos, pastas) para o Whisper | "abre o Omori" e "manda pro Erick Cuba" acertam por voz |
| 5 | Roteador: Groq decide o simples, Gemini o pesado | pedido simples responde em menos de 2 s |
| 6 | Começa a falar na 1ª frase ("Verificando, senhor") | a voz começa em até 1,5 s |
| 7 | Vários pedidos numa frase | "abre o Spotify, toca lofi e baixa o volume" faz os três |
| 8 | Autoteste ao abrir (mic, voz, IA, WAHA, internet) num card | o card mostra o que está fora e como arrumar |

### Fase 2: as mãos e as utilidades que o senhor pediu
| # | O quê | Pronto quando |
|---|---|---|
| 9 | **Área de integrações**: cada serviço liga sozinho com `setx CHAVE` e "quais integrações eu tenho?" mostra o que falta | ligar uma integração nova é só o setx e reabrir |
| 10 | **Leitor de PDF em voz alta** com "continua", "para", "volta" | lê um PDF de 10 páginas em partes |
| 11 | **Limpador de memória do Windows** (libera RAM sem fechar nada) e diz quanto liberou | "limpa a memória" mostra antes e depois |
| 12 | Clicar em qualquer botão de qualquer programa pelo nome | "clica em Salvar" no Bloco de Notas e no Word |
| 13 | Modos prontos: aula, estudo, jogo, dormir | cada modo faz tudo de uma vez e desfaz com "sai do modo" |
| 14 | "Aprende uma habilidade: quando eu disser X, faça Y" | a habilidade criada por voz funciona no dia seguinte |
| 15 | Responder o WhatsApp por voz e resumo dos não lidos | "responde que já vou" (com "sim") |
| 16 | Janelas: lado a lado, 2ª tela, layouts salvos | "modo trabalho" arruma as janelas |
| 17 | Saúde do PC: disco, RAM, temperatura, o que está pesando | "por que tá lento?" diz o culpado e oferece fechar |
| 18 | Instalar e atualizar programas pelo winget (com "sim") | "instala o VLC" funciona |

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
- [ ] 1. Cronômetro de cada pedido: quanto levou para ouvir, pensar, fazer e falar (mostra no console e num card).
- [ ] 2. Calibração guiada do microfone: "diga Bolha 3 vezes" e ele acerta o volume mínimo sozinho (hoje aparece "precisa de 350").
- [ ] 3. Limite de volume que se ajusta ao barulho do quarto ao longo do dia.
- [ ] 4. Saber quando o senhor terminou de falar (detector de voz leve), sem cortar no meio nem esperar demais.
- [ ] 5. Interromper: "Bolha, para" corta a fala dele na hora.
- [ ] 6. Conversa contínua: depois de responder, escuta mais 8 s sem precisar dizer "Bolha".
- [ ] 7. Vocabulário pessoal para o Whisper: nomes de contatos, jogos e pastas (acerta "Omori", "Erick Cuba").
- [ ] 8. A IA corrige a frase quando a transcrição vem estranha ("abre o o mori" -> "abre o Omori").
- [ ] 9. Nome "Bolha" sem falso alarme com "bola", "olha" (lista de palavras parecidas por contexto).
- [ ] 10. Abaixar a música e o jogo enquanto ouve (melhorar o que já existe).
- [ ] 11. Usar o microfone do celular como microfone do PC (pelo celular.py).
- [ ] 12. (Talvez) Reconhecer só a voz do João: só se ficar leve no i3.

## 2. Cérebro e conversa
- [ ] 13. Contexto de verdade: atalhos não pegam frases com "esse/isso/ele/lá"; a IA resolve pela conversa.
- [ ] 14. Groq decide rápido; Gemini só para o pesado (tela, textos longos). Ferramentas por chamada nativa, não JSON no texto.
- [ ] 15. Falar em pedaços: começa a falar a 1ª frase enquanto o resto ainda chega.
- [ ] 16. Frases prontas gravadas ("Verificando, senhor") para resposta instantânea.
- [ ] 17. Vários pedidos numa frase: "abre o Spotify, toca lofi e baixa o volume".
- [ ] 18. Perguntar quando estiver em dúvida, com as opções num card ("qual dos dois, senhor?").
- [ ] 19. Não repetir sempre as mesmas frases (variar "Às suas ordens").
- [ ] 20. Personalidade ajustável: mais sério, mais humor seco, mais curto.
- [ ] 21. Modo papo: conversa livre, ele pergunta de volta e lembra do assunto.
- [ ] 22. "Por que você fez isso?": explica o que fez e por quê.
- [ ] 23. Ver a tela: "o que é isso?", "qual o erro aqui?" (print + IA).
- [ ] 24. Boa noite: resumo do dia, lembretes de amanhã, e desliga a tela.

## 3. Memória que aprende
- [ ] 25. "Aprende: quando eu disser X, faça Y": atalhos pessoais por voz.
- [ ] 26. Aprender com correção: "não, era o Chrome" vira preferência guardada.
- [ ] 27. Apelidos: "o patrão" = contato tal; "meu jogo" = Omori; "o contrato" = tal arquivo.
- [ ] 28. Hábitos viram rotinas: "toda segunda 8h o senhor abre o Teams; quer que eu faça sozinho?"
- [ ] 29. "Observa o que eu faço": grava cliques e teclas e repete como macro (com botão PARAR).
- [ ] 30. Memória de pessoas: aniversários, quem é quem, o que cada um gosta.
- [ ] 31. Preferências automáticas: música por hora do dia, volume preferido por app.
- [ ] 32. Nota do senhor: "bom trabalho" / "errou" ajusta as próximas escolhas.
- [ ] 33. "O que você aprendeu essa semana?": ele conta.
- [ ] 34. Painel da memória na tela: ver, editar e apagar o que ele sabe.
- [ ] 35. Backup da memória (pendrive ou outra pasta).

## 4. Mãos: mexer em cada pedacinho do PC
- [ ] 36. Clicar em qualquer botão de qualquer programa pelo nome (UI Automation do Windows).
- [ ] 37. Ler o que está escrito numa janela (para a IA entender o programa aberto).
- [ ] 38. Visão de reserva: print + IA acha o botão quando o Windows não informa (pede confirmação).
- [ ] 39. Modo agente: "faz X no programa Y" em vários passos, mostrando cada passo num card, com botão PARAR.
- [ ] 40. Preencher formulários e campos de qualquer programa.
- [ ] 41. Janelas: lado a lado, mandar para a 2ª tela, maximizar, layouts salvos ("modo trabalho").
- [ ] 42. Windows: Wi-Fi, Bluetooth, modo escuro, não perturbe, saída de som (fone/caixa), resolução.
- [ ] 43. Instalar e atualizar programas pelo winget (confirmação).
- [ ] 44. Desinstalar programa (confirmação).
- [ ] 45. Limpeza: temporários, lixeira, downloads velhos (confirmação + relatório do que liberou).
- [ ] 46. "O que está pesando?" e fechar o culpado (confirmação se não for programa comum).
- [ ] 47. Imprimir arquivo.
- [ ] 48. Histórico da área de transferência ("cola o que eu copiei antes").
- [ ] 49. Atalhos de qualquer app por voz: "salva", "desfaz", "nova aba".
- [ ] 50. Organizar pasta (por tipo/data), renomear em lote, compactar/descompactar.
- [ ] 51. Converter arquivos: imagem para PDF, vídeo para MP3 (ffmpeg).
- [ ] 52. Volume por programa (Discord mais alto, jogo mais baixo).

## 5. Arquivos e documentos
- [ ] 53. Buscar dentro dos arquivos (texto de PDF e Word), não só pelo nome.
- [ ] 54. Perguntas sobre um documento ("qual o prazo nesse contrato?").
- [ ] 55. Ditar um documento (Word ou txt).
- [ ] 56. Ler PDF em voz alta.
- [ ] 57. Planilha: abrir, somar uma coluna, criar uma simples.
- [ ] 58. Fotos por data ("fotos de julho").
- [ ] 59. Backup automático de uma pasta.
- [ ] 60. Aviso de disco quase cheio.

## 6. Internet e navegador
- [ ] 61. Abas: "fecha as abas do YouTube", "volta para a aba do Gmail".
- [ ] 62. Resumir ou ler em voz alta a página aberta.
- [ ] 63. Acompanhar preço de produto e avisar quando baixar.
- [ ] 64. Rastrear encomenda dos Correios.
- [ ] 65. Traduzir o texto da tela.
- [ ] 66. "Abre o último arquivo baixado."
- [ ] 67. Favoritos por voz.
- [ ] 68. Pesquisa comparando opções (preço, avaliação) num card lado a lado.

## 7. Comunicação
- [ ] 69. WhatsApp: "responde que já vou" (para a última mensagem).
- [ ] 70. Resumo das mensagens não lidas.
- [ ] 71. Transcrever e ler os áudios recebidos no WhatsApp.
- [ ] 72. Mandar áudio gravado pelo WhatsApp.
- [ ] 73. Gmail: ler, resumir, responder (API oficial, confirmação).
- [ ] 74. Google Agenda: eventos do dia, criar evento.
- [ ] 75. Contatos VIP: avisa na hora; os outros só no resumo.
- [ ] 76. Não perturbe: segura os avisos e conta depois.

## 8. Rotina e casa
- [ ] 77. Modos: jogo, estudo, trabalho, dormir (cada um mexe em várias coisas de uma vez).
- [ ] 78. Pomodoro com foco (bloqueia distração, avisa a pausa).
- [ ] 79. Lista de tarefas e de compras por voz, num card.
- [ ] 80. Lembrete de água e de postura (opcional).
- [ ] 81. Contas a pagar com vencimento.
- [ ] 82. Aviso de chuva antes de sair.
- [ ] 83. Música por humor ("algo para animar").
- [ ] 84. (Se tiver) lâmpadas e tomadas inteligentes.
- [ ] 85. Contagem regressiva para datas ("quantos dias para a prova?").
- [ ] 86. Despertador com soneca ("mais 10 minutos").

## 9. Jogos e mídia
- [ ] 87. Modo jogo: fecha o que pesa, não perturbe, prioridade para o jogo.
- [ ] 88. Abrir jogo da Steam pelo nome.
- [ ] 89. FPS e temperatura no HUD.
- [ ] 90. "Grava os últimos 30 segundos" (Xbox Game Bar).
- [ ] 91. "Onde assisto tal filme?"
- [ ] 92. Retomar a música ou o vídeo de onde parou.

## 10. Saúde e segurança do PC
- [ ] 93. Relatório de saúde: disco, RAM, temperatura, atualizações pendentes.
- [ ] 94. Aviso de programa novo que começou a abrir com o Windows.
- [ ] 95. Bloquear o PC por voz.
- [ ] 96. Senha falada para ações perigosas (apagar, desinstalar).
- [ ] 97. Desfazer a última ação de arquivo (mover, renomear).
- [ ] 98. Modo visita: esconde notificações e cards pessoais.

## 11. Tela e celular
- [ ] 99. HUD fixo: CPU, RAM, clima, hora, próxima tarefa.
- [ ] 100. Notificações do Windows viram card do Bolha.
- [ ] 101. Temas do reator (azul, vermelho e dourado do Homem de Ferro).
- [ ] 102. Celular: mandar arquivo do celular para o PC e do PC para o celular.
- [ ] 103. Celular avisa quando o PC termina algo (download, render).
- [ ] 104. Celular: botões rápidos (modos, despertador, volume).

## 12. Ele se cuidando
- [ ] 105. Autoteste ao abrir: microfone, voz, IA, WAHA, internet, num card de status.
- [ ] 106. Atualizar sozinho (git pull) com confirmação.
- [ ] 107. Relatório de erro pronto para mandar ao Claude ou ao Codex.
- [ ] 108. Modo sem internet: só os atalhos locais, e avisa o que não dá.

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
- [ ] S1. **modo-aula**: abre Teams/Meet, silencia o WhatsApp, volume em 30, abre o caderno.
- [ ] S2. **modo-estudo**: Pomodoro de 25 min, lofi baixo, bloqueia YouTube e redes.
- [ ] S3. **modo-trabalho**: abre e-mail, agenda e as pastas do dia, lado a lado.
- [ ] S4. **modo-jogo**: fecha o que pesa, não perturbe, Discord aberto, prioridade para o jogo.
- [ ] S5. **modo-dormir**: boa noite, lembretes de amanhã, despertador, apaga a tela e baixa o volume.
- [ ] S6. **modo-filme**: tela cheia, som alto, notificações desligadas, luz do HUD apagada.
- [ ] S7. **modo-visita**: esconde notificações e cards pessoais.
- [ ] S8. **cheguei-em-casa**: o "papai chegou" com resumo e o que ficou pendente.
- [ ] S9. **saindo-de-casa**: clima e chuva, o que levar, bloqueia o PC.
- [ ] S10. **pausa-agora**: 5 minutos de alongamento guiado com contagem.

### Dia a dia
- [ ] S11. **lista-de-compras**: anota por voz, organiza por seção e manda no zap na hora de sair.
- [ ] S12. **contas-do-mes**: lista as contas com vencimento e avisa 2 dias antes.
- [ ] S13. **receita-com-o-que-tem**: "tenho ovo e arroz": pesquisa receita e mostra os passos num card.
- [ ] S14. **cozinhando**: lê a receita passo a passo, espera o "próximo", com timers.
- [ ] S15. **aniversarios**: avisa o aniversário e sugere a mensagem (manda só com "sim").
- [ ] S16. **agua-e-postura**: lembretes ao longo do dia, só com o PC em uso.
- [ ] S17. **resumo-da-semana**: o que o senhor fez, ouviu e pediu na semana.
- [ ] S18. **planejar-o-dia**: monta o dia com lembretes, agenda e tarefas, e pergunta o que falta.
- [ ] S19. **tarefas**: lista de tarefas com prioridade, riscar por voz.
- [ ] S20. **contagem-regressiva**: "quantos dias para a prova/viagem?" com card.

### Estudo
- [ ] S21. **explica-simples**: explica um assunto como para uma criança e depois como prova.
- [ ] S22. **quiz**: faz perguntas sobre um assunto e corrige as respostas faladas.
- [ ] S23. **resumo-de-pdf**: resume o PDF por capítulos num card com tópicos.
- [ ] S24. **flashcards**: cria cartões de estudo de um texto e revisa por voz.
- [ ] S25. **trabalho-escolar**: pesquisa com fontes, monta o esqueleto do trabalho no Word.
- [ ] S26. **corrige-texto**: corrige o texto copiado (ortografia e clareza) e cola de volta.
- [ ] S27. **traduz-tela**: traduz o texto selecionado ou da tela.
- [ ] S28. **conta-explicada**: resolve uma conta mostrando o passo a passo.
- [ ] S29. **idioma-do-dia**: uma frase em inglês por dia, com pronúncia.
- [ ] S30. **leitura-em-voz**: lê o artigo ou PDF em voz alta, com pausa e "continua".

### Arquivos e PC
- [ ] S31. **arrumar-downloads**: separa por tipo, apaga instalador velho (pergunta antes).
- [ ] S32. **limpeza-do-pc**: temporários, lixeira, cache; diz quanto liberou.
- [ ] S33. **backup-rapido**: copia uma pasta para o pendrive/outro disco.
- [ ] S34. **renomear-fotos**: renomeia por data, em lote.
- [ ] S35. **pdf-de-imagens**: junta prints/fotos num PDF.
- [ ] S36. **comprimir-para-enviar**: compacta e diminui arquivos grandes para mandar no zap.
- [ ] S37. **achar-arquivo-perdido**: procura por nome, conteúdo e data aproximada.
- [ ] S38. **saude-do-pc**: disco, RAM, temperatura, atualizações pendentes, num card.
- [ ] S39. **por-que-ta-lento**: acha o que está pesando e sugere o que fechar.
- [ ] S40. **instalar-programa**: instala pelo winget (pergunta antes).
- [ ] S41. **atualizar-tudo**: atualiza os programas pelo winget (pergunta antes).
- [ ] S42. **wifi-com-problema**: testa a internet, reinicia o adaptador, mostra o resultado.
- [ ] S43. **fone-ou-caixa**: troca a saída de som.
- [ ] S44. **print-e-manda**: print da tela e manda para alguém (pergunta antes).
- [ ] S45. **gravar-tela**: grava a tela por X minutos e salva.

### Comunicação
- [ ] S46. **responde-zap**: responde a última mensagem pelo que o senhor ditar (pergunta antes).
- [ ] S47. **resumo-do-zap**: resume as conversas não lidas, por pessoa.
- [ ] S48. **ouvir-audios**: transcreve e lê os áudios recebidos.
- [ ] S49. **avisa-que-atrasei**: manda "vou atrasar X minutos" para quem o senhor disser.
- [ ] S50. **mensagem-bonita**: escreve parabéns/agradecimento no tom do senhor.
- [ ] S51. **email-rapido**: dita e manda e-mail (pergunta antes).
- [ ] S52. **resumo-do-email**: lê e resume os e-mails importantes.
- [ ] S53. **marcar-compromisso**: cria evento na agenda e lembra antes.
- [ ] S54. **vip**: mensagem de quem é VIP avisa na hora; o resto só no resumo.
- [ ] S55. **nao-perturbe-ate**: segura avisos até um horário e conta tudo depois.

### Internet e compras
- [ ] S56. **comparar-precos**: compara um produto em várias lojas num card.
- [ ] S57. **vigiar-preco**: avisa quando o preço cair.
- [ ] S58. **rastrear-encomenda**: acompanha o código dos Correios e avisa mudanças.
- [ ] S59. **noticias-de**: notícias de um assunto (time, jogo, cidade) num card.
- [ ] S60. **placar**: placar e próximo jogo do time do senhor.
- [ ] S61. **cotacoes**: dólar, euro, bitcoin, com variação do dia.
- [ ] S62. **onde-assistir**: em qual streaming está o filme/série.
- [ ] S63. **resumo-de-video**: resume um vídeo do YouTube pela legenda.
- [ ] S64. **pesquisa-profunda**: pesquisa em várias fontes e monta um relatório com links.

### Diversão e jogos
- [ ] S65. **playlist-do-humor**: música pelo humor ("algo para animar", "para focar").
- [ ] S66. **abrir-jogo**: abre jogo da Steam/Epic pelo nome e entra no modo jogo.
- [ ] S67. **dica-do-jogo**: pesquisa dica/guia da parte em que o senhor travou.
- [ ] S68. **clipe**: salva os últimos 30 s do jogo (Xbox Game Bar).
- [ ] S69. **piada-e-curiosidade**: uma curiosidade ou piada seca de mordomo.
- [ ] S70. **contar-historia**: conta uma história curta (para dormir ou passar o tempo).
