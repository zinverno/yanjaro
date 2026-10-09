"""ID-only coverage planning. Public reports contain aggregate counts, never IDs."""
from __future__ import annotations
from itertools import combinations
import numpy as np
from .data import is_holdout, required_ids
from .remote_io import parquet_layout, MIB


def coverage_report(pf, pairs, *, budget_mib=512):
    """Read only item_id chunks; vector usability still requires real extraction.

    Choose a feasible group set using TRAINING pair counts only. Holdout counts
    are reported afterwards and never choose a group or a model hyperparameter.
    """
    layout = parquet_layout(pf)
    groups = layout['row_groups']
    if len(groups) > 63 or budget_mib != 512:
        raise ValueError('This bounded planner supports <=63 groups and the existing 512 MiB budget')
    wanted = required_ids(pairs)
    locations = {}
    id_bytes = 0
    for i in range(pf.num_row_groups):
        column = pf.metadata.row_group(i).column(0)
        if column.path_in_schema != 'item_id':
            raise ValueError('Expected item_id as the first Yambda column')
        id_bytes += column.total_compressed_size
        for batch in pf.iter_batches(batch_size=32768, row_groups=[i],
                                     columns=['item_id'], use_threads=False):
            for tid in batch.column(0).to_pylist():
                if tid in wanted:
                    if tid in locations:
                        raise ValueError('Duplicate required item ID in embedding table')
                    locations[tid] = i
    masks = []
    for pair in pairs:
        ids = required_ids([pair])
        masks.append(sum(1 << i for i in {locations[t] for t in ids})
                     if ids <= locations.keys() else 0)
    masks = np.asarray(masks, dtype=np.uint64)
    holdout = np.asarray([is_holdout(p['uid']) for p in pairs], dtype=bool)
    valid = masks != 0

    def snapshot(selected):
        mask = np.uint64(sum(1 << i for i in selected))
        covered = valid & ((masks & mask) == masks)
        train_users = {p['uid'] for p, ok, val in zip(pairs, covered, holdout) if ok and not val}
        holdout_users = {p['uid'] for p, ok, val in zip(pairs, covered, holdout) if ok and val}
        return {'groups': list(selected),
                'projected_vector_and_id_bytes': sum(groups[i]['compressed_bytes'] for i in selected),
                'structural_complete_pairs': int(covered.sum()),
                'train_pairs': int((covered & ~holdout).sum()),
                'holdout_pairs': int((covered & holdout).sum()),
                'train_users': len(train_users), 'holdout_users': len(holdout_users)}

    # Metadata cost bounds the largest feasible group count before enumeration.
    # ponytail: only one/two groups fit 512 MiB; review enumeration if layout changes.
    max_count = 0
    spent = MIB  # reserve footer/metadata traffic
    for group in sorted(groups, key=lambda g: g['compressed_bytes']):
        spent += group['compressed_bytes']
        if spent <= budget_mib*MIB:
            max_count += 1
    if max_count > 2:
        raise ValueError('Dataset layout changed; review bounded selection before enumerating')
    feasible = []
    structural_counts = []
    for count in range(1, max_count+1):
        for selected in combinations(range(len(groups)), count):
            cost = sum(groups[i]['compressed_bytes'] for i in selected)
            if cost+MIB <= budget_mib*MIB:
                mask = np.uint64(sum(1 << i for i in selected))
                train_count = int((valid & ~holdout & ((masks & mask) == masks)).sum())
                feasible.append((train_count, -cost, selected))
                structural_counts.append(int((valid & ((masks & mask) == masks)).sum()))
    best = max(feasible, key=lambda x: (x[0], x[1], tuple(-i for i in x[2]))) if feasible else None
    return {
        'interpretation': 'ID-only structural coverage, not validated vectors or trained-model metrics',
        'selection_rule': 'maximize training complete-pair count within 512 MiB; then minimize bytes; ordinal tie break',
        'dataset_rows': layout['rows'], 'dataset_row_groups': len(groups),
        'id_column_compressed_bytes': id_bytes,
        'pairs_in_source': len(pairs), 'required_ids': len(wanted),
        'required_ids_found': len(locations), 'required_ids_missing': len(wanted-locations.keys()),
        'pairs_missing_ids_even_after_full_scan': int((~valid).sum()),
        'full_projection_bytes': layout['projected_full_scan_bytes'],
        'single_group': [snapshot([i]) for i in range(len(groups))],
        'physical_prefix': [snapshot(range(i+1)) for i in range(len(groups))],
        'budget_mib': budget_mib, 'metadata_reserve_bytes': MIB,
        'feasible_group_sets': len(feasible),
        'max_structural_pairs_within_budget': max(structural_counts, default=0),
        'max_train_pairs_within_budget': max((f[0] for f in feasible), default=0),
        'best_within_budget': snapshot(best[2]) if best else None,
        'full_id_coverage': snapshot(range(len(groups))),
    }
