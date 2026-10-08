# ArmoredCreator — Architecture Definitiva

> **Status:** arquitetura em implementação, ferramenta por ferramenta  
> **Data:** 2026-10-07  
> **Base comportamental:** `armoredcreator-test`  
> **Objetivo:** executar o histórico das 3 fontes em CATCH-UP/ATACADO, isolado por fonte, e convergir ao estado permanente de LIVE nas três fontes.

---

## 1. Decisão central

Este projeto **não cria um segundo ArmoredCreator**.

O comportamento já comprovado no `armoredcreator-test` continua sendo a referência. O novo requisito é operacional:

1. drenar o histórico das três fontes;
2. executar essa drenagem em modo CATCH-UP/ATACADO;
3. manter banco, storage e checkpoint isolados por fonte;
4. usar a mesma inteligência e o mesmo pipeline comprovados;
5. quando o histórico de cada fonte for drenado, essa fonte passa para LIVE;
6. estado final: **F1 + F2 + F3 em LIVE**.

O modo ATACADO é uma **fase de catch-up**, não um produto permanente separado.

---

## 2. Fontes

| Fonte | Telegram ID | Característica |
|---|---:|---|
| F1 | `-1003788989075` | Fórum |
| F2 | `-1002698134896` | Fórum |
| F3 | `-1002039708059` | Canal/broadcast sem tópicos |

A arquitetura é **Telegram-first**. Fórum/tópicos são uma característica de uma fonte, não uma condição para o sistema funcionar.

---

# 3. ADR — acesso ao Telegram

## Decisão

**Telethon será o gateway principal de entrada Telegram para CATCH-UP e LIVE.**

O Bot API local não será usado como mecanismo principal de leitura histórica.

Quando a implementação já comprovada do destino/publicação exigir Bot API local, ele poderá permanecer nessa responsabilidade específica.

### Arquitetura

```
                    TELEGRAM
                       |
              +--------+--------+
              |                 |
          ENTRADA            DESTINO
              |                 |
          Telethon          Bot API local*
              |                 |
              v                 v
             Sync             Hub
              |
              v
         Coordinator
```

`*` somente onde houver necessidade comprovada; não criar dependência artificial.

### Motivos

Telethon já foi utilizado para validar as três fontes, incluindo a F3, que não possui fórum. A leitura histórica usa MTProto e não depende da disponibilidade de tópicos.

O domínio do sistema não deve conhecer a biblioteca diretamente. Deve conhecer uma abstração:

```
TelegramGateway
```

com uma implementação inicial:

```
TelethonTelegramGateway
```

O objetivo é impedir acoplamento da lógica de negócio à biblioteca de transporte.

---

# 4. Gateway Telegram

Responsabilidades conceituais:

```
TelegramGateway
├── descobrir fonte
├── ler histórico
├── ler histórico de tópico quando aplicável
├── observar LIVE
├── obter mensagem
├── materializar mídia
└── publicar quando essa responsabilidade estiver no gateway
```

A diferença entre fórum e canal deve ficar na camada de acesso:

```
Fonte com fórum
    -> leitura por tópicos

Fonte sem fórum
    -> leitura direta do histórico
```

A lógica de negócio permanece a mesma.

---

# 5. CATCH-UP → LIVE

Fluxo geral:

```
                  ARMOREDCREATOR
                       |
          +------------+------------+
          |            |            |
         F1           F2           F3
          |            |            |
       CATCH-UP     CATCH-UP     CATCH-UP
          |            |            |
       histórico     histórico     histórico
          |            |            |
          +------------+------------+
                       |
                 backlog drenado
                       |
                       v
              F1 + F2 + F3 LIVE
```

Cada fonte pode terminar em momento diferente:

```
F1 histórico drenado -> F1 LIVE
F2 histórico drenado -> F2 LIVE
F3 histórico drenado -> F3 LIVE
```

Não deve existir uma lacuna entre o último conteúdo histórico processável e a entrada em LIVE.

---

# 6. Execução em ATACADO

"ATACADO" significa **cada ferramenta drenar sua etapa sobre o backlog antes de liberar a próxima ferramenta**.

O CATCH-UP é uma esteira por ferramenta:

```
Discovery histórico
      |
      v
VISION — todos os candidatos da fonte
      |
      v
DOWNLOAD — todos os aprovados
      |
      v
IA — todos os materializados
      |
      v
STUDIO — todos da etapa
      |
      v
HUB — todos da etapa
      |
      v
CONFIRMAÇÃO + CLEANUP
```

O estado de cada candidato continua persistido no SQLite. "Atacado" não significa colocar toda a mídia em RAM/disco de uma vez; significa concluir a etapa lógica da ferramenta antes de avançar para a próxima.

