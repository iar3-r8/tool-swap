# Key Concepts

> **Source:** https://docs.ray.io/en/latest/serve/key-concepts.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the vocabulary. Needed to read every other page correctly: deployment vs replica vs application vs ingress. The deployment/replica distinction is what makes displacement live *inside* a replica while isolation lives *around* it.

---

## Deployment

Deployments are the central concept in Ray Serve. A deployment contains business logic or an ML model to handle incoming requests and can be scaled up to run across a Ray cluster. At runtime, **a deployment consists of a number of *replicas*, which are individual copies of the class or function that are started in separate Ray Actors (processes)**. The number of replicas can be scaled up or down (or even autoscaled) to match the incoming request load.

To define a deployment, use the `@serve.deployment` decorator on a Python class (or function). Then `bind` the deployment with optional constructor arguments to define an application. Finally, deploy the resulting application using `serve.run` (or the `serve run` CLI command).

```python
from ray import serve
from ray.serve.handle import DeploymentHandle


@serve.deployment
class MyFirstDeployment:
    # Take the message to return as an argument to the constructor.
    def __init__(self, msg):
        self.msg = msg

    def __call__(self):
        return self.msg


my_first_deployment = MyFirstDeployment.bind("Hello world!")
handle: DeploymentHandle = serve.run(my_first_deployment)
assert handle.remote().result() == "Hello world!"
```

## Application

**An application is the unit of upgrade in a Ray Serve cluster.** An application consists of one or more deployments. One of these deployments is considered the "ingress" deployment, which handles all inbound traffic.

Applications can be called via HTTP at the specified `route_prefix` or in Python using a `DeploymentHandle`.

## DeploymentHandle (composing deployments)

Ray Serve enables flexible model composition and scaling by allowing multiple independent deployments to call into each other. When binding a deployment, you can include references to *other bound deployments*. At runtime each of these arguments is converted to a `DeploymentHandle`.

```python
@serve.deployment
class Hello:
    def __call__(self) -> str:
        return "Hello"


@serve.deployment
class World:
    def __call__(self) -> str:
        return " world!"


@serve.deployment
class Ingress:
    def __init__(self, hello_handle: DeploymentHandle, world_handle: DeploymentHandle):
        self._hello_handle = hello_handle
        self._world_handle = world_handle

    async def __call__(self) -> str:
        hello_response = self._hello_handle.remote()
        world_response = self._world_handle.remote()
        return (await hello_response) + (await world_response)


hello = Hello.bind()
world = World.bind()

# The deployments passed to the Ingress constructor are replaced with handles.
app = Ingress.bind(hello, world)

# Deploys Hello, World, and Ingress.
handle: DeploymentHandle = serve.run(app)

assert handle.remote().result() == "Hello world!"
```

## Ingress deployment (HTTP handling)

One deployment is always the "top-level" one that is passed to `serve.run`. This deployment is called the "ingress deployment" because it serves as the entrypoint for all traffic to the application.

By default, the `__call__` method of the class is called and passed a `Starlette` request object. The response is serialized as JSON, but other `Starlette` response objects can also be returned directly.

```python
@serve.deployment
class MostBasicIngress:
    async def __call__(self, request: Request) -> str:
        name = (await request.json())["name"]
        return f"Hello {name}!"


app = MostBasicIngress.bind()
serve.run(app)
```

For more expressive HTTP handling, Serve comes with a built-in integration with `FastAPI`:

```python
fastapi_app = FastAPI()


@serve.deployment
@serve.ingress(fastapi_app)
class FastAPIIngress:
    @fastapi_app.get("/{name}")
    async def say_hi(self, name: str) -> str:
        return PlainTextResponse(f"Hello {name}!")


app = FastAPIIngress.bind()
serve.run(app)
```

---

## tool-swap notes

1. **The nesting is: cluster → application → deployment → replica (an actor process).** `image_uri` attaches at the *application* level; `@serve.multiplexed` LRU residency lives *inside* a replica. Nothing attaches at the level in between, which is where our eviction table sits. This is the granularity mismatch of [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) §4.3, stated in Ray's own vocabulary.
2. **"An application is the unit of upgrade"** appears here too, and is the phrase to quote when explaining why displacement on Ray is a control-plane action.
3. **FastAPI ingress is a genuine R3 win** and matches what our own proxy exposes.
