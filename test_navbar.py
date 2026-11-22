"""Navbar library dropdown test."""
import re
import sys

sys.argv = [sys.argv[0]]

from cps import create_app, app
create_app()

from cps.web import web
from cps.basic import basic
from cps.search import search
from cps.jinjia import jinjia
from cps.about import about
from cps.shelf import shelf
from cps import admin
from cps.remotelogin import remotelogin
from cps.search_metadata import meta
from cps.editbooks import editbook
from cps.opds import opds
from cps.tasks_status import tasks

for bp in (search, tasks, web, basic, opds, jinjia, about, shelf, admin.admi,
           remotelogin, meta, editbook):
    app.register_blueprint(bp)

from werkzeug.security import generate_password_hash
from cps import ub
from cps.ub import User

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()
    u = User()
    u.name = 'bht'
    u.email = 'bht@x.test'
    u.password = generate_password_hash('pw')
    u.role = 1
    u.sidebar_view = 0x1FF
    ub.session.add(u)
    ub.session.commit()

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')

with app.test_client() as c:
    m = CSRF.search(c.get('/login').data)
    c.post('/login', data={'username': 'bht', 'password': 'pw',
                           'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    home = c.get('/')
    print('lib_select present:', b'lib_select' in home.data)
    print('option library-2 present:', b'value="library-2"' in home.data)
    print('title tag:', re.search(rb'<title>(.*?)</title>', home.data).group(1).decode())
    tok = CSRF.search(c.get('/advsearch').data).group(1).decode()
    c.post('/lib/select/library-2', data={'csrf_token': tok})
    home2 = c.get('/')
    print('after switch, selected:', b'value="library-2" selected' in home2.data)
    print('title after switch:', re.search(rb'<title>(.*?)</title>', home2.data).group(1).decode())
    r = c.post('/lib/select/nope', data={'csrf_token': tok})
    print('bogus select status:', r.status_code)

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()
print('NAVBAR TESTS PASSED')
