# The Level 4 form of plan/03_TOOL_AUTHORING.md §7: the author supplies the
# Dockerfile, and it speaks our protocol by installing tool-swap-runtime.
# M1 never builds this image — TSWAP-C515 only probes that this file and its
# context directory exist — so it is kept minimal and readable.
FROM python:3.11-slim

WORKDIR /app

# The runtime distribution is what makes an author-built image ours: it
# provides the server that loads the handler and speaks the batched protocol.
RUN pip install --no-cache-dir tool-swap-runtime

COPY handler.py /app/handler.py

CMD ["python", "-m", "tool_swap_runtime"]
