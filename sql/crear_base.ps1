# Crea la base, el login y las tablas del laboratorio en el SQL Server del compose.
# Uso (desde la carpeta raiz del proyecto):  .\sql\crear_base.ps1
# Lee las passwords del .env, asi no quedan escritas en ningun script.
# Copia los .sql al contenedor, asi no depende de que la carpeta sql/ este montada.

$ErrorActionPreference = "Stop"

if (-not (Test-Path .env)) { throw "No encuentro .env. Ejecuta el script desde la raiz del proyecto." }

# Leer .env (formato CLAVE=valor; ignora comentarios y lineas vacias)
$envVars = @{}
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $envVars[$k.Trim()] = $v.Trim().Trim("'").Trim('"')
}

$saPwd = $envVars['MSSQL_SA_PASSWORD']
# La password de lab_user se toma del JSON de la conexion de Airflow
$labPwd = ($envVars['AIRFLOW_CONN_MSSQL_LAB'] | ConvertFrom-Json).password

if (-not $saPwd -or -not $labPwd) { throw "Faltan MSSQL_SA_PASSWORD o la password dentro de AIRFLOW_CONN_MSSQL_LAB en .env" }

$sqlcmd  = "/opt/mssql-tools18/bin/sqlcmd"
$scripts = "00_base_y_login.sql", "01_tablas_destino.sql", "02_tablas_staging.sql", "03_auditoria.sql"
$dir     = $PSScriptRoot

foreach ($s in $scripts) {
    Write-Host "==> $s"
    docker compose cp (Join-Path $dir $s) "sqlserver:/tmp/$s"
    if ($LASTEXITCODE -ne 0) { throw "No pude copiar $s al contenedor" }
    docker compose exec -T sqlserver $sqlcmd -C -S localhost -U sa -P $saPwd -b -i "/tmp/$s" -v "LAB_PWD=$labPwd"
    if ($LASTEXITCODE -ne 0) { throw "Fallo $s" }
}

Write-Host "`nTablas creadas (conectado como lab_user):"
docker compose exec -T sqlserver $sqlcmd -C -S localhost -U lab_user -P $labPwd -d labdb -W `
    -Q "SET NOCOUNT ON; SELECT s.name + '.' + t.name AS tabla FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id ORDER BY 1"