"""
Optional Docker-based execution sandbox.

Replaces direct subprocess execution with an ephemeral Docker container that:
- Mounts the project directory as /workspace (read-write)
- Has a read-only root filesystem + tmpfs for /tmp
- Drops all Linux capabilities
- Limits CPU shares and memory
- No network access by default

Usage in hybrid agent:
    python src/hybrid/agent.py --sandbox docker [--sandbox-image python:3.12-slim]

Design principles:
- Does NOT break the existing local execution mode (opt-in only)
- Falls back gracefully when Docker is unavailable
- Returns the same dict format as ToolRuntime.run_command
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


DOCKER_AVAILABLE: bool = bool(shutil.which("docker"))


class DockerSandbox:
    """Run commands inside an ephemeral Docker container.

    The container is destroyed after each command (``--rm``).  The project
    directory is mounted at ``/workspace`` with read-write access; everything
    else is read-only or tmpfs.

    Limitations:
    - Windows paths need Docker Desktop with WSL2 or Hyper-V volume mounting.
    - The image must be pulled before first use (``sandbox.pull_image()``).
    - Does not support interactive commands.
    """

    DEFAULT_IMAGE     = "python:3.12-slim"
    DEFAULT_MEM_LIMIT = "256m"
    DEFAULT_CPU_SHARES = 512          # relative weight; 1024 = host default
    DEFAULT_TIMEOUT   = 30

    def __init__(
        self,
        work_dir: str,
        image: str = DEFAULT_IMAGE,
        mem_limit: str = DEFAULT_MEM_LIMIT,
        cpu_shares: int = DEFAULT_CPU_SHARES,
        network: bool = False,
    ) -> None:
        if not DOCKER_AVAILABLE:
            raise RuntimeError(
                "Docker no encontrado. Instala Docker Desktop y asegúrate de que "
                "'docker' esté en el PATH para usar el sandbox."
            )
        self.work_dir   = str(Path(work_dir).resolve())
        self.image      = image
        self.mem_limit  = mem_limit
        self.cpu_shares = cpu_shares
        self.network    = network

    def run(
        self,
        command: str,
        timeout: int = DEFAULT_TIMEOUT,
        shell: str = "bash",
    ) -> dict:
        """Execute *command* inside the sandbox.

        Returns the same ``{stdout, stderr, returncode}`` dict as
        ``ToolRuntime.run_command``, plus a ``_sandbox: "docker"`` marker.
        """
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--read-only",
            f"--memory={self.mem_limit}",
            f"--cpu-shares={self.cpu_shares}",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
        ]

        if not self.network:
            docker_cmd.append("--network=none")

        # Mount project directory; /tmp must be writable even with --read-only
        docker_cmd += [
            "-v", f"{self.work_dir}:/workspace:rw",
            "-w", "/workspace",
            "--tmpfs", "/tmp:size=64m",
        ]

        docker_cmd += [self.image, shell, "-c", command]

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,   # extra buffer for container startup
            )
            return {
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
                "_sandbox": "docker",
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout en sandbox Docker ({timeout}s). Comando cancelado."}
        except Exception as exc:
            return {"error": f"Error en sandbox Docker: {exc}"}

    def is_image_available(self) -> bool:
        """Return True if the image exists locally (no pull needed)."""
        try:
            r = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0
        except Exception:
            return False

    def pull_image(self, quiet: bool = False) -> bool:
        """Pull the sandbox image. Returns True on success."""
        pull_cmd = ["docker", "pull"]
        if quiet:
            pull_cmd.append("--quiet")
        pull_cmd.append(self.image)
        try:
            r = subprocess.run(pull_cmd, capture_output=quiet, text=True, timeout=300)
            return r.returncode == 0
        except Exception:
            return False

    def ensure_image(self) -> bool:
        """Pull the image only if it is not already present locally."""
        if self.is_image_available():
            return True
        return self.pull_image()
