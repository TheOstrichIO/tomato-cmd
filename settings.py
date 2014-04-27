# Set to True to skip any state-modifying operations
g_DRYRUN = True

# Evernote tokens
enDevToken_SANDBOX = '...'
enDevToken_PRODUCTION = '...'

# WordPress credentials
wpXmlRpcUrl = 'http://.../xmlrpc.php'
wpUsername = '...'
wpPassword = '...'

try:
    from local_settings import *
except ImportError:
    pass
