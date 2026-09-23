# semif-qwen3-5-4b-twitter-eval

> Live eval of Twitter sentiment with Qwen3.5-4B via SemIf API — FastAPI + SSE UI with confusion matrix, accuracy and per-class metrics vs original labels.

Evalúa en vivo la clasificación de sentimiento de tweets con un LLM open-source y la compara con las etiquetas originales del dataset, en una interfaz web en tiempo real.

## Demo en video

Grabación del proyecto en funcionamiento. Se ve la clasificación fila por fila, la matriz de confusión actualizándose en vivo y la comparación final con las etiquetas originales:

<video controls width="100%">
  <source src="https://github.com/user-attachments/assets/05a524c2-c54a-4a2f-b952-63a3d00baa32" type="video/mp4">
</video>

Respaldo en el repo: [`Video/demo.mp4`](Video/demo.mp4)

## Qué hace este proyecto

1. Lee `archive/twitter_training.csv` (CSV sin cabecera, 74.682 filas).
2. Toma solo el texto del tweet (columna D).
3. Le pregunta a un modelo LLM: “¿cuál es el sentimiento de este tweet?”.
4. El modelo elige entre 4 clases (las mismas de la columna C).
5. La app compara la predicción con la etiqueta original y muestra en vivo:
   - fila actual, accuracy, latencia,
   - matriz de confusión,
   - métricas por clase,
   - lista de filas mal clasificadas.

```
Navegador ──SSE──► FastAPI (este repo) ──HTTP /decide──► SemIf API ──► Qwen3.5-4B (GPU local)
```

Este repo **no contiene el modelo**. Es un cliente HTTP + interfaz de evaluación. El modelo corre en la API SemIf, ya montada por separado.

## Modelo open-source usado

- **Modelo:** `Qwen/Qwen3.5-4B` (open-source, Qwen)
- **Cómo corre:** montado en local con el proyecto SemIf (`/ready` → `{"status":"ready", "model":"Qwen/Qwen3.5-4B"}`)
- **Hardware medido:** `cuda:0`, `bfloat16`
- **Velocidad medida:** ~200 ms por tweet (~40 s para 200 filas)
- **Modo de uso:** sin fine-tuning. Por cada tweet se envía:
  - `state` → texto del tweet (recortado a 4000 caracteres),
  - `question` → `"What is the sentiment of this tweet about the given topic?"`,
  - `options` → las 4 clases con su descripción (ver abajo).

  SemIf devuelve una probabilidad por clase y nos quedamos con la mayor.

## Opciones de clasificación

Son las clases de la columna C del CSV. Cada una se envía al modelo con su descripción en inglés (así está en `config.toml`):

| Clase | Significado | Descripción enviada al modelo |
|---|---|---|
| `positive` | El tweet habla bien del tema, apoya o muestra entusiasmo. | `The tweet expresses a positive, favorable or supportive sentiment about the topic.` |
| `negative` | El tweet critica, se queja o habla mal del tema. | `The tweet expresses a negative, critical or unfavorable sentiment about the topic.` |
| `neutral` | El tweet solo informa, sin carga positiva ni negativa. | `The tweet is factual or informational and expresses no clear positive or negative sentiment about the topic.` |
| `irrelevant` | El tweet no trata realmente del tema, es ruido. | `The tweet is not actually about the topic, or is off-topic noise.` |

## Resultado: 58% de accuracy, pero el modelo parece mejor que el dataset

Última corrida de referencia (200 filas, `results/metrics.json`):

- **Accuracy: 0.58 (116/200)**
- `positive`: P 0.65 / R 0.81 / F1 0.72
- `negative`: P 0.54 / R 0.96 / F1 0.69
- `neutral`: P 0.50 / R 0.09 / F1 0.16
- `irrelevant`: P 0.00 / R 0.00 / F1 0.00

Matriz (`gold → predicho`):

```
gold\predicted,positive,negative,neutral,irrelevant
positive,68,10,5,1
negative,1,43,0,1
neutral,23,20,5,5
irrelevant,12,6,0,0
```

