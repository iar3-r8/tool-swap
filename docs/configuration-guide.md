# Configuration guide

Let's build a tool-swap config together, starting from the smallest one
that works and growing it until it describes a real multi-GPU deployment.
As we go, you'll see how little you have to write and how much the router
does for you. If you ever need the exact type or default of a key, the
generated [Configuration reference](configuration.md) has every one of
them, generated from the schema so it never drifts from the code.

## Start with three lines

This is a complete, working config:

```yaml
# tools.yaml
tools:
  example_echo:
    path: ./tools/example_echo
```

That's it. `path:` points at a directory, and the directory holds the
tool's own `tool.yaml`, where the tool describes itself. The committed
[`tools/example_echo/tool.yaml`](../tools/example_echo/tool.yaml) is a
good model:

```yaml
name: example_echo
version: "0.1.0"
description: Echo the text you send it back, unchanged.
handler: handler.py:EchoHandler

runtime:
  requirements: requirements.txt

inputs:
  - name: text
    type: string
    description: The text to echo back, unchanged.
```

Notice what the tool is telling the agent here. The `description` is
required, and it matters: it's the text an LLM reads when deciding
whether to call this tool. The `inputs:` block declares what a request
carries, and your handler receives each input as a keyword argument.
Tool-swap batches requests, so handlers take and return lists, and one
uniform calling convention covers every tool.

Everything you didn't write has a default: the router listens on port
8600, idle tools stop after 900 seconds, requests are batched up to eight
at a time. You write only what you want to change. That's the design
promise of this file, and it scales: the same file that holds one echo
tool holds a fleet of models on several GPUs.

## Check your work

Before running anything, ask the router itself:

```bash
tswap validate
```

