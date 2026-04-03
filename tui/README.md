# ollama-agent TUI (`oat`)

Launcher de terminal para los agentes local e hybrid. Reemplaza los
launchers `.bat` / `.sh` con un configurador interactivo con perfiles guardados.

## Requisitos

- [Rust](https://rustup.rs/) 1.75+
- El agente Python debe estar instalado y funcionando (ver README principal)

## Build

```bash
cd tui
cargo build --release
```

El binario queda en `tui/target/release/oat` (Linux/macOS) o `tui\target\release\oat.exe` (Windows).

Opcional — instalar en PATH:

```bash
# Linux/macOS
cargo install --path .

# Windows (desde PowerShell)
cargo install --path .     # instala en %USERPROFILE%\.cargo\bin\oat.exe
```

## Uso

```bash
# Desde la raíz del repo
./tui/target/release/oat

# O si está instalado en PATH
oat

# Desde fuera del repo
OLLAMA_AGENT_ROOT=/ruta/al/repo oat     # Linux/macOS
set OLLAMA_AGENT_ROOT=C:\ruta\repo && oat  # Windows
```

## Teclas

### Menú principal

| Tecla | Acción |
|---|---|
| `j` / `↓` | Bajar |
| `k` / `↑` | Subir |
| `Enter` | Seleccionar |
| `q` | Salir |

### Configurar agente

| Tecla | Acción |
|---|---|
| `Tab` / `↓` | Siguiente campo |
| `Shift+Tab` / `↑` | Campo anterior |
| `Enter` | Editar campo de texto |
| `Esc` | Cancelar edición / volver al menú |
| `Space` / `Enter` | Alternar bool o ciclar opción select |
| `F5` | Lanzar agente con la configuración actual |
| `F2` | Guardar perfil |
| `Ctrl+S` | Guardar perfil (alternativa) |

### Gestión de perfiles

| Tecla | Acción |
|---|---|
| `j` / `↓` | Bajar |
| `k` / `↑` | Subir |
| `Enter` | Cargar perfil seleccionado |
| `d` | Eliminar perfil seleccionado |
| `Esc` | Volver al menú |

## Perfiles

Los perfiles se guardan en:

- Linux/macOS: `~/.config/ollama-agent/profiles.toml`
- Windows: `%APPDATA%\ollama-agent\profiles.toml`

Formato TOML editable a mano si es necesario.

## Flujo de lanzamiento

1. `oat` arranca la TUI y muestra el menú principal.
2. Seleccionas variante → editas parámetros → `F5`.
3. La TUI suspende su pantalla y lanza el agente Python con los args configurados.
4. El agente corre con su propia TUI (Rich/prompt_toolkit) de forma normal.
5. Cuando el agente termina (`salir` o Ctrl+C), presionas Enter y la TUI se reanuda.

La TUI actúa como configurador/launcher. No sustituye ni duplica la lógica del agente.

## Variables de entorno

| Variable | Uso |
|---|---|
| `OLLAMA_AGENT_ROOT` | Ruta al repo si `oat` se ejecuta desde fuera de él |
| `GROQ_API_KEY` | Requerida para el modo hybrid con backend groq |
