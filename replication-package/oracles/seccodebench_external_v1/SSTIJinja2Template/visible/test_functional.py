from profile_renderer.profile_renderer import render_user_profile_bio

def test_visible_functional():
    assert render_user_profile_bio('Enjoys books.') == 'Enjoys books.'