A ordem entre fontes também é deliberada: F2 só começa depois que a etapa atual de F1 estiver concluída; a próxima ferramenta só é liberada depois que a ferramenta anterior terminou a etapa definida para a fonte atual.

Na fase atual, **somente ArmoredSync está sendo fechado**. Vision e as etapas seguintes não devem ser acopladas ao Sync nem executadas até que o Sync esteja testado e validado ponta a ponta.

---

# 7. Fluxo definitivo do candidato

```
Telegram
   |
   v
ArmoredSync
   |
   v
DISCOVERY
   |
   v
RESERVE no SQLite
   |
   v
Coordinator
   |
   v
ArmoredVision V1
   |
   +--------------------+
   |                    |
sem produto          produto exato
   |                    |
   v                    v
WAITING_VISION      persistir
                    affiliate_url
                         |
                         v
                    materializar
                         |
                         v
                      ArmoredIA
                         |
                         v
                    ArmoredStudio
                         |
                         v
                     ArmoredHub
                         |
                         v
                  Telegram destino
                         |
                         v
                     CONFIRMED
                         |
                         v
                      PUBLISHED
                         |
                         v
                       cleanup
                         |
                         v
                      próximo
```

---

# 8. Regra crítica da Vision

Não será criado um novo "Vision Triage".

A inteligência de decisão é a **ArmoredVision V1 já existente/comprovada**.

Ela decide se o candidato possui produto exato e pode avançar.

### Sem produto exato

```
WAITING_VISION
```

O vídeo **não deve ser baixado apenas para descobrir depois** que não serve.

### Produto aceito

```
affiliate_url persistida
        |
        v
materialização permitida
```

---

# 9. Descoberta histórica

A descoberta deve reproduzir a semântica já comprovada do Sync.

Estruturas válidas observadas:

- `video + link`
- `video → link`
- `video + image + link`
- `image + image + video + link`
- múltiplos links conforme a estrutura real do grupo/álbum

A sequência `link → video` não deve ser inventada como candidato histórico do Sync.

Para grupos/álbuns:

1. coletar os vídeos;
2. coletar URLs Shopee únicas;
3. sem URL: nenhum candidato;
4. uma URL: selecionar o vídeo conforme a regra comprovada;
5. múltiplas URLs: produzir as combinações válidas sem duplicação;
6. manter ordenação determinística.

Não usar heurísticas não comprovadas de thumbnail, duração, nome de arquivo ou posição arbitrária.

---

# 10. Reserva

Reserva ocorre **antes do download**.

```
candidate discovered
        |
        v
SQLite RESERVE
        |
        v
Vision
```

Reserva não significa materialização.

Isso permite:

- recuperação após reinício;
- controle do backlog;
- auditoria;
- não baixar candidatos rejeitáveis;
- manter o SQLite como fonte da verdade.

---

# 11. Isolamento por fonte

O código é compartilhado; o estado não.

Estrutura conceitual:

```
batch/
└── sources/
    ├── source_1/
    │   ├── database/armored.db
    │   ├── storage/
    │   └── reports/
    │
    ├── source_2/
    │   ├── database/armored.db
    │   ├── storage/
    │   └── reports/
    │
    └── source_3/
        ├── database/armored.db
        ├── storage/
        └── reports/
```

Não duplicar programas por fonte.

O mesmo código recebe um contexto de fonte:

```
SourceContext
├── source_id
├── source_title
├── source_mode
├── database
├── storage_root
├── checkpoint
└── destino
```

---

# 12. Regra de isolamento

F1 nunca pode:

- reservar item de F2/F3;
- alterar checkpoint de F2/F3;
- utilizar storage de F2/F3;
- considerar publicação de outra fonte como sua;
- reutilizar estado operacional de outra fonte.

O mesmo vale para F2 e F3.

Uma fonte deve ser recuperável e auditável isoladamente.

---

# 13. SQLite

SQLite continua sendo a fonte de verdade.

Não introduzir:

- RabbitMQ;
- Redis;
- Celery;
- Kafka;
- filas físicas;
- `publish_queue`;
- estado definitivo apenas em memória.

Se o processo morrer, o estado necessário para continuar deve estar persistido.

---

# 14. Storage

Cada fonte possui seu workspace.

Exemplo:

```
source_1/storage/videos/{id}/
source_2/storage/videos/{id}/
source_3/storage/videos/{id}/
```

O padrão canônico continua:

```
storage/videos/{id}/
```

dentro do workspace da fonte.

Arquivos temporários e resultados não podem misturar fontes.

---

# 15. Coordinator

