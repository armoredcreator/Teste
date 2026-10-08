# ArmoredCreator — Arquitetura Definitiva

> **Status:** ArmoredSync fechado estruturalmente; inventário histórico reconstruído; Vision é a próxima ferramenta.  
> **Data da atualização:** 2026-10-08  
> **Base comportamental:** `armoredcreator-test` (congelado)

## 1. Decisão central

O projeto definitivo não cria um segundo ArmoredCreator. O comportamento comprovado do repositório congelado é incorporado nativamente no `Teste`, ferramenta por ferramenta.

A ordem definitiva é:

```text
ArmoredSync
    ↓
ArmoredVision
    ↓
ArmoredStock
    ↓
ArmoredIA
    ↓
ArmoredStudio
    ↓
ArmoredHub
    ↓
confirmação + cleanup
    ↓
CATCH-UP concluído
    ↓
LIVE
```

Cada ferramenta possui seu próprio módulo. Não criar um executor histórico que concentre Sync, Vision, download, IA, Studio e Hub.

## 2. Fontes

| Fonte | ID | Tipo |
|---|---:|---|
| F1 | `-1003788989075` | fórum |
| F2 | `-1002698134896` | fórum |
| F3 | `-1002039708059` | canal/broadcast |

O código é compartilhado; estado, banco, storage e checkpoint são isolados por fonte.

## 3. ArmoredSync — fechado

Estrutura:

```text
src/sync/
├── __init__.py
├── contracts.py
├── telegram_gateway.py
└── service.py
```

Responsabilidades:

- entrada Telegram;
- leitura histórica;
- futura leitura LIVE;
- descoberta de tópicos quando aplicável;
- leitura direta para fontes sem fórum;
- extração/validação de links;
- formação determinística de candidatos.

Não é responsabilidade do Sync:

- productOfferV2;
- download;
- IA;
- Studio;
- publicação;
- confirmação;
- cleanup.

### Contrato Shopee

Entrada aceita exclusivamente:

```text
https://s.shopee.com.br/<codigo_alphanumerico>
```

São rejeitados outros domínios, caminhos, HTTP, query e fragmentos.

A validação do produto é responsabilidade do Vision.

## 4. Inventário histórico real

Os bancos anteriores foram removidos e reconstruídos porque haviam sido coletados antes da correção definitiva do contrato de URL do Sync.

Reconstrução real realizada em 2026-10-08:

| Fonte | Vistos | Únicos gravados |
|---|---:|---:|
| F1 | 313 | **311** |
| F2 | 9.521 | **8.198** |
| F3 | 7.798 | **7.662** |
| **Total** | **17.632** | **16.171** |

Nenhuma mídia foi baixada e nenhuma mensagem Telegram foi modificada.

Os bancos ficam em:

```text
batch/sources/<source_id>/database/historical.db
```

O inventário de 16.171 ainda precisa da auditoria automática final dos URLs antes de ser marcado como **FREEZE definitivo**.

## 5. Descoberta histórica

Padrões comprovados:

- `video + link`;
- `video → link`;
- `video + image + link`;
- `image + image + video + link`;
- múltiplos links conforme a estrutura real.

`link → video` não é candidato artificial.

Deduplicação:

```text
source_id + original_url
```

## 6. ATACADO

ATACADO é uma propriedade da **etapa da ferramenta**, não uma fila física.

Modelo:

```text
ArmoredSync
   ↓
drena a etapa lógica do backlog
   ↓
ArmoredVision
   ↓
drena a etapa lógica do backlog
   ↓
ArmoredStock
   ↓
...
```

Não significa:

- carregar todos os vídeos na memória;
- fazer pré-download de tudo;
- criar `publish_queue`;
- introduzir RabbitMQ/Redis/Celery/Kafka.

As fontes permanecem individualizadas.

## 7. Isolamento por fonte

Conceitualmente:

```text
batch/
└── sources/
    ├── -1003788989075/
    │   ├── database/
    │   ├── storage/
    │   └── reports/
    ├── -1002698134896/
    │   ├── database/
    │   ├── storage/
    │   └── reports/
    └── -1002039708059/
        ├── database/
        ├── storage/
        └── reports/
```

