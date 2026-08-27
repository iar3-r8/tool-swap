# tool_torch — PyTorch fixture for Spike E
# Weights and payload are baked in at build time (§0a of spike-E-implementation.md)

ARG RAY_BASE_TAG
FROM ${RAY_BASE_TAG}

# === Framework deps ===
# NOTE: these run as the base image's ORIGINAL user (uid 1000, `ray`) BEFORE
# the uid renumbering further down, so they can write into the conda
# site-packages that is still owned by uid 1000 at this point (the original
# behaviour). The installed files stay world-readable, which is all the runtime
# worker needs (it only reads/executes them; Python silently skips .pyc writes
# into dirs it does not own). Do NOT move the usermod block above these.
RUN pip install --no-cache-dir \
    torch==2.8.0+cu129 \
    --extra-index-url https://download.pytorch.org/whl/cu129

# === Shared runtime deps (boto3 removed per §0a: no object storage) ===
RUN pip install --no-cache-dir \
    requests

# =====================================================================
# D22 — Pin the container runtime user to the HOST cluster uid.
#
# WHY the uid is pinned to the host's:
#   * Ray's `image_uri` runtime env launches the replica container with
#     `--userns=keep-id` and NO `--user` flag —
#     ray/_private/runtime_env/image_uri.py:174 hardcodes run_options=[] —
#     so the container worker runs as whatever uid the image's USER sets.
#   * The host's Ray session dirs (<session>/logs/events/ and
#     .../logs/export_events/) are mode 0755 and owned by the uid that started
#     the cluster. If the container worker's uid does not match that cluster
#     uid, the C++ core worker's event writer cannot open
#       <session>/logs/events/event_CORE_WORKER_<pid>.log
#     for writing; it throws an uncaught spdlog_ex -> std::terminate -> SIGABRT
#     (exit 134), and the message is invisible because RayLog has already
#     redirected fd 2.
#   * Fix (Option 1d, user-chosen): rebuild the image so the container process
#     runs as the HOST's cluster uid (default 1011 / gid 1013), matching the
#     cluster-starting user. build_images.sh passes the invoking user's real
#     uid/gid via --build-arg, so the image tracks whoever builds it.
#
# COST: this bakes a specific uid into the image, making it HOST-SPECIFIC.
# That is the accepted cost of Option 1d and is itself part of the spike's
# finding.
# =====================================================================
ARG SPIKE_UID=1011
ARG SPIKE_GID=1013

# Renumber the base image's EXISTING `ray` user to the host uid/gid, and make
# the home dir owned by it. Done once, as root.
#
# The base image's ACTUAL user/group layout (ray-project/ray,
# docker/base-deps/Dockerfile, master; image is docker.io/rayproject/ray) is:
#     ARG RAY_UID=1000; ARG RAY_GID=100
#     useradd -ms /bin/bash -d /home/ray ray --uid $RAY_UID --gid $RAY_GID
# i.e. on Ubuntu 22.04 the user `ray` (uid 1000) has the PRE-EXISTING
# `users` group (gid 100) as its primary group, and there is NO group named
# `ray`. The RUN block below must therefore NOT run `groupmod -g <gid> ray`
# (it fails with "group 'ray' does not exist"); instead it secures a group
# owning ${SPIKE_GID} (reusing whatever group already has that gid, otherwise
# creating one named `spike`) and points `ray` at it. It also fails loudly if
# a DIFFERENT account already owns ${SPIKE_UID}.
#
# We renumber the existing `ray` user (option (a)) rather than creating a new
# uid-1011 user (option (b)): the conda install and WORKDIR live under
# /home/ray and the base image's python/PATH assume the `ray` home. A fresh
# user with a different home (and no passwd entry for the old home) would break
# conda/python. Renumbering keeps the name `ray` — so paths and $HOME still
# resolve — while giving it the host uid.
#
# chown is the NARROWEST set: only /home/ray itself (so $HOME is writable for
# the worker). The ~15 GB /home/ray/anaconda3 tree is deliberately left as-is
# (world-readable: read+execute is enough for the interpreter and
# site-packages); a recursive chown there is expensive and buys nothing.
USER root
RUN set -eux; \
    if getent group "${SPIKE_GID}" >/dev/null; then \
        echo "reusing existing group with gid ${SPIKE_GID}: $(getent group "${SPIKE_GID}")"; \
    else \
        groupadd -g "${SPIKE_GID}" spike; \
    fi; \
    if getent passwd "${SPIKE_UID}" >/dev/null; then \
        if [ "$(getent passwd "${SPIKE_UID}" | cut -d: -f1)" = "ray" ]; then \
            echo "ray already has uid ${SPIKE_UID}"; \
        else \
            echo "ERROR: uid ${SPIKE_UID} is already taken by user '$(getent passwd "${SPIKE_UID}" | cut -d: -f1)'; refusing to renumber an unrelated account" >&2; \
            exit 1; \
        fi; \
    fi; \
    usermod -u "${SPIKE_UID}" -g "${SPIKE_GID}" ray; \
    chown "${SPIKE_UID}:${SPIKE_GID}" /home/ray
USER ${SPIKE_UID}

# === Baked assets (must run before COPY toolkit, so assets are cached) ===
# ASSET_SEED must differ from tool_tf's — step 2 needs distinct weight bytes.
# --chown=${SPIKE_UID} so the later `rm` works: /tmp is sticky (1777), only
# the owner may unlink.
COPY --chown=${SPIKE_UID}:${SPIKE_GID} fixtures/make_assets.py /tmp/make_assets.py
ARG WEIGHTS_MB=8
ARG PAYLOAD_MB=64
ARG ASSET_SEED=1001
# ${SPIKE_UID} cannot create /opt/spike: pre-create it as root, chown it to
# the runtime user, then run the asset generator as that user.
USER root
RUN mkdir -p /opt/spike && chown "${SPIKE_UID}:${SPIKE_GID}" /opt/spike
USER ${SPIKE_UID}
RUN python /tmp/make_assets.py \
      --weights /opt/spike/weights/ckpt.bin --weights-mb ${WEIGHTS_MB} \
      --payload /opt/spike/data/payload.bin --payload-mb ${PAYLOAD_MB} \
      --seed ${ASSET_SEED} \
    && rm /tmp/make_assets.py
ENV SPIKE_WEIGHTS_PATH=/opt/spike/weights/ckpt.bin
ENV SPIKE_PAYLOAD_PATH=/opt/spike/data/payload.bin

# === Shared toolkit code ===
# --chown so the runtime user owns (and can write __pycache__ into) the code
# it imports.
COPY --chown=${SPIKE_UID}:${SPIKE_GID} toolkit/ /home/ray/toolkit/
COPY --chown=${SPIKE_UID}:${SPIKE_GID} apps/ /home/ray/apps/
ENV PYTHONPATH="${PYTHONPATH}:/home/ray"

# === Identity (cannot be faked via runtime_env env_vars) ===
ENV SPIKE_IMAGE_MARKER=tool_torch

# Final runtime user: the pinned host uid (NOT root).
USER ${SPIKE_UID}
WORKDIR /home/ray
