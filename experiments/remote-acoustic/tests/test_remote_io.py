"""Synthetic fixtures: these tests provide no real-model evidence."""
import io
import json
import time
import pytest
from remote_acoustic.remote_io import RangeFile
from remote_acoustic.cli import main
from remote_acoustic.data import extract_needed_embeddings


class Response(io.BytesIO):
    def __init__(self, payload, start, end, size, status=206):
        super().__init__(payload)
        self.status = status
        self.headers = {'Content-Range': f'bytes {start}-{end}/{size}'}


def opener_for(payload, calls):
    def open_range(request, timeout):
        start, end = map(int, request.headers['Range'][6:].split('-'))
        calls.append((start, end))
        return Response(payload[start:end+1], start, end, len(payload))
    return open_range


def test_range_seek_byte_budget_and_no_hidden_prefetch():
    calls = []
    with RangeFile('embeddings.parquet', max_bytes=5, max_seconds=10,
                   opener=opener_for(b'abcdefgh', calls)) as f:
        f.seek(-4, 2)
        assert f.read(4) == b'efgh'
        assert f.stats()['received_bytes'] == 5
        f.seek(0)
        with pytest.raises(ValueError, match='budget'):
            f.read(1)
        with pytest.raises(ValueError, match='Unbounded'):
            f.read()
    assert calls == [(0, 0), (4, 7)]


@pytest.mark.parametrize('status,header', [(200, 'bytes 0-0/8'), (206, 'bytes 1-1/8'), (206, '')])
def test_ignored_or_wrong_range_rejected_before_body(status, header):
    class NeverRead(Response):
        def read(self, *args):
            pytest.fail('Must reject headers before reading any body')
    def bad(request, timeout):
        response = NeverRead(b'x', 0, 0, 8, status)
        response.headers['Content-Range'] = header
        return response
    with pytest.raises(ValueError):
        RangeFile('embeddings.parquet', max_bytes=8, max_seconds=10, opener=bad)


def test_deadline_and_truncation_fail_closed():
    with RangeFile('embeddings.parquet', max_bytes=8, max_seconds=10,
                   opener=opener_for(b'abcd', [])) as f:
        f.deadline = time.monotonic()-1
        with pytest.raises(TimeoutError):
            f.read(1)
    with pytest.raises(ValueError, match='Truncated'):
        RangeFile('embeddings.parquet', max_bytes=8, max_seconds=10,
                  opener=lambda *a, **k: Response(b'', 0, 0, 8))


def test_arrow_actual_schema_shape_and_exact_batch_stop(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq
    file = tmp_path/'synthetic.parquet'
    pq.write_table(pa.table({'item_id': pa.array([1, 2, 3, 4], type=pa.uint32()),
        'normalized_embed': pa.array([[1.]*128]*4, type=pa.large_list(pa.float64()))}),
        file, row_group_size=2)
    calls = []
    original = pq.ParquetFile.iter_batches
    def batches(self, *a, **k):
        for batch in original(self, *a, **k):
            calls.append(batch.num_rows)
            yield batch
    monkeypatch.setattr(pq.ParquetFile, 'iter_batches', batches)
    report = {}
    result = extract_needed_embeddings(str(file), {1, 2, 3, 4}, batch_size=2,
                                        max_batches=1, report=report)
    assert set(result) == {1, 2}
    assert calls == [2]
    assert report['rows_read'] == 2 and not report['complete_scan']


def test_train_rejects_unverified_data_and_removes_stale_model(tmp_path):
    work = tmp_path/'work'; work.mkdir()
    (work/'prepare.json').write_text(json.dumps({'source': 'synthetic-test-only'}))
    (work/'extract.json').write_text('{}')
    output = tmp_path/'model.json'; output.write_text('stale')
    with pytest.raises(ValueError, match='provenance'):
        main(['train', '--work', str(work), '--output', str(output)])
    assert not output.exists()


def test_arrow_through_strict_range_file(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    file = tmp_path/'synthetic.parquet'
    pq.write_table(pa.table({'item_id': [1, 2], 'normalized_embed': [[.5]*8]*2}), file)
    payload = file.read_bytes(); calls = []
    with RangeFile('embeddings.parquet', max_bytes=4*len(payload), max_seconds=10,
                   opener=opener_for(payload, calls)) as source:
        with pq.ParquetFile(source, pre_buffer=False) as pf:
            assert pf.read(columns=['item_id']).column(0).to_pylist() == [1, 2]
    assert calls[0] == (0, 0) and len(calls) > 1


def test_full_scan_budget_rejects_measured_slow_scan():
    from scripts.check_training_budget import check
    report = {'status': 'PASS', 'projected_full_scan_bytes': 7969776991,
              'io': {'received_bytes': 123424184, 'seconds': 62}}
    with pytest.raises(ValueError, match='exceeds budget'):
        check(report, 'train-full', 8192)
    assert check(report, 'train-bounded', 512) is None
    report['io']['seconds'] = 10
    with pytest.raises(ValueError, match='exceeds budget'):
        check(report, 'train-full', 512)
    assert check(report, 'train-full', 8192) < 3600
