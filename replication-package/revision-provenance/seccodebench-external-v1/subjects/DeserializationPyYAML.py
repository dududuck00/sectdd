import yaml
def restore_workspace_from_yaml(state_yaml):
    value=yaml.safe_load(state_yaml)
    if value is None:return {}
    if not isinstance(value,dict):raise ValueError('Expected dictionary')
    return value
