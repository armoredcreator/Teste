# ArmoredCreator — Teste

> **Projeto definitivo em construção.**
>
> Este repositório está evoluindo de um analisador histórico para a futura base
> definitiva do **ArmoredCreator**. O repositório
> `armoredcreator-test` permanece **congelado e intocável**: ele é uma
> referência de comportamento já comprovado, não uma dependência de runtime.

---

## 1. Princípio arquitetural

A regra central desta migração é:

```text
armoredcreator-test (referência congelada)
              │
              │ comportamento comprovado
              ▼
          Teste (código nativo)
              │
              ├── CATCH-UP
              └── LIVE
```

O resultado final **não** deverá exigir:

- `ARMORED_BASE_ROOT`;
- imports de `armoredcreator-test`;
- copiar o repositório antigo para dentro do novo;
- executar dois projetos acoplados.

Cada camada comprovada será trazida para este repositório, adaptada ao domínio
do `Teste`, testada e certificada antes de a próxima camada ser migrada.

O repositório congelado não será modificado.

---

# 2. Estado atual do projeto

## Histórico já certificado

O inventário histórico das três fontes foi concluído e auditado:

| Fonte | Candidatos únicos |
|---|---:|
| `-1003788989075` | 311 |
| `-1002698134896` | 8.194 |
| `-1002039708059` | 7.655 |
| **TOTAL** | **16.160** |

Auditorias já concluídas:

- descoberta histórica;
- deduplicação por `source_id + original_url`;
- rastreabilidade;
- composição de followups;
- reparo seguro das composições históricas;
- isolamento por fonte;
- recuperação de execução do coletor.

O número de **17.587** corresponde ao total de eventos candidatos observado
no scanner histórico; o SQLite persistiu **16.160 candidatos únicos**.

---

# 3. Fontes Telegram

As fontes são configuradas em:

```text
credentials/project.env
```

Atualmente:

```text
SOURCE_1=-1003788989075
SOURCE_2=-1002698134896
SOURCE_3=-1002039708059
```

O gateway Telegram diferencia:

- **forum** — histórico organizado por tópicos;
- **source** — canal/grupo sem tópicos.

A descoberta usa a mesma semântica histórica do Sync comprovado.

---

# 4. Regras de descoberta histórica

Os padrões suportados incluem:

1. `video + link`;
2. `video → link`;
3. `video + image + link`;
4. `image + image + video + link`.

`link + video` pode ser observado no histórico, mas não é emitido como
candidato válido pelo comportamento de Sync.

Para grupos/álbuns, a resolução utiliza:

- `grouped_id`;
- vídeos realmente presentes;
- URLs Shopee únicas;
- vínculo entre vídeo e mensagem de link.

Não existe uma regra física inventada de ordenação para substituir a semântica
comprovada.

---

# 5. Vision V1 — ETAPA 1 CONCLUÍDA

## Status

**CONCLUÍDA: migração nativa do Vision V1.**

O Vision não é mais importado do `armoredcreator-test`.

Código nativo:

```text
src/vision/
├── __init__.py
├── contracts.py
├── service.py
└── modules/
    └── v1/
        ├── __init__.py
        ├── shopee_api.py
        └── shopee_resolver.py
```

A implementação preserva o comportamento V1 comprovado:

```text
URL Shopee original
       │
       ▼
resolver
       │
       ├── shop_id
       └── item_id
       │
       ▼
productOfferV2
       │
       ├── produto não encontrado
       │       ↓
       │   VisionUnresolvedError
       │       ↓
       │   WAITING_VISION
       │
       └── produto encontrado
               │
               ▼
          affiliate URL
               │
               ▼
            ia_context
```

### Regras preservadas

- resolução direta de URLs Shopee;
- resolução de URLs curtas por redirect;
- identificação exata por `shop_id + item_id`;
- consulta `productOfferV2`;
- rejeição de produto divergente;
- uso de `offerLink` quando disponível;
- geração de short link quando necessário;
- construção de `ia_context`;
- `VisionUnresolvedError` quando o produto não pode ser confirmado.

### O que foi deliberadamente NÃO migrado

Vision V2 não entra nesta etapa.

Também não foi criado nenhum Vision Triage por:

- thumbnail;
- duração;
- metadados;
- heurística visual.

O V1 continua sendo a autoridade para validação exata do produto.

---

# 6. Credenciais Shopee

O `project.env` é a fonte local única de configuração.

