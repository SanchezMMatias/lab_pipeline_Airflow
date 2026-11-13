USE labdb;
GO
IF OBJECT_ID('lab.audit_lote', 'U') IS NULL
CREATE TABLE lab.audit_lote (
    audit_id          BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_audit_lote PRIMARY KEY,
    archivo           VARCHAR(200)   NOT NULL,
    schema_destino    VARCHAR(50)    NOT NULL,
    tabla_destino     VARCHAR(50)    NOT NULL,
    fecha_negocio     DATE           NOT NULL,
    lote_id           VARCHAR(80)    NOT NULL,
    sha256_origen     CHAR(64)       NOT NULL,
    sha256_curated    CHAR(64)       NULL,
    dag_id            VARCHAR(250)   NOT NULL,
    dag_run_id        VARCHAR(250)   NOT NULL,
    estado            VARCHAR(30)    NOT NULL CONSTRAINT CK_audit_estado CHECK (estado IN (
                        'EN_PROCESO', 'PUBLICADO', 'CORRECTO', 'RECHAZADO', 'FALLIDO',
                        'BLOQUEADO_DEPENDENCIA', 'YA_PROCESADO', 'CONFLICTO')),
    registros_esp     INT            NULL,
    registros_obt     INT            NULL,
    suma_cantidad_esp BIGINT         NULL,
    suma_cantidad_obt BIGINT         NULL,
    suma_importe_esp  DECIMAL(18,2)  NULL,
    suma_importe_obt  DECIMAL(18,2)  NULL,
    motivo            NVARCHAR(4000) NULL,
    inicio_utc        DATETIME2(3)   NOT NULL CONSTRAINT DF_audit_inicio DEFAULT SYSUTCDATETIME(),
    fin_utc           DATETIME2(3)   NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_audit_archivo')
    CREATE INDEX IX_audit_archivo ON lab.audit_lote (archivo, sha256_origen, estado);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_audit_run')
    CREATE INDEX IX_audit_run ON lab.audit_lote (dag_run_id);
GO
-- Detalle de errores por registro/columna (complementa el archivo en rejected/)
IF OBJECT_ID('lab.audit_error', 'U') IS NULL
CREATE TABLE lab.audit_error (
    error_id      BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_audit_error PRIMARY KEY,
    audit_id      BIGINT         NOT NULL CONSTRAINT FK_audit_error_lote REFERENCES lab.audit_lote (audit_id),
    nro_registro  INT            NULL,
    columna       VARCHAR(128)   NULL,
    valor         NVARCHAR(400)  NULL,
    motivo        NVARCHAR(400)  NOT NULL
);
GO
PRINT 'OK 03_auditoria';
