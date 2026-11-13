# Crea la base, el login y las tablas del laboratorio en el SQL Server del compose.
# Uso (desde la carpeta del proyecto):  .\sql\crear_base.ps1
# Lee las contraseñas del .env, así no quedan escritas en ningún script.

$ErrorActionPreference = "Stop"

# Leer .env (formato CLAVE=valor; ignora comentarios y líneas vacías)
$envVars = @{}
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $envVars[$k.Trim()] = $v.Trim().Trim("'").Trim('"')
}

$saPwd = $envVars['MSSQL_SA_PASSWORD']
# La password de lab_user se toma del JSON de la conexión de Airflow
$labPwd = ($envVars['AIRFLOW_CONN_MSSQL_LAB'] | ConvertFrom-Json).password

if (-not $saPwd -or -not $labPwd) { throw "Faltan MSSQL_SA_PASSWORD o la password en AIRFLOW_CONN_MSSQL_LAB dentro de .env" }

$sqlcmd = "/opt/mssql-tools18/bin/sqlcmd"
$scripts = "00_base_y_login.sql", "01_tablas_destino.sql", "02_tablas_staging.sql", "03_auditoria.sql"

foreach ($s in $scripts) {
    Write-Host "==> $s"
    docker compose exec -T sqlserver $sqlcmd -C -S localhost -U sa -P $saPwd -b -i "/sql/$s" -v "LAB_PWD=$labPwd"
    if ($LASTEXITCODE -ne 0) { throw "Falló $s" }
}

Write-Host "`nTablas creadas:"
docker compose exec -T sqlserver $sqlcmd -C -S localhost -U lab_user -P $labPwd -d labdb -W `
    -Q "SET NOCOUNT ON; SELECT s.name + '.' + t.name AS tabla FROM sys.tables t JOIN sys.schemas s ON s.schema_id = t.schema_id ORDER BY 1"