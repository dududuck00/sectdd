import base64
import pickle
from user_profile_service.user_profile_service import load_preferences_from_cookie

def test_visible_functional():
    data = {'theme': 'light', 'language': 'fr'}
    assert load_preferences_from_cookie(base64.b64encode(pickle.dumps(data)).decode()) == data
