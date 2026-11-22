"""Reproduce 404: library-2 detail/cover/download."""
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
from cps import get_current_library_db, get_current_library_id, db as cps_db

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
    u.role = (1 << 0) | (1 << 1)
    u.sidebar_view = 0x1FF
    ub.session.add(u)
    ub.session.commit()

CSRF = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')

with app.test_client() as c:
    m = CSRF.search(c.get('/login').data)
    c.post('/login', data={'username': 'bht', 'password': 'pw',
                           'csrf_token': m.group(1).decode(), 'remember_me': 'off'})
    tok = CSRF.search(c.get('/advsearch').data).group(1).decode()
    c.post('/lib/select/library-2', data={'csrf_token': tok})
    c.get('/')
    lib2 = get_current_library_db()
    print('current lib path:', lib2.config_calibre_dir)
    print('count:', lib2.session.query(cps_db.Books).count())
    for bid in (2, 3, 4):
        book = lib2.get_filtered_book(bid)
        print('get_filtered_book(%d):' % bid, book.title if book else None,
              'path:', book.path if book else None)
        r = c.get('/book/%d' % bid)
        print('  /book/%d ->' % bid, r.status_code)
        r = c.get('/cover/%d' % bid)
        print('  /cover/%d ->' % bid, r.status_code)
        if book:
            fmt = lib2.session.query(cps_db.Data.format).filter(cps_db.Data.book == bid).first()
            if fmt:
                r = c.get('/download/%d/%s' % (bid, fmt[0]))
                print('  /download/%d/%s ->' % (bid, fmt[0]), r.status_code)

with app.app_context():
    ub.session.query(User).filter(User.name == 'bht').delete()
    ub.session.commit()
print('DONE')