It loads, resolves and checks the whole file in one pass. Exit 0 means
you're good, and any warnings go to stderr. When something is wrong, each
diagnostic names the problem with a code like `TSWAP-C510`, points at
the exact spot (say `tools.example_echo.ttl`), and suggests the fix.
Those codes are the keys to the [troubleshooting
table](configuration.md#troubleshooting-every-diagnostic-code), which
covers every code the router can emit. In CI, add `--strict` to fail on
warnings too, or `--json` for a machine-readable report.

## Three ways to define a tool

The committed [`tools.example.yaml`](../tools.example.yaml) shows all
three forms, one per example tool, and they suit different situations.

The usual path is the directory with a `tool.yaml`, as above. You name
the directory, and the description, handler and inputs come along with
it. This is what a tool author ships, and it keeps each tool self
contained.

For a quick tool, you can write everything inline, with no separate
`tool.yaml` at all:

```yaml
tools:
  example_add:
    handler: ./tools/example_add/handler.py:AddHandler
    requirements: ./tools/example_add/requirements.txt
    description: Add two numbers and return their sum.
```

Paths resolve against the directory holding `tools.yaml`. And when a
tool needs an unusual base image, you supply the Dockerfile yourself:

```yaml
tools:
  example_build:
    build:
      context: ./tools/example_build
      dockerfile: Dockerfile
    description: A tool whose image is built from its own Dockerfile.
```

Tool-swap still runs its runtime inside the container; you're just in
control of what gets built. There's also `image:` to pin a pre-built
image. The one rule here: a tool has exactly one image source,
`image:`, `build:` or a managed `handler:`, and the validator tells you
immediately if you mix them.

## Set the baseline once, override per tool

Once you have more than a couple of tools, shared settings belong in
`defaults:`, and every tool inherits them:

```yaml
defaults:
  ttl: 900          # stop a tool's container after 15 idle minutes
  max_batch_size: 8 # requests the runtime groups into one batch
  group: cpu        # where a tool lands when it names no group
```

A tool overrides any of these in its own entry, so a chatty tool can
keep a longer `ttl` while the rest stay on the baseline. Two keys are
special: `env` merges key by key, so a tool's variables win per key
rather than replacing the whole map, and `mounts` concatenate, so a
tool's volumes are added on top of the shared ones in
`host:container[:ro|rw]` form.

## Groups: the heart of the swapping

This is where tool-swap earns its name. A **group** caps how many of its
member tools run at the same time, and when the cap is reached, the
router evicts one (least recently used by default) to make room:

```yaml
groups:
  cpu:
    max_resident: 2     # at most two CPU tools at once
    eviction: lru
  gpu0:
    max_resident: 1     # one tool on GPU 0 at a time
    devices: [0]
```

On a single-GPU box, `max_resident: 1` is what makes models *swap*.
Summarizer is running, translator gets a request, summarizer's container
stops, translator starts, and the GPU is never wasted on two models at
once. Eviction can also be `lifo` or `none` (wait instead of evicting).

Tools join through their `group:` key, or fall back to
`defaults.group`. Two things the validator nudges you on: `max_resident`
is a cap on concurrency, not a count, so setting it above the member
count only draws a warning (`TSWAP-C613`); and a tool that combines
`workers` above 1 with a `devices:` list multiplies its VRAM usage in a
way the scheduler can't see (`TSWAP-C523`), so the warning is worth
reading.

## Where any value actually comes from

When several places could set a value, tool-swap walks a fixed chain and
the first hit wins:

```
inline entry  →  tool.yaml (via path:)  →  defaults:  →  the tool's group  →  built-in default
```

The one sentinel is `ttl: -1`, which means "inherit whatever
`defaults:` says." And if you ever wonder why a value is what it is, the
router will tell you:

```bash
tswap config show example_echo
```

prints every effective value with its origin, and `--verbose` adds the
values each setting overrode along the way. That command is the fastest
way to understand any config you didn't write.

## Keep secrets out of the file

Config values can reference environment variables:

```yaml
router:
  auth_token: ${TSWAP_TOKEN:-}     # empty unless TSWAP_TOKEN is set
```

The `:-` part gives a fallback, so the file validates even when the
variable is unset. A bare `${VAR}` with no value is an error
(`TSWAP-C010`). Variables come from the process environment plus a
`.env` file next to the config, which tool-swap finds on its own; pass
`--env-file` to read a specific file instead. The committed
[`tools.example.yaml`](../tools.example.yaml) gives every reference a
default for exactly this reason: it validates in CI with no environment
at all.

## Moving the router and naming containers

The `router:` and `backend:` blocks are optional and rarely needed at
first. The defaults give you a local HTTP server on port 8600 with
Docker as the container backend. Reach for `router:` to change the port,
require a Bearer token on every request, or adjust logging, and for
`backend:` to
rename your containers or change what happens to orphaned ones:

```yaml
router:
  host: 0.0.0.0
  port: 8600
  auth_token: ${TSWAP_TOKEN:-}   # set it to require Bearer auth
  log_level: INFO

backend:
  type: docker
  network: tool-swap-net         # created if absent; every tool joins it
  container_prefix: ms-          # containers are named <prefix><tool>
  orphans: stop                  # containers whose tool left the config
```

## Your first multi-GPU config

Now put the pieces together. This is the same shape as
[`tools.example.yaml`](../tools.example.yaml): a fleet of CPU tools, one
GPU with two models that swap on demand:

```yaml
version: 1

defaults:
  group: cpu

groups:
  cpu:
    max_resident: 2
  gpu0:
    max_resident: 1
    devices: [0]

tools:
  summarizer:
    path: ./tools/summarizer
  translator:
    path: ./tools/translator
    group: gpu0
```

A few lines later, `tswap validate --strict` is green, and
`tswap config show translator` confirms that translator resolved into
the `gpu0` group with the shared device and the default `ttl`. Add a
third GPU group, add two more tools, and nothing else in the file
changes. That's the whole idea: the config describes what you want to
run, and the router handles the swapping, the batching and the
lifecycle underneath it.

## Where to go deeper

The [Configuration reference](configuration.md) lists every key with its
type, default and description, so when in doubt about a spelling, start
there. The [troubleshooting
table](configuration.md#troubleshooting-every-diagnostic-code) pairs
every `TSWAP-C*` and `TSWAP-S*` code with its cause and its fix. And if
you want to know why a default is what it is, the internal design
document, [plan/02_CONFIGURATION.md](../plan/02_CONFIGURATION.md), has
the reasoning behind the choices.