Variáveis necessárias:

```env
SHOPEE_APP_ID=...
SHOPEE_SECRET_KEY=...
SHOPEE_AFFILIATE_API_URL=https://open-api.affiliate.shopee.com.br/graphql
SHOPEE_API_TIMEOUT=30
SHOPEE_API_MAX_RETRIES=3
SHOPEE_API_RETRY_BASE_SECONDS=2
```

Segredos reais nunca devem entrar no Git.

O arquivo de referência é:

```text
credentials/project.env.example
```

---

# 7. CATCH-UP: regra operacional

O executor histórico não cria uma fila física.

O modelo é:

```text
SQLite histórico
      │
      ▼
1 candidato
      │
      ▼
RESERVED
      │
      ▼
Vision V1
      │
      ├── WAITING_VISION
      │       └── não baixa vídeo
      │
      └── aprovado
              │
              ▼
          DOWNLOAD
              │
              ▼
           ORIGINAL
              │
              ▼
       PROCESSAMENTO
              │
              ▼
          PUBLICAÇÃO
              │
              ▼
         CONFIRMAÇÃO
              │
              ▼
           CLEANUP
              │
              ▼
          próximo
```

Princípios:

- exatamente um item físico ativo;
- reserva no SQLite antes da mídia;
- Vision antes da materialização;
- nenhum pré-download em lote;
- falha técnica de Vision antes do ORIGINAL não avança o candidato;
- timeout/falha de download antes do ORIGINAL não avança o candidato;
- `WAITING_VISION` não deve bloquear candidatos posteriores;
- `RECOVERY` continua sendo estado retomável;
- publicação com resultado desconhecido nunca deve ser tratada como ausência
  confirmada.

---

# 8. Migração do runtime

A migração completa seguirá esta ordem:

### Etapa 1 — Vision V1
**CONCLUÍDA**

- ArmoredVision;
- Shopee resolver;
- Shopee Affiliate API;
- contratos Vision;
- integração do executor com Vision nativo;
- testes unitários.

### Etapa 2 — Core
**PRÓXIMA**

Trazer para o `Teste`:

- `Item`;
- estados;
- contratos de serviço;
- erros de domínio;
- `VisionResult`;
- contratos de publicação;
- contratos de Studio/IA.

### Etapa 3 — Database + Storage
**PENDENTE**

Migrar nativamente:

- banco de execução;
- estados;
- reserva;
- original imutável;
- hashes;
- workspace;
- cleanup.

### Etapa 4 — Materializer
**PENDENTE**

- Telethon;
- download por um item;
- arquivo `.part`;
- timeout de inatividade;
- validação de tamanho;
- rename atômico;
- finalização do ORIGINAL.

### Etapa 5 — Pipeline
**PENDENTE**

```text
Vision → IA → Studio → Publishing
```

adaptado para a nova arquitetura e sem runtime externo.

### Etapa 6 — Hub
**PENDENTE**

- publicação Telegram;
- destino;
- tópico;
- confirmação;
- `CONFIRMED`;
- `ABSENT`;
- `UNKNOWN`.

### Etapa 7 — Recovery
**PENDENTE**

- reconciliação;
- retomada;
- artefatos;
- publicação ambígua;
- nunca duplicar publicação.

### Etapa 8 — Coordinator
**PENDENTE**

O Coordinator será a única composição raiz:

```text
Coordinator
 ├── TelegramGateway
 ├── SQLite
 ├── Vision
 ├── Materializer
 ├── Studio
 ├── IA
 ├── Hub
 └── Recovery
```

### Etapa 9 — CATCH-UP real
**PENDENTE**

Executar o inventário histórico real, um candidato por vez.

### Etapa 10 — LIVE
**PENDENTE**

Somente depois de o CATCH-UP estar certificado.

---

# 9. Dependência temporária existente

Neste momento, a migração ainda está em andamento.

O executor mantém uma **fronteira temporária de compatibilidade** para as camadas
que ainda não foram migradas:

- Database;
- State;
- Storage;
- Pipeline;
- Recovery;
- Studio;
- IA;
- Hub.

Isso é intencional e documentado.

**Vision V1 já não atravessa essa fronteira.**

A meta da próxima etapa é eliminar progressivamente essa fronteira até que
`Teste` seja completamente autônomo.

Portanto, enquanto a migração não terminar, o executor ainda pode exigir
`ARMORED_BASE_ROOT` para as camadas restantes. Isso não é o estado final e
não deve ser tratado como arquitetura definitiva.

