# IA/MEGA legacy compatibility

`IA/MEGA/` se mantiene solo para compatibilidad con flujos anteriores de Windows.

Canonico:

- Agente local: `src/agent.py`
- Agente Hybrid: `src/hybrid/agent.py`
- Launchers Hybrid: `src/hybrid/windows/` y `src/hybrid/unix/`
- Instalacion de dependencias: `python scripts/install.py --hybrid`

Legado:

- `IA/MEGA/agent.py` es un shim que reenvia a `src/hybrid/agent.py`
- Los `.bat` de esta carpeta solo delegan a `src/hybrid/windows/*.bat`
- `requirements-mega.txt` y `--mega` siguen existiendo como alias de compatibilidad
- Para GPUs con menos VRAM, tambien existe `LOCAL CODER [qwen2.5-coder-7b].bat`
- `START OLLAMA.bat` intenta levantar el backend local
- `INSTALL MODEL [qwen2.5-coder-7b].bat` descarga el modelo recomendado para GPUs mas justas

No se versionan artefactos runtime en esta carpeta. Los logs e historial deben
quedar ignorados localmente.
