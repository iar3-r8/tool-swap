"""The build-form example tool: it upper-cases text.

Referenced indirectly by ``tools.example.yaml``'s ``example_build``
entry, whose ``build.context`` is this directory.  Nothing in M1 reads
this file — ``TSWAP-C515`` probes only the context directory and the
Dockerfile — but the directory would be a misleading example without the
handler its Dockerfile copies.
"""


class UpperHandler:
    """Upper-case each request's text."""

    def predict(self, batch: list[dict[str, str]]) -> list[dict[str, str]]:
        """Upper-case every item of the batch.

        Args:
            batch: One dict per request, each carrying ``text``.

        Returns:
            One dict per request, in the same order.
        """
        return [{"text": item["text"].upper()} for item in batch]
