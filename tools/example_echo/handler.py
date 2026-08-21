"""The dependency-free example tool: it echoes its input back.

Used by behaviour 23's golden-path test and by ``tools.example.yaml``
(behaviour 24).  M1 never imports this file — ``TSWAP-C513`` only probes
that it exists — so it is deliberately trivial; the batched calling
convention it follows is ADR-0005's (every handler takes and returns a
list).
"""


class EchoHandler:
    """Return each request unchanged."""

    def predict(self, batch: list[dict[str, str]]) -> list[dict[str, str]]:
        """Echo every item of the batch.

        Args:
            batch: One dict per request, each carrying ``text``.

        Returns:
            One dict per request, in the same order.
        """
        return [{"text": item["text"]} for item in batch]
