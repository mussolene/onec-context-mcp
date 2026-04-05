# Обычная форма: текстовый round-trip (контейнер ↔ модуль + поток)

## Зачем

Платформа хранит обычную форму в **`Ext/Form.bin`** — бинарный контейнер. Для команды и Git нужны:

- **читаемый diff** по модулю и описанию формы;
- **правка текстом** с предсказуемой обратной сборкой в тот же `Form.bin`.

По смыслу это близко к идее дизайнера (в т.ч. COM/ATL): *документ сериализуется в поток → правится → пишется обратно*. Здесь роль «текстового представления» выполняют **`Module.bsl`** и **`Form.stream.txt`**, а не публичный API 1С.

## Инструменты в репозитории

| Файл | Назначение |
|------|------------|
| `tools/1c/ordinary_form_roundtrip.py` | **Единая точка входа**: `extract` / `pack` / `verify` |
| `tools/1c/form_bin_tool.py` | Низкий уровень: разбор/сборка сегментов `Form.bin` |
| `tools/1c/form_stream_xml.py` | Опционально: `Form.stream.txt` ↔ lossless token XML (`--token-xml`) |

## Команды

Из корня репозитория (или с полными путями к обработке):

```bash
# Распаковать: указать каталог Ext/ или сам Form.bin
python3 tools/1c/ordinary_form_roundtrip.py extract path/to/Forms/ИмяФормы/Ext ./build/ordinary_form/ИмяФормы

# Опционально: XML по токенам (удобно для инструментов; round-trip через pack --from-token-xml)
python3 tools/1c/ordinary_form_roundtrip.py extract path/to/Ext ./build/ordinary_form/ИмяФормы --token-xml

# Собрать обратно (после правок Module.bsl и/или Form.stream.txt)
python3 tools/1c/ordinary_form_roundtrip.py pack ./build/ordinary_form/ИмяФормы path/to/Forms/ИмяФормы/Ext/Form.bin

# Если правили только Form.stream.tokens.xml:
python3 tools/1c/ordinary_form_roundtrip.py pack ./build/ordinary_form/ИмяФормы path/to/Ext/Form.bin --from-token-xml

# Проверка: split → join без изменений = тот же файл (для CI / golden)
python3 tools/1c/ordinary_form_roundtrip.py verify path/to/Ext/Form.bin
python3 tools/1c/ordinary_form_roundtrip.py verify path/to/Ext/Form.bin --with-stream-tokens
```

Make-обёртки (переменные обязательны):

```bash
make ordinary-form-extract FROM=path/to/Ext TO=build/of/myform EXTRA=--token-xml
make ordinary-form-pack DIR=build/of/myform DEST=path/to/Ext/Form.bin
make ordinary-form-verify FROM=path/to/Ext/Form.bin
```

## Состав каталога после `extract`

- **`Module.bsl`** — модуль формы (UTF-8 без BOM в файле; при `join` BOM добавляется как в оригинале).
- **`Form.stream.txt`** — внутренний текстовый поток `{ … }` платформы (не `lf:Form` управляемой формы).
- **`preamble.bin`**, **`segment_XX.bin`** — бинарные куски контейнера; **не править**, если нет уверенности.
- **`form.bin.manifest.json`** — метаданные сегментов для `pack`.
- **`Form.stream.tokens.xml`** — только с `--token-xml`.
- **`.ordinary_form_export.txt`** — маркер и ссылка на этот документ.

## Git и diff

- Коммитить можно **либо** только текстовый каталог (и генерировать `Form.bin` в пайплайне), **либо** и `Form.bin`, и текст — политика команды.
- Осмысленные diff: **`Module.bsl`**, **`Form.stream.txt`** (или **`Form.stream.tokens.xml`** при работе через XML).
- Бинарные **`segment_XX.bin`** обычно **не меняются** при правках подписей/модуля; если diff там большой — проверить, что не ломали структуру потока.

## Ограничения

- Формат контейнера **зависит от версии платформы**; тестируйте `verify` на той же ветке 8.x, с которой выгружен epf/cf.
- **`Form.stream.txt`** — внутренний язык платформы; семантика полей не документирована публично.
- После `pack` желательно **открыть форму в конфигураторе** той же версии платформы.

## Связь с MS COM/ATL (образно)

В клиенте 1С дизайнер форм опирается на **COM/ATL-стиль** компонентов и персист документа; **файл на диске** при XML-выгрузке — это уже **ваш** слой (`Form.bin`). Данный пайплайн **воспроизводит только файловый round-trip**, без вызова COM: эквивалент «сохранить в редактируемое представление → изменить → записать обратно» на уровне байтов контейнера.
