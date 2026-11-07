# zap-envios

<!-- resumo: Envio de WhatsApp em lote por planilha, grátis e de código aberto (MIT): planilha CSV, template com variáveis e variação de texto, agendamento com ritmo humano (janela horária, aquecimento, teto por dia), até 10 números por conta e opt-out. Hoje só o núcleo puro está pronto. -->

**Avise a sua própria base por WhatsApp sem queimar o seu número.** Suba uma planilha, escreva a mensagem, escolha o horário.
O `zap-envios` decide *quem recebe o quê, de qual número e quando*, com o ritmo de uma pessoa e não de um robô.

> *Open source (MIT). Python 3.12, só biblioteca padrão, zero dependências.*
> *English: a free, MIT-licensed core for bulk WhatsApp notices to your own contacts, built around the thing that actually gets numbers banned: pace, repetition and no way to opt out.*

## Por que existe

Todo mundo que já mandou aviso em massa por WhatsApp sabe o fim da história: o número é banido. O banimento quase nunca é azar, é padrão:
centenas de mensagens idênticas, sem pausa, de uma conta recém-criada, para gente que não pode pedir para sair. Este projeto trata esses quatro
pontos como regras do software, não como conselho.

## O que o núcleo faz

| | |
|---|---|
| **Número** | Só Brasil. DDD + celular; celular antigo de 8 dígitos ganha o nono; telefone fixo e DDD inexistente são recusados **com o motivo**. |
| **Planilha** | CSV do Excel (BOM, `;` ou `,`). A coluna do número pode se chamar `numero`, `telefone`, `celular`, `whatsapp`. Até 500 linhas. Duplicado conta uma vez; linha inválida volta com o número da linha. |
| **Template** | `{nome}` vem da coluna. Se a coluna falta, **a linha é recusada**: nunca sai um `{nome}` literal. `{Oi\|Olá\|E aí}` escolhe uma opção, sempre a mesma para o mesmo número, e o lote deixa de ser 500 mensagens idênticas. |
| **Saída** | Toda mensagem termina com "Responda SAIR para não receber mais mensagens." Quem pediu SAIR nunca entra em um plano. |
| **Ritmo** | Só das 9h às 18h (Brasília). Pausa aleatória de 20 a 60 s. **Número novo começa em 20 por dia e dobra**: 20, 40, 80, 160, 300. Teto de 300 por dia por número. O que passa vai para o dia seguinte. |
| **Vários números** | Até **10 números por conta**. O lote é repartido pela capacidade de cada um: o veterano recebe a fatia grande, o novo a pequena, e cada contato recebe de um número só. |
| **Determinístico** | Mesma planilha, mesmo template, mesmo plano. Dá para revisar o plano inteiro (hora, número e texto de cada mensagem) **antes** de enviar uma. |

## Exemplo

```python
import datetime as dt
from zoneinfo import ZoneInfo
import nucleo as n

lote = n.ler_csv("nome;celular\nAna;(11) 91234-5678\nBia;11 98888-7777\nCarlos;1133334444\n")
print(lote["invalidos"])   # [{'linha': 4, 'valor': '1133334444', 'motivo': 'telefone fixo não tem WhatsApp'}]

inicio = dt.datetime(2026, 11, 9, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
numeros = [{"id": "loja", "idade_dias": 10}, {"id": "novo", "idade_dias": 0}]
plano = n.planejar_multi(lote["contatos"], "{Oi|Olá} {nome}, seu pedido saiu!", inicio, numeros)

for a in plano["agenda"]:
    print(a["quando"], a["remetente"], a["numero"], repr(a["texto"]))
```

Testes: `python3 -m pytest -q tests` (29 testes; cada um leva o nome do defeito que impede, e o conjunto foi conferido por mutação: quebrar a
janela, o aquecimento, o opt-out ou a repartição faz algum teste falhar).

## Limites que a gente declara

- **WhatsApp não oficial.** O envio real (próximas fatias) passa por uma API não oficial (Evolution/Baileys). Mandar em massa para quem não tem o
  remetente salvo pode banir o número; o aquecimento, o teto e a saída reduzem o risco, **não o eliminam**. Para empresa falando com cliente
  em escala, o caminho certo é a API oficial da Meta.
- **É para avisar a própria base** (cobrança, lembrete, novidade para quem já é seu contato), não para disparo frio. Por isso o teto de 500
  linhas por planilha e de 10 números por conta. Spam é crime e quebra a LGPD; este projeto não ajuda com isso.
- "Enviado" será sempre "o WhatsApp aceitou", nunca "chegou".

## Roteiro

1. **Núcleo** (aqui): número, planilha, template, ritmo, vários números. ✅
2. **Conta**: login por e-mail com código de 6 dígitos, limites por e-mail e por IP, SQLite.
3. **Envio**: conexão por QR code ou código de pareamento (até 10 números), fila e worker; todo envio começa em modo `simular`.
4. **Tela**: planilha, template, prévia por linha e agendamento.

## Contribuir

Issues e PRs são bem-vindos. Regra da casa: toda mudança traz um teste que falha sem ela, com nome que descreve a falha. Em português ou
inglês, o que fizer a ideia chegar.

## Licença

MIT. © 2026 Genesis Innovation.
