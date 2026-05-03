"""ProvisioningJob — the unit of work written to a Storage Queue."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field


@dataclass
class ProvisioningJob:
    """Serialisable description of a single subscription provisioning run."""

    subscription_id: str
    subscription_name: str = ""
    management_group_id: str = ""
    attempt: int = 1
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_json(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "subscription_id": self.subscription_id,
                "subscription_name": self.subscription_name,
                "management_group_id": self.management_group_id,
                "attempt": self.attempt,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "ProvisioningJob":
        data = json.loads(raw)
        return cls(
            job_id=data.get("job_id", str(uuid.uuid4())),
            subscription_id=data["subscription_id"],
            subscription_name=data.get("subscription_name", ""),
            management_group_id=data.get("management_group_id", ""),
            attempt=data.get("attempt", 1),
        )
