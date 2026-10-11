"""Explicit GPU-only extraction from a reviewed local snapshot; no downloads."""
import os
from pathlib import Path
import time
import numpy as np

from .data import SCHEMA, digest, file_hash, is_hash, require, validate_manifest
from .features import load_window
from .model import ENCODER_ID, POOLING


def check_snapshot(path, receipt):
    root = Path(path).resolve(strict=True)
    require(receipt.get("id") == ENCODER_ID and receipt.get("weights_license") == "CC-BY-NC-4.0" and
            receipt.get("reviewed_code") is True, "Reviewed model license/code receipt required")
    revision = receipt.get("revision", "")
    require(len(revision) == 40 and all(c in "0123456789abcdef" for c in revision), "Pinned model revision required")
    files = receipt.get("files", {})
    require(isinstance(files, dict) and "config.json" in files and "preprocessor_config.json" in files and
            any(n.endswith(".safetensors") for n in files), "Need a complete safetensors snapshot")
    for name, expected in files.items():
        target = (root / name).resolve(strict=True)
        require(target.is_relative_to(root) and target.is_file() and is_hash(expected), "Unsafe snapshot file")
        require(file_hash(target) == expected, "Snapshot checksum mismatch")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    require(actual == set(files), "Unlisted snapshot files; review the complete snapshot")
    return root


def extract_embeddings(manifest, snapshot, receipt, *, authorized_remote=False, trust_reviewed_code=False):
    require(authorized_remote and trust_reviewed_code, "Explicit remote execution and reviewed-code flags required")
    validate_manifest(manifest, purpose="remote", verify_files=True)
    root = check_snapshot(snapshot, receipt)
    # Offline switches also apply to custom code's Hugging Face helpers.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    import torch
    from transformers import AutoModel, Wav2Vec2FeatureExtractor
    require(torch.cuda.is_available(), "GPU worker required; no owner-laptop fallback")
    torch.manual_seed(20261011)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_num_threads(2)
    processor = Wav2Vec2FeatureExtractor.from_pretrained(str(root), local_files_only=True)
    require(processor.sampling_rate == 24000, "Unexpected MERT sample rate")
    model = AutoModel.from_pretrained(str(root), local_files_only=True,
                                     trust_remote_code=True, use_safetensors=True)
    model.eval().requires_grad_(False).to("cuda")
    start = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    records = []
    with torch.inference_mode():
        for t in manifest["tracks"]:
            y = load_window(t, sr=24000)
            pooled = []
            # One fixed 5s window at a time bounds attention memory.
            for offset in range(0, len(y) - 5 * 24000 + 1, 5 * 24000):
                chunk = y[offset:offset + 5 * 24000]
                inputs = processor(chunk, sampling_rate=24000, return_tensors="pt")
                hidden = model(**{k: v.to("cuda") for k, v in inputs.items()}).last_hidden_state[0].float()
                pooled.append(torch.cat((hidden.mean(0), hidden.std(0, unbiased=False))).cpu().numpy())
            require(pooled, "No complete encoder windows")
            embedding = np.mean(pooled, axis=0)
            require(embedding.shape == (1536,) and np.isfinite(embedding).all(), "Unexpected MERT output")
            require(file_hash(t["path"]) == t["sha256"], "Audio changed during embedding extraction")
            records.append({"id": t["id"], "sha256": t["sha256"], "embedding": embedding.tolist()})
    torch.cuda.synchronize()
    return {"schema": SCHEMA, "kind": manifest["kind"], "dataset_sha256": digest(manifest),
            "encoder": {"id": ENCODER_ID, "revision": receipt["revision"],
                        "snapshot_sha256": digest(receipt), "weights_license": receipt["weights_license"],
                        "pooling": POOLING, "dimension": 1536, "frozen": True},
            "runtime": {"seconds": time.perf_counter() - start,
                        "peak_cuda_bytes": torch.cuda.max_memory_allocated(),
                        "device": torch.cuda.get_device_name(), "torch": torch.__version__,
                        "audio_seconds": sum(t["seconds"] for t in manifest["tracks"])},
            "tracks": records}
