"""Step 3 variant — the legacy ``container`` runtime_env key.

Re-runs the step 3 gate (two conflicting tools, one GPU, on demand)
through Ray's legacy ``runtime_env: {container: {...}}`` key instead of
``image_uri``. The ``image_uri`` form (step3_gpu_swap.py) structurally
cannot give the worker container a GPU: ``ImageURIPlugin.modify_context``
passes a hardcoded empty run_options list
(ray/_private/runtime_env/image_uri.py:174), so ``--runtime`` is
unreachable. The ``container`` key forwards ``run_options``
(ray/_private/runtime_env/image_uri.py:222-229), which is the only way
to pass the nvidia-container-runtime that injects both the device nodes
and the driver libraries on this host (ledger 9L, D34).

Differences from step3_gpu_swap.py — everything else is identical:

* ``runtime_env`` uses ``container`` (``image`` + ``run_options``)
  instead of ``image_uri``. The ``container`` key permits only
  ``config`` and ``env_vars`` alongside it
  (ray/runtime_env/runtime_env.py:397-404), and Serve itself injects
  ``env_vars`` (deployment context vars —
  ray/serve/_private/deployment_state.py:130-148), so the key set is
  exactly ``{container, env_vars}`` and passes validation.
* ``run_options`` carries the GPU passthrough that the host's manual
  ``podman run`` used (D34): the nvidia runtime plus the two env vars
  it keys on. NVIDIA_VISIBLE_DEVICES is pinned to physical device 0 —
  the only device of a 1-GPU cluster (SPIKE_RAY_NUM_GPUS=1).

The deployment classes are duplicated here (not reused) because the
decorators differ in ``ray_actor_options`` and step 3's image_uri form
is a recorded result that must stay reproducible byte-for-byte.
"""
from __future__ import annotations

import os
from ray import serve

from toolkit.deployments import Tool

# ── Build args ─────────────────────────────────────────────────
# D26: no ${...} placeholders — image names are written literally and
# overridable from the environment for other hosts.
IMAGE_TORCH = os.environ.get("SPIKE_IMAGE_TORCH_URI", "tool_torch:spike")
IMAGE_TF = os.environ.get("SPIKE_IMAGE_TF_URI", "tool_tf:spike")

# D34: the GPU passthrough. On this host only the nvidia-container-
# runtime injects the /dev/nvidia* nodes AND the driver libraries
# (libcuda.so.1) into the container; every other mechanism failed for
# a different reason (ledger 9L table). NVIDIA_VISIBLE_DEVICES=0
# gives exactly one device, matching the 1-GPU cluster; the worker's
# CUDA_VISIBLE_DEVICES (set by Ray from the GPU resource assignment,
# ray/_private/utils.py:276-300) then selects that same physical
# device inside the container, so CUDA index 0 is the host's.
NVIDIA_RUNTIME = os.environ.get(
    "SPIKE_NVIDIA_RUNTIME", "/usr/bin/nvidia-container-runtime"
)
NVIDIA_VISIBLE_DEVICES = os.environ.get("SPIKE_NVIDIA_VISIBLE_DEVICES", "0")


def _container_runtime_env(image: str) -> dict:
    """Build the legacy ``container`` runtime_env for one image.

    The container key forwards ``run_options`` verbatim into the
    worker's ``podman run`` command
    (ray/_private/runtime_env/image_uri.py:122-123), so the run
    options here are exactly the flags the manual D34 test used.

    Args:
        image: The locally built fixture image (name:tag).

    Returns:
        The ``runtime_env`` dict for a containerised deployment.
    """
    return {
        "container": {
            "image": image,
            "run_options": [
                f"--runtime={NVIDIA_RUNTIME}",
                f"--env=NVIDIA_VISIBLE_DEVICES={NVIDIA_VISIBLE_DEVICES}",
                "--env=NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            ],
        }
    }


@serve.deployment(
    ray_actor_options={
        "num_gpus": 1,
        "runtime_env": _container_runtime_env(IMAGE_TORCH),
    },
    autoscaling_config={
        "min_replicas": 0,
        "max_replicas": 1,
        "downscale_to_zero_delay_s": 60,
    },
)
class ToolTorch(Tool):
    def __init__(self):
        weights_path = os.environ.get(
            "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
        )
        super().__init__(weights_path=weights_path, vram_mb=4096)

    # No __call__ override: these deployments serve as ingresses, so the
    # HTTP entrypoint comes from Tool.__call__, which handles both the
    # Starlette-request and parsed-dict shapes.


@serve.deployment(
    ray_actor_options={
        "num_gpus": 1,
        "runtime_env": _container_runtime_env(IMAGE_TF),
    },
    autoscaling_config={
        "min_replicas": 0,
        "max_replicas": 1,
        "downscale_to_zero_delay_s": 60,
    },
)
class ToolTf(Tool):
    def __init__(self):
        weights_path = os.environ.get(
            "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
        )
        super().__init__(weights_path=weights_path, vram_mb=4096)

    # No __call__ override: ingress entrypoint inherited from Tool.__call__.


# ── Applications ───────────────────────────────────────────────
# .bind() already returns an Application; wrapping it again in
# serve.Application() would fail (its __init__ takes one bound
# deployment). Same double-wrap fixed in step2_builder.py.
application_torch = ToolTorch.bind()
application_tf = ToolTf.bind()
