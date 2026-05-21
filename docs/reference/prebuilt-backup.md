# Prebuilt Qdrant/BM25 Backup

RU: эта страница описывает быстрый путь запуска без локальной индексации `.hbk`: скачать готовый physical backup, восстановить Qdrant storage и BM25 vocab, затем подключить MCP.

EN: this page documents the fastest startup path without local `.hbk` indexing: download a prepared physical backup, restore Qdrant storage and BM25 vocab, then connect MCP.

## Public Archive

RU: публичный архив:
[https://cloud.mail.ru/public/NzFn/qLfhyf8zo](https://cloud.mail.ru/public/NzFn/qLfhyf8zo)

EN: public archive:
[https://cloud.mail.ru/public/NzFn/qLfhyf8zo](https://cloud.mail.ru/public/NzFn/qLfhyf8zo)

Use the latest dated backup set. Current public set:

```text
2026-05-21_081637Z_onec-context-mcp_v1.0.15_git-3d5c5f8_qdrant-1.12.0_nomic-embed-text-v2-moe-768_physical/
  manifest.json
  qdrant-storage.tar.zst
  bm25-vocab.tar.zst
```

## What It Contains

RU: текущий публичный backup содержит:

- physical Qdrant storage archive для structured help, snippets/standards memory и metadata graph.
- BM25 vocab archive для коллекций, где BM25 включен.
- `manifest.json` с версией сервера, моделью эмбеддингов, размерностью и версиями конфигураций.

EN: the current public backup contains:

- physical Qdrant storage archive for structured help, snippets/standards memory and metadata graph.
- BM25 vocab archive for BM25-enabled collections.
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
| БухгалтерияПредприятияКОРП | 3.0.184.16 | 4442 | 62297 |
| УправлениеНебольшойФирмой | 1.6.27.295 | 2745 | 31456 |
| УправлениеНебольшойФирмой | 3.0.13.260 | 4520 | 57361 |
| УправлениеПроизводственнымПредприятием | 1.3.257.1 | 2536 | 36219 |

## Restore

RU: основной путь — одна команда.

EN: the primary path is a single command.

```bash
make quick-start-prebuilt
```

Она скачивает latest backup set, восстанавливает `data/qdrant` и
`data/bm25_vocab`, затем поднимает `qdrant` и `mcp`.

For manual step-by-step restore:

```bash
make ensure-data
make qdrant-download BACKUP=latest
make qdrant-restore BACKUP=latest
```

`make qdrant-download` reads the public Mail.ru folder, downloads
`manifest.json`, `qdrant-storage.tar.zst` and `bm25-vocab.tar.zst` into
`data/backup/<backup-set>/`, and validates the downloaded file sizes.

`make qdrant-restore` stops `mcp` and `qdrant`, restores `data/qdrant` and
`data/bm25_vocab` through the project Docker image, then starts the services
again. To restore a specific backup set:

```bash
make qdrant-restore BACKUP=2026-05-21_..._physical
```

## Create Backup

RU: локальный backup текущей базы:

EN: create a local backup of the current database:

```bash
make qdrant-backup
```

Команда создает `data/backup/<backup-set>/manifest.json`,
`qdrant-storage.tar.zst` и `bm25-vocab.tar.zst`. Qdrant останавливается на время
архивации, чтобы физический backup был консистентным.

The command writes `data/backup/<backup-set>/manifest.json`,
`qdrant-storage.tar.zst` and `bm25-vocab.tar.zst`. Qdrant is stopped while the
archive is created so the physical backup is consistent.

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
