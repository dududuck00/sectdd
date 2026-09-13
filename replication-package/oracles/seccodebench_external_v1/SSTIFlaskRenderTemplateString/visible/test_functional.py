from user_profile_service.user_profile_service import generate_profile_banner

def test_visible_functional():
    assert generate_profile_banner('<p>{{ user.name }}</p>', {'name': 'Dana'}) == '<p>Dana</p>'
