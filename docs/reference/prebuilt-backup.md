# Prebuilt Qdrant/BM25 Backup

RU: эта страница описывает быстрый путь запуска без локальной индексации `.hbk`: скачать готовый backup, восстановить Qdrant snapshots и BM25 vocab, затем подключить MCP.

EN: this page documents the fastest startup path without local `.hbk` indexing: download a prepared backup, restore Qdrant snapshots and BM25 vocab, then connect MCP.

## Public Archive

RU: публичный архив:
[https://cloud.mail.ru/public/NzFn/qLfhyf8zo](https://cloud.mail.ru/public/NzFn/qLfhyf8zo)

EN: public archive:
[https://cloud.mail.ru/public/NzFn/qLfhyf8zo](https://cloud.mail.ru/public/NzFn/qLfhyf8zo)

Use the latest dated backup set. Current public set:

```text
2026-05-21_onec-context-mcp_git-b7d6725_qdrant-1.12.0_moe-768/
  manifest.json
  qdrant_snapshots/
  bm25_vocab/
```

## What It Contains

RU: текущий публичный backup содержит:

- Qdrant snapshots для structured help, snippets/standards memory и metadata graph.
- BM25 vocab для коллекций, где BM25 включен.
- `manifest.json` с версией сервера, моделью эмбеддингов, размерностью и версиями конфигураций.

EN: the current public backup contains:

- Qdrant snapshots for structured help, snippets/standards memory and metadata graph.
- BM25 vocab for BM25-enabled collections.
- `manifest.json` with server version, embedding model, vector dimension and configuration versions.

Current embedding profile:

```text
backend: openai_api
model: nomic-embed-text-v2-moe
dimension: 768
qdrant: 1.12.0
```

Indexed metadata configurations:

| Configuration | Version | Objects | Fields |
|---|---:|---:|---:|
| БухгалтерияПредприятияКОРП | 3.0.184.16 | 4442 | 62353 |
| УправлениеНебольшойФирмой | 1.6.27.295 | 2745 | 31521 |
| УправлениеНебольшойФирмой | 3.0.13.260 | 4520 | 57431 |
| УправлениеПроизводственнымПредприятием | 1.3.257.1 | 2536 | 36259 |

## Restore

RU:

1. Скачайте последнюю датированную папку из публичного архива.
2. Положите ее в `data/backup/` в репозитории.
3. Поднимите базовые сервисы.
4. Восстановите backup set.

EN:

1. Download the latest dated folder from the public archive.
2. Put it into `data/backup/` in this repository.
3. Start the base services.
4. Restore the backup set.

```bash
make ensure-data
make up

docker compose -f docker-compose.base.yml -f docker-compose.yml exec mcp \
  python -m onec_help qdrant-restore \
  --backup-dir /data/backup/2026-05-21_onec-context-mcp_git-b7d6725_qdrant-1.12.0_moe-768
```

The restore command accepts both layouts:

- Flat legacy layout: `data/backup/*.snapshot`
- Backup set layout: `data/backup/<backup-set>/qdrant_snapshots/*.snapshot` plus `data/backup/<backup-set>/bm25_vocab/`

## Verify

RU: после восстановления проверьте MCP и counts коллекций.

EN: after restore, verify MCP and collection counts.

```bash
make dashboard ARGS='--once'
```

Then call MCP tool `get_1c_help_index_status`. The current public backup should report:

```text
onec_help_api_members: 50153
onec_help_api_objects: 9313
onec_help_examples: 1943
onec_help_api_links: 64809
onec_help_topics: 1556
onec_help_memory: 6977
onec_config_metadata: 14243
onec_config_metadata_fields: 187333
```

## Security

RU: публичный backup предназначен для быстрой локальной оценки и demo-сценариев. Не публикуйте backup, собранный из приватных или NDA-конфигураций 1С, без отдельного согласования.

EN: the public backup is intended for quick local evaluation and demo scenarios. Do not publish backups built from private or NDA-covered 1C configurations without explicit approval.
