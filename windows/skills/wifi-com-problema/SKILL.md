---
nome: wifi-com-problema
descricao: testa a internet, reinicia o adaptador, mostra o resultado
gatilhos: a internet caiu; o wifi ta ruim
ia: sim
plano: S42
---
1. network_info. 2. Se estiver SEM internet: radio wifi off e depois radio wifi on (reinicia o adaptador), espere e network_info de novo. 3. Se continuar sem: sugira reiniciar o roteador.

```acoes
[
 {
  "name": "network_info",
  "args": {}
 }
]
```
