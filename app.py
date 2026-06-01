from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from functools import wraps
import psycopg2, psycopg2.extras, hashlib, os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'watchlist_secret_key_2024')
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS watchlist (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT DEFAULT 'Movie',
                status TEXT DEFAULT 'Plan to Watch',
                rating INTEGER DEFAULT 0,
                notes TEXT,
                total_episodes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )''')
            cur.execute('''CREATE TABLE IF NOT EXISTS episodes (
                id SERIAL PRIMARY KEY,
                watchlist_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                title TEXT DEFAULT '',
                watched INTEGER DEFAULT 0,
                FOREIGN KEY (watchlist_id) REFERENCES watchlist(id)
            )''')

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def fetchall_dict(cur):
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetchone_dict(cur):
    cols = [desc[0] for desc in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None

@app.route('/')
def index():
    logged_in = 'user_id' in session
    username = session.get('username', '')
    return render_template('index.html', logged_in=logged_in, username=username)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            return render_template('register.html', error='Passwords do not match.')
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                                (username, email, hash_password(password)))
            return redirect(url_for('login', success='Account created! Please login.'))
        except psycopg2.errors.UniqueViolation:
            return render_template('register.html', error='Username or email already exists.')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    success = request.args.get('success')
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM users WHERE username=%s AND password=%s',
                            (username, hash_password(password)))
                user = fetchone_dict(cur)
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

# --- API Routes ---
@app.route('/api/watchlist', methods=['GET'])
@login_required
def get_watchlist():
    category = request.args.get('category', '')
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    query = 'SELECT * FROM watchlist WHERE user_id=%s'
    params = [session['user_id']]
    if category:
        query += ' AND category=%s'; params.append(category)
    if status:
        query += ' AND status=%s'; params.append(status)
    if search:
        query += ' AND title ILIKE %s'; params.append(f'%{search}%')
    query += ' ORDER BY created_at DESC'
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = fetchall_dict(cur)
            items = []
            for row in rows:
                cur.execute('SELECT COUNT(*) FROM episodes WHERE watchlist_id=%s AND watched=1', (row['id'],))
                row['watched_count'] = cur.fetchone()[0]
                items.append(row)
    return jsonify(items)

@app.route('/api/watchlist', methods=['POST'])
@login_required
def add_item():
    data = request.json
    status = data.get('status', 'Plan to Watch')
    rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
    total_eps = data.get('total_episodes', 0)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO watchlist (user_id, title, category, status, rating, notes, total_episodes) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                (session['user_id'], data['title'], data.get('category','Movie'), status, rating, data.get('notes',''), total_eps)
            )
            wid = cur.fetchone()[0]
            if total_eps > 0:
                for ep in range(1, total_eps + 1):
                    cur.execute('INSERT INTO episodes (watchlist_id, episode_number) VALUES (%s,%s)', (wid, ep))
    return jsonify({'success': True})

@app.route('/api/watchlist/<int:item_id>', methods=['PUT'])
@login_required
def update_item(item_id):
    data = request.json
    status = data['status']
    rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
    total_eps = data.get('total_episodes', 0)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE watchlist SET title=%s, category=%s, status=%s, rating=%s, notes=%s, total_episodes=%s WHERE id=%s AND user_id=%s',
                (data['title'], data['category'], status, rating, data['notes'], total_eps, item_id, session['user_id'])
            )
            cur.execute('SELECT COUNT(*) FROM episodes WHERE watchlist_id=%s', (item_id,))
            existing = cur.fetchone()[0]
            if total_eps > 0 and existing != total_eps:
                cur.execute('DELETE FROM episodes WHERE watchlist_id=%s', (item_id,))
                for ep in range(1, total_eps + 1):
                    cur.execute('INSERT INTO episodes (watchlist_id, episode_number) VALUES (%s,%s)', (item_id, ep))
            elif total_eps == 0:
                cur.execute('DELETE FROM episodes WHERE watchlist_id=%s', (item_id,))
            if status == 'Completed' and total_eps > 0:
                cur.execute('UPDATE episodes SET watched=1 WHERE watchlist_id=%s', (item_id,))
    return jsonify({'success': True})

@app.route('/api/watchlist/<int:item_id>', methods=['DELETE'])
@login_required
def delete_item(item_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM episodes WHERE watchlist_id=%s', (item_id,))
            cur.execute('DELETE FROM watchlist WHERE id=%s AND user_id=%s', (item_id, session['user_id']))
    return jsonify({'success': True})

@app.route('/api/episodes/<int:item_id>', methods=['GET'])
@login_required
def get_episodes(item_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM watchlist WHERE id=%s AND user_id=%s', (item_id, session['user_id']))
            item = fetchone_dict(cur)
            if not item:
                return jsonify({'error': 'Not found'}), 404
            cur.execute('SELECT * FROM episodes WHERE watchlist_id=%s ORDER BY episode_number', (item_id,))
            eps = fetchall_dict(cur)
    return jsonify({'title': item['title'], 'episodes': eps})

@app.route('/api/episodes/<int:ep_id>/toggle', methods=['POST'])
@login_required
def toggle_episode(ep_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT e.*, w.user_id FROM episodes e JOIN watchlist w ON w.id=e.watchlist_id WHERE e.id=%s', (ep_id,))
            ep = fetchone_dict(cur)
            if not ep or ep['user_id'] != session['user_id']:
                return jsonify({'error': 'Not found'}), 404
            new_val = 0 if ep['watched'] else 1
            cur.execute('UPDATE episodes SET watched=%s WHERE id=%s', (new_val, ep_id))
    return jsonify({'watched': new_val})

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM watchlist WHERE user_id=%s', (session['user_id'],))
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=%s AND status='Watching'", (session['user_id'],))
            watching = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=%s AND status='Completed'", (session['user_id'],))
            completed = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=%s AND status='Plan to Watch'", (session['user_id'],))
            plan = cur.fetchone()[0]
    return jsonify({'total': total, 'watching': watching, 'completed': completed, 'plan': plan})

@app.route('/api/recent-watchlist')
def recent_watchlist():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT w.title, w.category, w.status, u.username FROM watchlist w JOIN users u ON u.id=w.user_id ORDER BY w.created_at DESC LIMIT 4')
            items = fetchall_dict(cur)
    return jsonify(items)

@app.route('/api/my-recent-watchlist')
@login_required
def my_recent_watchlist():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT title, category, status FROM watchlist WHERE user_id=%s ORDER BY created_at DESC LIMIT 4', (session['user_id'],))
            items = fetchall_dict(cur)
    return jsonify(items)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
