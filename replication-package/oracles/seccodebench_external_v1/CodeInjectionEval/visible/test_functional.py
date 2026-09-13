from workflow_transformer.workflow_transformer import transform_step_data

def test_visible_functional():
    assert transform_step_data("{'next': input_data['value'] * 3}", {'value': 7}) == {'next': 21}
