# docker-py — `Container.logs()`

**Source:** installed `docker` package **7.2.0** (source read, not online docs):
- `Container.logs` — `.venv/lib/python3.11/site-packages/docker/models/containers.py:294`
- `APIClient.logs` — `.venv/lib/python3.11/site-packages/docker/api/container.py:821`
- result shaping — `APIClient._get_result_tty` — `api/client.py:485`
- `CancellableStream` — `utils/socket.py`

**Captured:** 2026-09-14, for M2a behaviours 14–26.

---

## 1. Signature and argument names (verbatim) **[READ]**

`Container.logs(**kwargs)` (models/containers.py:294) forwards all kwargs to
`self.client.api.logs(self.id, **kwargs)` (line 323). The API signature
(api/container.py:821–823) is the authority:

```python
def logs(self, container, stdout=True, stderr=True, stream=False,
         timestamps=False, tail='all', since=None, follow=None,
         until=None): ...
```

| kwarg | default | verbatim doc |
| --- | --- | --- |
| `stdout` | `True` | *"Get STDOUT."* |
| `stderr` | `True` | *"Get STDERR."* |
| `stream` | `False` | *"Stream the response."* |
| `timestamps` | `False` | *"Show timestamps."* |
| `tail` | `'all'` | *"Output specified number of lines at the end of logs. Either an integer of number of lines or the string `all`."* Invalid ints (< 0, non-int) are silently **reset to `'all'`**, not an error (line 860–861) |
| `since` | `None` | *"Show logs since a given datetime, integer epoch (in seconds) or float"* — `InvalidArgument` if not a positive datetime/int/float (line 872–875) |
| `follow` | `None` | *"Follow log output."* — **`if follow is None: follow = stream`** (line 853–854). Passing `stream=True` therefore also follows; passing both is redundant but harmless |
| `until` | `None` | *"Show logs that occurred before the given datetime, integer epoch (in seconds), or float"* — requires **API ≥ 1.35** (`InvalidVersion` below, line 878–881) |

## 2. Returns: are lines `bytes`? **[READ]**

**Yes — always `bytes`, never `str`, and never decoded by the SDK.**

Docstrings (models/containers.py:316–317 and api/container.py:846–847):
*"(generator of bytes or bytes): Logs from the container."*

The code path confirms it (api/client.py:485–500, `_get_result_tty`):

- **Tty-enabled container** (`_check_is_tty` true): non-stream →
  `self._result(res, binary=True)` (raw bytes); stream →
  `_stream_raw_result(res)` (raw byte chunks). No demultiplexing.
- **Non-tty container**: the Engine multiplexes stdout/stderr with 8-byte
  headers; the SDK strips them via `_multiplexed_response_stream_helper`
  (stream) or `_multiplexed_buffer_helper` (non-stream, joined with `b''`).
  Either way the chunks are **`bytes`**.

So the caller must `.decode(...)` explicitly. Note the contrast with the
`run(detach=False)` path, which returns `b''.join(out)` — also bytes.

Streaming form:

```python
for chunk in container.logs(stream=True, follow=True, tail=200):
    # chunk is bytes (one or more log frames after header stripping)
```

The stream object returned when `stream=True` is a **`CancellableStream`**
(api/container.py:898–899, `utils/socket.py`) — an iterator that also exposes
`close()` to abort an open follow early. The docstring calls it *"a blocking
generator"* — iterating it **blocks until output arrives**; there is no
built-in per-chunk timeout (the `requests`-level timeout is what applies to
the open connection).

## 3. Details that bite in behaviours 14–26 **[READ]**

- **Default `tail='all'`** — an unbounded `logs()` call fetches the entire
  log of a long-lived tool container. Always pass `tail` when you only want
  the tail (or `since`).
- **`follow` silently equals `stream`** — `logs(stream=True)` follows
  forever; `logs(follow=False, stream=True)` is the explicit non-following
  streaming form (reads to the end of the current log and stops).
- **`tail` + `follow=True`** is valid: start streaming from the last N lines
  and keep following — the documented way to get "last 200 lines then live".
- **`timestamps=True`** changes the chunk encoding (timestamps prefixed) —
  decode logic must tolerate it.
- **No `max_bytes` / length cap exists** in the SDK — truncation is the
  caller's responsibility.
- `logs` raises `APIError` (api/container.py:850–852); `InvalidArgument` /
  `InvalidVersion` are raised client-side before any HTTP call.
