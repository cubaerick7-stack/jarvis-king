---
nome: modo-aula
descricao: abre Teams/Meet, silencia o WhatsApp, volume em 30 e abre o caderno
gatilhos: vou ter aula; hora da aula
plano: S1
---
Liga o modo aula (volume 30, Teams, não perturbe: o WhatsApp fica em silêncio) e abre o caderno (OneNote).
Se o senhor disser que a aula é pelo Meet, abra o Google Meet com open_url meet.google.com.
No fim da aula, "sai do modo" desfaz tudo.

```acoes
[
 {
  "name": "enter_mode",
  "args": {
   "name": "aula"
  }
 },
 {
  "name": "open_target",
  "args": {
   "target": "onenote"
  }
 }
]
```