Uma fonte nunca deve:

- reservar item de outra;
- alterar checkpoint de outra;
- usar storage de outra;
- considerar publicação de outra como sua.

## 8. Telegram

Telethon é o gateway principal de entrada para CATCH-UP e LIVE.

A camada de domínio conhece a abstração:

```text
TelegramGateway
      ↓
TelethonTelegramGateway
```

Fórum e canal não devem gerar duas lógicas de negócio. A diferença fica no gateway:

```text
fórum → leitura por tópicos
canal → leitura direta
```

Bot API local só permanece onde uma responsabilidade de destino/publicação já comprovada exigir isso.

## 9. Próxima etapa — banco operacional

Antes do Vision de integração, deve ser definido o banco operacional definitivo por fonte e por etapa.

Objetivos:

- SQLite como fonte de verdade;
- reserva antes da materialização;
- estado persistido;
- checkpoint independente;
- recuperação após reinício;
- nenhuma fila física.

O `historical.db` reconstruído é o inventário de entrada; ele não deve ser confundido automaticamente com o banco operacional final.

## 10. ArmoredVision

O próximo módulo deve ser independente do Sync.

Fluxo:

```text
original_url
    ↓
resolver Shopee
    ↓
shop_id + item_id
    ↓
productOfferV2
    ├── produto não encontrado
    │       ↓
    │   WAITING_VISION
    │       ↓
    │   não materializar
    │
    └── produto exato
            ↓
       affiliate_url
            ↓
        ia_context
```

Regras:

- V1 é a autoridade;
- `generateShortLink` não prova elegibilidade;
- não criar Vision Triage;
- não baixar para descobrir depois se o produto existe;
- Vision V2 fica fora desta etapa.

## 11. Fluxo posterior

Depois do Vision:

```text
Vision
  ↓
ArmoredStock
  ↓
ArmoredIA
  ↓
ArmoredStudio
  ↓
ArmoredHub
  ↓
confirmação Telegram
  ↓
CONFIRMED / ABSENT / UNKNOWN
  ↓
cleanup somente quando seguro
```

`UNKNOWN` nunca deve ser tratado automaticamente como `ABSENT` e nunca deve disparar republicação automática.

## 12. Coordinator

Existe um único Coordinator como composição raiz:

```text
Coordinator
 ├── SourceContext F1
 ├── SourceContext F2
 └── SourceContext F3
```

O Coordinator conecta as ferramentas; ele não deve absorver a implementação delas.

## 13. Checkpoint e recuperação

O checkpoint não pode ultrapassar conteúdo ainda não resolvido.

Falhas recuperáveis não podem:

- avançar checkpoint indevidamente;
- marcar terminalmente um item que ainda pode ser retomado;
- causar perda de candidato.

Recovery utiliza somente artefatos realmente existentes e imutáveis.

## 14. Princípios permanentes

- SQLite é a fonte de verdade.
- Coordinator é a composição raiz.
- exatamente um item físico ativo na execução normal de materialização/processamento.
- CATCH-UP → LIVE.
- nenhuma fila física.
- nenhum pré-download em lote.
- nenhuma dependência definitiva de `armoredcreator-test`.
- fontes isoladas.
- Vision antes de materialização.
- `UNKNOWN` não é `ABSENT`.
- timeout recuperável não encerra artificialmente o fluxo.

## 15. Critério de liberação de ferramenta

Uma ferramenta só libera a próxima quando tiver:

1. módulo próprio;
2. contrato definido;
3. testes automatizados;
4. execução isolada real;
5. documentação atualizada.

Portanto:

```text
ArmoredSync → 🟢
Inventário/freeze → 🟡
Banco operacional → 🔴
ArmoredVision → 🔴
ArmoredStock → 🔴
ArmoredIA → 🔴
ArmoredStudio → 🔴
ArmoredHub → 🔴
CATCH-UP E2E → 🔴
LIVE → 🔴
```

## 16. Referência congelada

`armoredcreator-test` responde à pergunta:

> Como o comportamento comprovado funcionava?

`Teste` deve responder:

> Como o ArmoredCreator definitivo funciona?

A referência congelada não será modificada nem usada como runtime definitivo.
