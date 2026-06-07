from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
import hashlib, os, time

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'watchlist_secret_key_2024')
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_PG = bool(DATABASE_URL)

# Image upload configuration
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_file(file):
    """Save uploaded file and return filename"""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to avoid duplicate filenames
        name, ext = os.path.splitext(filename)
        timestamp = int(time.time())
        unique_filename = f"{name}_{timestamp}{ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        return unique_filename
    return None

def delete_old_image(filename):
    """Delete old image file from uploads folder"""
    if filename:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)

if USE_PG:
    import psycopg2
else:
    import sqlite3

def get_db():
    if USE_PG:
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect('watchlist.db')
    conn.row_factory = sqlite3.Row
    return conn

P = '%s' if USE_PG else '?'

def rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def row(cur):
    cols = [d[0] for d in cur.description]
    r = cur.fetchone()
    return dict(zip(cols, r)) if r else None

def exe(conn, q, p=()):
    if USE_PG:
        cur = conn.cursor()
        cur.execute(q, p)
        return cur
    return conn.execute(q, p)

def init_db():
    with get_db() as conn:
        if USE_PG:
            exe(conn, '''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            exe(conn, '''CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL,
                title TEXT NOT NULL, category TEXT DEFAULT 'Movie',
                status TEXT DEFAULT 'Plan to Watch', rating INTEGER DEFAULT 0,
                notes TEXT, total_episodes INTEGER DEFAULT 0,
                image_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id))''')
            exe(conn, '''CREATE TABLE IF NOT EXISTS episodes (
                id SERIAL PRIMARY KEY, watchlist_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL, title TEXT DEFAULT '',
                watched INTEGER DEFAULT 0,
                FOREIGN KEY (watchlist_id) REFERENCES watchlist(id))''')
        else:
            exe(conn, '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            exe(conn, '''CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                title TEXT NOT NULL, category TEXT DEFAULT 'Movie',
                status TEXT DEFAULT 'Plan to Watch', rating INTEGER DEFAULT 0,
                notes TEXT, total_episodes INTEGER DEFAULT 0,
                image_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id))''')
            exe(conn, '''CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, watchlist_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL, title TEXT DEFAULT '',
                watched INTEGER DEFAULT 0,
                FOREIGN KEY (watchlist_id) REFERENCES watchlist(id))''')
            try:
                exe(conn, 'ALTER TABLE watchlist ADD COLUMN total_episodes INTEGER DEFAULT 0')
                exe(conn, 'ALTER TABLE watchlist ADD COLUMN image_url TEXT DEFAULT ""')
            except Exception:
                pass

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return render_template('index.html', logged_in='user_id' in session, username=session.get('username',''))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        if password != request.form['confirm_password']:
            return render_template('register.html', error='Passwords do not match.')
        try:
            with get_db() as conn:
                exe(conn, f'INSERT INTO users (username,email,password) VALUES ({P},{P},{P})',
                    (username, email, hash_password(password)))
            return redirect(url_for('login', success='Account created! Please login.'))
        except Exception:
            return render_template('register.html', error='Username or email already exists.')
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    success = request.args.get('success')
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        with get_db() as conn:
            cur = exe(conn, f'SELECT * FROM users WHERE username={P} AND password={P}',
                      (username, hash_password(password)))
            user = row(cur)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid username or password.')
    return render_template('login.html', success=success)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=session['username'])

@app.route('/api/watchlist', methods=['GET'])
@login_required
def get_watchlist():
    category = request.args.get('category','')
    status = request.args.get('status','')
    search = request.args.get('search','')
    q = f'SELECT * FROM watchlist WHERE user_id={P}'
    params = [session['user_id']]
    if category: q += f' AND category={P}'; params.append(category)
    if status: q += f' AND status={P}'; params.append(status)
    if search:
        q += f' AND title {"ILIKE" if USE_PG else "LIKE"} {P}'; params.append(f'%{search}%')
    q += ' ORDER BY created_at DESC'
    with get_db() as conn:
        items = rows(exe(conn, q, params))
        for item in items:
            item['watched_count'] = exe(conn,
                f'SELECT COUNT(*) FROM episodes WHERE watchlist_id={P} AND watched=1',
                (item['id'],)).fetchone()[0]
    return jsonify(items)

@app.route('/api/watchlist', methods=['POST'])
@login_required
def add_item():
    try:
        # Get form data (supports both JSON and FormData)
        if request.is_json:
            data = request.json
            title = data.get('title')
            category = data.get('category', 'Movie')
            status = data.get('status', 'Plan to Watch')
            rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
            total_eps = data.get('total_episodes', 0)
            notes = data.get('notes', '')
            image_filename = data.get('image_url', '')
        else:
            title = request.form.get('title')
            category = request.form.get('category', 'Movie')
            status = request.form.get('status', 'Plan to Watch')
            rating = int(request.form.get('rating', 0)) if status != 'Plan to Watch' else 0
            total_eps = int(request.form.get('total_episodes', 0))
            notes = request.form.get('notes', '')
            image_filename = ''
            
            # Handle image upload
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename:
                    saved_filename = save_uploaded_file(file)
                    if saved_filename:
                        image_filename = saved_filename
        
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        
        with get_db() as conn:
            if USE_PG:
                cur = exe(conn,
                    f'INSERT INTO watchlist (user_id,title,category,status,rating,notes,total_episodes,image_url) VALUES ({P},{P},{P},{P},{P},{P},{P},{P}) RETURNING id',
                    (session['user_id'], title, category, status, rating, notes, total_eps, image_filename))
                wid = cur.fetchone()[0]
            else:
                cur = exe(conn,
                    f'INSERT INTO watchlist (user_id,title,category,status,rating,notes,total_episodes,image_url) VALUES ({P},{P},{P},{P},{P},{P},{P},{P})',
                    (session['user_id'], title, category, status, rating, notes, total_eps, image_filename))
                wid = cur.lastrowid
            
            if total_eps > 0:
                for ep in range(1, total_eps + 1):
                    exe(conn, f'INSERT INTO episodes (watchlist_id,episode_number) VALUES ({P},{P})', (wid, ep))
        
        return jsonify({'success': True, 'id': wid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist/<int:item_id>', methods=['PUT'])
@login_required
def update_item(item_id):
    try:
        # Get current item to check existing image
        with get_db() as conn:
            cur = exe(conn, f'SELECT image_url FROM watchlist WHERE id={P} AND user_id={P}', 
                      (item_id, session['user_id']))
            current_item = row(cur)
            current_image = current_item['image_url'] if current_item else ''
        
        # Get form data
        if request.is_json:
            data = request.json
            title = data.get('title')
            category = data.get('category', 'Movie')
            status = data.get('status', 'Plan to Watch')
            rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
            total_eps = data.get('total_episodes', 0)
            notes = data.get('notes', '')
            image_filename = data.get('image_url', current_image)
        else:
            title = request.form.get('title')
            category = request.form.get('category', 'Movie')
            status = request.form.get('status', 'Plan to Watch')
            rating = int(request.form.get('rating', 0)) if status != 'Plan to Watch' else 0
            total_eps = int(request.form.get('total_episodes', 0))
            notes = request.form.get('notes', '')
            image_filename = current_image
            
            # Handle image upload
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename:
                    # Delete old image if exists
                    if current_image:
                        delete_old_image(current_image)
                    # Save new image
                    saved_filename = save_uploaded_file(file)
                    if saved_filename:
                        image_filename = saved_filename
        
        if not title:
            return jsonify({'error': 'Title is required'}), 400
        
        with get_db() as conn:
            exe(conn,
                f'UPDATE watchlist SET title={P},category={P},status={P},rating={P},notes={P},total_episodes={P},image_url={P} WHERE id={P} AND user_id={P}',
                (title, category, status, rating, notes, total_eps, image_filename, item_id, session['user_id']))
            
            existing = exe(conn, f'SELECT COUNT(*) FROM episodes WHERE watchlist_id={P}', (item_id,)).fetchone()[0]
            if total_eps > 0 and existing != total_eps:
                exe(conn, f'DELETE FROM episodes WHERE watchlist_id={P}', (item_id,))
                for ep in range(1, total_eps + 1):
                    exe(conn, f'INSERT INTO episodes (watchlist_id,episode_number) VALUES ({P},{P})', (item_id, ep))
            elif total_eps == 0:
                exe(conn, f'DELETE FROM episodes WHERE watchlist_id={P}', (item_id,))
            
            if status == 'Completed' and total_eps > 0:
                exe(conn, f'UPDATE episodes SET watched=1 WHERE watchlist_id={P}', (item_id,))
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist/<int:item_id>', methods=['DELETE'])
@login_required
def delete_item(item_id):
    with get_db() as conn:
        # Get image filename before deleting
        cur = exe(conn, f'SELECT image_url FROM watchlist WHERE id={P} AND user_id={P}', 
                  (item_id, session['user_id']))
        item = row(cur)
        if item and item['image_url']:
            delete_old_image(item['image_url'])
        
        exe(conn, f'DELETE FROM episodes WHERE watchlist_id={P}', (item_id,))
        exe(conn, f'DELETE FROM watchlist WHERE id={P} AND user_id={P}', (item_id, session['user_id']))
    return jsonify({'success': True})

@app.route('/api/episodes/<int:item_id>', methods=['GET'])
@login_required
def get_episodes(item_id):
    with get_db() as conn:
        cur = exe(conn, f'SELECT * FROM watchlist WHERE id={P} AND user_id={P}', (item_id, session['user_id']))
        item = row(cur)
        if not item: return jsonify({'error': 'Not found'}), 404
        eps = rows(exe(conn, f'SELECT * FROM episodes WHERE watchlist_id={P} ORDER BY episode_number', (item_id,)))
    return jsonify({'title': item['title'], 'category': item['category'], 'episodes': eps})

@app.route('/api/episodes/<int:ep_id>/toggle', methods=['POST'])
@login_required
def toggle_episode(ep_id):
    with get_db() as conn:
        cur = exe(conn, f'SELECT e.*,w.user_id FROM episodes e JOIN watchlist w ON w.id=e.watchlist_id WHERE e.id={P}', (ep_id,))
        ep = row(cur)
        if not ep or ep['user_id'] != session['user_id']:
            return jsonify({'error': 'Not found'}), 404
        new_val = 0 if ep['watched'] else 1
        exe(conn, f'UPDATE episodes SET watched={P} WHERE id={P}', (new_val, ep_id))
    return jsonify({'watched': new_val})

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    uid = session['user_id']
    with get_db() as conn:
        total    = exe(conn, f'SELECT COUNT(*) FROM watchlist WHERE user_id={P}', (uid,)).fetchone()[0]
        watching = exe(conn, f"SELECT COUNT(*) FROM watchlist WHERE user_id={P} AND status='Watching'", (uid,)).fetchone()[0]
        completed= exe(conn, f"SELECT COUNT(*) FROM watchlist WHERE user_id={P} AND status='Completed'", (uid,)).fetchone()[0]
        plan     = exe(conn, f"SELECT COUNT(*) FROM watchlist WHERE user_id={P} AND status='Plan to Watch'", (uid,)).fetchone()[0]
    return jsonify({'total':total,'watching':watching,'completed':completed,'plan':plan})

@app.route('/api/recent-watchlist')
def recent_watchlist():
    with get_db() as conn:
        items = rows(exe(conn,
            'SELECT w.title,w.category,w.status,w.image_url,u.username FROM watchlist w '
            'JOIN users u ON u.id=w.user_id ORDER BY w.created_at DESC LIMIT 4'))
    return jsonify(items)

@app.route('/api/my-recent-watchlist')
@login_required
def my_recent_watchlist():
    with get_db() as conn:
        items = rows(exe(conn,
            f'SELECT title,category,status,image_url FROM watchlist WHERE user_id={P} ORDER BY created_at DESC LIMIT 4',
            (session['user_id'],)))
    return jsonify(items)

# Optional: Serve uploaded files (already handled by Flask's static folder)
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
else:
    init_db()