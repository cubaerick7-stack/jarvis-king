---
nome: saindo-de-casa
descricao: clima e chuva, o que levar, bloqueia o PC
gatilhos: vou sair; to saindo; saindo de casa
ia: sim
plano: S9
---
1. rain_warning: se for chover, lembre o guarda-chuva.
2. Mostre a lista de compras, se houver.
3. Diga os lembretes de hoje que ainda faltam.
4. Pergunte se pode bloquear o PC (power_action bloquear).

```acoes
[
 {
  "name": "rain_warning",
  "args": {}
 },
 {
  "name": "list_show",
  "args": {
   "list": "compras"
  }
 }
]
```
