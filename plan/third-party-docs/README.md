# Third-party documentation captures

Local copies of external documentation that the plan's evaluations depend on, so that claims made in [`plan/`](../) can be checked without re-crawling, and so that quotations remain verifiable if the upstream page changes or its version moves.

## Contents

| Directory | Upstream | Version captured | Why it is here |
| --- | --- | --- | --- |
| [`ray-serve/`](ray-serve/INDEX.md) | https://docs.ray.io/en/latest/serve/ | Ray 2.57.0 | Evidence base for [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) and [`ADR-0003`](../adr/0003-ray-serve-not-adopted.md) |
| [`ray-core/`](ray-core/runtime-env-excerpt.md) | https://docs.ray.io/en/latest/ray-core/ | Ray 2.57.0 | The `runtime_env` / `image_uri` reference that **D2** would depend on |

Start with [`ray-serve/INDEX.md`](ray-serve/INDEX.md): it catalogues every page in the Ray Serve section, captured or not, and records which findings post-date the evaluation document.

## Conventions

Each captured file begins with a header giving:

- the **source URL**,
- the **upstream version** at capture and the **capture date**,
- a one-line statement of **relevance to tool-swap**,
- an explicit note if the capture is **condensed** or an **excerpt** rather than complete.

Each file ends with a **tool-swap notes** section separating what the source says from what we conclude from it. Upstream prose and code are verbatim; only navigation chrome, banners and image markup are stripped, and admonitions are rendered as blockquotes. **Text outside the notes sections can be quoted as the vendor's own words.**

## Rules of use

1. **These are snapshots, not the truth.** Upstream moves. Before a captured fact is used to decide something, check the version in the header, and re-verify anything marked *experimental* or *alpha*.
2. **Do not edit the captured prose.** Corrections and disagreements belong in the tool-swap notes section, or in the plan document that cites it.
3. **Record what was skipped.** The catalogue lists uncaptured pages and their contents, so that "not considered" is distinguishable from "considered and set aside".
4. **Attribute clearly.** These are third-party materials reproduced for internal technical evaluation; they retain their original authorship and licensing.

## Capture tooling

Pages were fetched with the Oxylabs MCP `universal_scraper` tool in markdown mode. The Oxylabs **AI Studio** tools (`ai_crawler`, `ai_map`) would do this in bulk but require `OXYLABS_AI_STUDIO_API_KEY`, which [`.roo/mcp.json`](../../.roo/mcp.json) does not currently set — see §4 of [`ray-serve/INDEX.md`](ray-serve/INDEX.md).
