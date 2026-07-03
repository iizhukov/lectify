import os

from pathlib import Path


def get_repo_root() -> Path:
    root_env = os.environ.get("LECTIFY_ROOT")

    if not root_env:
        raise ValueError("LECTIFY_ROOT environment variable not set")

    return Path(root_env)


def get_service_proto(service: Path) -> Path:
    relative_path = service.relative_to(get_repo_root())

    if not relative_path.parts or relative_path.parts[0] != "services":
        raise ValueError(f"Service must be in a 'services' directory")

    in_service_path = relative_path.relative_to("services")
    
    return get_repo_root() / "proto" / in_service_path / "index.proto"
