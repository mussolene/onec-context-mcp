# Локальный BSL Language Server (exec JAR)

Файл **`bsl-language-server-exec.jar`** в этот каталог **не входит в git** (размер ~110 МБ).

Скопируйте артефакт сборки:

```bash
cp /path/to/bsl-language-server/build/libs/bsl-language-server-*-exec.jar \
  docs/cursor-examples/bsl-language-server-local/bsl-language-server-exec.jar
```

Либо задайте `BSL_LS_JAR` в окружении. Инструкции агента — в [SKILL.md](SKILL.md).
