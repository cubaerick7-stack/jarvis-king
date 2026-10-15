---
nome: arrumar-downloads
descricao: separa por tipo, apaga instalador velho (pergunta antes)
gatilhos: arruma os downloads
ia: sim
plano: S31
---
Organiza a pasta Downloads em subpastas por tipo (pergunta antes; dá para desfazer). Depois ofereça clean_old_downloads para mandar o que tem mais de 90 dias para a Lixeira.

```acoes
[
 {
  "name": "organize_folder",
  "args": {
   "folder": "downloads",
   "by": "tipo"
  }
 }
]
```
