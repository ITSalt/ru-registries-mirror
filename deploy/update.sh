#!/usr/bin/env bash
# Снимает реестры и публикует изменения. Запускается по таймеру на машине
# с российским выходом в сеть.
#
# Git вынесен сюда, а не в update.py, намеренно: скрипт съёма не должен уметь
# делать push. Так его безопасно запускать руками и в отладке.
set -euo pipefail

MIRROR_DIR="${MIRROR_DIR:-$HOME/ru-registries-mirror}"
SKILL_DIR="${SKILL_DIR:-$HOME/PepperSkills/pepper-ru-web-compliance/anthropic}"
PYTHON="${PYTHON:-$MIRROR_DIR/.venv/bin/python}"

cd "$MIRROR_DIR"

# Скилл — источник парсеров. Держим его в актуальном состоянии, иначе зеркало
# будет разбирать выгрузки старой логикой.
git -C "$(dirname "$(dirname "$SKILL_DIR")")" pull --ff-only --quiet || \
  echo "предупреждение: не удалось обновить скилл, используется текущая версия" >&2

git pull --ff-only --quiet

set +e
"$PYTHON" update.py --skill-path "$SKILL_DIR"
STATUS=$?
set -e

if [[ -n "$(git status --porcelain data index.json)" ]]; then
  git add data index.json
  git commit -q -m "data: обновление реестров $(date -u +%Y-%m-%d)"
  git push -q
  echo "опубликовано"
else
  echo "изменений нет, коммит не нужен"
fi

# Ненулевой код означает, что часть реестров снять не удалось. Таймер это
# покажет в systemctl status — молча терять такое нельзя: устаревающее зеркало
# внешне неотличимо от работающего.
exit $STATUS
