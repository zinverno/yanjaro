# Локальные артефакты 0.2.0rc2-1 — 2026-10-07

Каталог проекта: `/home/zinvernix/projects/yanjaro-music`. Ничего из перечисленного не опубликовано в Release/AUR. Архив source — локальный snapshot, не опубликованный Git-тег. После сборки отчёты дополнялись результатами; приложение внутри артефактов заморожено.

| Файл относительно проекта | SHA-256 |
|---|---|
| `dist/native/yanjaro-0.2.0rc2-1-any.pkg.tar.zst` | `a853fcb567048e73510a8b17f70529a3c0e22d4f07ca9a3adc59ed47b36f04cc` |
| `dist/native/yanjaro-0.2.0rc2.tar.gz` | `1ca7cc6f075a775d37d3a1f508e23b2b183f4a04167ca56cc53305cf8268c8ac` |
| `dist/yanjaro_music-0.2.0rc2-py3-none-any.whl` | `fb233a5ecd2c67fc335f3c8d722e0817cd372a33adf79d72ec75433d7b90766d` |
| `dist/yanjaro_music-0.2.0rc2.tar.gz` | `389a884548f758fd95a5477a5e2dee2e3a870f6784bdebcc254dfdfd549edeb3` |

`packaging/.SRCINFO` создан makepkg из реального PKGBUILD, SHA-256 source совпадает с таблицей. `dist/native/SHA256SUMS` содержит контрольные суммы нативных пакетов. Wheel содержит entry point `yanjaro`, все QML/SVG/qmldir и объявленные SecretStorage/Jeepney; sdist и native прошли проверку исключения личных данных, токенов и dev-окружения. В пакетах нет профиля эксперимента, локальных pins, хранилища токенов или данных пользователя.

## Проверенная среда

Manjaro Stable, системный Python 3.14.7, PySide6/Qt 6.11.2, python-mpv 1.0.8, mpv 0.41.0. SecretStorage 3.5.0-1 и Jeepney 0.9.0-3 взяты из настроенных репозиториев, их SHA-256 сверены с локальной pacman sync database. Они находятся в отдельном `/tmp` prefix/venv, а копия базы пакетов смонтирована только в namespace сборки. Основной системный Python и база pacman не изменялись.

Полный `makepkg --force --cleanbuild` с `check()` прошёл: 48 проверок, desktop-file-validate, реальные Qt/libmpv с локальным WAV и `ao=null`. Это не чистая Manjaro VM или Arch chroot; обе проверки NOT RUN. Единственная диагностика fakeroot и 40 предупреждений namcap разобраны в [VALIDATION.md](../VALIDATION.md) и [NAMCAP.md](NAMCAP.md).

Применённая команда после подготовки изолированной накладки:

```sh
bwrap --ro-bind / / --dev /dev \
  --bind /home/zinvernix/projects/yanjaro-music /home/zinvernix/projects/yanjaro-music \
  --bind /tmp /tmp \
  --ro-bind /tmp/yanjaro-rc2-system/var/lib/pacman/local /var/lib/pacman/local \
  --setenv PATH /tmp/yanjaro-rc2-build-venv/bin:/usr/bin:/bin \
  --setenv XDG_CACHE_HOME /tmp/yanjaro-rc2-build-cache \
  --chdir /home/zinvernix/projects/yanjaro-music/dist/native \
  makepkg --force --cleanbuild
```

Для обычной подготовленной сборочной машины предназначен `./scripts/build-native.sh`; скрипт не устанавливает недостающие системные зависимости. Повторная подготовка после изменения отчётов создаст другой source hash и честно обновит рецепт.

## Установка и границы доказательств

Изолированная установка настоящим pacman rc1-3→rc2-1: PASS. Файлы приложения совпали побайтно с рабочим исходником, synthetic XDG-настройка сохранилась; установленный launcher из другого cwd загрузил Qt Quick, SDK, libmpv и завершился. IPC и Secret Service в этом smoke заменены тестовыми объектами. Такой запуск не подтверждает сохранённый вход, звук или карточку ОС.

Wheel дополнительно установлен в новый изолированный Python 3.13 venv. Все зависимости установлены офлайн из локальных wheels с `--require-hashes -r requirements.lock`; приложение — из собранного wheel без editable install. Запуск его entry point из `/tmp` загрузил собственные QML, SDK и libmpv и корректно закрыл окно. В тесте IPC/Secret Service заменены явно, пользовательские XDG-каталоги не использовались. PASS для установленного wheel; это также не живая desktop-приёмка.

На основной системе установка rc2 и живая матрица остаются NOT RUN до отдельного согласования/выполнения. После установки точная команда запуска — `/usr/bin/yanjaro`, также меню Yanjaro Music. [Установка и приёмка](RELEASE.md), [Secret Service и MPRIS](DESKTOP-INTEGRATION.md). Реальные новые снимки rc2 пока отсутствуют; синтетические снимки и старый rc1 не выданы за них.
