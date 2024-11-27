import os

import requests
from datetime import datetime
from dateutil.relativedelta import relativedelta
from prefect import task, flow

from taxifare.interface.main import evaluate, preprocess, train
from taxifare.ml_logic.registry import mlflow_transition_model
from taxifare.params import *

@task
def preprocess_new_data(min_date: str, max_date: str):
    return preprocess(min_date, max_date)

@task
def evaluate_production_model(min_date: str, max_date: str):
    return evaluate(min_date, max_date, "Production")

@task
def re_train(min_date: str, max_date: str, split_ratio: str):
    return train(min_date, max_date, split_ratio)

@task
def transition_model(current_stage: str, new_stage: str):
    return mlflow_transition_model(current_stage, new_stage)


@flow(name=PREFECT_FLOW_NAME)
def train_flow():
    """
    Build the Prefect workflow for the `taxifare` package. It should:
        - preprocess 1 month of new data, starting from EVALUATION_START_DATE
        - compute `old_mae` by evaluating the current production model in this new month period
        - compute `new_mae` by re-training, then evaluating the current production model on this new month period
        - if the new one is better than the old one, replace the current production model with the new one
        - if neither model is good enough, send a notification!
    """

    min_date = EVALUATION_START_DATE
    max_date = str(datetime.strptime(min_date, "%Y-%m-%d") + relativedelta(months=1)).split()[0]

    preprocess_new_data_task = preprocess_new_data.submit(min_date, max_date)
    prod_model = evaluate_production_model.submit(min_date, max_date, wait_for=[preprocess_new_data_task])
    new_model = re_train.submit(min_date, max_date, split_ratio=0.2, wait_for=[preprocess_new_data_task])

    old_mae = prod_model.result()
    new_mae = new_model.result()

    if old_mae > new_mae:
        transition_model.submit("Staging", "Production")
        notify(old_mae, new_mae)

    if old_mae < new_mae:
        transition_model.submit("Production", "Production")
        notify(old_mae, new_mae)


def notify(old_mae, new_mae):
    """
    Notify about the performance
    """
    base_url = 'https://chat.api.lewagon.com'
    channel = 'YOUR_BATCH_NUMBER' # Change to your batch number
    url = f"{base_url}/{channel}/messages"
    author = 'YOUR_GITHUB_NICKNAME' # Change this to your github nickname
    if new_mae < old_mae and new_mae < 2.5:
        content = f"🚀 New model replacing old in production with MAE: {new_mae} the Old MAE was: {old_mae}"
    elif old_mae < 2.5:
        content = f"✅ Old model still good enough: Old MAE: {old_mae} - New MAE: {new_mae}"
    else:
        content = f"🚨 No model good enough: Old MAE: {old_mae} - New MAE: {new_mae}"
    data = dict(author=author, content=content)
    response = requests.post(url, data=data)
    response.raise_for_status()



if __name__ == "__main__":
    train_flow()
