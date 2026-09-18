#!/usr/bin/env bash
# Снимает реестры и публикует изменения. Запускается по расписанию на машине
# с российским выходом в сеть.
#
# Git вынесен сюда, а не в update.py, намеренно: скрипт съёма не должен уметь
# делать push. Так его безопасно запускать руками и в отладке.
set -euo pipefail

MIRROR_DIR="${MIRROR_DIR:-$HOME/ru-registries-mirror}"
SKILL_DIR="${SKILL_DIR:-$HOME/skill-src/anthropic}"
PYTHON="${PYTHON:-python3}"
LOG="${LOG:-$HOME/mirror-update.log}"

exec >>"$LOG" 2>&1
echo "=== $(date -Is) ==="

cd "$MIRROR_DIR"

# Скилл — источник парсеров. Если он выложен git-репозиторием, держим в
# актуальном состоянии; если это просто каталог с файлами, работаем как есть.
SKILL_ROOT="$(cd "$SKILL_DIR/.." && pwd)"
if git -C "$SKILL_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$SKILL_ROOT" pull --ff-only --quiet || echo "предупреждение: скилл не обновился"
fi

git pull --ff-only --quiet || echo "предупреждение: git pull зеркала не прошёл"

set +e
"$PYTHON" update.py --skill-path "$SKILL_DIR"
STATUS=$?
set -e

if [[ -n "$(git status --porcelain data index.json)" ]]; then
  git add data index.json
  git commit -q -m "data: обновление реестров $(date -u +%Y-%m-%d)"
  git push -q && echo "опубликовано"
else
  echo "изменений нет, коммит не нужен"
fi

# Ненулевой код означает, что часть реестров снять не удалось. Терять это молча
# нельзя: устаревающее зеркало внешне неотличимо от работающего.
exit $STATUS
