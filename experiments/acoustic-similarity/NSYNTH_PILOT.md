# NSynth note timbre pilot — NOT RUN

[Official NSynth](https://magenta.tensorflow.org/datasets/nsynth), Google Inc.,
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): 305,979 four-second
16 kHz notes from 1,006 instruments; pitch/velocity and instrument identities,
with qualities annotated using human evaluation and heuristics. These are individual
notes from sample libraries, not songs. Cite Engel et al., *Neural Audio Synthesis
of Musical Notes with WaveNet Autoencoders* (2017); identify subset/feature changes.

HTTP HEAD measurements on 2026-10-11, JSON/WAV tar.gz:

| Archive | Bytes | MiB | Notes |
|---|---:|---:|---:|
| train | 23,815,298,079 | 22,712.04 | 289,205 |
| valid | 1,068,767,009 | 1,019.26 | 12,678 |
| test | 349,501,546 | 333.31 | 4,096 |

The legacy download host's HTTPS certificate did not match its hostname. Verification
was **not disabled**. Its official HTTP test object's size/ETag matches the HTTPS
[Google bucket object](https://storage.googleapis.com/download.magenta.tensorflow.org/datasets/nsynth/nsynth-test.jsonwav.tar.gz)
(size 349,501,546, ETag `5e6f8719bf7e16ad0a00d518b78af77d`, generation
1491603911045000). No NSynth audio was downloaded. Details:
[dataset-availability.json](validation/dataset-availability.json).

TFRecord tar files are much larger: test 1,050,327,040 bytes, valid 3,250,995,200,
train 74,159,943,680, from [official TFDS checksums](https://github.com/tensorflow/datasets/blob/master/tensorflow_datasets/datasets/nsynth/checksums.tsv).
A `tfds.load(split=...)` request is not evidence of bounded download. Unlike ZIP,
a gzip tar has no central member directory for efficient verified random access.
The smallest complete official JSON/WAV split is test; streaming part of gzip would
not guarantee sufficient instruments/metadata and would not verify the whole archive.

Concrete prepared experiment: `nsynth.prepare_note_triplets(examples_json)` accepts
at most 4,096 notes, retains pitches 48/60/72 at velocity 100, and compares official
quality sets (excluding tempo-synced). Same pitch and velocity for all three members;
three distinct instruments, positive quality Jaccard >=.5, gap >=.5. No family/genre
classification target. Instrument IDs are deterministically assigned 50/25/25 to
train/validation/test, >=12 instruments total. This repurposes the original test
archive as a custom pilot cohort, not the canonical NSynth benchmark. All derivatives
of each note/instrument must remain together. Before extraction, bind official archive
integrity, metadata and per-note audio hashes, and reject duplicate audio across splits.
Performer independence is UNKNOWN because NSynth does not identify performers.

The existing MFCC mean/std/delta timbre representation can be extracted over exactly
four seconds under a **new note schema**, without padding notes to pass the old
10-second song gate. Compare uniform DSP distance to a separate contrastive diagonal
head, report held-out instrument results by pitch, velocity and quality. Never combine
these results with song similarity metrics. The metadata planner and its controlled
pitch/velocity/group checks are tested; real extraction/training is NOT RUN.

Downloading the 333.31 MiB test archive **in addition to the approved Groove cohort
would exceed the shared 512 MiB budget**. It is not part of this run. A subsequent
separately approved acquisition budget is required; no paid resource is needed for
this small note pilot. The actual retained-note/triplet counts remain unknown until
its metadata is obtained and checked. Do not invent them.
