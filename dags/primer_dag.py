from airflow import DAG
from airflow.operators.empty import EmptyOperator
from datetime import datetime 

with DAG (
    dag_id= "primer_dag",
    tags=["mis_dags"],
    start_date=datetime(2023, 1, 1),
    schedule="@daily",
    catchup=False,
)as dag:
    inicio = EmptyOperator(task_id="inicio")
    fin = EmptyOperator(task_id="fin")
    inicio >> fin 