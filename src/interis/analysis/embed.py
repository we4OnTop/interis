"""Multilingual sentence embeddings (intfloat/multilingual-e5-base) via transformers.

Implemented directly (mean pooling + L2 normalisation, as documented for E5) instead of
pulling in sentence-transformers. E5 expects the prefixes "query: " / "passage: ".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from interis._bootstrap import require_offline


class Encoder:
    def __init__(self, model_dir: Path, threads: int | None = None) -> None:
        require_offline()
        import torch
        from transformers import AutoModel, AutoTokenizer

        if threads:
            torch.set_num_threads(threads)
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        self.model = AutoModel.from_pretrained(model_dir, local_files_only=True,
                                               use_safetensors=True).eval()

    def encode(self, texts: list[str], prefix: str = "query: ",
               batch_size: int = 32) -> np.ndarray:
        torch = self._torch
        if not texts:
            return np.zeros((0, self.model.config.hidden_size), dtype=np.float32)
        out = []
        for i in range(0, len(texts), batch_size):
            batch = [prefix + t for t in texts[i:i + batch_size]]
            enc = self.tokenizer(batch, padding=True, truncation=True, max_length=512,
                                 return_tensors="pt")
            with torch.inference_mode():
                hidden = self.model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
            out.append(torch.nn.functional.normalize(pooled, dim=-1).numpy())
        return np.vstack(out)
