"""Synthetic ID layouts, no real user IDs or downloaded vectors in fixtures."""
import argparse
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from remote_acoustic.cli import parse_row_groups
from remote_acoustic.data import extract_needed_embeddings, is_holdout
from remote_acoustic import coverage


def test_coverage_reads_only_ids_and_selects_without_holdout_votes(tmp_path, monkeypatch):
    path = tmp_path/'synthetic.parquet'
    pq.write_table(pa.table({'item_id': list(range(1, 7)),
                            'normalized_embed': [[.5]*8]*6}), path, row_group_size=2)
    original_layout = coverage.parquet_layout
    def layout(pf):
        result = original_layout(pf)
        for group, size in zip(result['row_groups'], [270_000_000, 123_000_000, 270_000_000]):
            group['compressed_bytes'] = size
        return result
    monkeypatch.setattr(coverage, 'parquet_layout', layout)
    original_batches = pq.ParquetFile.iter_batches
    def ids_only(self, *a, **kw):
        assert kw['columns'] == ['item_id']
        return original_batches(self, *a, **kw)
    monkeypatch.setattr(pq.ParquetFile, 'iter_batches', ids_only)
    train_uid = next(u for u in range(100) if not is_holdout(u))
    held_uid = next(u for u in range(100) if is_holdout(u))
    pair = {'uid': train_uid, 'context': [1, 2], 'positive': 3, 'negative': 4}
    pairs = [pair, dict(pair, uid=held_uid), dict(pair, positive=99)]
    pairs += [{'uid': held_uid, 'context': [3, 4], 'positive': 5, 'negative': 6}]*20
    with pq.ParquetFile(path) as pf:
        report = coverage.coverage_report(pf, pairs)
    assert report['required_ids_missing'] == 1
    assert report['pairs_missing_ids_even_after_full_scan'] == 1
    assert report['best_within_budget']['groups'] == [0, 1]
    assert report['best_within_budget']['train_pairs'] == 1
    assert report['best_within_budget']['holdout_pairs'] == 1
    assert report['full_id_coverage']['structural_complete_pairs'] == 22


def test_extract_only_requested_group_and_reject_invalid_selection(tmp_path):
    path = tmp_path/'synthetic.parquet'
    pq.write_table(pa.table({'item_id': [1, 2, 3, 4],
                            'normalized_embed': [[.5]*8]*4}), path, row_group_size=2)
    stats = {}
    result = extract_needed_embeddings(str(path), {1, 2, 3, 4}, row_groups=[1], report=stats)
    assert set(result) == {3, 4}
    assert stats['row_groups_requested'] == [1] and stats['selected_rows'] == 2
    assert not stats['complete_scan']
    for groups in [[], [1, 1], [-1], [2]]:
        with pytest.raises(ValueError, match='row groups'):
            extract_needed_embeddings(str(path), {1}, row_groups=groups)


@pytest.mark.parametrize('value', ['', '-1', '0,0', '30', '1;echo bad', '$(echo 1)'])
def test_row_group_arguments_fail_closed(value):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_row_groups(value)


def test_row_group_selection_is_explicit():
    assert parse_row_groups('0,29') == [0, 29]
