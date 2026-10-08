# Namcap — 2026-10-07

Namcap 3.6.0-3 и его недостающие зависимости распакованы в `/tmp/yanjaro-namcap`, без установки в системный Python. SHA-256 сверены с локальной базой Manjaro Stable. Проверены рецепт и собранный пакет.

Результат не выдаётся за «без предупреждений»:

- `E: Dependency python-cryptography detected and not included` относится к `yandex_music/utils/decrypt.py`. Импорт находится внутри `decrypt_track`; SDK объявляет `cryptography` только для extra `crypto`. Наш путь `MusicApi.stream` использует `tracks_download_info` → `DownloadInfo.get_direct_link`, выбирает MP3/AAC без preview и передаёт ссылку mpv. `FileDownloadInfo.download`/`decrypt_track` не вызываются. Lossless/encraw в продукт не добавлены.
- `W` для orjson, ujson, pydantic-core, aiofiles/aiohttp, websockets/betterproto — опциональные SDK extras JSON/async/ynison, подтверждены METADATA официального wheel. Синхронный SDK работает в фоновом потоке, JSON имеет stdlib fallback; Ynison не используется. Эти модули сохранены как часть неизменённого SDK, но не включены в обязательные зависимости приложения.
- `W` о предположительно лишних `qt6-svg`, `qt6-wayland`, `xdg-utils`, `mpv`, `python-pysocks` не означает, что их следует удалить: это SVG-ресурсы, платформенный плагин, браузерный вход, динамический libmpv и зависимость `requests[socks]` SDK.
- `hicolor-icon-theme` удовлетворяется транзитивно, анализатор это отмечает.
- В кандидате `-2` отсутствовал комментарий Maintainer. В рецепте `-3` указан реальный владелец `zinverno` и его GitHub-профиль.

Перед отправкой AUR повторить анализ в чистой целевой среде. Не устанавливать неиспользуемые extras только ради пустого вывода статического анализатора.
