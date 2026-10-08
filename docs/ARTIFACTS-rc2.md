# Локальные артефакты rc2 — 2026-10-07

Каталог проекта: `/home/zinvernix/projects/yanjaro-music`. Ничего из перечисленного не опубликовано в Release/AUR. Архив source — локальный snapshot, не опубликованный Git-тег. После сборки отчёты дополнялись результатами; приложение внутри артефактов заморожено.

Предыдущий rc2-1 сохранён без изменения содержимого (старые source/wheel/sdist перенесены в архив):

| Файл относительно проекта | SHA-256 |
|---|---|
| `dist/native/yanjaro-0.2.0rc2-1-any.pkg.tar.zst` | `a853fcb567048e73510a8b17f70529a3c0e22d4f07ca9a3adc59ed47b36f04cc` |
| `dist/rc2-1/yanjaro-0.2.0rc2.tar.gz` | `1ca7cc6f075a775d37d3a1f508e23b2b183f4a04167ca56cc53305cf8268c8ac` |
| `dist/rc2-1/yanjaro_music-0.2.0rc2-py3-none-any.whl` | `fb233a5ecd2c67fc335f3c8d722e0817cd372a33adf79d72ec75433d7b90766d` |
| `dist/rc2-1/yanjaro_music-0.2.0rc2.tar.gz` | `389a884548f758fd95a5477a5e2dee2e3a870f6784bdebcc254dfdfd549edeb3` |

Архивный `dist/rc2-1/.SRCINFO` создан makepkg из реального PKGBUILD, SHA-256 source совпадает с таблицей. Актуальные packaging/PKGBUILD и .SRCINFO сгенерированы для сборки rc2-2. `dist/native/SHA256SUMS` содержит контрольные суммы нативных пакетов. Wheel содержит entry point `yanjaro`, все QML/SVG/qmldir и объявленные SecretStorage/Jeepney; sdist и native прошли проверку исключения личных данных, токенов и dev-окружения. В пакетах нет профиля эксперимента, локальных pins, хранилища токенов или данных пользователя.

## Проверенная среда первой сборки rc2-1

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

## Установка rc2-1 и границы доказательств

Изолированная установка настоящим pacman rc1-3→rc2-1: PASS. Файлы приложения совпали побайтно с рабочим исходником, synthetic XDG-настройка сохранилась; установленный launcher из другого cwd загрузил Qt Quick, SDK, libmpv и завершился. IPC и Secret Service в этом smoke заменены тестовыми объектами. Такой запуск не подтверждает сохранённый вход, звук или карточку ОС.

Wheel дополнительно установлен в новый изолированный Python 3.13 venv. Все зависимости установлены офлайн из локальных wheels с `--require-hashes -r requirements.lock`; приложение — из собранного wheel без editable install. Запуск его entry point из `/tmp` загрузил собственные QML, SDK и libmpv и корректно закрыл окно. В тесте IPC/Secret Service заменены явно, пользовательские XDG-каталоги не использовались. PASS для установленного wheel; это также не живая desktop-приёмка.

Владелец отдельно согласовал и выполнил установку на основной системе: read-only pacman подтвердил rc2-1, SecretStorage 3.5.0-1 и Jeepney 0.9.0-3. Файлы приложения совпали с кандидатом. Функциональная живая матрица проверяется отдельно. Точная команда запуска — `/usr/bin/yanjaro`, также меню Yanjaro Music. [Установка и приёмка](RELEASE.md), [Secret Service и MPRIS](DESKTOP-INTEGRATION.md). После живой приёмки в README добавлены шесть проверенных реальных снимков: пять из rc2-1 и станции из rc2-2. Снимок системной карточки не получен; её работу подтвердил владелец.

История новой локальной ветки сохранена также в `dist/yanjaro-rc2-review.bundle` (Git bundle, не установочный пакет). Она ведётся в `/tmp/yanjaro-git`, защищённая `.git` основной папки не менялась. Bundle проверяется `git bundle verify`; из него можно получить отдельный обычный checkout командой `git clone -b feature/player-polish-and-discovery dist/yanjaro-rc2-review.bundle /путь/к/новому/checkout`. В bundle нет пользовательских XDG-данных или секретов; он содержит историю проекта, включая ранее разрешённые снимки rc1, и не предназначен для автоматической публичной публикации.

## Кандидат rc2-2

Точечное исправление после живого ConnectTimeout описано в [NETWORK-rc2.md](NETWORK-rc2.md). Полный набор после изменения — 51 тест PASS. rc2-1 сохранён отдельно и не перезаписан. Владелец отдельно согласовал и установил rc2-2, подтвердил сохранённый вход и переходы без ручного повтора. Волна сыграла пять партий; в 63 запросах подготовки ошибки не возникали, поэтому живое срабатывание автоматического повтора ещё не наблюдалось.

| Артефакт rc2-2 относительно проекта | SHA-256 |
|---|---|
| `dist/native/yanjaro-0.2.0rc2-2-any.pkg.tar.zst` | `7ba013afe09722b774ba180597e6c31dc68fc19516bcb714cea39f18d0812ea3` |
| `dist/rc2-2/yanjaro-0.2.0rc2.tar.gz` | `4233db47fc854975652ac630204a30f35a083f87078112be3390f7ac42d67f95` |
| `dist/yanjaro_music-0.2.0rc2-py3-none-any.whl` | `0d6559bc5a687a3475183467eeb9825aa4ed099631fc91eb0871daad9d009217` |
| `dist/yanjaro_music-0.2.0rc2.tar.gz` | `912a2eea9b4febdc863a8033a33fa7ae1d1f20c9ec13c81efbd06bbd46ad3e15` |

Полный makepkg/check() повторён в очищенном каталоге с системным Python 3.14.7 и уже установленными владельцем declared dependencies; накладка package database и build-venv для этой сборки не понадобились. Namespace оставляет основной `/usr` read-only. Чистая ОС/chroot по-прежнему NOT RUN. Вывод сборки завершился кодом 0 без прежней диагностики libfakeroot. Все 478 записей архива имеют UID/GID 0 и безопасные режимы. Namcap: 0 E / 28 W (необязательные SDK extras и динамические зависимости).

Настоящий pacman обновил отдельный `/tmp` root с rc2-1 на rc2-2; launcher из другого cwd загрузил собственные ресурсы и закрылся, синтетическая XDG-настройка сохранилась. Новый wheel переустановлен в отдельном venv и его entry point тоже прошёл smoke. IPC/Secret Service в этих smoke — явные test doubles. Состав/зависимости/исключение секретов и соответствие байтов приложения проверены снова. В source/sdist/native включены только пять вручную просмотренных реальных снимков rc2 из согласованной приёмки, без кодов входа и системных уведомлений.

Снимок станций rc2-2 и дальнейшие результаты приёмки добавлены в рабочую документацию **после** этой сборки. Из-за этого отчёты/изображения в HEAD могут быть новее вложенных в архив. Все файлы приложения совпадают с кандидатом; замороженные артефакты и их хеши не менялись. Следующая подготовка source snapshot включит новую документацию с новым SHA-256.

На 2026-10-08 перед подготовкой packaging rc2-3 исходный архив rc2-2, рецепт и .SRCINFO сохранены без изменения в `dist/rc2-2/`. Native rc2-2, wheel/sdist не перезаписывались. Новые доказательства ведутся в PUBLIC-TEST-PREP.md.
