import base64,io,pickle
class DataUnpickler(pickle.Unpickler):
    def find_class(self,module,name):raise pickle.UnpicklingError('Object construction forbidden')
    def persistent_load(self,pid):raise pickle.UnpicklingError('Persistent reference forbidden')
def load_preferences_from_cookie(encoded_prefs):
    if not encoded_prefs:return {}
    value=DataUnpickler(io.BytesIO(base64.b64decode(encoded_prefs))).load()
    if not isinstance(value,dict):raise ValueError('Expected dictionary')
    return value
