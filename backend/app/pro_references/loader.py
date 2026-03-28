"""
Pro reference swing database — load, query, and save pre-computed feature data.

Files are stored as .npz archives under app/pro_references/data/.
Key format: "{player}_{stroke_type}", e.g. "federer_forehand".

DB-backed methods (get_by_id, list_available_from_db) query the pro_references
table for status="ready" records and load the .npz from the stored npz_path.
The old file-scan methods (load_all, get_reference, list_available) are kept
as a fallback and are deprecated — prefer the DB-backed methods for new code.
"""
import logging
import uuid
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).parent / "data"


def save_reference(
    player: str,
    stroke_type: str,
    joint_angles: dict[str, np.ndarray],
    phases: dict[str, tuple[int, int]],
    metadata: dict | None = None,
    data_dir: str | Path | None = None,
) -> Path:
    """
    Persist a pro reference swing as a .npz file.

    Called by build_pro_references.py and generate_synthetic_reference.py.
    Returns the path to the saved file.
    """
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)

    key = f"{player}_{stroke_type}"
    out_path = data_dir / f"{key}.npz"

    # Flatten phases dict to two arrays for npz storage
    phase_keys = list(phases.keys())
    phase_values = np.array([list(v) for v in phases.values()], dtype=np.int32)

    save_dict: dict[str, object] = {
        "_player": player,
        "_stroke_type": stroke_type,
        "_phase_keys": np.array(phase_keys),
        "_phase_values": phase_values,
    }
    for angle_name, arr in joint_angles.items():
        save_dict[f"angle_{angle_name}"] = arr
    if metadata:
        for k, v in metadata.items():
            save_dict[f"meta_{k}"] = np.array(v) if not isinstance(v, np.ndarray) else v

    np.savez(out_path, **save_dict)
    logger.info("Saved reference %s → %s", key, out_path)
    return out_path


class ProReferenceDB:
    """Loads and manages pre-computed professional swing feature data."""

    def __init__(self, data_dir: str | Path | None = None):
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.references: dict[str, dict] = {}

    def load_all(self) -> None:
        """Load all .npz files from data_dir into memory."""
        npz_files = list(self._data_dir.glob("*.npz"))
        if not npz_files:
            logger.warning("No .npz reference files found in %s", self._data_dir)
            return

        for path in npz_files:
            self._load_file(path)

        logger.info("Loaded %d pro reference(s) from %s", len(self.references), self._data_dir)

    def _load_file(self, path: Path) -> None:
        data = np.load(path, allow_pickle=False)

        player = str(data["_player"])
        stroke_type = str(data["_stroke_type"])

        # Reconstruct phases dict
        phase_keys = [str(k) for k in data["_phase_keys"]]
        phase_values = data["_phase_values"]
        phases = {k: (int(phase_values[i, 0]), int(phase_values[i, 1])) for i, k in enumerate(phase_keys)}

        # Reconstruct joint_angles dict
        joint_angles: dict[str, np.ndarray] = {}
        for key in data.files:
            if key.startswith("angle_"):
                angle_name = key[len("angle_"):]
                joint_angles[angle_name] = data[key]

        # Reconstruct metadata dict
        metadata: dict = {}
        for key in data.files:
            if key.startswith("meta_"):
                meta_key = key[len("meta_"):]
                metadata[meta_key] = data[key]

        ref_key = f"{player}_{stroke_type}"
        self.references[ref_key] = {
            "player": player,
            "stroke_type": stroke_type,
            "joint_angles": joint_angles,
            "phases": phases,
            "metadata": metadata,
        }
        logger.debug("Loaded reference: %s", ref_key)

    def get_reference(self, player: str, stroke_type: str) -> dict | None:
        """Return the reference dict for (player, stroke_type), or None if not found."""
        return self.references.get(f"{player}_{stroke_type}")

    def list_available(self) -> list[dict]:
        """
        Return list of {player, stroke_type} dicts for all file-scan loaded references.

        .. deprecated::
            Use list_available_from_db() for new code. This file-scan fallback
            will be removed once the DB is the authoritative source.
        """
        warnings.warn(
            "list_available() uses the deprecated file-scan path. "
            "Use list_available_from_db(session) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return [
            {"player": v["player"], "stroke_type": v["stroke_type"]}
            for v in self.references.values()
        ]

    # ------------------------------------------------------------------
    # DB-backed methods (preferred over file-scan fallback)
    # ------------------------------------------------------------------

    async def get_by_id(self, session: "AsyncSession", ref_id: uuid.UUID) -> dict | None:
        """
        Load a pro reference by its DB UUID.

        Queries the pro_references table for a ready record, then loads
        the .npz from its npz_path. Returns the same dict structure as
        _load_file(), or None if not found / not ready.
        """
        from sqlalchemy import select
        from app.models import ProReference, ProReferenceStatus

        result = await session.execute(
            select(ProReference).where(
                ProReference.id == ref_id,
                ProReference.status == ProReferenceStatus.ready,
            )
        )
        record = result.scalar_one_or_none()
        if record is None or not record.npz_path:
            return None

        path = Path(record.npz_path)
        if not path.exists():
            logger.warning("npz_path does not exist on disk: %s", path)
            return None

        self._load_file(path)
        key = f"{record.player_name}_{record.stroke_type.value}"
        return self.references.get(key)

    async def list_available_from_db(self, session: "AsyncSession") -> list:
        """
        Return ProReferenceListItem instances for all ready DB records.

        This is the DB-backed replacement for the deprecated list_available().
        """
        from sqlalchemy import select
        from app.models import ProReference, ProReferenceListItem, ProReferenceStatus

        result = await session.execute(
            select(ProReference).where(ProReference.status == ProReferenceStatus.ready)
        )
        records = result.scalars().all()
        return [ProReferenceListItem.model_validate(r) for r in records]
