-- Crea la base y el login del laboratorio. Idempotente: se puede ejecutar varias veces.
-- Se ejecuta con: sqlcmd ... -v LAB_PASSWORD="..." -i /sql/init.sql
IF DB_ID('labdb') IS NULL
    CREATE DATABASE labdb;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'lab_user')
    CREATE LOGIN lab_user WITH PASSWORD = '$(LAB_PASSWORD)', CHECK_POLICY = ON;
ELSE
    ALTER LOGIN lab_user WITH PASSWORD = '$(LAB_PASSWORD)';
GO

USE labdb;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'lab_user')
    CREATE USER lab_user FOR LOGIN lab_user;
GO

ALTER ROLE db_owner ADD MEMBER lab_user;
GO
