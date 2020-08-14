#!/usr/bin/env python3

import aiopg
import markdown
import os.path
import psycopg2
import re
import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.locks
import tornado.options
import tornado.web
import unicodedata

from tornado.options import define, options

define("port", default=8888, help="run on the given port", type=int)
define("db_host", default="127.0.0.1", help="blog database host")
define("db_port", default=5432, help="blog database port")
define("db_database", default="blog", help="blog database name")
define("db_user", default="blog", help="blog database user")
define("db_password", default="blog", help="blog database password")


class NoResultError(Exception):
    pass


async def maybe_create_tables(db):
    try:
        with (await db.cursor()) as cur:
            await cur.execute("SELECT COUNT(*) FROM entries LIMIT 1")
            await cur.fetchone()
    except psycopg2.ProgrammingError:
        with open("schema.sql") as f:
            schema = f.read()
        with (await db.cursor()) as cur:
            await cur.execute(schema)

class Application(tornado.web.Application):
    def __init__(self, db):
        self.db = db
        handlers = [
            (r"/", HomeHandler),
            (r"/archive", ArchiveHandler),
            (r"/feed", FeedHandler),
            (r"/entry/([^/]+)", EntryHandler),
            (r"/delete/([^/]+)", DeleteHandler),
            (r"/compose", ComposeHandler),
            (r"/fileup/([^/]+)", IndexHandler),
            (r"/upload/([^/]+)", UploadHandler),
            (r"/auth/create", AuthCreateHandler),
            (r"/auth/login", AuthLoginHandler),
            (r"/auth/logout", AuthLogoutHandler),
        ]
        settings = dict(
            blog_title=u"Tornado Blog",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            ui_modules={"Entry": EntryModule},
            xsrf_cookies=False,
            cookie_secret="__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
            login_url="/auth/login",
            debug=True,
        )
        super(Application, self).__init__(handlers, **settings)


class BaseHandler(tornado.web.RequestHandler):
    def row_to_obj(self, row, cur):
        """Convert a SQL row to an object supporting dict and attribute access."""
        obj = tornado.util.ObjectDict()
        for val, desc in zip(row, cur.description):
            obj[desc.name] = val
        return obj

    async def execute(self, stmt, *args):
        """Execute a SQL statement.

        Must be called with ``await self.execute(...)``
        """
        with (await self.application.db.cursor()) as cur:
            await cur.execute(stmt, args)

    async def query(self, stmt, *args):
        """Query for a list of results.

        Typical usage::

            results = await self.query(...)

        Or::

            for row in await self.query(...)
        """
        with (await self.application.db.cursor()) as cur:
            await cur.execute(stmt, args)
            return [self.row_to_obj(row, cur) for row in await cur.fetchall()]

    async def queryone(self, stmt, *args):
        """Query for exactly one result.
        Raises NoResultError if there are no results, or ValueError if
        there are more than one.
        """
        results = await self.query(stmt, *args)
        if len(results) == 0:
            raise NoResultError()
        elif len(results) > 1:
            raise ValueError("Expected 1 result, got %d" % len(results))
        return results[0]

    async def prepare(self):
        user_id = self.get_secure_cookie("blogdemo_user")
        #print(user_id)
        if user_id:
            self.current_user = await self.queryone(
                "SELECT * FROM authors WHERE id = %s", int(user_id)
            )

    async def any_author_exists(self):
        #return bool(await self.query("SELECT * FROM authors LIMIT 1"))
        return self.get_secure_cookie("blogdemo_user")

class IndexHandler(BaseHandler):
    def get(self,slug):
        self.render("upload_form.html",slug=slug)
class UploadHandler(tornado.web.RequestHandler):
    async def post(self,slug):
        file1 = self.request.files['file1'][0]
        original_fname = file1['filename']
        extension = '.jpg'
        f_name=slug
        final_n=slug+extension
        output_file = open("uploads/" + final_n, 'wb')
        output_file.write(file1['body'])
        self.redirect("/")
        #self.finish("file" + final_filename + " is uploaded")
