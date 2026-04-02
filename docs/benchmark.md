# Benchmark

## Objetivo

Comparar Ollama Agent frente a Aider y OpenCode en 3 tareas cortas y repetibles.

## Tareas

1. Extraer una utilidad compartida sin romper tests.
2. Añadir documentacion de seguridad alineada con el codigo.
3. Renombrar una variante del producto y actualizar referencias.

## Metrica

- tiempo total
- archivos tocados
- tests pasan o no
- cambios manuales extra requeridos
- errores o regresiones detectadas

## Plantilla de resultados

| Herramienta | Tarea 1 | Tarea 2 | Tarea 3 | Tests | Notas |
|---|---:|---:|---:|---|---|
| Ollama Agent | pendiente | pendiente | pendiente | pendiente | ejecutar con backend local reproducible |
| Aider | pendiente | pendiente | pendiente | pendiente | no estaba instalado en esta maquina |
| OpenCode | pendiente | pendiente | pendiente | pendiente | instalado, pero no se han comprometido numeros no reproducibles |

## Estado actual

En esta maquina:

- `OpenCode` estaba presente como binario local.
- `Aider` no estaba instalado.
- No se han publicado numeros inventados.

Cuando se complete el benchmark, este archivo debe incluir:

- commit exacto benchmarkeado
- modelo usado
- hardware
- comando exacto por herramienta
- log o transcript de cada corrida
