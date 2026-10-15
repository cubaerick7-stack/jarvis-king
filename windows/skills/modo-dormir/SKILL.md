---
nome: modo-dormir
descricao: boa noite, lembretes de amanhã, despertador, apaga a tela e baixa o volume
ia: sim
plano: S5
---
Liga o modo dormir: boa noite com o resumo do dia e os lembretes de amanhã, volume 10, não perturbe e apaga a tela.
Se não houver despertador marcado, pergunte a hora e use set_alarm.

```acoes
[
 {
  "name": "enter_mode",
  "args": {
   "name": "dormir"
  }
 }
]
```
