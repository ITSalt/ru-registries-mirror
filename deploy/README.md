# Развёртывание

Зеркало должно сниматься с машины, у которой российский выход в сеть —
`reestrs.minjust.gov.ru` и `*.rkn.gov.ru` иначе не отвечают.

## Что нужно

- VPS в РФ, Linux с systemd, Python 3.11+
- deploy key с правом записи **только в этот репозиторий**

Ключ выдаётся именно на этот репозиторий, а не на аккаунт: коробка с крон-джобой
не должна иметь доступа к остальным репозиториям.

## Установка

```bash
sudo useradd -m -s /bin/bash mirror
sudo -iu mirror

git clone git@github.com:ITSalt/ru-registries-mirror.git
git clone https://github.com/ITSalt/PepperSkills.git

cd ru-registries-mirror
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

git config user.name  "ru-registries-mirror"
git config user.email "mirror@itsalt.ru"
```

Проверка до включения таймера:

```bash
.venv/bin/python update.py \
  --skill-path ~/PepperSkills/pepper-ru-web-compliance/anthropic
```

Все пять реестров должны сняться. Если `reestrs.minjust.gov.ru` отвечает
ошибкой — значит выход у VPS не российский, и смысла в нём нет.

## Таймер

```bash
sudo cp deploy/ru-registries-mirror.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ru-registries-mirror.timer
systemctl list-timers ru-registries-mirror.timer
```

Прогон вручную и разбор проблем:

```bash
sudo systemctl start ru-registries-mirror.service
journalctl -u ru-registries-mirror.service -n 50
```

## За чем следить

Главный риск этого сервиса — **тихая деградация**: таймер работает, коммиты
идут, а один из реестров месяцами приходит с ошибкой. Внешне зеркало выглядит
живым, а данные протухли.

Поэтому:

- `update.py` возвращает ненулевой код, если хоть один реестр не снят;
- в `index.json` у такого реестра `status: "failed"` и `last_error`;
- потребители обязаны смотреть на `status` и `fetched_at`, а не только на наличие файла.

Простейший внешний контроль — проверять возраст `generated_at` в манифесте:

```bash
curl -s https://raw.githubusercontent.com/ITSalt/ru-registries-mirror/main/index.json \
  | python3 -c "
import json,sys,datetime
d=json.load(sys.stdin)
age=(datetime.datetime.now(datetime.timezone.utc)
     - datetime.datetime.fromisoformat(d['generated_at'])).days
bad=[k for k,v in d['registries'].items() if v.get('status')!='ok']
print(f'возраст манифеста: {age} д; не снято: {bad or \"нет\"}')
sys.exit(1 if age>2 or bad else 0)"
```

## Если VPS недоступен

В `.github/workflows/update.yml` лежит запасной прогон на GitHub Actions. Он
снимает только те три реестра, что доступны глобально, и запускается **вручную**
(`workflow_dispatch`). Автоматического расписания у него нет намеренно: два
писателя в один репозиторий устроили бы гонку и конфликты в git.
