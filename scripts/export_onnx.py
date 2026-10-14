"""Export the two serving models to int8 ONNX + tokenizer files.

Needs torch, onnx, onnxruntime and `transformers<5` (v5's mask code does not
trace); the serving image does NOT need any of them -- the Dockerfile runs this
in a build stage and copies only the output directory.

    python scripts/export_onnx.py --out onnx_models
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

BGE = "BAAI/bge-base-en-v1.5"
CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _export(name: str, stem: str, pair_input: bool, out: Path) -> None:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(name)
    model = (AutoModelForSequenceClassification if pair_input else AutoModel).from_pretrained(name).eval()
    if pair_input:
        sample = tokenizer(["hello world"], ["a passage"], return_tensors="pt")
    else:
        sample = tokenizer(["hello world"], return_tensors="pt")
    names = [k for k in ("input_ids", "attention_mask", "token_type_ids") if k in sample]

    class Wrapper(torch.nn.Module):
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, *args):
            result = self.inner(**dict(zip(names, args)))
            return result.logits if pair_input else result.last_hidden_state

    fp32, int8 = out / f"{stem}.fp32.onnx", out / f"{stem}.onnx"
    torch.onnx.export(
        Wrapper(model), tuple(sample[k] for k in names), str(fp32), input_names=names, output_names=["out"],
        dynamic_axes={**{k: {0: "b", 1: "s"} for k in names}, "out": {0: "b"}}, opset_version=17, dynamo=False,
    )
    # Per-channel, and the embedding table too for BGE: the best of the int8
    # variants measured (embedding cosine vs torch >= 0.991 on the check
    # queries; default per-tensor dynamic quantization fell to 0.971).
    quantize_dynamic(
        str(fp32), str(int8), weight_type=QuantType.QInt8, per_channel=True,
        op_types_to_quantize=["MatMul"] if pair_input else ["MatMul", "Gather"],
    )
    os.remove(fp32)
    tokenizer.backend_tokenizer.save(str(out / f"{stem}.tokenizer.json"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("onnx_models"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    _export(BGE, "bge", pair_input=False, out=args.out)
    _export(CROSS_ENCODER, "ce", pair_input=True, out=args.out)
    for f in sorted(args.out.iterdir()):
        print(f"{f.name}  {f.stat().st_size // 2**20} MB")


if __name__ == "__main__":
    main()
