"""Small CPU-only models used by NN_DaVinci examples and runtime verification."""

import torch
from torch import nn


class TinyResidualCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = nn.Conv2d(3, 8, 3, padding=1)
        self.conv = nn.Conv2d(8, 8, 3, padding=1)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Linear(8, 4)

    def forward(self, x):
        skip = torch.relu(self.stem(x))
        features = self.conv(skip)
        # The data-dependent branch intentionally exercises runtime fallback.
        if bool((features.mean() > -100).item()):
            features = torch.relu(features + skip)
        return self.head(self.pool(features).flatten(1))


class TinyStaticCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 6, 3, padding=1)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Linear(6, 3)

    def forward(self, x):
        return self.head(self.pool(torch.relu(self.conv(x))).flatten(1))


def make_model():
    torch.manual_seed(7)
    return TinyResidualCNN().eval()


def make_static_model():
    torch.manual_seed(7)
    return TinyStaticCNN().eval()

