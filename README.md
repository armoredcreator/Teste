# ArmoredCreator — Teste

> **Projeto definitivo em construção.**
>
> O repositório `armoredcreator-test` permanece **congelado e intocável**. Ele é referência de comportamento comprovado, não dependência de runtime.

## 1. Estado atual

A migração é feita **ferramenta por ferramenta**, cada uma no seu próprio módulo:

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

**ArmoredSync é a etapa atualmente fechada estruturalmente. ArmoredVision ainda não foi iniciada como etapa de integração.**

### Status objetivo

| Etapa | Status |
|---|---|
| ArmoredSync — módulo próprio | 🟢 concluído |
| ArmoredSync — testes | 🟢 33 testes da suíte atual passam |
| ArmoredSync — inventário histórico real | 🟢 reconstruído |
| Auditoria final dos URLs nos SQLite | 🟡 próxima verificação |
| Banco operacional definitivo por ferramenta/fonte | 🔴 pendente |
| ArmoredVision | 🔴 pendente |
| ArmoredStock | 🔴 pendente |
| ArmoredIA | 🔴 pendente |
| ArmoredStudio | 🔴 pendente |
| ArmoredHub | 🔴 pendente |
| CATCH-UP ponta a ponta | 🔴 pendente |
| LIVE | 🔴 pendente |

## 2. ArmoredSync

Código:

```text
src/sync/
├── __init__.py
├── contracts.py
├── telegram_gateway.py
└── service.py
```

Responsabilidades exclusivas:

- entrada Telegram;
- leitura histórica e futura LIVE;
- descoberta de tópicos quando a fonte for fórum;
- leitura direta quando a fonte não for fórum;
- extração e validação do link de entrada;
- formação determinística de candidatos.

O Sync **não**:

- consulta `productOfferV2`;
- baixa vídeo;
- executa IA;
- edita mídia;
- publica;
- confirma publicação;
- faz cleanup.

### Contrato de entrada Shopee

O Sync aceita somente:

```text
https://s.shopee.com.br/<codigo_alphanumerico>
```

Rejeita outros domínios, caminhos, HTTP, query e fragmentos.

A validação exata do produto fica para o ArmoredVision.

## 3. Inventário histórico reconstruído

Os bancos anteriores foram apagados porque haviam sido coletados antes do contrato definitivo de URL do ArmoredSync.

A coleta foi executada novamente do zero pelo Sync corrigido, em 2026-10-08:

| Fonte | Candidatos vistos | Candidatos únicos gravados |
|---|---:|---:|
| `-1003788989075` | 313 | **311** |
| `-1002698134896` | 9.521 | **8.198** |
| `-1002039708059` | 7.798 | **7.662** |
| **TOTAL** | **17.632** | **16.171** |

A coleta foi somente leitura:

- nenhum vídeo foi baixado;
- nenhuma mensagem Telegram foi modificada;
- cada fonte possui seu próprio `historical.db`.

Estrutura atual:

```text
batch/
└── sources/
    ├── -1003788989075/
    │   └── database/historical.db
    ├── -1002698134896/
    │   └── database/historical.db
    └── -1002039708059/
        └── database/historical.db
```

**Importante:** 16.171 é o inventário reconstruído. Antes de congelá-lo como entrada definitiva do pipeline, os três SQLite devem passar pela auditoria automática do contrato de URL.

## 4. Fontes

| Fonte | Telegram ID | Tipo |
|---|---:|---|
| F1 | `-1003788989075` | fórum |
| F2 | `-1002698134896` | fórum |
| F3 | `-1002039708059` | canal/broadcast |

A arquitetura é Telegram-first. Fórum não é requisito universal.

## 5. Descoberta histórica

Padrões comprovados:

- `video + link`;
- `video → link`;
- `video + image + link`;
- `image + image + video + link`;
- múltiplos links conforme a estrutura real do grupo/álbum.

`link → video` não é convertido artificialmente em candidato.

A deduplicação histórica é por:

```text
source_id + original_url
```

## 6. Separação por ferramenta e por fonte

O código é compartilhado; o estado é isolado.

```text
src/
├── sync/
├── vision/
├── stock/
├── ia/
├── studio/
├── hub/
└── core/
```

A execução futura deverá usar:

```text
Fonte 1 → etapa atual
Fonte 2 → etapa atual
Fonte 3 → etapa atual
          ↓
próxima ferramenta
```

"ATACADO" significa drenar a etapa lógica da ferramenta sobre o backlog, **não** baixar toda a mídia de uma vez nem criar fila física.

## 7. Princípios que não mudam

- Coordinator é a composição raiz.
- SQLite é a fonte de verdade.
- Não usar RabbitMQ, Redis, Celery ou Kafka.
- Não criar `publish_queue` ou outra fila física.
- Não fazer pré-download em lote.
- Manter fontes isoladas.
- Vision ocorre antes da materialização.
- `UNKNOWN` nunca equivale automaticamente a `ABSENT`.
- Timeout recuperável não deve avançar checkpoint indevidamente.
- Recovery só pode usar artefatos realmente existentes e imutáveis.
- CATCH-UP converge para LIVE; CATCH-UP não é um produto separado.

## 8. ArmoredVision — próxima etapa

O Vision V1 existente ainda precisa ser **migrado, testado e validado como ferramenta independente** depois do fechamento definitivo do inventário.

Regras já definidas para essa etapa:

```text
original_url
    ↓
resolver Shopee
    ↓
shop_id + item_id
    ↓
productOfferV2
    ├── não encontrado → WAITING_VISION
    └── encontrado → affiliate_url + ia_context
```

Não usar `generateShortLink` como prova de elegibilidade.

Não criar Vision Triage por thumbnail, duração ou heurística visual.

Vision V2 não entra nesta etapa.

## 9. Ordem de implementação

1. 🟢 ArmoredSync
2. 🟡 auditoria/freeze do inventário
3. 🔴 banco operacional definitivo por fonte
4. 🔴 ArmoredVision
5. 🔴 ArmoredStock
6. 🔴 ArmoredIA
7. 🔴 ArmoredStudio
8. 🔴 ArmoredHub
9. 🔴 confirmação + cleanup
10. 🔴 CATCH-UP real ponta a ponta
11. 🔴 LIVE

Cada ferramenta só é liberada quando tiver:

1. módulo próprio;
2. testes automatizados;
3. validação real isolada;
4. documentação atualizada.

## 10. Testes

A validação estrutural atual do repositório foi executada com:

```powershell
python -m pytest -q -W error::RuntimeWarning
```

Resultado atual informado para esta etapa:

```text
33 passed
```

Além disso, o teste específico do ArmoredSync passou com:

```text
5 passed
```

Esses testes comprovam a estrutura do módulo, **não** substituem a validação real do Telegram. A reconstrução histórica real foi executada separadamente e produziu os 16.171 candidatos acima.

## 11. Referência congelada

`armoredcreator-test`:

- não deve ser modificado;
- não deve ser dependência do runtime final;
- serve apenas para comparar comportamento comprovado.

O objetivo do `Teste` é incorporar esse comportamento nativamente.

## 12. Regra de documentação

Ao terminar cada etapa:

```text
implementar
   ↓
testar
   ↓
validar
   ↓
documentar
   ↓
congelar
   ↓
próxima ferramenta
```

Não considerar uma etapa concluída apenas porque existe um commit.
