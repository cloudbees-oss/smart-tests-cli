from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddingOptions:
    """The `embedding` block of GET commits/collect/options."""
    mode: str  # "server" or "client". Always sent by the backend.
    # The fields below are only populated when mode == "client".
    model_id: int | None = None
    provider: str | None = None
    model_name: str | None = None
    dimensions: int | None = None
    canonical_id: int | None = None

    @property
    def is_client_mode(self) -> bool:
        return self.mode == "client"

    @classmethod
    def from_collect_options(cls, options: dict[str, Any]) -> "EmbeddingOptions | None":
        """Returns None if the server didn't send an `embedding` block (older server)."""
        e = options.get("embedding")
        if not e:
            return None
        return cls(
            mode=e["mode"],
            model_id=e.get("modelId"),
            provider=e.get("provider"),
            model_name=e.get("modelName"),
            dimensions=e.get("dimensions"),
            canonical_id=e.get("canonicalId"),
        )
