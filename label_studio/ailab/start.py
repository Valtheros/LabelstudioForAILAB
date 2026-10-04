"""Run migrations, then serve with the bundled production WSGI server."""
import os
import subprocess
import sys

if __name__ == '__main__':
    subprocess.run([sys.executable, 'manage.py', 'locked_migrate'], check=True)
    os.execvp('uwsgi', ['uwsgi', '--http', ':8080', '--module', 'core.wsgi:application',
                       '--master', '--processes', '2', '--threads', '2', '--enable-threads',
                       '--single-interpreter', '--lazy-apps', '--need-app', '--die-on-term',
                       '--buffer-size', '65535', '--http-timeout', '3600', '--harakiri', '3600',
                       '--reload-on-rss', '750', '--disable-logging'])
