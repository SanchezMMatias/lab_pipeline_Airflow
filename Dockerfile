FROM apache/airflow:3.4.0

USER root
# Driver ODBC 18 de Microsoft (necesario para pyodbc -> SQL Server / Azure SQL / Cloud SQL)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && . /etc/os-release \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/${VERSION_ID}/prod ${VERSION_CODENAME} main" \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && apt-get autoremove -yqq --purge \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

USER airflow
COPY requirements.txt /requirements.txt
# Fijar la versión de Airflow evita que pip la actualice sin querer
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt