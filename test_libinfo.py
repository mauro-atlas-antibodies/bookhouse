import re, sys
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
for bp in (search,tasks,web,basic,opds,jinjia,about,shelf,admin.admi,remotelogin,meta,editbook):
    app.register_blueprint(bp)
from werkzeug.security import generate_password_hash
from cps import ub
from cps.ub import User
with app.app_context():
    ub.session.query(User).filter(User.name=='bht').delete(); ub.session.commit()
    u=User(); u.name='bht'; u.email='bht@x.test'; u.password=generate_password_hash('pw'); u.role=1; u.sidebar_view=0x1FF
    ub.session.add(u); ub.session.commit()
CSRF=re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')
with app.test_client() as c:
    m=CSRF.search(c.get('/login').data); c.post('/login',data={'username':'bht','password':'pw','csrf_token':m.group(1).decode(),'remember_me':'off'})
    home=c.get('/')
    print('lib-info present:', b'lib-info' in home.data)
    print('lib-name present:', 'Main Library' in home.data.decode() and 'lib-name' in home.data.decode())
    print('lib-desc present:', 'Primary Bookhouse library' in home.data.decode())
    tok=CSRF.search(c.get('/advsearch').data).group(1).decode()
    c.post('/lib/select/library-2',data={'csrf_token':tok})
    home2=c.get('/')
    print('after switch lib-name:', 'Library 2' in home2.data.decode())
    print('after switch desc:', 'Second Bookhouse test library' in home2.data.decode())
with app.app_context():
    ub.session.query(User).filter(User.name=='bht').delete(); ub.session.commit()
print('LIBINFO TESTS PASSED')