O Coordinator continua sendo a composição central.

Não criar três Coordinators diferentes.

Modelo:

```
Coordinator
   |
   +-- SourceContext F1
   +-- SourceContext F2
   +-- SourceContext F3
```

A separação ocorre pelo contexto de execução, não pela duplicação do código.

---

# 16. Checkpoint

Checkpoint é obrigatório no CATCH-UP.

Regra:

> o checkpoint nunca pode ultrapassar conteúdo que ainda precisa ser resolvido.

Um candidato pendente não pode ser "pulando" pelo checkpoint somente porque o processo chegou a mensagens posteriores.

O checkpoint deve permitir retomada após:

- queda do processo;
- reinício;
- timeout;
- erro de rede;
- falha de Vision;
- falha de Studio;
- falha Telegram.

---

# 17. Falhas e recuperação

Timeout ou erro transitório não deve matar o LIVE nem transformar automaticamente um item recuperável em terminal FAILED.

Exemplo:

```
download timeout
      |
      v
estado recuperável
      |
      v
retry/recovery
```

O histórico não pode desaparecer porque um processo foi reiniciado.

---

# 18. Confirmação Telegram

Estados conceituais:

```
CONFIRMED
ABSENT
UNKNOWN
```

Regra absoluta:

```
UNKNOWN != ABSENT
UNKNOWN != CONFIRMED
```

Portanto:

```
UNKNOWN
  |
  +--> não republicar automaticamente
```

A confirmação precisa ser suficientemente forte para liberar a etapa seguinte.

---

# 19. Cleanup

Cleanup somente depois da confirmação correta:

```
Hub
  |
  v
Telegram
  |
  v
CONFIRMED
  |
  v
PUBLISHED
  |
  v
cleanup
```

Nunca apagar o único artefato antes de confirmar a publicação.

---

# 19.1. Estrutura física das ferramentas

Cada ferramenta possui seu próprio módulo. Não concentrar a implementação de várias ferramentas em um executor histórico.

```
src/
├── sync/
│   ├── __init__.py
│   ├── contracts.py
│   ├── telegram_gateway.py
│   └── service.py
├── vision/
├── stock/
├── ia/
├── studio/
├── hub/
├── core/
└── coordinator.py
```

### ArmoredSync

É responsável exclusivamente por:

- entrada Telegram;
- leitura histórica/LIVE;
- descoberta de tópicos quando a fonte é fórum;
- leitura direta quando a fonte não é fórum;
- extração e validação do link de entrada;
- formação determinística de candidatos.

Não é responsabilidade do Sync:

- consultar `productOfferV2`;
- baixar/materializar vídeo;
- executar IA;
- editar mídia;
- publicar;
- confirmar publicação;
- limpar workspace.

### Contrato de entrada Shopee

O Sync aceita exclusivamente:

`https://s.shopee.com.br/<codigo_alphanumerico>`

Rejeita no momento da coleta qualquer outro domínio, caminho, HTTP, query ou fragmento. A resolução do produto fica para ArmoredVision.

### Regra de migração

A ferramenta só é liberada para a próxima etapa quando houver:

1. implementação no módulo próprio;
2. testes automatizados;
3. validação real da ferramenta isoladamente.

Portanto, **não executar o CATCH-UP completo enquanto ArmoredSync não estiver validado**.

# 20. Resultado comprovado pelo projeto Teste

A investigação histórica já encontrou:

| Fonte | Candidatos válidos |
|---|---:|
| F1 | 312 |
| F2 | 9.484 |
| F3 | 7.791 |
| **Total** | **17.587** |

Esses números representam **candidatos descobertos**, não quantidade garantida de downloads ou publicações.

O analisador também comprovou que:

- F1 funciona via fórum;
- F2 funciona via fórum;
- F3 funciona diretamente, sem tópicos;
- nenhuma mídia precisou ser baixada para a investigação;
- a lógica de descoberta consegue reconhecer as estruturas reais encontradas.

---

# 21. O que o projeto Teste representa

O projeto `Teste` é uma ferramenta de investigação/validação histórica.

Ele não deve substituir o ArmoredCreator.

Sua função foi provar:

```
Telegram
   |
   v
histórico
   |
   v
candidatos reais
```

sem materializar mídia nem alterar o banco operacional de produção.

As descobertas dele serão incorporadas ao sistema real.

---

# 22. O que não fazer

### Não criar outro produto

Não manter permanentemente:

```
BatchCreator + LiveCreator
```

Batch é uma fase.

### Não criar Vision Triage

A Vision V1 continua sendo a inteligência.

### Não baixar tudo antecipadamente

Discovery e materialização são etapas diferentes.

