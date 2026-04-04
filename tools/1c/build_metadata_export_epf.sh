#!/usr/bin/env bash
# Сборка tools/1c/MetadataExport.epf из XML-выгрузки внешней обработки
# (исходники: .nosync/MetadataExportEpf/, корень — каталог с MetadataExport.xml).
#
# Способы (см. руководство администратора 1Ci KB, Appendix 7.4.8 и 4.7.6.8):
#   1) 1cv8 CONFIG … /LoadExternalDataProcessorOrReportFromFiles <корень.xml|каталог> <выход.epf>
#      (для 8.5.x проверено: корневой файл MetadataExport.xml)
#   2) ibsrv — не «собирает» epf; поднимает автономный сервер для веб/SSH/прямого доступа
#   3) ibcmd — админутилита ИБ/сервера; прямой подкоманды «собрать epf из XML» в типовой поставке нет
#   4) SSH к ibsrv — команда агента конфигуратора load-external-data-processor-or-report-from-files
#
# Переменные:
#   ONEC_1CV8   — полный путь к 1cv8 (толстый клиент/конфигуратор)
#               Пример macOS (плоская установка): /opt/1cv8/8.5.1.1150/1cv8
#               Пример Linux: /opt/1cv8/8.3.xx/x86_64/1cv8
#   OUT_EPF     — куда писать epf (по умолчанию: каталог скрипта / MetadataExport.epf)
#   ONEC_IB     — каталог файловой ИБ для /F (разрешение типов при сборке; см. skill 1c-platform-cli)
#
# Временная ИБ через CREATEINFOBASE (лёгкий шаблон .cf / .dt; не используйте тяжёлые продуктивные базы):
#   ONEC_AUTO_TEMP_IB=1     — создать файловую ИБ перед CONFIG, если ONEC_IB не задан
#   ONEC_EMPTY_CF           — путь к минимальному шаблону (.cf или .dt) для /UseTemplate (обязателен при AUTO)
#   ONEC_TEMP_IB            — каталог новой файловой ИБ (по умолчанию: $TMPDIR/onec-metadata-export-$$/ib)
#   ONEC_TEMP_ADDTOLIST     — если задано непустое имя — добавить ИБ в список (ibases.v8i) через /AddToList
#   ONEC_REMOVE_TEMP_IB=1   — после успешной сборки удалить каталог ONEC_IB, если мы его создавали
#
# Headless (Linux CI): конфигуратор всё равно тянет GUI-стек — задайте виртуальный дисплей, например:
#   Xvfb :99 -screen 0 1280x1024x24 &
#   export DISPLAY=:99
#   (зависимости: GTK/WebKit/шрифты — см. skill 1c-platform-cli)
# macOS: надёжнее запуск из залогиненной пользовательской сессии, не из «голого» SSH.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC_DIR="${METADATA_EXPORT_SRC:-$REPO_ROOT/.nosync/MetadataExportEpf}"
ROOT_XML="$SRC_DIR/MetadataExport.xml"
OUT_EPF="${OUT_EPF:-$SCRIPT_DIR/MetadataExport.epf}"
LOG_FILE="${LOG_FILE:-${OUT_EPF%.epf}_1cv8_build.log}"

CREATED_TEMP_IB=0
ONEC_IB_EFFECTIVE=""

die() { echo "error: $*" >&2; exit 1; }

cleanup_temp_ib() {
	if [[ "${ONEC_REMOVE_TEMP_IB:-0}" != "1" ]] || [[ "$CREATED_TEMP_IB" != "1" ]]; then
		return 0
	fi
	local d="${ONEC_IB_EFFECTIVE:-}"
	[[ -n "$d" ]] || return 0
	echo "==> удаление временной ИБ: $d"
	rm -rf "${d:?}"
	CREATED_TEMP_IB=0
}

create_temp_ib_if_needed() {
	local bin="$1"
	if [[ -n "${ONEC_IB:-}" ]]; then
		ONEC_IB_EFFECTIVE="$ONEC_IB"
		return 0
	fi
	if [[ "${ONEC_AUTO_TEMP_IB:-0}" != "1" ]]; then
		ONEC_IB_EFFECTIVE=""
		return 0
	fi
	[[ -n "${ONEC_EMPTY_CF:-}" ]] || die "ONEC_AUTO_TEMP_IB=1 требует ONEC_EMPTY_CF (путь к .cf или .dt)"
	local tib="${ONEC_TEMP_IB:-${TMPDIR:-/tmp}/onec-metadata-export-$$/ib}"
	local parent dump_cr create_log
	parent="$(dirname "$tib")"
	mkdir -p "$parent"
	[[ ! -e "$tib" ]] || die "каталог ИБ уже существует (удалите или задайте другой ONEC_TEMP_IB): $tib"
	dump_cr="${parent}/create_ib_DumpResult.txt"
	create_log="${parent}/create_ib_Out.log"
	local conn="File=\"${tib}\";"
	echo "==> CREATEINFOBASE (временная ИБ): $tib"
	if [[ -n "${ONEC_TEMP_ADDTOLIST:-}" ]]; then
		"$bin" CREATEINFOBASE "$conn" /UseTemplate "$ONEC_EMPTY_CF" /AddToList "$ONEC_TEMP_ADDTOLIST" /DumpResult "$dump_cr" /Out "$create_log"
	else
		"$bin" CREATEINFOBASE "$conn" /UseTemplate "$ONEC_EMPTY_CF" /DumpResult "$dump_cr" /Out "$create_log"
	fi
	[[ -f "$dump_cr" ]] || die "нет $dump_cr после CREATEINFOBASE"
	# strings(1) не подходит для одного символа «0»; учитываем UTF-8 BOM
	if ! python3 -c "import pathlib,sys; b=pathlib.Path(sys.argv[1]).read_bytes().lstrip(b'\\xef\\xbb\\xbf').strip(); sys.exit(0 if b==b'0' else 1)" "$dump_cr"; then
		die "CREATEINFOBASE: код результата не 0 (см. $create_log и $dump_cr)"
	fi
	ONEC_IB_EFFECTIVE="$tib"
	CREATED_TEMP_IB=1
	trap cleanup_temp_ib EXIT
}

