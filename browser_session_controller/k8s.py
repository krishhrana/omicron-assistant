from __future__ import annotations

import time

_core_v1 = None
_loaded = False


def _load_config() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    # Import lazily so local tooling doesn't require kubernetes installed.
    from kubernetes import config as k8s_config  # type: ignore

    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()


def core_v1_api():
    global _core_v1
    if _core_v1 is not None:
        return _core_v1
    _load_config()
    from kubernetes import client as k8s_client  # type: ignore

    _core_v1 = k8s_client.CoreV1Api()
    return _core_v1


def ensure_runner_service(*, namespace: str, service_name: str, port: int, selector: dict[str, str]) -> None:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes.client.rest import ApiException  # type: ignore

    api = core_v1_api()
    svc = k8s_client.V1Service(
        metadata=k8s_client.V1ObjectMeta(name=service_name, labels=selector),
        spec=k8s_client.V1ServiceSpec(
            type="ClusterIP",
            selector=selector,
            ports=[k8s_client.V1ServicePort(name="mcp", port=port, target_port=port)],
        ),
    )
    try:
        api.create_namespaced_service(namespace=namespace, body=svc)
    except ApiException as exc:
        if exc.status != 409:
            raise


def ensure_runner_pod(
    *,
    namespace: str,
    pod_name: str,
    image: str,
    service_account_name: str,
    port: int,
    controller_internal_url: str,
    runner_broker_token: str,
    artifacts_s3_bucket: str | None = None,
    artifacts_s3_prefix: str | None = None,
    uploader_image: str = "amazon/aws-cli:2",
    output_dir: str = "/output",
    secrets_dir: str = "/secrets",
) -> None:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes.client.rest import ApiException  # type: ignore

    api = core_v1_api()
    labels = {"app": "pw-mcp-runner", "session": pod_name}

    cmd = r"""
set -euo pipefail
umask 077
mkdir -p {secrets_dir}
curl -fsSL -H "Authorization: Bearer $RUNNER_BROKER_TOKEN" "{controller}/internal/runner-secrets" > {secrets_dir}/runtime.env
exec npx -y @playwright/mcp@latest --port {port} --isolated --output-dir {output_dir} --secrets {secrets_dir}/runtime.env --save-video 1920x1080 --viewport-size 1920x1080
""".strip().format(
        controller=controller_internal_url.rstrip("/"),
        port=port,
        output_dir=output_dir,
        secrets_dir=secrets_dir,
    )

    containers: list = [
        k8s_client.V1Container(
            name="playwright-mcp",
            image=image,
            command=["/bin/sh", "-lc", cmd],
            env=[
                k8s_client.V1EnvVar(name="RUNNER_BROKER_TOKEN", value=runner_broker_token),
            ],
            ports=[k8s_client.V1ContainerPort(container_port=port, name="mcp")],
            volume_mounts=[
                k8s_client.V1VolumeMount(name="output", mount_path=output_dir),
                k8s_client.V1VolumeMount(name="secrets", mount_path=secrets_dir),
                k8s_client.V1VolumeMount(name="dshm", mount_path="/dev/shm"),
            ],
        )
    ]

    if artifacts_s3_bucket and artifacts_s3_prefix:
        upload_cmd = f"aws s3 cp --recursive {output_dir} s3://$S3_BUCKET/$S3_PREFIX"
        containers.append(
            k8s_client.V1Container(
                name="uploader",
                image=uploader_image,
                command=["/bin/sh", "-lc", "sleep infinity"],
                env=[
                    k8s_client.V1EnvVar(name="S3_BUCKET", value=artifacts_s3_bucket),
                    k8s_client.V1EnvVar(name="S3_PREFIX", value=artifacts_s3_prefix),
                ],
                volume_mounts=[k8s_client.V1VolumeMount(name="output", mount_path=output_dir)],
                lifecycle=k8s_client.V1Lifecycle(
                    pre_stop=k8s_client.V1LifecycleHandler(
                        _exec=k8s_client.V1ExecAction(command=["/bin/sh", "-lc", upload_cmd])
                    )
                ),
            )
        )

    pod = k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(name=pod_name, labels=labels),
        spec=k8s_client.V1PodSpec(
            service_account_name=service_account_name,
            restart_policy="Never",
            containers=containers,
            volumes=[
                k8s_client.V1Volume(name="output", empty_dir=k8s_client.V1EmptyDirVolumeSource()),
                k8s_client.V1Volume(name="secrets", empty_dir=k8s_client.V1EmptyDirVolumeSource()),
                k8s_client.V1Volume(name="dshm", empty_dir=k8s_client.V1EmptyDirVolumeSource(medium="Memory")),
            ],
        ),
    )
    try:
        api.create_namespaced_pod(namespace=namespace, body=pod)
    except ApiException as exc:
        if exc.status != 409:
            raise


def wait_for_pod_ready(*, namespace: str, pod_name: str, timeout_seconds: int) -> None:
    api = core_v1_api()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        pod = api.read_namespaced_pod(name=pod_name, namespace=namespace)
        phase = getattr(getattr(pod, "status", None), "phase", None)
        if phase == "Running":
            conditions = getattr(getattr(pod, "status", None), "conditions", None) or []
            for cond in conditions:
                if getattr(cond, "type", None) == "Ready" and getattr(cond, "status", None) == "True":
                    return
        time.sleep(1.5)
    raise TimeoutError(f"Pod {namespace}/{pod_name} did not become Ready within {timeout_seconds}s")


def delete_runner_resources(*, namespace: str, pod_name: str, service_name: str) -> None:
    from kubernetes.client.rest import ApiException  # type: ignore

    api = core_v1_api()
    try:
        api.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
    except ApiException as exc:
        if exc.status != 404:
            raise
    try:
        api.delete_namespaced_service(name=service_name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise

