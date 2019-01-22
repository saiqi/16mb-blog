import os
import re
import functools
import datetime
import urllib

from flask import Flask, redirect, url_for, session, request, flash, render_template
from peewee import CharField, TextField, BooleanField, DateTimeField
from playhouse.flask_utils import FlaskDB, object_list, get_object_or_404
from playhouse.sqlite_ext import FTS5Model, RowIDField, SearchField, SQL

SECRET_KEY = os.getenv('APP_SECRET_KEY')
ADMIN_PASSWORD = os.getenv('APP_ADMIN_PASSWORD')
APP_DIR = os.path.dirname(os.path.realpath(__file__))
DATABASE = 'sqliteext:///%s' % os.path.join(APP_DIR, 'blog.db')

app = Flask(__name__)
app.config.from_object(__name__)

flask_db = FlaskDB(app)
database = flask_db.database


class BlogEntry(flask_db.Model):
    title = CharField()
    slug = CharField(unique=True)
    content = TextField()
    published = BooleanField(index=True)
    timestamp = DateTimeField(index=True)

    def __build_slug(self):
        self.slug = re.sub(r'[^\w]+', '-', self.title.lower())

    def update_search_index(self):
        try:
            idx_entry = EntryIndex.get(EntryIndex.rowid == self.id)
        except EntryIndex.DoesNotExist:
            EntryIndex.create(rowid=self.id, title=self.title,
                              content=self.content)
        else:
            idx_entry.content = self.content
            idx_entry.title = self.title
            idx_entry.save()

    def save(self, *args, **kwargs):
        if not self.slug:
            self.__build_slug()
        if not self.timestamp:
            self.timestamp = datetime.datetime.utcnow()
        result = super(BlogEntry, self).save(*args, **kwargs)
        self.update_search_index()
        return result

    @classmethod
    def public(cls):
        return BlogEntry.select().where(BlogEntry.published == True)

    @classmethod
    def search(cls, query):
        words = [word.strip() for word in query.split() if word.strip()]
        if not words:
            return BlogEntry.select().where(BlogEntry.id == 0)
        else:
            search = ' '.join(words)
        return (BlogEntry
                .select(BlogEntry, EntryIndex.rank().alias('score'))
                .join(EntryIndex, on=(BlogEntry.id == EntryIndex.rowid))
                .where((BlogEntry.published == True) & (EntryIndex.match(search)))
                .order_by(SQL('score')))

    @classmethod
    def drafts(cls):
        return BlogEntry.select().where(BlogEntry.published == False)


class EntryIndex(FTS5Model):

    class Meta:
        database = database

    rowid = RowIDField()
    title = SearchField()
    content = SearchField()


def login_required(func):
    @functools.wraps(func)
    def inner(*args, **kwargs):
        if session.get('logged_in'):
            return func(*args, **kwargs)
        return redirect(url_for('login', next=request.path))
    return inner


@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next') or request.form.get('next')
    if request.method == 'POST' and request.form.get('password'):
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            session['logged_in'] = True
            session.permament = True
            flash('You are logged in !', 'success')
            return redirect(next_url or url_for('index'))
        else:
            flash('Incorrect password', 'danger')
    return render_template('login.html', next_url=next_url)


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        session.clear()
        return redirect(url_for('login'))
    return render_template('logout.html')


@app.route('/')
def index():
    search_query = request.args.get('q')
    if search_query:
        query = BlogEntry.search(search_query)
    else:
        query = BlogEntry.public().order_by(BlogEntry.timestamp.desc())
    return object_list('index.html', query, search=search_query, check_bounds=False)


@app.route('/drafts')
@login_required
def drafts():
    query = BlogEntry.drafts().order_by(BlogEntry.timestamp.desc())
    return object_list('index.html', query, check_bounds=False)


@app.route('/<slug>/')
def detail(slug):
    if session.get('logged_in'):
        query = BlogEntry.select()
    else:
        query = BlogEntry.public()
    entry = get_object_or_404(query, BlogEntry.slug == slug)
    return render_template('detail.html', entry=entry)


@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        if request.form.get('title') and request.form.get('content'):
            entry = BlogEntry.create(
                title=request.form['title'],
                content=request.form['content'],
                published=request.form.get('published') or False
            )
            flash('Entry created successfully.', 'success')
            if entry.published:
                return redirect(url_for('detail', slug=entry.slug))
            else:
                return redirect(url_for('edit', slug=entry.slug))
        else:
            flash('Title and content are required', 'danger')
    return render_template('create.html', entry=BlogEntry(title='', content=''))


@app.route('/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit(slug):
    entry = get_object_or_404(BlogEntry, BlogEntry.slug == slug)
    if request.method == 'POST':
        if request.form.get('title') and request.form.get('content'):
            entry.title = request.form['title']
            entry.content = request.form['content']
            entry.published = request.form.get('published') or False
            entry.save()
            flash('Entry saved successfully', 'success')
            if entry.published:
                return redirect(url_for('detail', slug=entry.slug))
            else:
                return redirect(url_for('edit', slug=entry.slug))
        else:
            flash('Title and content are required', 'danger')
    return render_template('edit.html', entry=entry)


@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
    querystring = dict((key, value) for key, value in request_args.items())
    for key in keys_to_remove:
        querystring.pop(key, None)
    querystring.update(new_values)
    return urllib.parse.urlencode(querystring)


if __name__ == '__main__':
    database.create_tables([BlogEntry, EntryIndex])
    app.run(debug=True)