[[ -f "$ROOT_XML" ]] || die "нет $ROOT_XML — проверьте METADATA_EXPORT_SRC или .nosync/MetadataExportEpf"

find_1cv8() {
	if [[ -n "${ONEC_1CV8:-}" && -x "$ONEC_1CV8" ]]; then
		echo "$ONEC_1CV8"
		return 0
	fi
	local d arch b
	for d in /opt/1cv8/*; do
		[[ -d "$d" ]] || continue
		b="$d/1cv8"
		if [[ -x "$b" ]]; then
			echo "$b"
			return 0
		fi
		for arch in aarch64 x86_64 arm64; do
			b="$d/$arch/1cv8"
			if [[ -x "$b" ]]; then
				echo "$b"
				return 0
			fi
		done
	done
	return 1
}

build_via_1cv8() {
	local bin
	bin="$(find_1cv8)" || die "не найден 1cv8: задайте ONEC_1CV8=/полный/путь/к/1cv8"
	create_temp_ib_if_needed "$bin"
	echo "==> 1cv8 CONFIG /LoadExternalDataProcessorOrReportFromFiles"
	echo "    bin: $bin"
	echo "    каталог XML: $SRC_DIR"
	echo "    выход: $OUT_EPF"
	# Платформа 8.5+ в логе указывает «корневой файл» — передаём MetadataExport.xml (см. ROOT_XML).
	if [[ -n "${ONEC_IB_EFFECTIVE:-}" ]]; then
		echo "    ИБ (/F): $ONEC_IB_EFFECTIVE"
		"$bin" CONFIG /DisableStartupMessages /Visible false /F "$ONEC_IB_EFFECTIVE" \
			/LoadExternalDataProcessorOrReportFromFiles "$ROOT_XML" "$OUT_EPF" \
			/Out "$LOG_FILE"
	else
		echo "    ИБ (/F): не задана — возможны ошибки или потеря типов (рекомендуется ONEC_IB или ONEC_AUTO_TEMP_IB)"
		"$bin" CONFIG /DisableStartupMessages /Visible false \
			/LoadExternalDataProcessorOrReportFromFiles "$ROOT_XML" "$OUT_EPF" \
			/Out "$LOG_FILE"
	fi
	echo "    лог: $LOG_FILE"
	cleanup_temp_ib
	trap - EXIT
}

print_ibsrv_info() {
	cat <<'EOF'

==> ibsrv (автономный сервер)
    Сам по себе не компилирует .epf. Типичный сценарий:
      ibsrv --data=/path/to/ss-data --database-path=/path/to/file-ib [ --enable-ssh-gate --ssh-port=1543 ... ]
    Далее — клиент (веб/тонкий) или SSH/ibcmd к этому экземпляру.

EOF
}

print_ibcmd_info() {
	cat <<'EOF'

==> ibcmd
    Управление автономным сервером и ИБ (--pid, --remote ssh://host:port, --data).
    Сборка внешней обработки из файлов XML — штатно через конфигуратор (п.1) или SSH-команду
    load-external-data-processor-or-report-from-files (п.4), а не отдельной подкоманды ibcmd.

EOF
}

print_ssh_info() {
	cat <<'EOF'

==> SSH (конфигуратор в агентском режиме к автономному серверу)
    На ibsrv должен быть включён SSH-шлюз (--enable-ssh-gate, --ssh-port, --ssh-host-key).
    После подключения клиентом 1С по SSH и привязки к ИБ (connect-ib), команда группы config:
      load-external-data-processor-or-report-from-files --file=<полный_путь/MetadataExport.xml> --ext-file=<полный_путь/MetadataExport.epf>
    Синтаксис интерактивного протокола — в руководстве: §7.3.5, Appendix 4.7.6.8.

EOF
}

MODE="${1:-all}"

case "$MODE" in
1cv8)
	build_via_1cv8
	;;
ibsrv)
	print_ibsrv_info
	;;
ibcmd)
	print_ibcmd_info
	;;
ssh)
	print_ssh_info
	;;
all)
	if find_1cv8 2>/dev/null; then
		build_via_1cv8
	else
		echo "Пропуск 1cv8: не задан ONEC_1CV8 и не найден /opt/1cv8/*/…/1cv8"
		echo "Задайте, например: export ONEC_1CV8=/opt/1cv8/8.3.xx.xxxx/aarch64/1cv8"
	fi
	print_ibsrv_info
	print_ibcmd_info
	print_ssh_info
	;;
*)
	die "usage: $0 [all|1cv8|ibsrv|ibcmd|ssh]"
	;;
esac
