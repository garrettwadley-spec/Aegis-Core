def train_run(spec=None):
    spec = spec or {"model":"xgboost","features":64}
    return {"model_uri":"models:/aegis@candidate","note":"training stub complete","spec":spec}
