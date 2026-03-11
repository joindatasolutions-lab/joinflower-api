from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory request limiter by client address.
limiter = Limiter(key_func=get_remote_address)
