import os
from .base import *

if os.environ.get('DJANGO_ENV') == 'production':
    from .prod import *
else:
    from .dev import *
