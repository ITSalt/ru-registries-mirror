#!/usr/bin/env python3
"""Забирает государственные реестры из первоисточников и публикует их как JSON.

Зачем это существует. Часть ведомственных хостов — `reestrs.minjust.gov.ru` и
все `*.rkn.gov.ru` — отвечает только с российских адресов. Инструменты,
работающие откуда угодно ещё, не могут проверить упоминание иностранного агента
или запрещённой организации вообще никак. Этот скрипт запускается на машине с
российским выходом, снимает реестры и выкладывает нормализованный JSON, который
уже доступен всем.

Что здесь ВАЖНО и чего нельзя потерять при доработках:

1. Публикуется только то, что снято с ОФИЦИАЛЬНОГО источника. Зеркалить чужое
   зеркало бессмысленно — цепочка происхождения теряется, а вместе с ней и
   единственное, ради чего это делается.
2. Каждый файл несёт URL первоисточника, sha256 его исходных байт и время
   съёма. Потребитель должен уметь сказать, откуда данные и насколько устарели,
   не веря нам на слово.
3. `freshness_window_days` публикуется рядом с данными. Это не украшение: по
   нему потребитель решает, можно ли делать вывод «упоминаний не найдено».
   Реестр иноагентов пополняется еженедельно, и просроченная копия даёт худший
   из отказов — тихое ложное «всё чисто».

Разбор форматов не дублируется: используется `registries.py` из скилла
pepper-ru-web-compliance. Две расходящиеся реализации парсинга одних и тех же
кривых выгрузок — гарантированный источник расхождений между тем, что видит
зеркало, и тем, что видит скилл при прямом доступе.

Использование:
    python3 update.py --skill-path ~/src/PepperSkills/pepper-ru-web-compliance/anthropic
    python3 update.py --skill-path ... --only minjust_foreign_agents
    PEPPER_SKILL_PATH=... python3 update.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent
DATA_DIR = REPO / "data"
INDEX = REPO / "index.json"
SCHEMA_VERSION = 1
GENERATOR = "ITSalt/ru-registries-mirror"

# Окно свежести: сколько дней данные реестра ещё можно считать пригодными для
# утверждения «упоминаний не найдено». Определяется темпом пополнения:
# иноагентов вносят еженедельно, перечни организаций меняются раз в месяцы.
FRESHNESS_WINDOW_DAYS = {
    "minjust_foreign_agents": 10,
    "minjust_undesirable_orgs": 30,
    "minjust_extremist_orgs": 45,
    "fsb_terrorist_orgs": 45,
    "minjust_extremist_materials": 30,
}
DEFAULT_WINDOW_DAYS = 30


def load_skill_module(skill_path: Path):
    """Подключает registries.py из скилла как модуль."""
    scripts = skill_path / "scripts"
    target = scripts / "registries.py"
    if not target.exists():
        raise SystemExit(
            f"не найден {target}\n"
            "Укажите путь к каталогу anthropic/ скилла pepper-ru-web-compliance "
            "через --skill-path или переменную PEPPER_SKILL_PATH."
        )
    sys.path.insert(0, str(scripts))
    import registries  # noqa: E402
    return registries


def dump_stable(payload: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    """Сериализует файл так, чтобы git-диффы оставались построчными.

    Каждая запись — одна строка. Иначе еженедельный коммит четырёхмегабайтного
    реестра переписывал бы файл целиком и репозиторий разнесло бы за год.
    """
    head = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    assert head.rstrip().endswith("}")
    head = head.rstrip()[:-1].rstrip()
    lines = [head + ",", '  "entries": [']
    for i, entry in enumerate(entries):
        row = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        lines.append("    " + row + ("," if i < len(entries) - 1 else ""))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def entries_fingerprint(entries: list[dict[str, Any]]) -> str:
    blob = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def existing_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("entries_sha256")
    except Exception:
        return None


def fetch_one(registries, key: str) -> tuple[dict[str, Any], list[dict[str, Any]] | None, str | None]:
    """Снимает один реестр строго с официального источника."""
    spec = registries.REGISTRIES[key]
    official = [s for s in spec.sources if s.trust == "official"]
    if not official:
        return {}, None, "у реестра нет официального источника"

    errors: list[str] = []
    for source in official:
        try:
            raw = registries.fetch_source_bytes(source)
            entries = [asdict(e) if not isinstance(e, dict) else e
                       for e in source.parser(raw)]
            if not entries:
                errors.append(f"{source.url}: разобрано 0 записей")
                continue
            meta = {
                "schema_version": SCHEMA_VERSION,
                "registry": key,
                "title": spec.title,
                "generator": GENERATOR,
                "source_url": source.url,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "source_bytes": len(raw),
                "source_trust": "official",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "freshness_window_days": FRESHNESS_WINDOW_DAYS.get(key, DEFAULT_WINDOW_DAYS),
                "entry_count": len(entries),
                "entries_sha256": entries_fingerprint(entries),
            }
            return meta, entries, None
        except Exception as exc:
            errors.append(f"{source.url[:70]}: {type(exc).__name__}: {exc}")
    return {}, None, "; ".join(errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skill-path", default=os.environ.get("PEPPER_SKILL_PATH"),
                        help="каталог anthropic/ скилла pepper-ru-web-compliance")
    parser.add_argument("--only", action="append", default=None,
                        help="обновить только указанный реестр (можно повторять)")
    parser.add_argument("--proxy", default=os.environ.get("PEPPER_RU_REGISTRY_PROXY"),
                        help="прокси до ведомственных хостов, если скрипт запущен не в РФ")
    args = parser.parse_args()

    if not args.skill_path:
        raise SystemExit("нужен --skill-path или переменная PEPPER_SKILL_PATH")

    registries = load_skill_module(Path(args.skill_path).expanduser().resolve())
    if args.proxy:
        registries.set_proxy(args.proxy)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    keys = args.only or list(registries.REGISTRIES)

    index: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "registries": {},
    }
    # Реестры, не тронутые этим запуском, сохраняем в индексе как были: иначе
    # выборочный прогон --only стёр бы сведения обо всех остальных.
    if INDEX.exists():
        try:
            index["registries"] = json.loads(INDEX.read_text(encoding="utf-8")).get("registries", {})
        except Exception:
            pass

    changed, failed = [], []
    for key in keys:
        meta, entries, error = fetch_one(registries, key)
        path = DATA_DIR / f"{key}.json"
        if error or entries is None:
            failed.append(key)
            prev = index["registries"].get(key, {})
            prev.update({"status": "failed", "last_error": (error or "")[:300],
                         "last_attempt_at": index["generated_at"]})
            index["registries"][key] = prev
            print(f"  ОШИБКА  {key}: {(error or '')[:160]}")
            continue

        was = existing_fingerprint(path)
        if was != meta["entries_sha256"]:
            path.write_text(dump_stable(meta, entries), encoding="utf-8")
            changed.append(key)
            mark = "обновлён"
        else:
            mark = "без изменений"

        index["registries"][key] = {
            "title": meta["title"],
            "file": f"data/{key}.json",
            "entry_count": meta["entry_count"],
            "source_url": meta["source_url"],
            "source_sha256": meta["source_sha256"],
            "entries_sha256": meta["entries_sha256"],
            "fetched_at": meta["fetched_at"],
            "freshness_window_days": meta["freshness_window_days"],
            "status": "ok",
        }
        print(f"  {mark:<14} {key:<30} записей: {meta['entry_count']}")

    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")

    print(f"\nизменено файлов: {len(changed)}; не снято: {len(failed)}")
    if failed:
        print("Не снятые реестры сохраняют в индексе status=failed — потребитель "
              "обязан трактовать это как «данных нет», а не как «записей нет».")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
