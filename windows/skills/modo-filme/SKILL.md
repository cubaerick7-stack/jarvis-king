---
nome: modo-filme
descricao: tela cheia, som alto, notificações desligadas, luz do HUD apagada
gatilhos: hora do filme; vamos ver um filme
plano: S6
---
Liga o modo filme (volume 80, não perturbe, HUD apagado). Se houver vídeo do YouTube aberto, use youtube_control com "tela cheia".

```acoes
[
 {
  "name": "enter_mode",
  "args": {
   "name": "filme"
  }
 }
]
```