### Não assumir fórum

Telegram pode ser fórum, grupo ou canal.

### Não duplicar código

F1/F2/F3 usam a mesma implementação parametrizada.

### Não misturar estado

Banco, storage e checkpoints são isolados.

### Não criar filas físicas

SQLite + Coordinator continuam suficientes.

### Não inventar comportamento

O comportamento comprovado é a referência.

---

# 23. Fases de implementação

## Fase 1 — congelamento comportamental

Documentar e preservar o comportamento comprovado do `armoredcreator-test`.

## Fase 2 — TelegramGateway

Criar a abstração e a implementação Telethon.

## Fase 3 — SourceContext

Parametrizar banco, storage, checkpoint e destino por fonte.

## Fase 4 — CATCH-UP Sync

Integrar a descoberta histórica comprovada.

## Fase 5 — Reserva

Persistir o candidato antes da materialização.

## Fase 6 — Vision V1

Executar a inteligência real.

## Fase 7 — Materialização

Baixar somente candidatos aceitos.

## Fase 8 — Pipeline

Executar:

```
IA → Studio → Hub → Telegram → confirmação → cleanup
```

## Fase 9 — Recovery

Testar reinício, timeout, UNKNOWN e falhas intermediárias.

## Fase 10 — Drenagem

Processar o backlog das três fontes.

## Fase 11 — Transição

Cada fonte migra de CATCH-UP para LIVE sem lacuna.

## Fase 12 — Operação final

Comprovar:

```
F1 LIVE
F2 LIVE
F3 LIVE
```

---

# 24. Critérios de aceitação

## Telegram

- [ ] Telethon é o gateway principal de entrada.
- [ ] Histórico de F1 é percorrido.
- [ ] Histórico de F2 é percorrido.
- [ ] Histórico de F3 é percorrido.
- [ ] Fórum não é requisito universal.
- [ ] LIVE funciona para as três fontes.

## Discovery

- [ ] Estruturas reais são reconhecidas.
- [ ] Nenhum candidato é inventado.
- [ ] `link → video` não vira candidato artificialmente.
- [ ] Álbuns seguem a semântica comprovada.

## Isolamento

- [ ] DB F1 separado.
- [ ] DB F2 separado.
- [ ] DB F3 separado.
- [ ] Storage F1 separado.
- [ ] Storage F2 separado.
- [ ] Storage F3 separado.
- [ ] Checkpoints independentes.

## Vision

- [ ] V1 é usada.
- [ ] Não existe triagem paralela inventada.
- [ ] Rejeitados não são baixados.
- [ ] `affiliate_url` é persistida antes da materialização.

## Pipeline

- [ ] Um item físico ativo por vez.
- [ ] Download somente após aceite.
- [ ] IA executada.
- [ ] Studio executado.
- [ ] Hub executado.
- [ ] Telegram confirmado.
- [ ] UNKNOWN não republica.
- [ ] Cleanup somente após confirmação.

## Recovery

- [ ] Reinício recupera estado.
- [ ] Timeout não destrói o pipeline.
- [ ] Checkpoint não pula candidato não resolvido.
- [ ] Falha transitória permanece recuperável.

## Convergência

- [ ] F1 histórico drenado.
- [ ] F1 LIVE.
- [ ] F2 histórico drenado.
- [ ] F2 LIVE.
- [ ] F3 histórico drenado.
- [ ] F3 LIVE.
- [ ] F1/F2/F3 monitoram novos conteúdos simultaneamente.

---

# 25. Estado final

```
                    ARMORED CREATOR
                           |
             +-------------+-------------+
             |             |             |
            F1            F2            F3
             |             |             |
          CATCH-UP      CATCH-UP      CATCH-UP
             |             |             |
          histórico      histórico      histórico
             |             |             |
             +-------------+-------------+
                           |
                    backlog drenado
                           |
                           v
                 +-------------------+
                 |     SOMENTE LIVE  |
                 |                   |
                 | F1 → LIVE         |
                 | F2 → LIVE         |
                 | F3 → LIVE         |
                 +-------------------+
```

---

# 26. Princípio definitivo

> **Não estamos criando outro ArmoredCreator. Estamos colocando o ArmoredCreator já comprovado para executar primeiro o backlog histórico das três fontes em CATCH-UP/ATACADO, com estado isolado por fonte, usando a mesma inteligência e o mesmo pipeline comprovados, e depois convergir naturalmente para o único estado permanente desejado: LIVE nas três fontes.**

Este documento é a referência arquitetural para a implementação. Qualquer mudança que altere esse comportamento deve ser tratada como uma decisão arquitetural explícita, e não introduzida silenciosamente durante a implementação.
