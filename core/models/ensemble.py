"""Ensemble: simple average of the top 2–3 validated pipelines. Offered only
when their MASE values are within ~10% of each other — averaging similar
performers cancels their individual errors."""
from __future__ import annotations

import numpy as np

from core.models.base import BaseModel


class Ensemble(BaseModel):
    name = "Ensemble"

    def __init__(self, members: list[BaseModel]):
        super().__init__()
        if len(members) < 2:
            raise ValueError("an ensemble needs at least two members")
        self.members = members
        self.n_params = sum(m.n_params for m in members)
        self.min_history = max(m.min_history for m in members)
        self.interval_grows = any(m.interval_grows for m in members)

    def _fit(self, y, driver, period_index):
        # members are already fitted by the selection layer; fit them here
        # only if they have not seen data yet
        for m in self.members:
            if m.y_ is None:
                m.fit(y, driver, period_index)

    def predict(self, horizon):
        return np.mean([m.predict(horizon) for m in self.members], axis=0)

    def fitted_values(self):
        return np.nanmean([m.fitted_values() for m in self.members], axis=0)

    def params(self):
        return {"members": [m.name for m in self.members]}

    def explain(self):
        names = ", ".join(m.name for m in self.members)
        return (f"Several models performed almost equally well ({names}); "
                "averaging them is more stable than trusting any single one.")