class HomeHandler(BaseHandler):
        @tornado.web.authenticated
        async def get(self):
            id = self.get_secure_cookie("blogdemo_user")
            entries = await self.query(
                "SELECT * FROM entries WHERE author_id = %s", int(id)
            )
            self.render("home.html",entries=entries)



class DeleteHandler(BaseHandler):
    async def post(self, slug):
        await self.execute("DELETE  FROM entries WHERE slug = %s", slug)
        self.render("delete.html")

class EntryHandler(BaseHandler):
    async def get(self, slug):
        entry = await self.queryone("SELECT * FROM entries WHERE slug = %s", slug)
        if not entry:
            raise tornado.web.HTTPError(404)

        id = self.current_user.id
        votes = await self.query(
        "SELECT * FROM votes WHERE id =%s AND author_id= %s LIMIT 1",
        int(entry['id']),
        id,
        )
        up=await self.query("SELECT sum(vote) FROM votes WHERE vote =%s AND slug = %s",int(1),slug)
        down=await self.query("SELECT sum(vote) FROM votes WHERE vote =%s AND slug = %s",int(-1),slug)
        #print(up,down)
        down=down[0]
        up=up[0]

        if up['sum']!=None:
            up=up['sum']
        else:
            up=0
        if down['sum']!=None:
            down=down['sum']*-1
        else:
            down=0
        if len(votes)!=0:
            votes=dict(votes[0])
        temp='did not voted'
        if len(votes)!=0:
            #print(votes)
            if votes['vote']==1:
                temp='upvoted'
            else:
                temp='downvoted'
        self.render("entry.html", entry=entry,votes=temp,up=up,down=down,rec=id)
        #print("comment is",self.current_user['name'],self.get_argument("comment"))

        if self.get_argument("comment"):
            #print(self.get_argument("comment"))
            comment=str(self.get_argument("comment")+str(self.get_secure_cookie("blogdemo_user"))+"~")
            await self.execute(
                "UPDATE entries SET comments = %s || comments "
                "WHERE id = %s",
                comment,
                entry['id'],
            )

        if self.get_argument("vote"):
            if self.get_argument("vote")=='like':
                vote=1
            else:
                vote=-1
            if len(votes)!=0:
                #print(" updated")
                await self.execute(
                    "UPDATE votes SET vote = %s "
                    "WHERE id = %s AND author_id=%s",
                    int(vote),
                    entry['id'],
                    id,
                )
            else:
                #print(" inserted")
                await self.execute(
                    "INSERT INTO votes (id,author_id,vote,slug)"
                    "VALUES (%s,%s,%s,%s)",
                    int(entry['id']),
                    id,
                    int(vote),
                    slug,
                )

def Sort_Tuple(tup):

    # reverse = None (Sorts in Ascending order)
    # key is set to sort using second element of
    # sublist lambda has been used
    tup.sort(key = lambda x: x[1])
    return tup
class ArchiveHandler(BaseHandler):
    @tornado.web.authenticated
    async def get(self):
        entries = await self.query("SELECT * FROM entries ORDER BY published DESC")
        l=[]
        #print(entries)
        for i in range(len(entries)):
            cur=entries[i]
            up=await self.query("SELECT sum(vote) FROM votes WHERE vote =%s AND slug = %s",int(1),cur['slug'])
            down=await self.query("SELECT sum(vote) FROM votes WHERE vote =%s AND slug = %s",int(-1),cur['slug'])
            down=down[0]
            up=up[0]
            if up['sum']!=None:
                up=up['sum']
            else:
                up=0
            if down['sum']!=None:
                down=down['sum']*-1
            else:
                down=0
            if up+down==0:
                l.append((cur,0))
            else:
                count=up/(up+down)
                l.append((cur,count))
        tup=Sort_Tuple(l)
        #print(tup)
        entries=[]
        for i in range(len(tup)):
            entries.append(tup[len(tup)-i-1][0])
        self.render("archive.html", entries=entries)

