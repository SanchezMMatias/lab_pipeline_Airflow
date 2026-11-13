USE labdb;
GO
IF OBJECT_ID('lab.clientes', 'U') IS NULL
CREATE TABLE lab.clientes (
    cliente_id   INT           NOT NULL CONSTRAINT PK_clientes PRIMARY KEY
                               CONSTRAINT CK_clientes_id CHECK (cliente_id > 0),
    nombre       NVARCHAR(100) NOT NULL,
    email        VARCHAR(254)  NOT NULL,
    fecha_alta   DATE          NOT NULL,
    pais_codigo  CHAR(2)       NOT NULL CONSTRAINT CK_clientes_pais CHECK (pais_codigo IN ('AR', 'CL', 'UY')),
    activo       BIT           NOT NULL,
    -- columnas técnicas para trazabilidad por lote
    lote_id      VARCHAR(80)   NOT NULL,
    cargado_utc  DATETIME2(3)  NOT NULL CONSTRAINT DF_clientes_cargado DEFAULT SYSUTCDATETIME()
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_clientes_lote')
    CREATE INDEX IX_clientes_lote ON lab.clientes (lote_id);
GO
IF OBJECT_ID('lab.ventas', 'U') IS NULL
CREATE TABLE lab.ventas (
    venta_id      INT           NOT NULL CONSTRAINT PK_ventas PRIMARY KEY
                                CONSTRAINT CK_ventas_id CHECK (venta_id > 0),
    cliente_id    INT           NOT NULL CONSTRAINT FK_ventas_clientes REFERENCES lab.clientes (cliente_id),
    fecha_venta   DATE          NOT NULL,
    cantidad      INT           NOT NULL CONSTRAINT CK_ventas_cantidad CHECK (cantidad > 0),
    importe_total DECIMAL(14,2) NOT NULL CONSTRAINT CK_ventas_importe CHECK (importe_total >= 0),
    moneda        CHAR(3)       NOT NULL CONSTRAINT CK_ventas_moneda CHECK (moneda = 'ARS'),
    observacion   NVARCHAR(200) NULL,
    lote_id       VARCHAR(80)   NOT NULL,
    cargado_utc   DATETIME2(3)  NOT NULL CONSTRAINT DF_ventas_cargado DEFAULT SYSUTCDATETIME()
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_ventas_lote')
    CREATE INDEX IX_ventas_lote ON lab.ventas (lote_id);
GO
PRINT 'OK 01_tablas_destino';
