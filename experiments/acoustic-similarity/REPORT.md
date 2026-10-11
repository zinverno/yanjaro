> Новый этап: отдельный [CPU rhythm pilot](CPU_PILOT.md), [его фактический отчёт](CPU_REPORT.md).
> Ниже сохранён исходный отчёт полного multi-aspect эксперимента на HEAD `da55781`;
> он не задаёт предпосылки для первого CPU rhythm обучения.

# Фактический отчёт — 2026-10-11

**Реально обученная acoustic similarity модель: NOT RUN.** Полноценных или
демонстрационных весов не опубликовано. Подготовлены рабочий DSP baseline,
локальный CLI, отдельные contrastive heads и GPU-only адаптер frozen MERT.
Обучение heads реально исполнено только в synthetic unit tests для проверки
оптимизатора; такие массивы не выдаются за музыкальные embeddings/метки.

## Baseline на разрешённом аудио

Проверены **10/10** прежних оригиналов CC0 и точные hashes страниц/аудио из PR #9:
Joth — 4, Spring Spring — 4, Juhani Junkala — 2. Всего три авторские группы,
150 s фиксированных исходных окон, **0** reviewed acoustic triplets.
Все записи diagnostic, никакого train/test из десяти файлов не изготовлено.

[Полный машинный отчёт](validation/baseline-report.json) содержит права и источники,
hashes, Lab27, оценённый BPM, top-3 и отдельные расстояния. В репозитории нет аудио,
private manifests, embeddings или сырых страниц/ответов.

| Фактическая проверка | Результат |
|---|---|
| Сверка оригиналов и сохранённых CC0 evidence | PASS — 10/10 |
| Извлечение Lab27 + rhythm72 + timbre85 + energy10 | PASS — 10/10 |
| Повторяемость признаков | PASS — точное совпадение двух извлечений |
| Поиск каждым из 10 файлов, исключение самого файла | PASS — 10/10 |
| Новые загрузки аудио / весов | 0 / 0 |
| Python socket attempts во время baseline | 0 |
| DSP elapsed / peak process RSS | 4.162 s / 194.89 MiB |
| Frozen MERT baseline и inference | NOT RUN |
| Реальное contrastive обучение | NOT RUN |

Среда: Python 3.12.13, NumPy 2.2.6, scipy 1.15.3, librosa 0.11.0, soundfile 0.13.1
(libsndfile — в JSON), 2 BLAS/OMP threads. Время — один наблюдаемый проход с уже
прогретым numba cache, без загрузки данных/весов; это не benchmark ноутбука или GPU
и не оценка скорости обработки полного каталога.

Несколько фактических первых результатов DSP поиска:

| Query | Ближайший по формуле |
|---|---|
| s01 | s04 |
| o01 | o03 |
| o02 | s01 |
| u01 | o03 |
| u02 | s03 |

Это диагностические результаты, **не подтверждённое слуховое сходство**. Жанр,
название и исполнитель в формуле не участвовали. `o02` оценён в 85.23 BPM, тогда
как авторский tag — 129; не заменяем одно значение другим без review. Расхождение
DSP-экстракторов само по себе также не определяет истинный BPM.

## Метрики качества по аспектам

| Аспект / срез | DSP baseline | Frozen baseline | Learned |
|---|---|---|---|
| Rhythm triplet accuracy | NOT RUN | NOT RUN | NOT RUN |
| Timbre triplet accuracy | NOT RUN | NOT RUN | NOT RUN |
| Energy/dynamics triplet accuracy | NOT RUN | NOT RUN | NOT RUN |
| Одинаковый жанр, разный ритм | NOT RUN | NOT RUN | NOT RUN |
| Разный жанр, похожий ритм | NOT RUN | NOT RUN | NOT RUN |
| Одинаковый BPM, разная инструментовка | NOT RUN | NOT RUN | NOT RUN |
| BPM accuracy против независимой разметки | NOT RUN | — | — |

Причина первых шести строк: нет согласованных независимых acoustic judgments.
У вычисленных top-K нет ground truth; считать accuracy/recall из них нельзя.
Превосходство над baseline **не установлено**. Prepared evaluation сравнивает
каждый learned head с baseline на тех же frozen features, учитывает ties, artist
groups и общих кандидатов; неполный test не может установить improvement.

## Проверки реализации

[Квитанция](validation/checks.json), [лог 33 тестов](validation/tests.txt):

- **PASS: 33 tests**, 0 skips, 4.019 s в итоговом проходе.
- PASS: исходный extractor PR #6 побайтно сохранён; 27 descriptors получаются.
- PASS: права проверяются до decode, изменение audio/evidence отвергается;
  missing, short, silent и nonfinite inputs не проходят молча.
- PASS: split leakage по записи/исполнителям/коллаборациям; duplicate hashes и
  противоречивые triplets отклоняются. Test features не изменяют trained weights.
- PASS: optimizer меняет известный искусственный порядок; повторное обучение
  детерминировано; frozen arrays не мутируют; demo model отклоняется CLI.
- PASS: controlled pulses проверяют rhythm/genre separation, timbre при одинаковом
  темпе и энергию при изменении gain. Это тесты механики, не музыка или human review.
- PASS: installed CLI, dependency check (27 packages), create-only JSON 0600,
  self-exclusion, стабильное ранжирование, новые query с отдельными правами.
- PASS: GPU adapter отказывает без explicit remote/code flags, проверяет hashes и
  лишние snapshot-файлы. **Настоящий model forward/GPU: NOT RUN**.

Первый прогон выявил асимметрию BPM distance на машинном округлении; исправлено
вычислением `log2(max/min)` при сохранённой строгой проверке симметрии. При review
учтено объединение коллабораций и общих кандидатов, чтобы не завышать число
независимых наблюдений. Не менялись production tests/условия или чужие ветки.

## Следующий практический шаг

Подготовить конкретный allowlist расширенного corpus, начиная с **некоммерческого
MTG-Jamendo**: целевой план 2000 песен / >=200 artist groups, индивидуальный license
audit, byte/time budget, слепая разметка отдельно для трёх аспектов и независимый
test. [DATA.md](DATA.md) содержит первичные доказательства и альтернативы. До
согласования нет массовой загрузки. Можно начать с независимого review имеющихся
десяти записей, но оно не превращает их в достаточный train corpus.

После достаточных данных и предоставления worker — согласованный небольшой GPU
probe MERT-95M, измерение стоимости, затем frozen baseline → обучение 1703 весов →
однократный test. MERT/MuQ веса ограничены NC; [сравнение](ENCODERS.md) не выдаёт
результаты чужих статей за наше качество. [REMOTE.md](REMOTE.md) описывает отдельные
границы реальных Yandex IDs и большого каталога.

Не выполнены: human listening, real embeddings/training, GPU/driver compatibility,
throughput/cost benchmark, full-catalog coverage, native desktop acceptance и
дистрибутивные сборки этого эксперимента. Release, AUR, Render и production не менялись.
