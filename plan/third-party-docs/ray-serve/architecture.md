# Architecture

> **Source:** https://docs.ray.io/en/latest/serve/architecture.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the process model. This is the page to quote when discussing "Ray is heavy" (open question 7) — it names the actors that exist, though not their memory footprint. Also documents the request lifecycle, the queue-until-a-replica-is-available behaviour that is the core of the **D25** objection, and the fault-tolerance model.

---

Serve runs on Ray and utilizes Ray actors.

## High-Level View

There are three kinds of actors that are created to make up a Serve instance:

- **Controller**: A global actor unique to each Serve instance that manages the control plane. The Controller is responsible for creating, updating, and destroying other actors. Serve API calls like creating or getting a deployment make remote calls to the Controller.
- **HTTP Proxy**: By default there is one HTTP proxy actor on the head node. This actor runs a Uvicorn HTTP server that accepts incoming requests, forwards them to replicas, and responds once they are completed. For scalability and high availability, you can also run a proxy on each node in the cluster via the `proxy_location` field.
- **gRPC Proxy**: If Serve is started with valid `port` and `grpc_servicer_functions`, then the gRPC proxy is started alongside the HTTP proxy.
- **Replicas**: Actors that actually execute the code in response to a request. For example, they may contain an instantiation of an ML model. Each replica processes individual requests from the proxy. The replica may batch the requests using `@serve.batch`.

## Lifetime of a request

When an HTTP or gRPC request is sent to the corresponding proxy:

1. The request is received and parsed.
2. Ray Serve looks up the correct deployment associated with the HTTP URL path or application name metadata. Serve places the request in a queue.
3. For each request in a deployment's queue, an available replica is looked up and the request is sent to it. **If no replicas are available (that is, more than `max_ongoing_requests` requests are outstanding at each replica), the request is left in the queue until a replica becomes available.**

Each replica maintains a queue of requests and executes requests one at a time, possibly using `asyncio` to process them concurrently. If the handler is declared with `async def`, the replica will not wait for the handler to run. Otherwise, the replica blocks until the handler returns.

When making a request via a `DeploymentHandle` instead of HTTP or gRPC for model composition, the request is placed on a queue in the `DeploymentHandle`, and we skip to step 3 above.

## Fault tolerance

Application errors like exceptions in your model evaluation code are caught and wrapped. A 500 status code is returned with the traceback information. The replica will be able to continue to handle requests.

Machine errors and faults are handled by Ray Serve as follows:

- When replica Actors fail, the Controller Actor replaces them with new ones.
- When the proxy Actor fails, the Controller Actor restarts it.
- When the Controller Actor fails, Ray restarts it.
- When using the KubeRay RayService, KubeRay recovers crashed nodes or a crashed cluster. You can avoid cluster crashes by using the GCS FT feature.
- **If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover.**

When a machine hosting any of the actors crashes, those actors are automatically restarted on another available machine. All data in the Controller (routing policies, deployment configurations, etc) is checkpointed to the Ray Global Control Store (GCS) on the head node. Transient data in the router and the replica (like network connections and internal request queues) will be lost for this kind of failure.

## Ray Serve Autoscaling

- The Serve Autoscaler runs in the Serve Controller actor.
- Each `DeploymentHandle` and each replica periodically pushes its metrics to the autoscaler.
- For each deployment, the autoscaler periodically checks `DeploymentHandle` queues and in-flight queries on replicas to decide whether or not to scale the number of replicas.
- Each `DeploymentHandle` continuously polls the controller to check for new deployment replicas. Whenever new replicas are discovered, it sends any buffered or new queries to the replica until `max_ongoing_requests` is reached. Queries are sent to replicas using a **power of two choices** scheduling strategy, subject to the constraint that no replica is handling more than `max_ongoing_requests` requests at a time.

> **Note.** When the controller dies, requests can still be sent via HTTP, gRPC and `DeploymentHandle`, but autoscaling is paused. When the controller recovers, autoscaling resumes, but all previously collected metrics are lost.

## Ray Serve API Server

Ray Serve provides a CLI for managing your Ray Serve instance, as well as a REST API. Each node in your Ray cluster provides a Serve REST API server that can connect to Serve and respond to Serve REST requests.

## FAQ

### How does Serve ensure horizontal scalability and availability?

You can configure Serve to start one proxy Actor per node with the `proxy_location` field. Each proxy binds to the same port. You can use your own load balancer on top of Ray Serve.

### How do DeploymentHandles work?

`DeploymentHandles` wrap a handle to a "router" on the same node which routes requests to replicas for a deployment. When a request is sent from one replica to another via the handle, the requests go through the same data path as incoming HTTP or gRPC requests. This enables the same deployment selection and batching procedures to happen.

### What happens to large requests?

Serve utilizes Ray's shared memory object store and in-process memory store. Small request objects are directly sent between actors via network call. Larger request objects (100KiB+) are written to the object store and the replica can read them via zero-copy read.

---

## tool-swap notes

1. **The queueing rule in step 3 is the D25 objection in Ray's own words.** A request waits for *a replica of its own deployment* to become available. There is no path by which a queued request for tool B causes tool A to release a GPU.
2. **Process inventory:** controller + one proxy per node (+ optional gRPC proxy) + one actor per replica, on top of the Ray core processes (GCS, raylet, dashboard). This is the concrete list for open question 7 — **but the page gives no memory figures, so the "heavy" claim still needs measuring, not quoting.**
3. **"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"** is a significant operational statement for a single-DGX deployment without Kubernetes. It cuts against guardrail 8 (restart must be cheap and stateless).
4. **The 100KiB object-store threshold** is relevant to our image-heavy payloads: large tensors would travel through plasma rather than by value, which is a genuine efficiency win over our HTTP-body approach.
5. **Errors return 500 with a traceback**, and the replica survives — comparable to our error contract, though we return structured errors rather than tracebacks.
