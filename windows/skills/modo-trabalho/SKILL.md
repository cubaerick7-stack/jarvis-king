---
nome: modo-trabalho
descricao: abre e-mail, agenda e as pastas do dia, lado a lado
gatilhos: hora de trabalhar; vou trabalhar
ia: sim
plano: S3
---
Liga o modo trabalho (layout "trabalho", que abre o que faltar). Depois:
1. gmail_list para os e-mails novos e calendar_events (hoje) para a agenda, se o Google estiver conectado.
2. Se ainda não existir o layout, explique: arrume as janelas e diga "salva esse layout como trabalho".

```acoes
[
 {
  "name": "enter_mode",
  "args": {
   "name": "trabalho"
  }
 }
]
```
