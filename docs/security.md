# Seguridad

## Modelo real

Ollama Agent no usa un sandbox de sistema operativo propio. La seguridad actual es una combinacion de:

- restriccion de rutas al `ROOT_DIR`
- resolucion canonica con `Path.resolve()`
- blocklist de comandos destructivos
- separacion entre directorio de trabajo actual (`WORK_DIR`) y raiz permitida (`ROOT_DIR`)

Esto reduce riesgo operativo, pero no equivale a un contenedor, una VM o una politica MAC del sistema.

## Comandos bloqueados

La blocklist vive en `common_runtime.BLOCKED_COMMAND_PATTERNS`.

Patrones cubiertos ahora:

- `rm`, `rmdir`, `del`, `erase`
- `rd`
- `Remove-Item`
- `format`
- `reg delete`, `reg add`
- `shutdown`, `reboot`, `poweroff`
- `mkfs`, `diskpart`
- `chmod 777`
- `cmd /c` con borrado o format
- `powershell` con `remove-item`, `del`, `rm`, `rmdir`
- `curl ... | ...`
- `Invoke-WebRequest ... | ...`

Limitacion importante:

- Es una blocklist. No prueba que un comando sea seguro.
- Puede haber bypasses por combinaciones no contempladas.
- Si necesitas aislamiento fuerte, ejecuta el agente dentro de un sandbox del sistema o una VM.

## Paths absolutos

`resolve_in_root(path, work_dir, root_dir)` permite rutas absolutas solo si, tras resolverlas, siguen dentro de `root_dir`.

Consecuencia:

- `C:\repo\src\app.py` se permite si `root_dir` es `C:\repo`
- `C:\Windows\system32\drivers\etc\hosts` se bloquea

## Symlinks

Se usa `Path.resolve()`, asi que los symlinks no se tratan como texto plano.

Consecuencia:

- un symlink dentro del repo que apunte fuera del repo queda bloqueado
- un symlink dentro del repo que siga apuntando dentro del repo se permite

## Salir del work_dir

El modelo no puede sacar la tool layer fuera del root permitido:

- `read_file`, `write_file`, `edit_file`, `move_file`, `delete_file`, `list_directory`, `find_files`, `grep` pasan por `resolve_in_root`
- `change_directory()` actualiza `WORK_DIR`, pero mantiene `ROOT_DIR` como limite duro

Si el modelo intenta salir del workspace:

- se lanza `ValueError("Ruta fuera del directorio permitido: ...")`
- la tool devuelve error y la accion no se ejecuta

## Limites de la sandbox actual

Lo que si hace:

- bloquea parte de los comandos mas peligrosos
- evita lecturas/escrituras fuera del root permitido
- evita escapes via symlink resuelto

Lo que no hace:

- no impide todo comando dañino posible
- no limita CPU/RAM/red a nivel OS
- no inspecciona intencion semantica completa del shell
- no aplica ACL ni aislamiento de procesos

## Recomendacion operativa

Para trabajo sensible:

- usa un repo desechable o copia temporal
- ejecuta el agente con un usuario de pocos privilegios
- si quieres aislamiento fuerte, usa contenedor, VM o sandbox del sistema
