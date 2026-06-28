"""
Redis-based UE state manager.

Stores per-UE state as Redis hashes under the key pattern `ue:{ue_index}`.
Events are stored as a Redis list under `ue:{ue_index}:events`.
"""

import json
import time
from typing import Any, Dict, List, Optional

import redis
from loguru import logger


class RedisUEManager:
    """Manages UE state in Redis for cross-module access."""

    KEY_PREFIX = "ue:"
    EVENTS_SUFFIX = ":events"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        password: Optional[str] = None,
        db: int = 0,
    ):
        self._client = redis.Redis(
            host=host,
            port=port,
            password=password or None,
            db=db,
            decode_responses=True,
            socket_connect_timeout=5,
        )
        # Quick connectivity check
        try:
            self._client.ping()
            logger.info(f"Redis connected at {host}:{port} db={db}")
        except redis.ConnectionError as e:
            logger.error(f"Redis connection failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _ue_key(self, ue_index: int) -> str:
        return f"{self.KEY_PREFIX}{ue_index}"

    def _events_key(self, ue_index: int) -> str:
        return f"{self.KEY_PREFIX}{ue_index}{self.EVENTS_SUFFIX}"

    # ------------------------------------------------------------------
    # UE CRUD
    # ------------------------------------------------------------------

    def set_ue(self, ue_index: int, data: Dict[str, Any]) -> None:
        """Write / overwrite all fields for a UE."""
        key = self._ue_key(ue_index)
        payload: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                payload[k] = json.dumps(v)
            elif v is None:
                payload[k] = ""
            else:
                payload[k] = str(v)
        self._client.hset(key, mapping=payload)

    def update_ue(self, ue_index: int, data: Dict[str, Any]) -> None:
        """Update specific fields without overwriting the entire hash."""
        key = self._ue_key(ue_index)
        payload: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                payload[k] = json.dumps(v)
            elif v is None:
                payload[k] = ""
            else:
                payload[k] = str(v)
        self._client.hset(key, mapping=payload)

    def get_ue(self, ue_index: int) -> Optional[Dict[str, Any]]:
        """Return the full hash for a UE, or None if missing."""
        key = self._ue_key(ue_index)
        raw = self._client.hgetall(key)
        if not raw:
            return None
        return self._decode_ue(raw)

    def get_all_ues(self) -> List[Dict[str, Any]]:
        """Return all UEs sorted by index."""
        keys = sorted(
            self._client.keys(f"{self.KEY_PREFIX}*"),
            key=lambda k: int(k.split(":")[-1]) if k.split(":")[-1].isdigit() else 0,
        )
        results: List[Dict[str, Any]] = []
        for key in keys:
            if key.endswith(self.EVENTS_SUFFIX):
                continue
            raw = self._client.hgetall(key)
            if raw:
                ue = self._decode_ue(raw)
                # Attach index from key
                try:
                    ue["_index"] = int(key.split(":")[-1])
                except ValueError:
                    pass
                results.append(ue)
        return results

    def remove_ue(self, ue_index: int) -> None:
        """Delete a UE hash and its events list."""
        self._client.delete(self._ue_key(ue_index))
        self._client.delete(self._events_key(ue_index))

    def clear_all(self) -> None:
        """Delete all UE keys managed by this instance."""
        keys = self._client.keys(f"{self.KEY_PREFIX}*")
        if keys:
            self._client.delete(*keys)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def append_event(self, ue_index: int, event_type: str, detail: str = "") -> None:
        """Append a timestamped event to the UE's event list."""
        entry = {
            "ts": round(time.time() * 1000),
            "type": event_type,
            "detail": detail,
        }
        self._client.rpush(self._events_key(ue_index), json.dumps(entry))

    def get_events(self, ue_index: int) -> List[Dict[str, Any]]:
        """Return all events for a UE in chronological order."""
        raw_list = self._client.lrange(self._events_key(ue_index), 0, -1)
        events: List[Dict[str, Any]] = []
        for raw in raw_list:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_ue(raw: Dict[str, str]) -> Dict[str, Any]:
        """Decode Redis hash values back to Python types where possible."""
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            if v == "":
                out[k] = None
            else:
                # Try JSON parse for complex fields
                try:
                    out[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    # Try int / float
                    try:
                        out[k] = int(v)
                    except ValueError:
                        try:
                            out[k] = float(v)
                        except ValueError:
                            out[k] = v
        return out
