from collections import namedtuple

# Set to True to skip any state-modifying operations
g_DRYRUN = True

# Evernote tokens
enDevToken_SANDBOX = '...'
enDevToken_PRODUCTION = '...'

# WordPress credentials
WordPressCredentials = namedtuple('WordPressCredentials',
                                  ['xmlrpc_url', 'username', 'password'])
WORDPRESS = {
    'my-wp-site': WordPressCredentials('http://.../xmlrpc.php',
                                       '...',
                                       '...'),
    'default': 'my-wp-site',
    }

try:
    from local_settings import *
except ImportError:
    pass
