"""Error taxonomy for the container backend seam (M2a behaviour 9).

This module holds the seven exception classes the container backend
raises: the six concrete failure classes of plan §4.3
(``plans/m2a-container-backend-seam.md``) plus the base, which doubles
as the fallback for an unrecognised SDK exception.  ``BackendError``
derives from ``Exception`` and the six concrete classes derive from
``BackendError``, so the taxonomy is a single catch point and a closed
seam — the module exposes no exception type outside the seven.

Every member carries a human ``message`` and an actionable ``remedy``.
The message states what went wrong — M2b's ``FAILED`` reason reuses it
verbatim ("M2b formats it, it does not invent it", plan §6 item 6) —
and the remedy is the user's next step, surfaced to a user in
``/status``.  An omitted remedy resolves to the class's own non-empty
default, so a message-only construction still renders usefully; an
explicitly blank remedy raises ``ValueError`` so that non-emptiness is
a construction-time invariant, not a property of the defaults alone.
"""

from __future__ import annotations


class BackendError(Exception):
    """Base of the backend error taxonomy; also the fallback for an
    unrecognised SDK exception (plan §4.3).
    """

    _DEFAULT_REMEDY = (
        "The message carries the underlying error text — inspect it, and "
        "report the failure if it does not match a known backend error."
    )

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        """Store the failure and resolve the effective remedy.

        Args:
            message: What went wrong — the value M2b's ``FAILED``
                reason reuses verbatim.
            remedy: The user's next step, surfaced in ``/status``.
                Keyword-only: ``message`` and ``remedy`` are
                interchangeable strings, so a positional remedy would
                be a silently swapped message.  When omitted, the
                class's own non-empty default remedy is used.

        Raises:
            ValueError: ``remedy`` is provided but empty or
                whitespace-only — a blank remedy leaves a user at a
                dead tool with no next step, so it is rejected at
                construction rather than stored.
        """
        if remedy is not None and not remedy.strip():
            raise ValueError(
                "remedy must not be empty or whitespace-only; omit it "
                "to use the class's default remedy"
            )
        self.message = message
        self.remedy = remedy if remedy is not None else self._DEFAULT_REMEDY
        super().__init__(self.message, self.remedy)

    def __str__(self) -> str:
        """Render both the message and the effective remedy.

        The ``/status`` consumer reads this string, so the remedy is
        part of the rendering even when the caller omitted it.
        """
        return f"{self.message} (remedy: {self.remedy})"


class BackendUnavailableError(BackendError):
    """Raised when the container daemon is unreachable."""

    _DEFAULT_REMEDY = (
        "Check that the container daemon is running and reachable, and "
        "that DOCKER_HOST names the daemon tool-swap is configured to use."
    )


class ImageNotFoundError(BackendError):
    """Raised when the image reference does not exist."""

    _DEFAULT_REMEDY = (
        "The image reference named in the message does not exist — "
        "build it with `tswap build <tool>`."
    )


class ContainerNameConflictError(BackendError):
    """Raised when the container name is already taken."""

    _DEFAULT_REMEDY = (
        "The container name named in the message is already taken — "
        "free it with `tswap down`."
    )


class ContainerStartError(BackendError):
    """Raised when the daemon refused the start for another reason."""

    _DEFAULT_REMEDY = (
        "See the underlying error text in the message for why the daemon "
        "refused the start."
    )


class ContainerNotFoundError(BackendError):
    """Raised when the container has vanished."""

    _DEFAULT_REMEDY = (
        "The container was removed out of band, outside tool-swap's "
        "control — start the tool again."
    )


class GpuUnavailableError(BackendError):
    """Raised when a GPU device request could not be satisfied."""

    _DEFAULT_REMEDY = (
        "Install or repair the NVIDIA container toolkit so the requested "
        "GPU device can be satisfied."
    )
