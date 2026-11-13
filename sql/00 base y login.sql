-- Ejecutar como sa. Crea la base, el login del laboratorio y el schema.
-- Uso: sqlcmd ... -i /sql/00_base_y_login.sql -v LAB_PWD=<password de lab_user>
IF DB_ID('labdb') IS NULL CREATE DATABASE labdb;
GO
IF SUSER_ID('lab_user') IS NULL
    CREATE LOGIN lab_user WITH PASSWORD = '$(LAB_PWD)', DEFAULT_DATABASE = labdb, CHECK_POLICY = ON;
GO
USE labdb;
GO
IF USER_ID('lab_user') IS NULL CREATE USER lab_user FOR LOGIN lab_user;
GO
IF SCHEMA_ID('lab') IS NULL EXEC('CREATE SCHEMA lab AUTHORIZATION dbo');
GO
-- Solo datos: el usuario del pipeline no crea ni borra tablas
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::lab TO lab_user;
GO
PRINT 'OK 00_base_y_login';