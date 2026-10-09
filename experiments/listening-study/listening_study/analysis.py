"""Conditional choice proportions; participant and crossed source uncertainty."""
import random
import uuid
from collections import Counter, defaultdict
from .common import VERSION, PROMPTS, require
from .design import schedule, validate_study


def validate_response(response, study):
    fields = {"schema", "study_id", "study_sha256", "demo", "phase", "slot", "prompt_id",
              "participant_id", "status", "answers"}
    require(set(response) == fields, "Unexpected/missing response fields (PII is not accepted)")
    for key, expected in (("schema", VERSION), ("study_id", study["study_id"]),
                          ("study_sha256", study["sha256"]), ("demo", study["demo"]), ("phase", study["phase"])):
        require(type(response[key]) is type(expected) and response[key] == expected, "Response provenance mismatch: " + key)
    try:
        pid = uuid.UUID(response["participant_id"])
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Participant ID must be a random UUID") from None
    require(pid.version == 4 and str(pid) == response["participant_id"], "Expected canonical random UUIDv4")
    require(response["status"] == "complete", "Only voluntarily exported complete sessions are accepted")
    assigned = schedule(study, response["slot"], response["prompt_id"])
    answers = response["answers"]
    require(isinstance(answers, list) and len(answers) == len(assigned), "Incomplete session")
    for answer, task in zip(answers, assigned):
        require(set(answer) == {"trial_id", "choice", "heard"} and answer["trial_id"] == task["id"],
                "Unknown, repeated, or out-of-order trial")
        require(answer["choice"] in ("left", "right", "neither", "skip"), "Invalid choice")
        require(isinstance(answer["heard"], dict) and set(answer["heard"]) == {"source", "left", "right"}
                and all(type(v) is bool for v in answer["heard"].values()), "Invalid listening flags")
        require(answer["choice"] == "skip" or all(answer["heard"].values()), "Choice without listening")
    return assigned


def fraction(counts):
    a, b = counts
    return a / (a + b) if a + b else None


def interval(values, draws):
    valid = sorted(v for v in values if v is not None)
    if len(valid) < .95 * draws:
        return {"ci95": None, "valid_resamples": len(valid), "reason": "Too many resamples with no decisive choices"}
    def quantile(q):
        position = q * (len(valid) - 1)
        i = int(position)
        return valid[i] + (valid[min(i + 1, len(valid) - 1)] - valid[i]) * (position - i)
    return {"ci95": [quantile(.025), quantile(.975)], "valid_resamples": len(valid)}


def bootstrap(cells, participants, sources, *, draws, seed, crossed=False):
    if len(participants) < 2 or (crossed and len(sources) < 2):
        return {"ci95": None, "valid_resamples": 0, "reason": "Need at least two clusters"}
    rng = random.Random(seed)
    values = []
    for _ in range(draws):
        people = Counter(rng.choices(participants, k=len(participants)))
        songs = Counter(rng.choices(sources, k=len(sources))) if crossed else dict.fromkeys(sources, 1)
        a = b = 0
        for (p, s), (ca, cb) in cells.items():
            weight = people.get(p, 0) * songs.get(s, 0)
            a += ca * weight
            b += cb * weight
        values.append(fraction((a, b)))
    return interval(values, draws)


def analyze(study, responses, *, draws=2000, seed=20261009):
    validate_study(study)
    require(type(draws) is int and 200 <= draws <= 20000, "Use 200..20000 bootstrap draws")
    seen, slots, grouped = set(), set(), defaultdict(list)
    for response in responses:
        assigned = validate_response(response, study)
        pid = response["participant_id"]
        slot = response["prompt_id"], response["slot"]
        require(pid not in seen and slot not in slots, "Duplicate participant or assignment slot")
        seen.add(pid)
        slots.add(slot)
        grouped[response["prompt_id"]].append((response, assigned))
    output = {}
    for prompt in PROMPTS:
        rows = grouped[prompt]
        cells, source_counts = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
        totals, controls, sides = Counter(), Counter(), Counter()
        for response, assigned in rows:
            pid = response["participant_id"]
            for answer, task in zip(response["answers"], assigned):
                choice = answer["choice"]
                outcome = choice
                if choice in ("left", "right"):
                    first = (choice == "left") == task["first_left"]
                    outcome = ("rhythm" if first else "genre") if task["kind"] == "primary" else ("both_near" if first else "both_far")
                if task["kind"] == "control":
                    controls[outcome] += 1
                    continue
                totals[outcome] += 1
                if choice in ("left", "right"):
                    sides[choice] += 1
                cell = cells[(pid, task["source"])]  # Keep zero-choice participants in resampling.
                count = source_counts[task["source"]]
                if outcome in ("rhythm", "genre"):
                    index = 0 if outcome == "rhythm" else 1
                    cell[index] += 1
                    count[index] += 1
        participants = sorted({p for p, _ in cells})
        sources = sorted(source_counts)
        a, b = totals["rhythm"], totals["genre"]
        by_person = {p: [sum(c[i] for (person, _), c in cells.items() if person == p) for i in (0, 1)] for p in participants}
        person_rates = [v for c in by_person.values() if (v := fraction(c)) is not None]
        song_rates = [v for c in source_counts.values() if (v := fraction(c)) is not None]
        output[prompt] = {
            "participants": len(rows), "primary_sources": len(sources), "primary_outcomes": dict(totals),
            "primary_trials": sum(totals.values()), "decisive_choices": a + b,
            "rhythm_share_among_decisive": fraction((a, b)),
            "rhythm_share_all_primary": a / sum(totals.values()) if totals else None,
            "participant_cluster_bootstrap": bootstrap(cells, participants, sources, draws=draws, seed=f"{seed}:{prompt}"),
            "crossed_participant_source_bootstrap": bootstrap(cells, participants, sources, draws=draws, seed=f"{seed}:{prompt}:crossed", crossed=True),
            "equal_participant_mean": sum(person_rates) / len(person_rates) if person_rates else None,
            "equal_source_mean": sum(song_rates) / len(song_rates) if song_rates else None,
            "leave_one_source_out": {s: fraction((a - c[0], b - c[1])) for s, c in source_counts.items()},
            "by_source": {s: {"rhythm": c[0], "genre": c[1], "share": fraction(c)} for s, c in source_counts.items()},
            "control_outcomes": dict(controls), "chosen_sides": dict(sides),
        }
    return {"schema": VERSION, "study_sha256": study["sha256"], "demo": study["demo"], "phase": study["phase"],
            "bootstrap_draws": draws, "bootstrap_seed": seed, "results_by_prompt": output,
            "interpretation": "Exploratory conditional proportion; synthetic results are not listener evidence. No hypothesis confirmation."}
