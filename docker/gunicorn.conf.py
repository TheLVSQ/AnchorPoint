# Gunicorn configuration file
# https://docs.gunicorn.org/en/stable/configure.html

import multiprocessing

# Server socket
bind = "0.0.0.0:8000"

# Worker processes
workers = 2
worker_class = "sync"
worker_connections = 1000

# Timeouts
timeout = 120          # Kill worker after 120s (was defaulting to 30s)
keepalive = 5
graceful_timeout = 30

# Logging
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s'

# Process naming
proc_name = "anchorpoint"

# Restart workers after this many requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 100

# gunicorn 24+ starts a control socket under $HOME/.gunicorn by default. We
# don't use `gunicornc`, and the app user can't write /root, so turn it off.
control_socket_disable = True
