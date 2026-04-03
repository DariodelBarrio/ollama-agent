"""Schemas opcionales de validación para las herramientas expuestas al LLM.

Cuando Pydantic está instalado, estos modelos permiten validar argumentos
antes de invocar la herramienta real y devolver errores más útiles al modelo.
"""

from __future__ import annotations

try:
    from pydantic import BaseModel, Field, ValidationError

    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = Field = ValidationError = None
    PYDANTIC_AVAILABLE = False


if PYDANTIC_AVAILABLE:
    # Cada schema refleja una tool disponible para que la validación sea
    # consistente con las definiciones JSON enviadas al modelo.
    class RunCommandArgs(BaseModel):
        command: str = Field(..., description="Comando a ejecutar.")
        shell: str = Field("auto", description="Shell: 'auto', 'powershell', 'bash', 'sh', 'cmd'.")
        timeout: int = Field(60, description="Tiempo maximo de ejecucion en segundos.")


    class ReadFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")


    class WriteFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")
        content: str = Field(..., description="Contenido a escribir.")


    class EditFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")
        old_text: str = Field(..., description="Texto a buscar.")
        new_text: str = Field(..., description="Texto de reemplazo.")
        replace_all: bool = Field(False, description="Reemplazar todas las ocurrencias.")
        use_regex: bool = Field(False, description="Interpretar old_text como regex.")


    class FindFilesArgs(BaseModel):
        pattern: str = Field(..., description="Patron glob.")
        path: str = Field(".", description="Directorio de busqueda.")


    class GrepArgs(BaseModel):
        pattern: str = Field(..., description="Patron regex a buscar.")
        path: str = Field(".", description="Directorio de busqueda.")
        extension: str = Field("", description="Filtrar por extension (ej. '.py').")


    class ListDirectoryArgs(BaseModel):
        path: str = Field(".", description="Ruta del directorio.")


    class DeleteFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo o carpeta.")


    class CreateDirectoryArgs(BaseModel):
        path: str = Field(..., description="Ruta de la carpeta a crear.")


    class MoveFileArgs(BaseModel):
        src: str = Field(..., description="Ruta origen.")
        dst: str = Field(..., description="Ruta destino.")


    class SearchWebArgs(BaseModel):
        query: str = Field(..., description="Consulta de busqueda.")
        max_results: int = Field(5, description="Numero maximo de resultados.")


    class FetchUrlArgs(BaseModel):
        url: str = Field(..., description="URL a descargar.")
        max_chars: int = Field(4000, description="Maximo de caracteres a retornar.")


    class ChangeDirectoryArgs(BaseModel):
        path: str = Field(..., description="Ruta del nuevo directorio de trabajo.")


    TOOL_SCHEMA_MAP: dict[str, type[BaseModel]] = {
        "run_command": RunCommandArgs,
        "read_file": ReadFileArgs,
        "write_file": WriteFileArgs,
        "edit_file": EditFileArgs,
        "find_files": FindFilesArgs,
        "grep": GrepArgs,
        "list_directory": ListDirectoryArgs,
        "delete_file": DeleteFileArgs,
        "create_directory": CreateDirectoryArgs,
        "move_file": MoveFileArgs,
        "search_web": SearchWebArgs,
        "fetch_url": FetchUrlArgs,
        "change_directory": ChangeDirectoryArgs,
    }
else:
    # Fallback ligero cuando el entorno no incluye Pydantic.
    TOOL_SCHEMA_MAP = {}
