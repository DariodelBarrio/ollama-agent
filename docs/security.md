# Seguridad

## Modelo real

Ollama Agent no usa un sandbox de sistema operativo propio. La seguridad es una
combinación de guardas de aplicación:

- Restricción de rutas al `ROOT_DIR` del workspace.
- Resolución canónica con `Path.resolve()` antes de cualquier operación de archivo.
- Blocklist de patrones de comandos destructivos.
- Límites de tamaño en lectura y escritura de archivos.
- Guard explícito contra borrado del directorio raíz del workspace.

Esto reduce riesgo operativo, pero **no equivale a un contenedor, una VM o una
política MAC del sistema**.

---

## Validación de rutas

`resolve_in_root(path, work_dir, root_dir)` permite rutas absolutas y relativas
solo si, tras resolverlas con `Path.resolve()`, siguen dentro de `root_dir`.

| Ruta | Resultado si root_dir = C:\repo |
|---|---|
| `src/app.py` | Permitida |
| `C:\repo\src\app.py` | Permitida (absoluta, dentro de root) |
| `../../etc/passwd` | Bloqueada — ValueError |
| `C:\Windows\system32\hosts` | Bloqueada — ValueError |

**Symlinks:** Se usa `Path.resolve()`, por lo que un symlink dentro del repo
que apunte fuera queda bloqueado; uno que siga apuntando dentro del repo se permite.

**Cambio de directorio:** `change_directory()` actualiza `WORK_DIR` pero mantiene
`ROOT_DIR` como límite duro. El agente no puede salir del workspace raíz.

---

## Comandos bloqueados

La blocklist vive en `common_runtime.BLOCKED_COMMAND_PATTERNS` (17 patrones regex).
Se aplica sobre el comando lowercased antes de ejecutar cualquier subprocess.

| # | Patrón | Qué bloquea |
|---|---|---|
| 1 | `\b(rm\|rmdir\|del\|erase)\s` | Borrado de archivos/directorios |
| 2 | `\brd\s` | `rd` (alias de rmdir en cmd) |
| 3 | `remove-item\b` | PowerShell Remove-Item |
| 4 | `format\b` | Formateo de volúmenes |
| 5 | `reg\s+(delete\|add)\b` | Modificación del registro de Windows |
| 6 | `shutdown\b` | Apagado del sistema |
| 7 | `reboot\b` | Reinicio del sistema |
| 8 | `poweroff\b` | Apagado forzado |
| 9 | `mkfs\b` | Creación de sistema de archivos (Linux) |
| 10 | `diskpart\b` | Particionado (Windows) |
| 11 | `chmod\s+777\b` | Permisos excesivamente abiertos |
| 12 | `cmd /c ... (del\|erase\|rd\|rmdir\|format\|shutdown)` | Borrado/formato vía cmd /c |
| 13 | `powershell ... (remove-item\|del\|rm\|rmdir)` | Borrado vía pipeline PowerShell |
| 14 | `curl\b.*\|` | Descarga + ejecución inline vía pipe |
| 15 | `wget\b.*\|` | Descarga + ejecución inline vía pipe |
| 16 | `invoke-webrequest\b.*\|` | Descarga + ejecución inline (PowerShell) |
| 17 | `\bgit\s+clean\b` | Borrado de archivos no rastreados del workspace |

**Nota sobre patrones 1-2:** Usan `\b` (word boundary) en lugar de `(^|\s)`.
Esto captura variantes como `bash -c "rm -rf ."` donde `rm` va precedido de `"`,
no de espacio.

**Limitación de la blocklist:**

- Es una lista de exclusión. No prueba que un comando sea seguro.
- Comandos que invocan código destructivo por indirección (p.ej. `python -c "import shutil; shutil.rmtree(...)"`) pueden no ser capturados.
- Si necesitas aislamiento fuerte, usa el sandbox Docker opcional (`src/sandbox.py`) o ejecuta el agente en un contenedor/VM.

---

## Operaciones de archivo

### Límites de tamaño

| Operación | Límite |
|---|---|
| `read_file` | 2 MB por archivo |
| `write_file` | 10 MB por contenido |
| `grep` | Archivos > 1 MB ignorados |
| Contexto de proyecto | 16 KB (CLAUDE.md / README.md) |

### Guard de borrado del workspace raíz

`delete_file` rechaza explícitamente el `root_dir` como destino:

```
delete_file("/ruta/al/workspace") → error: "No se puede eliminar el directorio raíz del workspace."
```

Subdirectorios dentro del workspace sí pueden borrarse.

---

## Fetch de URLs (`fetch_url`)

La herramienta `fetch_url` puede acceder a cualquier URL accesible desde la
máquina donde corre el agente, incluyendo servicios locales (`localhost`, `127.0.0.1`).

Esto es SSRF de aplicación controlado:

- No hay elevación de privilegios (el agente ya corre en la máquina local).
- Puede exponer datos de servicios locales (Ollama API, bases de datos con interfaz HTTP, etc.) si el modelo lo solicita.
- No se bloquea por defecto porque los usos legítimos (acceder a docs de un servidor de desarrollo, Swagger, etc.) son comunes.

Si el agente tiene acceso a servicios internos sensibles, no le des acceso a `fetch_url` o ejecuta el agente en una red aislada.

---

## Sandbox Docker (opcional)

`src/sandbox.py` ofrece ejecución de comandos dentro de un contenedor efímero:

- `--rm`: el contenedor se destruye tras cada comando.
- `--read-only`: raíz del contenedor solo lectura; `/tmp` montado como tmpfs.
- `--cap-drop=ALL`: sin capabilities Linux.
- `--security-opt=no-new-privileges`: sin escalada de privilegios.
- `--network=none`: sin red por defecto.
- Límites de CPU (`--cpu-shares`) y memoria (`--memory`).

El workspace del proyecto se monta como `rw` en `/workspace` — el agente puede
escribir en él, pero no en el resto del sistema de archivos del host.

**Limitaciones del sandbox Docker:**

- Solo intercepta `run_command`. Las operaciones de archivo (`write_file`, `edit_file`, etc.) siguen ejecutándose en el host local.
- Requiere Docker Desktop en Windows (WSL2 o Hyper-V para montaje de volúmenes).
- No previene que el agente escriba archivos maliciosos en el workspace vía `write_file`.
- No es un sandbox de OS completo; un root dentro del contenedor con volumen montado puede escribir al workspace del host.

Uso: `python src/hybrid/agent.py --sandbox docker [--sandbox-image python:3.12-slim]`

---

## Recomendación operativa

Para trabajo con código sensible o no confiable:

1. Usa un repo desechable o copia temporal del proyecto.
2. Ejecuta el agente con un usuario de pocos privilegios.
3. Activa el sandbox Docker (`--sandbox docker`) para mayor aislamiento de ejecución de comandos.
4. Para aislamiento fuerte: usa contenedor, VM o una máquina dedicada.
