"""Container image availability preflight for deployments."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from aftwin.runtime.executor import (
    CommandExecutionError,
    CommandExecutor,
    CommandFailureKind,
)


class ImagePreflight(Protocol):
    """Deployment-time boundary answering which images cannot be provided."""

    def missing_images(self, images: Sequence[str]) -> tuple[str, ...]:
        """Return every image that is neither present locally nor obtainable."""
        ...


class DockerImagePreflight:
    """Resolve image availability through the local Docker daemon."""

    def __init__(
        self,
        executor: CommandExecutor,
        *,
        executable: str = "docker",
        inspect_timeout_seconds: float = 30.0,
        pull_timeout_seconds: float = 600.0,
        pull_missing: bool = True,
    ) -> None:
        if not executable:
            raise ValueError("executable must not be empty")
        if inspect_timeout_seconds <= 0 or pull_timeout_seconds <= 0:
            raise ValueError("image preflight timeouts must be positive")
        self._executor = executor
        self._executable = executable
        self._inspect_timeout_seconds = inspect_timeout_seconds
        self._pull_timeout_seconds = pull_timeout_seconds
        self._pull_missing = pull_missing

    def missing_images(self, images: Sequence[str]) -> tuple[str, ...]:
        """Check local presence first and fall back to one pull attempt."""
        missing: list[str] = []
        for image in dict.fromkeys(images):
            if self._image_is_local(image):
                continue
            if self._pull_missing and self._pull(image):
                continue
            missing.append(image)
        return tuple(missing)

    def _image_is_local(self, image: str) -> bool:
        return self._run_availability_probe(
            [self._executable, "image", "inspect", image],
            timeout_seconds=self._inspect_timeout_seconds,
        )

    def _pull(self, image: str) -> bool:
        return self._run_availability_probe(
            [self._executable, "pull", image],
            timeout_seconds=self._pull_timeout_seconds,
        )

    def _run_availability_probe(self, argv: list[str], *, timeout_seconds: float) -> bool:
        """Treat only a clean non-zero exit as unavailability evidence."""
        try:
            self._executor.run(argv, timeout_seconds=timeout_seconds)
        except CommandExecutionError as error:
            if error.kind is CommandFailureKind.NON_ZERO_EXIT:
                return False
            raise
        return True