---

# 10. Como instalar

Na raiz:

```powershell
python -m pip install -r requirements.txt
```

Dependências principais atuais:

- Telethon;
- python-dotenv;
- requests.

---

# 11. Verificação de configuração

```powershell
python .\scripts\check_config.py
```

O arquivo real:

```text
credentials/project.env
```

não deve ser versionado.

A sessão Telegram fica em:

```text
credentials/telegram/armoredsync.session
```

---

# 12. Scanner histórico

```powershell
python .\scripts\scan_sources.py
```

Relatórios:

```text
reports/
├── pattern_summary.json
├── pattern_evidence.jsonl
└── pattern_evidence.csv
```

A descoberta é separada da materialização de mídia.

---

# 13. CATCH-UP executor

Durante a migração, as camadas ainda não nativas podem utilizar
temporariamente a referência congelada.

Exemplo temporário:

```powershell
$env:ARMORED_BASE_ROOT="C:\caminho\para\armoredcreator-test"
python .\scripts\run_historical_catchup.py
```

**Esse comando não representa a arquitetura final.**

Quando Database, Storage, Pipeline, Studio, IA, Hub e Recovery forem migrados,
`ARMORED_BASE_ROOT` será removido definitivamente.

---

# 14. Testes

A cada etapa concluída, a regra é:

1. implementar;
2. adicionar testes;
3. executar a suíte;
4. corrigir regressões;
5. atualizar este README;
6. registrar o commit/PR;
7. somente então iniciar a próxima etapa.

Para a etapa atual, os testes nativos do Vision cobrem:

- resolução direta de URL;
- identificação exata;
- retorno de affiliate URL;
- construção de `ia_context`;
- produto não encontrado;
- conversão para `VisionUnresolvedError`.

---

# 15. Critério de conclusão do projeto

O projeto somente será considerado definitivamente migrado quando:

- nenhum import/runtime depender de `armoredcreator-test`;
- `ARMORED_BASE_ROOT` deixar de existir;
- Coordinator for a composição única;
- SQLite for a fonte de verdade;
- existir apenas um item físico ativo;
- CATCH-UP histórico estiver executando;
- Recovery estiver certificado;
- publicação Telegram estiver certificada;
- `UNKNOWN` não gerar republicação automática;
- CATCH-UP → LIVE estiver implementado;
- as três fontes estiverem isoladas logicamente;
- todos os testes estiverem verdes;
- o comportamento comprovado do projeto congelado estiver preservado.

---

# 16. Referência congelada

`armoredcreator-test` continua sendo a referência histórica de comportamento.

Ele não deve ser:

- modificado;
- usado como dependência definitiva;
- transformado em submodule;
- acoplado ao runtime final.

A finalidade dele é responder:

> “Como o comportamento comprovado funcionava?”

A finalidade do `Teste` é responder:

> “Como o ArmoredCreator definitivo funciona?”

---

# 17. Histórico das etapas

| Etapa | Status | Resultado |
|---|---|---|
| Descoberta histórica | CONCLUÍDA | 16.160 candidatos únicos |
| Auditoria de rastreabilidade | CONCLUÍDA | aprovada |
| Auditoria de composição | CONCLUÍDA | 19/19 followups aprovados |
| Inventário SQLite | CONCLUÍDA | isolado por fonte |
| Executor CATCH-UP inicial | EM MIGRAÇÃO | ponte temporária criada |
| Vision V1 nativo | **CONCLUÍDA** | sem dependência do runtime antigo |
| Core nativo | PENDENTE | próxima etapa |
| Database/Storage nativos | PENDENTE | — |
| Materializer nativo | PENDENTE | — |
| Pipeline nativo | PENDENTE | — |
| Hub nativo | PENDENTE | — |
| Recovery nativo | PENDENTE | — |
| Coordinator definitivo | PENDENTE | — |
| CATCH-UP real | PENDENTE | — |
| LIVE | PENDENTE | — |

---

## Regra de ouro

**Não avançar uma etapa porque “parece funcionar”.**

Cada camada precisa ser:

```text
código comprovado
      ↓
migração nativa
      ↓
teste
      ↓
integração
      ↓
certificação
      ↓
documentação atualizada
      ↓
próxima camada
```

Esse README é a documentação única do projeto e deve ser atualizado ao final
de cada etapa concluída.
