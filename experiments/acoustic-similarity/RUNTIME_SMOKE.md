# Runtime-only проверка после отказа cap2

Обучение cap2 и оценка реального test — **NOT RUN**. Оба real-training jobs
`cap2-pilot` и `groove-pilot` остаются `if: false`. Старое разрешение не используется.

## Причина и исправление

В [job 114457384889](https://github.com/zinverno/yanjaro/actions/runs/38135097182/job/114457384889)
checkout прошёл, затем в 11:19:48.584 UTC проверка
`test -x "$RUNNER_TOOL_CACHE/Python/3.12.13/x64/bin/python3"` вернула exit 1.
Это подтверждает отсутствие исполняемого файла по предположенному пути, а не ошибку
pip, данных или оптимизатора. `setup-python` из другого job не подготавливает этот runner.
Старые [свидетельства и отрицательный статус](CAP2_RUN.md) сохранены неизменными.

В отключённом cap2 job теперь явно вызывается
`actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` с
`python-version: '3.12.13'`: тот же SHA и patch-version, что у существующего `tests`.
В следующем shell step проверяются точная версия и `python3 -m pip`.
Отдельный `runtime-smoke` проверяет тот же setup на своём `ubuntu-24.04` runner.

[Документация закреплённого action](https://github.com/actions/setup-python/blob/a26af69be951a213d495a4c3e4e4022e16d87065/README.md):
action добавляет выбранный Python в PATH следующих шагов; при отсутствии версии
в кеше получает её из GitHub Releases.

## Проверяемый сценарий

1. Точный Python 3.12.13; `python`, `python3`, `python -m pip` и `pip` доступны
   после setup step.
2. Неизменный `requirements.lock`, `--require-hashes --only-binary=:all:`,
   без pip retries; локальный пакет устанавливается с `--no-index --no-deps
   --no-build-isolation`.
3. `pip check` и импорт `acoustic_similarity` в следующем step.
4. Все unit tests через `scripts/runtime_smoke.py`. На время suite запрещены
   реальные socket/DNS обращения, acquisition, cap2 fit, rhythm train/evaluate
   и cap2 score на split=test. Любая попытка делает smoke FAIL, даже если тест
   перехватил исключение. Существующие mock-сетевые тесты остаются.
5. Установленные CLI `yanjaro-similarity --help`, `yanjaro-rhythm --help`
   и `python -m acoustic_similarity.cap2 --help`, без входных аудио.

Численные unit-регрессии по сохранённым train-признакам, включая воспроизведение
старых весов и ограничений cap2 в памяти, сохранены. Это не запуск эксперимента:
новых model/metrics нет, real test исключён. Синтетические сигналы unit tests
не выдаются за реальные данные или качество музыки. Обычные `tests` и distro CI
также могут автоматически исполняться на PR; ни один training job не включается.

Локальная проверка: **PASS, 75 tests, forbidden_calls=[]**. Remote smoke пока
**NOT RUN**; после выполнения здесь будет зафиксирован фактический run и результат.

## Сетевой трафик runtime

Разрешены инфраструктурные получения: закреплённые GitHub Actions, исходный код
ветки, Python 3.12.13 из `actions/python-versions` при cache miss и колёса PyPI
для неизменного lockfile. Python/package traffic **не относится** к лимиту
42 MiB будущих исследовательских данных и артефактов. Smoke не скачивает MIDI/WAV,
датасеты или энкодеры. Фактические cache/download строки будут сохранены после run;
полный wire traffic не измеряется и не будет назван нулевым.
Новые платные сервисы не создаются; используется стандартный CPU runner.

## Следующий единственный опыт: подготовлен, отключён

После PASS smoke инфраструктурное исправление проверено. На текущем HEAD
включение старого job недостаточно: исторические guards `run_number=5`, attempt=1,
parent `15e911d829a6f3683129de2bfcac37e47f55e995` намеренно неизменны и отвергнут
новый контекст. Эти guards не являются разрешением на новый опыт.

После **отдельной инструкции пользователя** потребуются новый привязанный к
конкретному запуску authorization commit, отдельные run/parent/output bindings
и их проверки. Нельзя переназначать исторические результаты или переиспользовать
run 38135097182. Подготовка runtime уже содержится в job; модельная конфигурация
и научный сценарий остаются из frozen proposal: 332 прежних train-triplets,
300 эпох, lr=0.1, L2=0.01, margin=0.05, temperature=0.1, ±ln(2)/2;
MIDI-only preflight перед тремя утверждёнными WAV drummer6; 42 MiB, 10 минут,
600 CPU seconds, 4 GiB virtual memory, два потока, без исследовательских retries.
После единственной будущей попытки job снова отключается. До нового разрешения
нет acquisition, cap2 training или новых held-out метрик.
