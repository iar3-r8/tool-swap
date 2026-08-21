"""The inline-handler example tool: it adds two numbers.

Referenced by ``tools.example.yaml``'s ``example_add`` entry, which
declares this file with an inline ``handler:`` and its own
``requirements:`` — the form with no ``tool.yaml`` at all.  M1 never
imports this file (``TSWAP-C513`` only probes that it exists), so it is
deliberately trivial; the calling convention it follows is ADR-0005's:
every handler takes and returns a list.
"""


class AddHandler:
    """Return the sum of each request's two numbers."""

    def predict(self, batch: list[dict[str, float]]) -> list[dict[str, float]]:
        """Add ``a`` and ``b`` for every item of the batch.

        Args:
            batch: One dict per request, each carrying ``a`` and ``b``.

        Returns:
            One dict per request, in the same order.
        """
        return [{"sum": item["a"] + item["b"]} for item in batch]
