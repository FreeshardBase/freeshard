import asyncio
import subprocess as std_subprocess
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from shard_core.service.crypto import PublicKey
from fastapi import Response
from fastapi import status
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from httpx import AsyncClient
from httpx import URL, Request
from requests import PreparedRequest
from requests_http_signature import HTTPSignatureAuth

from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.util.subprocess import subprocess, SubprocessError

WAITING_DOCKER_IMAGE = "nginx:alpine"


async def pair_new_terminal(
    api_client, name="my_terminal", assert_success=True
) -> Response:
    pairing_code = await get_pairing_code(api_client)
    response = await add_terminal(api_client, pairing_code["code"], name)
    if assert_success:
        assert response.status_code == 201
    return response


async def get_pairing_code(api_client: AsyncClient, deadline=None):
    params = {"deadline": deadline} if deadline else {}
    response = await api_client.get("protected/terminals/pairing-code", params=params)
    response.raise_for_status()
    return response.json()


async def add_terminal(api_client, pairing_code, t_name):
    return await api_client.post(
        f"public/pair/terminal?code={pairing_code}", json={"name": t_name}
    )


async def wait_until_app_installed(api_client: AsyncClient, app_name, timeout=60):
    end = time.time() + timeout
    while True:
        if time.time() > end:
            raise TimeoutError(f"App {app_name} was not installed in time")
        response = await api_client.get(f"protected/apps/{app_name}")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            await asyncio.sleep(2)
            continue
        app = InstalledApp.model_validate(response.json())
        if app.status in (
            Status.INSTALLING,
            Status.INSTALLATION_QUEUED,
            Status.UNINSTALLING,
            Status.UNINSTALLATION_QUEUED,
            Status.REINSTALLING,
            Status.REINSTALLATION_QUEUED,
        ):
            await asyncio.sleep(2)
            continue
        elif app.status in (Status.STOPPED, Status.RUNNING):
            return app
        else:
            raise AssertionError(f"Unexpected app status: {app.status}")


async def wait_until_app_uninstalled(api_client: AsyncClient, app_name, timeout=20):
    end = time.time() + timeout
    while True:
        if time.time() > end:
            raise TimeoutError(f"App {app_name} was not uninstalled in time")
        response = await api_client.get(f"protected/apps/{app_name}")
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return
        await asyncio.sleep(2)


async def wait_until_all_apps_installed(async_client: AsyncClient):
    while True:
        apps = (await async_client.get("protected/apps")).json()
        if any(
            app["status"] in (Status.INSTALLING, Status.INSTALLATION_QUEUED)
            for app in apps
        ):
            await asyncio.sleep(2)
        else:
            return


async def install_app(async_client: AsyncClient, app_name: str):
    response = await async_client.post(f"protected/apps/{app_name}")
    assert response.status_code == status.HTTP_201_CREATED
    await wait_until_app_installed(async_client, app_name)


def mock_app_store_path():
    return Path(__file__).parent / "mock_app_store"


def _git_tracked_mock_app_store_files() -> set[Path]:
    store = mock_app_store_path()
    listing = std_subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=store,
        capture_output=True,
        text=True,
        check=True,
    )
    return {store / name for name in listing.stdout.split("\0") if name}


def build_mock_app_store_zips(target_root: Path) -> Path:
    """Pack every mock app directory into <target_root>/<name>/<name>.zip.

    Fixture files that are not committed would be absent from a fresh checkout,
    so the packed app would differ between a developer machine and CI.
    """
    tracked = _git_tracked_mock_app_store_files()
    for app_dir in sorted(p for p in mock_app_store_path().iterdir() if p.is_dir()):
        sources = sorted(p for p in app_dir.rglob("*") if p.is_file())
        untracked = [str(p.relative_to(app_dir)) for p in sources if p not in tracked]
        assert (
            not untracked
        ), f"{app_dir.name} has uncommitted fixture files: {untracked}"
        zip_path = target_root / app_dir.name / f"{app_dir.name}.zip"
        zip_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(zip_path, "w") as zip_file:
            for source in sources:
                zip_file.write(source, source.relative_to(app_dir))
    return target_root


def verify_signature_auth(request: PreparedRequest, pubkey: PublicKey) -> VerifyResult:
    class KR(HTTPSignatureKeyResolver):
        def resolve_private_key(self, key_id: str):
            pass

        def resolve_public_key(self, key_id: str):
            return pubkey.to_bytes()

    return HTTPSignatureAuth.verify(
        request,
        signature_algorithm=algorithms.RSA_PSS_SHA512,
        key_resolver=KR(),
    )


def modify_request_like_traefik_forward_auth(request: PreparedRequest) -> Request:
    url = urlparse(request.url)
    netloc_without_subdomain = url.netloc.split(".", maxsplit=1)[1]
    return Request(
        method=request.method,
        url=URL(f"https://{netloc_without_subdomain}/internal/auth"),
        headers={
            "X-Forwarded-Proto": url.scheme,
            "X-Forwarded-Host": url.netloc,
            "X-Forwarded-Uri": url.path,
            "X-Forwarded-Method": request.method,
            "signature-input": request.headers["signature-input"],
            "signature": request.headers["signature"],
            "date": request.headers["date"],
        },
    )


@asynccontextmanager
async def docker_network_portal():
    try:
        await subprocess("docker", "network", "create", "portal")
    except SubprocessError:
        pass  # network already exists
    try:
        yield
    finally:
        await _force_remove_docker_network("portal")


async def _force_remove_docker_network(network: str):
    """Disconnect all containers from a network, then remove it."""
    try:
        output = await subprocess(
            "docker",
            "network",
            "inspect",
            network,
            "--format",
            "{{range .Containers}}{{.Name}} {{end}}",
        )
        container_names = output.split()
        for name in container_names:
            try:
                await subprocess("docker", "network", "disconnect", "-f", network, name)
            except SubprocessError:
                pass
    except SubprocessError:
        pass  # network doesn't exist, nothing to do
    try:
        await subprocess("docker", "network", "rm", network)
    except SubprocessError:
        pass


async def retry_async(
    f: Callable, timeout: int = 90, frequency: int = 3, retry_errors=None
):
    if not retry_errors:
        retry_errors = [AssertionError]

    end = time.time() + timeout
    last_error = None
    result = None
    while time.time() < end:
        try:
            result = await f()
        except Exception as e:
            if type(e) in retry_errors:
                last_error = e
            else:
                raise e
        else:
            last_error = None
            break

        await asyncio.sleep(frequency)

    if last_error:
        raise last_error

    return result
