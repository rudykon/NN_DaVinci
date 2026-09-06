"""Local, weight-free Transformer corpus for import and semantic tests."""

from __future__ import annotations


def make_model():
    import torch

    class TinyTransformer(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embedding = torch.nn.Embedding(128, 32)
            layer = torch.nn.TransformerEncoderLayer(
                d_model=32, nhead=4, dim_feedforward=64, dropout=0.0, batch_first=True,
            )
            self.encoder = torch.nn.TransformerEncoder(layer, num_layers=2)
            self.head = torch.nn.Linear(32, 8)

        def forward(self, tokens):
            hidden = self.embedding(tokens)
            return self.head(self.encoder(hidden).mean(dim=1))

    return TinyTransformer()
