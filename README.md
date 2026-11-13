# Laboratorio Airflow: ingesta de archivos `.dat` a SQL Server (local)

Pipeline que recibe archivos `schema_tabla_YYYYMMDD.dat`, los copia sin tocar a **raw**, los valida y normaliza contra un contrato YAML, deja el resultado en **curated** (o el detalle de errores en **rejected**), los carga a SQL Server con staging + publicación transaccional, concilia lo publicado contra los archivos de control, registra todo en una tabla de auditoría y manda un correo de resumen.

Corre en el `docker-compose` oficial de **Airflow 3.4.0** (CeleryExecutor) más SQL Server 2022 y Mailpit. El diseño separa:

- **`lab_pipeline/`**: núcleo en Python puro, **sin imports de Airflow**. Toda la lógica de negocio vive acá y se prueba con pytest.
- **`dags/lab_archivos_dag.py`**: solo orquestación. Cada tarea llama a una función de `lab_pipeline.pasos` y traduce excepciones a la semántica de Airflow.

Para pasar a Azure o Google alcanza con escribir `storage/azure.py` o `storage/gcs.py` y un YAML de entorno nuevo. Ni la normalización ni el DAG cambian.

---

## Estado

| Checklist del paso 9 | Estado |
|---|---|
| `pytest` pasa completo | ✅ 84 unitarios (host) + 4 de integración contra SQL Server (worker) |
| Los 11 escenarios dan el estado esperado | ✅ ver [tabla de escenarios](#escenarios-paso-8) |
| Reejecutar todo de cero da los mismos resultados | ✅ `evidencias/local/reproceso-desde-cero/RESUMEN.txt` |
| Sin credenciales en el repo (`git grep -i -E "password\|pwd=\|secret"`) | ✅ solo aparecen placeholders del `.env.example` y nombres de variables; `.env` en `.gitignore` |
| Los logs no muestran cadenas de conexión ni filas de datos | ✅ 0 coincidencias de `PWD=`/`password`/`UID=` y de valores de registros; solo aparecen totales de control del lote (ver notas) |
| El DAG no importa `storage/local.py` | ✅ usa `Entorno.storage()`, que lo elige según `config/entornos/<lab_entorno>.yaml` |
| README con los pasos | ✅ este archivo |
| Capturas de la vista Grid | ⚠️ reemplazadas por `tareas.txt` (estado de cada tarea por CLI). Si las piden como imagen, hay que sacarlas a mano desde la UI |

---

## Estructura

```
├── dags/lab_archivos_dag.py         # orquestacion: TaskGroup por tabla generado desde los YAML
├── lab_pipeline/                    # nucleo (montado en /opt/airflow/src, PYTHONPATH)
│   ├── config/tablas/lab_clientes.yaml, lab_ventas.yaml   # contratos: unica fuente de verdad
│   ├── config/entornos/local.yaml   # lo unico que cambia por entorno
│   ├── contrato.py                  # carga y valida los YAML; orden de carga por dependencias
│   ├── entorno.py                   # lee el YAML de entorno y fabrica el Storage
│   ├── nombres.py                   # parseo de schema_tabla_YYYYMMDD.dat, lote_id, rutas por zona
│   ├── storage/base.py, local.py    # interfaz Storage + implementacion con escritura atomica
│   ├── control.py                   # sha256, estructura, .ctl, sumatorias, validacion pre-carga
│   ├── normalizacion.py             # reglas por tipo logico, errores acumulados
│   ├── carga_sql.py                 # staging, validaciones, publicacion transaccional
│   ├── conciliacion.py, auditoria.py, resumen.py
│   ├── errores.py                   # ErrorCalidad / ErrorTransitorio y subclases
│   └── pasos.py                     # una funcion por tarea del DAG
├── sql/00..03_*.sql, crear_base.ps1 # base, login, tablas (idempotentes)
├── tests/                           # pytest (unitarios + integracion)
├── datos/
│   ├── prompts/                     # prompts usados con la IA
│   ├── generar_sinteticos.py        # generador deterministico (respuesta a los prompts)
│   ├── validos/{originales,esperados}/, manifiesto.json
│   └── negativos/
├── scripts/
│   ├── verificar_manifiesto.sh      # verificacion independiente (awk/sha256sum, sin Python)
│   ├── escenario.sh                 # dispara un escenario y junta evidencias
│   ├── correr_escenarios.sh         # todos los escenarios automatizables en serie
│   ├── clear_tarea.sh               # "Clear" de una tarea via API REST (escenarios 6 y 10)
│   ├── reset_lab.sh                 # vacia tablas, lab_data y Mailpit
│   ├── test_integracion.sh          # corre test_idempotencia.py dentro del worker
│   └── evidencia_sql.py
└── evidencias/local/<escenario>/    # tareas, audit_lote, .ctl, rejected, correo
```

Zonas en `lab_data/` (volumen compartido por todos los contenedores de Airflow):

```
entrada/                                   # llegan los .dat (no se borran)
raw/fecha=2026-11-09/lote=<lote_id>/       # copia exacta + .ctl
curated/fecha=2026-11-09/lote=<lote_id>/   # normalizado + .ctl
rejected/fecha=2026-11-09/lote=<lote_id>/  # <archivo>.errores.json
```

`lote_id` es determinístico: `lab.ventas-20261109-<12 primeros del sha256>`. El mismo archivo siempre cae en el mismo lote.

---

## Cómo levantarlo

```bash
# 1. Configuracion (nunca commitear .env)
cp .env.example .env              # completar passwords y FERNET_KEY

# 2. Imagen con msodbcsql18 + requirements y arranque
docker compose build
docker compose up -d

# 3. Base, login lab_user y tablas (como sa; el pipeline nunca usa sa)
powershell -File sql/crear_base.ps1     # lee las passwords del .env

# 4. Verificaciones
docker compose exec airflow-worker python -c "import pyodbc; print(pyodbc.drivers())"
docker compose exec airflow-worker python -c "from airflow.providers.odbc.hooks.odbc import OdbcHook; print(OdbcHook(odbc_conn_id='mssql_lab').get_first('SELECT 1'))"
# Mailpit: http://localhost:8025   Airflow: http://localhost:8080 (airflow/airflow)

# 5. Activar el DAG
docker compose exec airflow-scheduler airflow dags unpause lab_archivos
```

Conexiones (en `.env`, como `AIRFLOW_CONN_*` en JSON):

| conn_id | Uso |
|---|---|
| `mssql_lab` | SQL Server con `lab_user`, que solo tiene SELECT/INSERT/UPDATE/DELETE sobre el schema `lab` y no puede crear tablas |
| `smtp_mailpit` | **la que usa `local.yaml`**: Mailpit en `mailpit:1025`, sin TLS ni credenciales |
| `smtp_lab` | Gmail real (ya estaba en el `.env`). No se usa en local para no mandar correos reales en cada prueba |

Variables de Airflow: `lab_entorno` (viene del compose, `local`), `lab_mail_destinatario` (opcional, pisa al destinatario del YAML) y `lab_demora_publicacion_s` (solo para el escenario 9; normalmente `0`).

### Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q                      # 84 unitarios, sin Airflow ni SQL
bash scripts/test_integracion.sh         # 4 de integracion dentro del worker, contra SQL Server
bash scripts/verificar_manifiesto.sh     # verificacion independiente de los datos sinteticos
```

### Disparar el DAG

```bash
# Desde la UI: Trigger con param fecha_negocio. Por CLI:
docker compose exec airflow-scheduler airflow dags trigger lab_archivos -c '{"fecha_negocio": "2026-11-09"}'

# O con evidencias automaticas:
bash scripts/escenario.sh 01-validos 2026-11-09 datos/validos/originales/*_20261109.dat
bash scripts/reset_lab.sh && bash scripts/correr_escenarios.sh reproceso-desde-cero
```

---

## El DAG

```
clientes: recibir → a_raw → normalizar → validar_precarga → cargar_staging → validar_staging → publicar → conciliar ─┐
                                                                                                                  ▼
ventas:   recibir → a_raw → normalizar → validar_precarga → cargar_staging → validar_staging → verificar_dependencias → publicar → conciliar
                                                                                                                                    │
                                                              enviar_resumen (ALL_DONE) → verificar_estado_final (ALL_DONE) ◄──────┘
```

- Hay un **TaskGroup por tabla**, generado en un loop desde los YAML. `orden_de_carga()` resuelve `depende_de` y detecta ciclos.
- Por XCom solo viajan dicts chicos: rutas, `lote_id`, `audit_id` y estado. Nunca datos.
- **Errores de calidad vs. transitorios.** `ErrorCalidad` y sus subclases se convierten en `AirflowFailException`, que falla sin reintentar. Cualquier otra excepción (`pyodbc.OperationalError`, I/O) sube tal cual y se aplican `retries=3` con backoff exponencial. `LoteYaProcesado` y "no llegó archivo" se convierten en `AirflowSkipException`.
- **`verificar_dependencias`** usa `ALL_DONE` para correr aunque clientes haya fallado y así poder marcar ventas como `BLOQUEADO_DEPENDENCIA`. Si la propia tabla no llegó a staging, se saltea.
- **`on_failure_callback`**: si una tarea muere por un error técnico sin reintentos pendientes, marca la fila de auditoría como `FALLIDO` con el tipo y el mensaje de la excepción. No pisa estados ya informados (RECHAZADO, CONFLICTO...).
- **Trampa del estado final**: `verificar_estado_final` corre después del correo y lee `lab.audit_lote` (en Airflow 3 las tareas no pueden consultar la base de metadatos). Si algún archivo no quedó `CORRECTO` ni `YA_PROCESADO`, el run termina `failed` aunque el correo haya salido bien.
- Cada conexión SQL tiene `conn.timeout = 30`. Sin eso, un SQL Server colgado deja la tarea esperando para siempre (ver escenario 9).

### Estados de auditoría

`EN_PROCESO → PUBLICADO → CORRECTO` (CORRECTO solo después de conciliar). Si algo falla: `RECHAZADO` (calidad), `FALLIDO` (técnico, integridad o conciliación), `BLOQUEADO_DEPENDENCIA`, `YA_PROCESADO` o `CONFLICTO`, siempre con `motivo`. El detalle por registro y columna queda en `lab.audit_error` y en `rejected/.../<archivo>.errores.json`.

Idempotencia, decidida en la recepción (`auditoria.decidir_recepcion`):

| Situación | Estado | Acción |
|---|---|---|
| Nombre nuevo | EN_PROCESO | procesar |
| Mismo nombre y sha256, ya CORRECTO | YA_PROCESADO | saltear el resto del grupo |
| Mismo nombre, sha256 distinto | CONFLICTO | no tocar raw ni SQL |
| Mismo nombre y sha256, intento previo no correcto | EN_PROCESO | reprocesar |

### Publicación

Es una transacción por tabla con `SET XACT_ABORT ON`:

1. Chequea con `UPDLOCK, HOLDLOCK` que el lote no esté ya publicado.
2. Hace `INSERT ... SELECT` desde staging.
3. Borra el staging del lote.
4. Marca `PUBLICADO` en la auditoría.
5. Hace `COMMIT`.

Cualquier error revierte todo, incluidos un timeout del cliente o un corte de conexión. Si un reintento encuentra el lote ya publicado, no reinserta: limpia el staging y sigue a conciliar. La transacción la maneja Python (pyodbc con `autocommit=False`) en lugar de un `BEGIN TRAN`/`THROW 50001` en T-SQL. Es equivalente y evita anidar transacciones con la transacción implícita de pyodbc.

---

## Datos sintéticos (paso 4)

- Los prompts están en `datos/prompts/`. La "respuesta de la IA" quedó como **generador determinístico** (`datos/generar_sinteticos.py`, semilla fija). El generador parte de los valores **limpios**, escribe con ellos el normalizado esperado y después "ensucia" cada valor para producir el original. Así el esperado no depende del código que se está probando.
- Son 20 clientes y 100 ventas, con **315 anomalías** registradas en el manifiesto: espacios externos, emails en mayúsculas, país en minúsculas, fechas en los 3 formatos, `sí/SÍ/Si/true/1/no/NO/false/0`, coma decimal, `NULL/N/A/null/espacios` en observación, comillas internas duplicadas y acentos en UTF-8.
- El manifiesto no se da por bueno: `scripts/verificar_manifiesto.sh` recalcula conteos, sumas, sha256 y la integridad referencial con `tail/wc/awk/sha256sum`. Salida en `evidencias/local/00-verificacion-manifiesto.txt`. Probé que el script **detecta** una alteración: cambiar un importe en 0.01 da 2 diferencias.
- El test `test_sintetico_original_normaliza_igual_al_esperado_byte_a_byte` compara la salida del pipeline con el esperado byte a byte. Además, en el escenario 1 el curated que generó Airflow tiene **el mismo sha256** que `datos/validos/esperados/`.

---

## Escenarios (paso 8)

Evidencias en `evidencias/local/<escenario>/`: `tareas.txt` (estado de cada tarea, el equivalente textual del Grid), `audit_lote.txt` (`SELECT` de `lab.audit_lote` y `lab.audit_error` del run, más conteos en destino), `.ctl` raw y curated, `rejected__*.errores.json`, y `correo.html` + `correo_asunto.txt` (desde la API de Mailpit).

| # | Escenario | Archivo(s) | Resultado obtenido | Run |
|---|---|---|---|---|
| 1 | Válidos con anomalías corregibles | 20261109 | clientes y ventas **CORRECTO**; 20 y 100 filas; cantidad 633 e importe 1207807.85 = manifiesto | success |
| 2a | Fecha imposible | clientes 20261110 | **RECHAZADO**: reg 2, fecha_alta `31/02/2026`: fecha inexistente | failed |
| 2b | Obligatorio vacío | clientes 20261111 | **RECHAZADO**: reg 2, nombre: obligatorio vacío | failed |
| 3 | Columnas faltantes | ventas 20261112 | **RECHAZADO** estructural: reg 2 tiene 6 columnas, se esperan 7 | failed |
| 4a | Clave duplicada | ventas 20261113 | **RECHAZADO**: reg 3, venta_id 1302 duplicada; destino sin cambios | failed |
| 4b | Cliente inexistente | ventas 20261114 | **RECHAZADO** (etapa referencias): cliente_id 999 inexistente; destino sin cambios | failed |
| 5 | Solo encabezado | clientes 20261116 | **RECHAZADO**: archivo sin registros | failed |
| 6 | Control alterado | `.ctl` curated de ventas editado + Clear de `validar_precarga` | **FALLIDO** antes de cargar: sumatorias del curated distintas al .ctl. Al restaurar el `.ctl` y repetir el Clear: CORRECTO, sin reinsertar | failed / success |
| 7 | Reejecución del lote exitoso | 20261109 de nuevo | ambos **YA_PROCESADO**, resto del grupo skipped, conteos iguales | success |
| 8 | Mismo nombre, otro contenido | importe cambiado en `entrada/lab_ventas_20261109.dat` | ventas **CONFLICTO**; raw y SQL sin tocar | failed |
| 9 | Falla transitoria | 20261119 + `docker pause sqlserver` 50 s en plena publicación | intento 1: `HYT00 Query timeout expired`; intento 2 OK; **CORRECTO**, 30 filas, sin duplicados | success |
| 10 | Diferencia SQL vs control | `UPDATE lab.ventas SET importe_total += 1 WHERE venta_id = 1` + Clear de `conciliar` | **FALLIDO**: importe esperado 1207807.85 vs obtenido 1207808.85 (dif +1.00); correo con la diferencia. Al revertir: CORRECTO | failed / success |
| 11 | Falla de clientes | clientes 20261118 (email inválido) + ventas 20261118 válido | clientes RECHAZADO, ventas **BLOQUEADO_DEPENDENCIA** (aunque su staging validó bien), correo enviado | failed |
| extra | Importe con 3 decimales | ventas 20261115 | **RECHAZADO**: `12,345` no se redondea | failed |
| extra | Moneda USD | ventas 20261117 | **RECHAZADO**: valor no permitido | failed |

Para el 6 y el 10 hace falta "Clear" de una tarea puntual. Como los runs manuales de Airflow 3 no tienen `logical_date`, `airflow tasks clear` no sirve para esto, así que `scripts/clear_tarea.sh` lo hace por la API REST v2 (`clearTaskInstances` con `include_downstream`).

**Reproceso desde cero**: después de `reset_lab.sh`, `correr_escenarios.sh` repite todos los escenarios automatizables (todos menos 6, 9 y 10, que necesitan intervención manual) y deja el resumen en `evidencias/local/reproceso-desde-cero/RESUMEN.txt`. Todos los estados coincidieron con la primera pasada. Incluye además el caso `19-clientes-nuevos-mismo-dia`: clientes y ventas del 19 quedan ambos CORRECTO (25 clientes y 130 ventas en total), lo que confirma la corrección del bug de la bitácora (punto 8).

---

## Bitácora: lo que fue pasando

Lo que no salió a la primera y cómo se resolvió, en orden.

1. **Paso 3: los tests no pasaban.** No era un problema de código: faltaban los YAML. `lab_pipeline/config/` estaba vacía y `cargar_contratos()` fallaba con `No hay contratos en ...`. Al crearlos aparecieron dos cosas más:
   - El `.gitignore` tenía `config/` (pensado para la carpeta de Airflow), que **también ignoraba `lab_pipeline/config/`**: los contratos nunca se iban a commitear. Lo cambié a `/config/`.
   - Al `.gitignore` le faltaba el salto de línea final, y la regla que agregué quedó pegada a `.vscode/`.
2. **El SMTP apuntaba a Gmail real.** La conexión `smtp_lab` del `.env` usaba `smtp.gmail.com` con una cuenta personal. Para no mandar un correo real en cada uno de los ~25 runs de prueba, agregué `smtp_mailpit` y la puse en `local.yaml`, como pide la guía. `smtp_lab` quedó intacta.
3. **La IA se equivocó en los datos**, tal como avisa la guía. En la primera versión del generador el apodo "Tomi" (comillas internas) terminó en la cliente 7, Valentina Díaz, con el email de ella. Se detectó revisando las filas a mano y se corrigió para que quedara en Tomás Álvarez (cliente 8).
4. **Error mío en un test**: esperaba "9 columnas" para una fila que tiene 8.
5. **Escenario 1 OK a la primera.** El curated generado en Airflow quedó idéntico byte a byte al esperado, y la conciliación coincidió con el manifiesto verificado con awk.
6. **Staging huérfano en el camino "ya publicado".** En el escenario 6, al hacer Clear, el reintento recargaba staging y `publicar` veía el lote ya publicado y salía sin limpiar: quedaban 100 filas sueltas en `stg_ventas`. Ahora ese camino borra el staging del lote.
7. **Errores viejos en `audit_error`.** Al hacer Clear, el `audit_id` se reutiliza, y la fila CORRECTO del escenario 10 todavía mostraba el error del escenario 6. Ahora el detalle se reemplaza en cada intento y se limpia al quedar CORRECTO.
8. **El bug de diseño más interesante (escenario 9): FK contra clientes del mismo día.** Las ventas del 19 referencian clientes nuevos (191-195) que llegan ese mismo día. Como las tablas avanzan **en paralelo hasta staging**, `ventas.validar_staging` chequeaba la FK antes de que esos clientes se publicaran, y **rechazaba ventas válidas** con "5 cliente_id inexistentes". Con los datos del 09 no aparecía porque todos los clientes eran de un lote ya cargado. La solución: las referencias hacia tablas de `depende_de` se validan en `verificar_dependencias`, después de que la dependencia publica. Las demás validaciones de staging (conteo, identificador existente) siguen en paralelo. El run que destapó el problema quedó en `evidencias/local/09-previo-bug-fk-mismo-dia/`, y el escenario 4b se volvió a correr con el código final (la versión anterior está en `04b-...-version-inicial/`).
9. **Columnas vacías en la CLI.** `airflow tasks states-for-dag-run -o plain` deja `logical_date` vacío y corre las columnas, así que el primer intento de monitorear el escenario 9 nunca vio la tarea en `running` y la pausa no se disparó. Se resolvió parseando la salida `-o table` por `|`.
10. **Cómo provocar el escenario 9 de forma reproducible.** La publicación dura milisegundos, así que es imposible pausar SQL Server "a mitad del INSERT" a mano. Agregué la Variable `lab_demora_publicacion_s`, que hace un `WAITFOR DELAY` dentro de la transacción, después del INSERT y antes del commit. Con `docker pause` en ese momento, el `conn.timeout = 30` corta la sentencia (`HYT00`), `XACT_ABORT ON` revierte el INSERT, Airflow reintenta al minuto y publica una sola vez. Sin el timeout por sentencia, la tarea hubiera quedado colgada indefinidamente.
11. **Tests de integración que corrían código viejo.** `docker compose cp tests worker:/tmp/labtests` copia como root. El `rm -rf` posterior (como usuario airflow) fallaba en silencio, y la segunda copia quedaba **anidada** en `/tmp/labtests/tests`. pytest seguía corriendo la primera versión y daba verde. Lo noté cuando un test que debía fallar pasó. `scripts/test_integracion.sh` ahora copia a un directorio nuevo cada vez.
12. **`/` en el run_id.** La primera corrida "desde cero" se colgó porque el nombre del escenario (`reproceso-desde-cero/01-validos`) terminaba en el run_id, Airflow rechazaba el trigger y el script esperaba un run inexistente. Ahora se reemplaza `/` y el script falla enseguida si el trigger no se acepta.
13. **Dos corridas a la vez.** Al cortar esa corrida colgada se mató el proceso padre, pero el `correr_escenarios.sh` hijo siguió vivo y continuó con el script ya corregido, intercalando escenarios con la corrida nueva (01 → 11 → 07 → 12). `max_active_runs=1` evitó que se pisaran dentro de Airflow, pero se mezclaban los archivos de `entrada/` y el reset. Se mataron los procesos sueltos (`ps -ef | grep escenario`), se reseteó y se corrió una sola vez. Al cortar un script de escenarios, hay que verificar que no queden hijos vivos.

---

## Decisiones y notas

- **Dependencia sin archivo.** Ventas se bloquea solo si clientes **tuvo archivo** ese día y no quedó OK. Si no llegó clientes, ventas sigue y la FK se valida contra lo ya publicado. Sin esta regla, los escenarios 3 y 4 (que solo traen ventas) quedarían bloqueados en vez de rechazados.
- **CONFLICTO.** Se aplica la tabla de la guía al pie de la letra: mismo nombre con otro sha256 es conflicto aunque el intento previo haya sido RECHAZADO. Para corregir un archivo rechazado hay que mandarlo con otra fecha o nombre. Las filas CONFLICTO no cuentan como historia, así que el archivo original sigue dando YA_PROCESADO.
- **Staging de lotes rechazados.** Se conserva para diagnosticar y lo limpia el próximo intento del mismo lote. Al publicar, el staging del lote se borra dentro de la misma transacción.
- **Logs.** No se loguean valores de registros. El detalle va a `rejected/` y a `audit_error`, y los mensajes de excepción solo traen conteos. Lo único con números de negocio es el mensaje de conciliación (totales esperado/obtenido del lote), que hace falta para entender la falla.
- **`verificar_estado_final` sin archivos.** Si no se registró ningún archivo en el run (por ejemplo, una fecha sin archivos en `entrada/`), falla. Prefiero que un olvido se vea rojo.
- **Sumas en `audit_lote`.** La tabla tiene columnas fijas `suma_cantidad_*` y `suma_importe_*`, y `auditoria.MAPA_SUMAS` traduce las `columnas_suma` del contrato. Una tabla nueva con otras sumas necesitaría columnas nuevas o una tabla de sumatorias por lote.
- **`__pycache__/`** ya está en `.gitignore`, pero hay `.pyc` versionados de antes. Para sacarlos: `git rm -r --cached lab_pipeline/__pycache__ tests/__pycache__`.

## Próximo paso: Azure / Google

1. `lab_pipeline/storage/azure.py` (Blob, `upload_blob(overwrite=False)`) y `storage/gcs.py` (`if_generation_match=0` para no sobrescribir), registrados en `entorno.crear_storage()`.
2. `config/entornos/azure.yaml` y `gcp.yaml` con el tipo de storage, el contenedor o bucket y los conn_id de Azure SQL / Cloud SQL y del correo.
3. `AIRFLOW_VAR_LAB_ENTORNO=azure|gcp` en AKS / Composer.
