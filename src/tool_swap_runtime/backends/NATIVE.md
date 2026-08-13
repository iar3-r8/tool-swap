# Native Backend

The native backend executes AI agent tools directly on the host system without
containerization. It provides low-latency execution for trusted tool definitions
and is the default backend for development and local deployment scenarios.

## Features

- Direct process execution with environment isolation
- CPU, CUDA, and TensorFlow device detection
- Lifecycle hooks for warm-up and teardown
- Pre-flight system validation
