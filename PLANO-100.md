# Bolha 3.0: plano dos 100+ recursos

Plano montado com o João em 14/10/2026 para a "mega atualização". Quem pegar um item (Claude ou Codex)
marca `[x]` aqui no mesmo commit. As regras de sempre continuam: grátis, leve no i3 de 8 GB, tudo em
português, e **sempre pergunta antes de apagar, mandar, publicar, instalar ou gastar dinheiro**.

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
