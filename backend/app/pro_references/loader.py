"""
Pro reference swing database — load, query, and save pre-computed feature data.

Files are stored as .npz archives under app/pro_references/data/.
Key format: "{player}_{stroke_type}", e.g. "federer_forehand".
"""
import logging
from pathlib import Path

import numpy as np

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
        """Return list of {player, stroke_type} dicts for all loaded references."""
        return [
            {"player": v["player"], "stroke_type": v["stroke_type"]}
            for v in self.references.values()
        ]
