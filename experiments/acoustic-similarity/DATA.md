> Дополнение CPU rhythm pilot: [CPU_PILOT.md](CPU_PILOT.md).
> Прежние ограничения multi-aspect/MERT эксперимента ниже не являются
> предпосылками первого rhythm-only обучения. Его real-data gate сохранён отдельно.

# Разрешённые данные и расширение

## Сейчас: десять CC0, только диагностика

Исходные файлы ранее получены из точных File(s) вложений авторов OpenGameArt.
Проверка заново сверяет SHA-256 оригиналов и сохранённых страниц с квитанцией PR #9,
а также явную CC0-ссылку в HTML **до декодирования**. Это повторное использование
подтверждённых локальных байтов, новых загрузок нет. Права CC0 не гарантируют
отсутствие чужих samples: сохранена оговорка источника о правах заявителя.
Основание: [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).

| IDs | Авторская группа | Первичные публикации |
|---|---|---|
| o01–o04 | Joth | [Funked Up](https://opengameart.org/content/funked-up), [Bossa Nova](https://opengameart.org/content/bossa-nova), [8Bit Title Screen](https://opengameart.org/content/8bit-title-screen), [Fantasy Orchestral Theme](https://opengameart.org/content/fantasy-orchestral-theme) |
| s01–s04 | Spring Spring / Julie Damsgaard | [Jazz](https://opengameart.org/content/jazz-1), [Fusion Jazz](https://opengameart.org/content/basically-not-fusion-jazz), [Courtroom](https://opengameart.org/content/courtroom-and-judgement), [Kingdom](https://opengameart.org/content/kingdom-of-a-million-elephants-under-a-white-parasol) |
| u01–u02 | Juhani Junkala | [Boss Battle](https://opengameart.org/content/boss-battle-music), [JRPG Trailer](https://opengameart.org/content/jrpg-trailer-theme) |

Все имеют `split=diagnostic`, `training=false`, `remote=false`. 15-секундные окна
оставлены как в PR #9: 30–45 s, для короткого o03 центр. Baseline использует исходный
уровень сигнала, не нормализованные для прослушивания clips. Никаких labels из
старого screening не создано. Четыре недоступных Bandcamp-записи не запрашивались.

## Предлагаемый основной corpus

**2000 полных песен / не менее 200 независимых artist groups из MTG-Jamendo**,
после согласования списка и лимита получения. Это целевой план, не доступный или
разрешённый к загрузке прямо сейчас набор. Первая фаза — только manifest/audit
кандидатов; все конкретные записи должны получить собственные основания прав.

Первичные доказательства:

- [README на `cafd8e20c265ed84f1e61f1c875327971f43a62f`](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/README.md#license): code Apache-2.0, metadata CC BY-NC-SA 4.0, audio под индивидуальными CC лицензиями; распространитель ограничивает использование некоммерческим исследованием/академическими задачами.
- [Таблица индивидуальных audio licenses](https://github.com/MTG/mtg-jamendo-dataset/blob/cafd8e20c265ed84f1e61f1c875327971f43a62f/audio_licenses.txt) — проверяется для каждого выбранного track ID, а не заменяется лицензией README.
- Дополнительно сохранить страницу конкретной публикации, URL/условия официального
  канала получения, attribution и hash evidence. Наличие ссылки или жанрового тега
  не доказывает право скачать и обучать модель.

Для первой выборки выбирать CC0/CC BY/CC BY-SA без ND, с отдельным учётом условий
metadata/distributor. NC допустим только при подтверждённом некоммерческом scope.
Не переносить автоматически вывод о допустимости исследования на product integration,
публикацию derived artifacts/весов или коммерческий запуск; для этого нужна отдельная
проверка условий. Текстовых tags не превращать в perceptual labels.

При достаточном покрытии: 1400/300/300 песен, ориентир 140/30/30 независимых artist
groups для train/validation/test. Это целевые числа, splits назначаются группами,
а не подгоняются до точных размеров. По одной заранее выбранной 15 s области на
песню, одна recording_group для всех известных версий песни. Окна выбираются до
оценок сходства, без умножения десяти файлов на формально разные crops.

Разметка: ориентир 6000 train triplets суммарно (2000 на аспект), 600 validation и
600 test (200 на аспект), с двумя независимыми review и возможностью отказаться.
Для обязательных срезов — минимум 20 заданий и 5 независимых блоков каждый,
предпочтительно больше после оценки согласия. Числа — план, не измеренный объём
и не power analysis. Расходы/сроки разметки пока неизвестны.

## Дополнительные источники для отдельных аспектов

| Источник | Применимое основание | Назначение и ограничения |
|---|---|---|
| [Groove MIDI Dataset](https://magenta.tensorflow.org/datasets/groove) | Google публикует MIDI и синтезированный звук исполнения под CC BY 4.0 | 13.6 h, 10 drummers, измеряемые onset/tempo, полезен для ритма и same-tempo разных рисунков. Split по drummer/session, а не случайным тактам; genre не target. Это ударные, не full-song timbre benchmark |
| [NSynth](https://magenta.tensorflow.org/datasets/nsynth) | Google, CC BY 4.0 | 305,979 отдельных четырёхсекундных нот; контролировать pitch/velocity, отделять instruments. Полезен для будущей независимой проверки тембра; не заменяет песни. Текущий 10 s manifest его отклоняет: нужен отдельный протокол коротких нот, padding/repeat нельзя выдавать за дополнительные записи |
| [FMA на `607364e7d8263f890d23c838802f29637600611f`](https://github.com/mdeff/fma/blob/607364e7d8263f890d23c838802f29637600611f/README.md#license) | Metadata CC BY 4.0, **audio по лицензии конкретного автора**; corpus предназначен для исследований | Альтернатива MTG при недостатке разрешённых исполнителей. Проверить поле license и первоисточник каждой записи; genre split и готовые жанровые метки не дают acoustic labels |

Ни один из этих корпусов в этом этапе не загружен. Прямой интернет-доступ не равен
разрешению на массовую загрузку. Будущий запрос владельцу должен содержать конкретный
allowlist, proof по каждому файлу, общий byte/time budget, место хранения и policy
для derived embeddings. Без этого нет remote upload или расхода облачного бюджета.

## Формат права и provenance

Manifest содержит: стабильный dataset_id/revision, kind, id, artist_ids (включая
соавторов/aliases после нормализации), recording_group, split, path, sha256, start,
seconds и rights. Rights требуют reviewed/acquisition/analysis=true, название
лицензии, source_url, attribution, verified_on, scope, evidence_path и его SHA-256.
Training и remote — самостоятельные флаги подтверждённого scope, не выводятся из
analysis. Запрет/неизвестность отклоняет всю операцию до чтения первого аудиофайла.

При отзыве записи — удалить исходник, embeddings и результаты, построенные на ней,
создать новую версию manifest и переобучить/переоценить затронутые веса. Derived
артефакты не считать автоматически свободными от условий исходных данных.