class FeedHandler(BaseHandler):
    async def get(self):
        entries = await self.query(
            "SELECT * FROM entries ORDER BY published DESC LIMIT 10"
        )
        self.set_header("Content-Type", "application/atom+xml")
        self.render("feed.xml", entries=entries)

class ComposeHandler(BaseHandler):
    @tornado.web.authenticated
    async def get(self):
        id = self.get_argument("id", None)
        entry = None
        if id:
            entry = await self.queryone("SELECT * FROM entries WHERE id = %s", int(id))
        self.render("compose.html", entry=entry)

    @tornado.web.authenticated
    async def post(self):
        id = self.get_argument("id", None)
        title = self.get_argument("title")
        text = self.get_argument("markdown")
        html = markdown.markdown(text)
        if id:
            try:
                entry = await self.queryone(
                    "SELECT * FROM entries WHERE id = %s", int(id)
                )
            except NoResultError:
                raise tornado.web.HTTPError(404)

            slug = entry.slug
            await self.execute(
                "UPDATE entries SET title = %s, markdown = %s, html = %s "
                "WHERE id = %s",
                title,
                text,
                html,
                int(id),
            )
        else:
            slug = unicodedata.normalize("NFKD", title)
            slug = re.sub(r"[^\w]+", " ", slug)
            slug = "-".join(slug.lower().strip().split())
            slug = slug.encode("ascii", "ignore").decode("ascii")
            if not slug:
                slug = "entry"
            while True:
                e = await self.query("SELECT * FROM entries WHERE slug = %s", slug)
                if not e:
                    break
                slug += "-2"
            await self.execute(
                "INSERT INTO entries (author_id,title,slug,markdown,html,published,updated)"
                "VALUES (%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                self.current_user.id,
                title,
                slug,
                text,
                html,
            )
        self.redirect("/entry/" + slug)



class AuthCreateHandler(BaseHandler):
    def get(self):
        self.render("create_author.html")
    async def post(self):
        if await self.any_author_exists():
            raise tornado.web.HTTPError(400, "Please logout first!")
        hashed_password = self.get_argument("password")
        author = await self.queryone(
            "INSERT INTO authors (email, name, hashed_password) "
            "VALUES (%s, %s, %s) RETURNING id",
            self.get_argument("email"),
            self.get_argument("name"),
            tornado.escape.to_unicode(hashed_password),
        )
        self.set_secure_cookie("blogdemo_user", str(author.id))
        self.redirect(self.get_argument("next", "/"))
class AuthLoginHandler(BaseHandler):
    async def get(self):
        # If there are no authors, redirect to the account creation page.
        if await self.any_author_exists():
            self.redirect("/auth/create")
        else:
            self.render("login.html", error=None)

    async def post(self):
        try:
            author = await self.queryone(
                "SELECT * FROM authors WHERE email = %s", self.get_argument("email")
            )
        except NoResultError:
            self.render("login.html", error="email not found")
            return
        cur_pas=self.get_argument("password")
        if author.hashed_password==cur_pas:
            self.set_secure_cookie("blogdemo_user", str(author.id))
            self.redirect(self.get_argument("next", "/"))
        else:
            self.render("login.html", error="incorrect password")

class AuthLogoutHandler(BaseHandler):
    def get(self):
        self.clear_cookie("blogdemo_user")
        self.redirect(self.get_argument("next", "/"))


class EntryModule(tornado.web.UIModule):
    def render(self, entry):
        return self.render_string("modules/entry.html", entry=entry)


async def main():
    tornado.options.parse_command_line()

    # Create the global connection pool.
    async with aiopg.create_pool(
        host=options.db_host,
        port=options.db_port,
        user=options.db_user,
        password=options.db_password,
        dbname=options.db_database,
    ) as db:
        await maybe_create_tables(db)
        app = Application(db)
        app.listen(options.port)
        # In this demo the server will simply run until interrupted
        # with Ctrl-C, but if you want to shut down more gracefully,
        # call shutdown_event.set().
        shutdown_event = tornado.locks.Event()
        await shutdown_event.wait()


if __name__ == "__main__":
    tornado.ioloop.IOLoop.current().run_sync(main)
