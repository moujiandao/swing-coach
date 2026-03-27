# RQ task: orchestrates the full analysis pipeline
# Implemented in Task 1.3+
import logging

logger = logging.getLogger(__name__)


def run_analysis(analysis_id: str) -> None:
    """Entry point for RQ worker. Runs the full CV + feedback pipeline."""
    raise NotImplementedError("Implemented in Task 1.3")