Revisando a mano los “fallos”, gran parte del error parece estar en las **etiquetas originales**, no en el modelo. Ejemplos reales de `results/predictions.jsonl`:

- Texto: `im getting on borderlands and i will murder you all`
  - Base: `positive` → Modelo: `negative`. El modelo tiene razón.
- Texto: `that was the first borderlands session [...] i actually had a really bad combat experience`
  - Base: `positive` → Modelo: `negative`. El modelo tiene razón.
- Texto: `Rock-Hard La Varlope, RARE & POWERFUL, HANDSOME JACKPOT, Borderlands 3 (Xbox)...`
  - Base: `neutral` → Modelo: `positive`. Es un anuncio promocional, la predicción es razonable.

En resumen: el 58% mide **acuerdo con una base ruidosa**, no calidad real. El modelo open-source clasifica con criterio bastante sensato.

## Requisitos

- `uv` instalado (gestiona Python 3.11 solo).
- API SemIf corriendo con el modelo cargado:
  ```bash
  curl http://localhost:8000/ready
  # -> {"status":"ready","model":"Qwen/Qwen3.5-4B", ...}
  ```
- Dataset en `archive/twitter_training.csv` (ya incluido en este repo).

## Arranque

```bash
uv sync
uv run python -m twitter_eval
```

Elige un puerto libre desde `8050`, imprime la URL y abre el navegador:

```bash
uv run python -m twitter_eval --port 9000 --no-browser
```

Uso en la UI:

1. Ajusta **Filas** (por defecto 300, `0` = todo el archivo).
2. Elige **Muestra**: primeras N filas o aleatoria reproducible.
3. Pulsa **Iniciar**. Puedes **Pausar / Reanudar / Detener** en cualquier momento.
4. Al terminar verás el panel de comparación final y las filas mal clasificadas.

## Configuración (`config.toml`)

| Clave | Descripción |
|---|---|
| `semif_api_url` | URL de la API SemIf (`http://localhost:8000`). |
| `csv_path` | CSV sin cabecera. Columnas: A=ID, B=topic, C=label, D=texto. |
| `limit` / `sample` / `seed` | Nº de filas, modo `head` \| `random`, semilla. |
| `question` | Criterio enviado al modelo. |
| `max_state_chars` | Recorte defensivo (SemIf no trunca, falla si desborda). |
| `[[labels]]` | Las 4 clases y sus descripciones. |
| `host` / `preferred_port` | Servidor de la UI. |

Se puede sobreescribir con env: `SEMIF_API_URL`, `TWITTER_EVAL_CSV`, `TWITTER_EVAL_LIMIT`, `TWITTER_EVAL_RESULTS_DIR`.

## Salidas

En `results/` tras cada corrida (carpeta ignorada por git):

- `predictions.jsonl` — una línea por fila (real, predicho, scores, tiempos).
- `metrics.json` — accuracy, macro/weighted, por clase, matriz y metadatos.
- `confusion_matrix.csv` — matriz en CSV.

API de la UI:

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/snapshot` | Estado completo. |
| `GET` | `/events` | Stream SSE, un evento por fila. |
| `GET` | `/api/semif` | Readiness de SemIf. |
| `GET` | `/api/results` / `/api/misclassified` | Resultados y fallos. |
| `POST` | `/api/start` `/api/pause` `/api/resume` `/api/stop` | Control. |

## Estructura

```
src/twitter_eval/
  config.py    carga de config.toml + entorno
  labels.py    vocabulario de clases y opciones SemIf
  dataset.py   lectura y muestreo del CSV
  client.py    cliente httpx de SemIf (reintentos, /ready, /decide)
  metrics.py   métricas incrementales
  runner.py    orquestación y bus de eventos
  server.py    FastAPI + SSE
  __main__.py  puerto libre + uvicorn + navegador
web/           UI (index.html, app.js, styles.css)
Video/demo.mp4 demo en funcionamiento
archive/       twitter_training.csv + twitter_validation.csv
```
