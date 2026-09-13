from workspace_state_manager.workspace_state_manager import restore_workspace_from_yaml

def test_visible_functional():
    assert restore_workspace_from_yaml('open_tabs: [draft.py]\nactive_panel: editor') == {'open_tabs': ['draft.py'], 'active_panel': 'editor'}
