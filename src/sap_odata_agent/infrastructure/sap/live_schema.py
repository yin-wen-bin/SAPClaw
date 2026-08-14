from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sap_odata_agent.infrastructure.indexing.dual_source_index_builder import SapMetadataParser


@dataclass(slots=True)
class LiveSchemaSnapshot:
    service_name: str
    entities: dict[str, set[str]]
    key_fields: dict[str, set[str]]
    sortable_fields: dict[str, set[str]]
    metadata_fingerprint: str
    checked_at: str
    fetched_at: float


@dataclass(slots=True)
class LiveSchemaOverlay:
    service_name: str
    runtime_schema_source: str
    stale: bool
    snapshot: LiveSchemaSnapshot | None
    error: str = ""


class LiveSchemaProvider:
    """Read-only, bounded-cache provider for the SAP service runtime schema."""

    def __init__(
        self,
        *,
        fetch_metadata: Callable[[str], tuple[str, str]],
        fresh_ttl_seconds: int = 300,
        max_stale_seconds: int = 86400,
        clock: Callable[[], float] = time.time,
        parser: SapMetadataParser | None = None,
    ) -> None:
        self.fetch_metadata = fetch_metadata
        self.fresh_ttl_seconds = max(0, fresh_ttl_seconds)
        self.max_stale_seconds = max(self.fresh_ttl_seconds, max_stale_seconds)
        self.clock = clock
        self.parser = parser or SapMetadataParser()
        self._cache: dict[str, LiveSchemaSnapshot] = {}

    def get(self, service_name: str, *, force_refresh: bool = False) -> LiveSchemaOverlay:
        now = self.clock()
        cached = self._cache.get(service_name)
        if cached is not None and not force_refresh and now - cached.fetched_at <= self.fresh_ttl_seconds:
            return LiveSchemaOverlay(service_name, "cache", False, cached)

        try:
            xml_text, metadata_url = self.fetch_metadata(service_name)
            parsed = self.parser.parse(xml_text, service_name, metadata_url)
            entity_fields: dict[str, set[str]] = {
                item.entity_set: set() for item in parsed.entities
            }
            entity_keys = {
                item.entity_set: set(item.key_fields) for item in parsed.entities
            }
            sortable_fields: dict[str, set[str]] = {
                item.entity_set: set() for item in parsed.entities
            }
            for field in parsed.fields:
                entity_fields.setdefault(field.entity_set, set()).add(field.field_name)
                if field.sortable:
                    sortable_fields.setdefault(field.entity_set, set()).add(field.field_name)
            snapshot = LiveSchemaSnapshot(
                service_name=service_name,
                entities=entity_fields,
                key_fields=entity_keys,
                sortable_fields=sortable_fields,
                metadata_fingerprint=hashlib.sha256(xml_text.encode("utf-8")).hexdigest(),
                checked_at=datetime.now(timezone.utc).isoformat(),
                fetched_at=now,
            )
            self._cache[service_name] = snapshot
            return LiveSchemaOverlay(service_name, "live", False, snapshot)
        except Exception as exc:  # cache fallback is the runtime safety boundary
            if cached is not None and now - cached.fetched_at <= self.max_stale_seconds:
                return LiveSchemaOverlay(service_name, "cache", True, cached, str(exc))
            return LiveSchemaOverlay(service_name, "none", False, None, str(exc))

    def invalidate(self, service_name: str) -> None:
        cached = self._cache.get(service_name)
        if cached is not None:
            cached.fetched_at = 0.0

    def seed(self, snapshot: LiveSchemaSnapshot) -> None:
        """Seed a trusted cache snapshot (primarily for deterministic tests)."""

        self._cache[snapshot.service_name] = snapshot
