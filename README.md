# nmr-timing

Estimación y comparación de tiempos de cálculo (wall-time y core-hours) a
partir de los archivos de salida de cálculos NMR hechos con **ReSpect**
(4 componentes), **ADF/ZORA** y **Gaussian (DFT)**.

Pensado para comparaciones *estimativas* entre niveles de teoría cuando los
cálculos se corrieron en distintas máquinas y con distinto número de cores.
El comparador justo es **core-hours** (= wall_hours × n_cores), pero hay que
leerlo como **orden de magnitud**: ReSpect 4c con bases pesadas (p. ej.
upcS-3) no escala igual que DFT.

---

## Qué extrae de cada formato

| Formato  | Detección (por contenido)        | Cores            | Wall-time                                   | Exactitud |
|----------|----------------------------------|------------------|---------------------------------------------|-----------|
| ReSpect  | `ReSpect program, version`       | `--nt=N`         | suma de cada `elapsed time H:MM:SS`         | **real**  |
| ADF/ZORA | header `NMR 2019` / `<Mon..>`    | `Procs: N`       | último timestamp − primero (por línea)      | aprox (incluye IO) |
| Gaussian | `Entering Gaussian System`       | `%nprocshared`   | `Elapsed time` si existe (G16); si no, `Job cpu time / ncores` | G16 real / G09 **estimado** |

La columna `time_source` de la salida indica de dónde salió cada número, para
que en el paper quede explícito qué tan exacto es.

### Cálculos ReSpect cortados (relanzados)
Si una corrida murió y la relanzaste, vas a tener **dos o más archivos** del
mismo cálculo. El programa los **agrupa por el `Work directory`** que ReSpect
imprime adentro de cada archivo, los ordena cronológicamente por `Starting
time` y **suma los wall-times**, contando cuántos reinicios hubo
(`n_restarts`). No hace falta que los concatenes a mano.

---

## Cómo organizar tus archivos

La regla de oro: **una carpeta por cálculo lógico** (un sistema + un método).
El nombre de esa carpeta se usa como etiqueta `system` en la tabla.

```
mis_calculos/                  <- raíz que le pasás al programa
│
├── 01_HALO1_respect/          <- un cálculo ReSpect (4c)
│   ├── slurm-2350591.out          (si NO se cortó: un solo .out)
│   │
│   └── # si SE cortó y relanzaste, poné los fragmentos juntos acá:
│       slurm-2350591_part1.out
│       slurm-2350591_part2.out    (se suman automáticamente)
│
├── 01_HALO1_zora/             <- el mismo sistema en ZORA
│   └── nmr_ZORA.log
│
├── 01_HALO1_dft/              <- el mismo sistema en DFT/Gaussian
│   └── 01_RS_011_nmr.log
│
├── 02_HALO2_respect/
│   └── ...
└── ...
```

### Reglas concretas
1. **Una subcarpeta = un cálculo.** No mezcles dos sistemas distintos ni dos
   métodos distintos en la misma carpeta.
2. **Para ReSpect cortado:** dejá todos los fragmentos en la misma carpeta.
   Se agrupan por el `Work directory` interno, así que aunque cambies el
   nombre del archivo se suman igual (mientras el `Work directory` coincida).
3. **Nombrá las carpetas de forma consistente** para poder cruzar el mismo
   sistema entre métodos, por ejemplo `01_HALO1_<metodo>`. La parte común
   (`01_HALO1`) te deja agrupar después en Excel.
4. **Extensiones:** por defecto escanea `.out`, `.log`, `.txt`. Los archivos
   de ReSpect suelen ser `.out` (salida SLURM) y los de ZORA/Gaussian `.log`.
5. **No importa que sobren archivos** (`.chk`, `.gjc`, inputs): el detector
   ignora todo lo que no sea una salida reconocible.

> Tip: el campo `basis` se intenta detectar pero es best-effort. Si querés que
> aparezca siempre (p. ej. `upcS-3`), lo más robusto es ponerlo en el nombre
> de la carpeta y editar/agregar la columna en el Excel resultante, o avisame
> y agrego lectura de basis desde un archivo `meta.txt` opcional por carpeta.

---

## Instalación

```bash
git clone https://github.com/<tu-usuario>/nmr-timing.git
cd nmr-timing
pip install -r requirements.txt
# (opcional) pip install -e .
```

Requiere Python 3.9+.

## Uso

Escanear una raíz completa e imprimir la tabla:

```bash
python -m nmr_timing.cli mis_calculos/
```

Exportar a CSV y Excel:

```bash
python -m nmr_timing.cli mis_calculos/ --csv tiempos.csv --excel tiempos.xlsx
```

Archivos sueltos (sin estructura de carpetas):

```bash
python -m nmr_timing.cli a.out b.log c.log
```

Cambiar extensiones a escanear:

```bash
python -m nmr_timing.cli mis_calculos/ --ext .out,.log
```

### Salida

Una fila por cálculo lógico con estas columnas:

| columna        | significado |
|----------------|-------------|
| `system`       | etiqueta (nombre de la carpeta) |
| `calc_type`    | `respect` / `zora` / `gaussian` |
| `method`       | método detectado (p. ej. `4c-mDKS`, `mPW1PW91/GenECP`, `ZORA`) |
| `basis`        | base (best-effort) |
| `n_cores`      | cores usados |
| `wall_hours`   | tiempo de pared (horas) |
| `core_hours`   | `wall_hours × n_cores` → comparador entre máquinas |
| `n_steps`      | ReSpect: nº de sub-jobs sumados (scf/cs/…) |
| `n_restarts`   | ReSpect: nº de reinicios detectados |
| `completed`    | terminó normalmente |
| `time_source`  | de dónde salió el wall-time |
| `notes`        | mezcla de cores, fragmentos unidos, estimaciones, etc. |

Además imprime un resumen de `core_hours` agregado por tipo de cálculo.

---

## Caveats (importantes para el paper)

- **core-hours = orden de magnitud, no precisión.** El escalado no es lineal y
  difiere entre métodos; sirve para mostrar el efecto, no para benchmarking
  estricto.
- **Fuentes de tiempo heterogéneas:** ReSpect da wall real; Gaussian G09 da CPU
  (se estima wall = CPU/cores); ZORA usa diferencia de timestamps (incluye IO y
  setup). La columna `time_source` lo deja explícito por fila.
- **Cálculos incompletos:** no rompen el análisis; quedan con `completed=False`
  y los tiempos parciales que se hayan podido leer.

## Estructura del repo

```
nmr-timing/
├── nmr_timing/
│   ├── __init__.py
│   ├── parsers.py      # detección de tipo + 3 parsers -> CalcResult
│   ├── aggregate.py    # agrupa fragmentos ReSpect, escanea carpetas
│   └── cli.py          # CLI + export CSV/Excel + resumen
├── examples/           # archivos de muestra
├── requirements.txt
└── README.md
```

## Roadmap / posibles extensiones

- Lectura opcional de `meta.txt` por carpeta para fijar `basis`, `method`,
  solvente, etc.
- Normalización de wall-time a un nº de cores de referencia (con disclaimer de
  escalado no lineal).
- Soporte a más pasos de ReSpect (`--rsp`, `--esr`) ya contemplado en el parser.
