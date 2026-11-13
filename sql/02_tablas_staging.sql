USE labdb;
GO
-- Sin PK ni FK a propósito: se cargan y luego se validan con consultas
-- para poder explicar cada error (duplicados, cliente inexistente).
IF OBJECT_ID('lab.stg_clientes', 'U') IS NULL
CREATE TABLE lab.stg_clientes (
    lote_id      VARCHAR(80)   NOT NULL,
    nro_registro INT           NOT NULL,   -- línea del archivo, para reportar errores
    cliente_id   INT           NOT NULL,
    nombre       NVARCHAR(100) NOT NULL,
    email        VARCHAR(254)  NOT NULL,
    fecha_alta   DATE          NOT NULL,
    pais_codigo  CHAR(2)       NOT NULL,
    activo       BIT           NOT NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_stg_clientes_lote')
    CREATE INDEX IX_stg_clientes_lote ON lab.stg_clientes (lote_id);
GO
IF OBJECT_ID('lab.stg_ventas', 'U') IS NULL
CREATE TABLE lab.stg_ventas (
    lote_id       VARCHAR(80)   NOT NULL,
    nro_registro  INT           NOT NULL,
    venta_id      INT           NOT NULL,
    cliente_id    INT           NOT NULL,
    fecha_venta   DATE          NOT NULL,
    cantidad      INT           NOT NULL,
    importe_total DECIMAL(14,2) NOT NULL,
    moneda        CHAR(3)       NOT NULL,
    observacion   NVARCHAR(200) NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_stg_ventas_lote')
    CREATE INDEX IX_stg_ventas_lote ON lab.stg_ventas (lote_id);
GO
PRINT 'OK 02_tablas_staging';
