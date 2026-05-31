from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3, hashlib, os

app = Flask(__name__)
app.secret_key = 'watchlist_secret_key_2024'
DB = 'watchlist.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        conn.execute('''CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watchlist_id INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            title TEXT DEFAULT '',
            watched INTEGER DEFAULT 0,
            FOREIGN KEY (watchlist_id) REFERENCES watchlist(id)
        )''')
        # migrate: add total_episodes if not exists
        try:
            conn.execute('ALTER TABLE watchlist ADD COLUMN total_episodes INTEGER DEFAULT 0')
        except Exception:
            pass

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

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
                conn.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                             (username, email, hash_password(password)))
            return redirect(url_for('login', success='Account created! Please login.'))
        except sqlite3.IntegrityError:
            return render_template('register.html', error='Username or email already exists.')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    success = request.args.get('success')
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        with get_db() as conn:
            user = conn.execute('SELECT * FROM users WHERE username=? AND password=?',
                                (username, hash_password(password))).fetchone()
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
    query = 'SELECT * FROM watchlist WHERE user_id=?'
    params = [session['user_id']]
    if category:
        query += ' AND category=?'; params.append(category)
    if status:
        query += ' AND status=?'; params.append(status)
    if search:
        query += ' AND title LIKE ?'; params.append(f'%{search}%')
    query += ' ORDER BY created_at DESC'
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item['watched_count'] = conn.execute(
                'SELECT COUNT(*) FROM episodes WHERE watchlist_id=? AND watched=1', (item['id'],)
            ).fetchone()[0]
            items.append(item)
    return jsonify(items)

@app.route('/api/watchlist', methods=['POST'])
@login_required
def add_item():
    data = request.json
    status = data.get('status', 'Plan to Watch')
    rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
    total_eps = data.get('total_episodes', 0)
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO watchlist (user_id, title, category, status, rating, notes, total_episodes) VALUES (?,?,?,?,?,?,?)',
            (session['user_id'], data['title'], data.get('category','Movie'), status, rating, data.get('notes',''), total_eps)
        )
        wid = cur.lastrowid
        if total_eps > 0:
            for ep in range(1, total_eps + 1):
                conn.execute('INSERT INTO episodes (watchlist_id, episode_number) VALUES (?,?)', (wid, ep))
    return jsonify({'success': True})

@app.route('/api/watchlist/<int:item_id>', methods=['PUT'])
@login_required
def update_item(item_id):
    data = request.json
    status = data['status']
    rating = data.get('rating', 0) if status != 'Plan to Watch' else 0
    total_eps = data.get('total_episodes', 0)
    with get_db() as conn:
        conn.execute(
            'UPDATE watchlist SET title=?, category=?, status=?, rating=?, notes=?, total_episodes=? WHERE id=? AND user_id=?',
            (data['title'], data['category'], status, rating, data['notes'], total_eps, item_id, session['user_id'])
        )
        # rebuild episodes if total changed
        existing = conn.execute('SELECT COUNT(*) FROM episodes WHERE watchlist_id=?', (item_id,)).fetchone()[0]
        if total_eps > 0 and existing != total_eps:
            conn.execute('DELETE FROM episodes WHERE watchlist_id=?', (item_id,))
            for ep in range(1, total_eps + 1):
                conn.execute('INSERT INTO episodes (watchlist_id, episode_number) VALUES (?,?)', (item_id, ep))
        elif total_eps == 0:
            conn.execute('DELETE FROM episodes WHERE watchlist_id=?', (item_id,))
        # auto-complete all episodes if status is Completed
        if status == 'Completed' and total_eps > 0:
            conn.execute('UPDATE episodes SET watched=1 WHERE watchlist_id=?', (item_id,))
    return jsonify({'success': True})

@app.route('/api/watchlist/<int:item_id>', methods=['DELETE'])
@login_required
def delete_item(item_id):
    with get_db() as conn:
        conn.execute('DELETE FROM episodes WHERE watchlist_id=?', (item_id,))
        conn.execute('DELETE FROM watchlist WHERE id=? AND user_id=?', (item_id, session['user_id']))
    return jsonify({'success': True})

@app.route('/api/episodes/<int:item_id>', methods=['GET'])
@login_required
def get_episodes(item_id):
    with get_db() as conn:
        item = conn.execute('SELECT * FROM watchlist WHERE id=? AND user_id=?', (item_id, session['user_id'])).fetchone()
        if not item:
            return jsonify({'error': 'Not found'}), 404
        eps = [dict(r) for r in conn.execute('SELECT * FROM episodes WHERE watchlist_id=? ORDER BY episode_number', (item_id,)).fetchall()]
    return jsonify({'title': item['title'], 'episodes': eps})

@app.route('/api/episodes/<int:ep_id>/toggle', methods=['POST'])
@login_required
def toggle_episode(ep_id):
    with get_db() as conn:
        ep = conn.execute('SELECT e.*, w.user_id FROM episodes e JOIN watchlist w ON w.id=e.watchlist_id WHERE e.id=?', (ep_id,)).fetchone()
        if not ep or ep['user_id'] != session['user_id']:
            return jsonify({'error': 'Not found'}), 404
        new_val = 0 if ep['watched'] else 1
        conn.execute('UPDATE episodes SET watched=? WHERE id=?', (new_val, ep_id))
    return jsonify({'watched': new_val})

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    with get_db() as conn:
        total = conn.execute('SELECT COUNT(*) FROM watchlist WHERE user_id=?', (session['user_id'],)).fetchone()[0]
        watching = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=? AND status='Watching'", (session['user_id'],)).fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=? AND status='Completed'", (session['user_id'],)).fetchone()[0]
        plan = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=? AND status='Plan to Watch'", (session['user_id'],)).fetchone()[0]
    return jsonify({'total': total, 'watching': watching, 'completed': completed, 'plan': plan})

@app.route('/api/recent-watchlist')
def recent_watchlist():
    """Public: latest 4 items across all users (no auth needed for landing page preview)."""
    with get_db() as conn:
        items = [dict(row) for row in conn.execute(
            'SELECT w.title, w.category, w.status, u.username FROM watchlist w '
            'JOIN users u ON u.id = w.user_id ORDER BY w.created_at DESC LIMIT 4'
        ).fetchall()]
    return jsonify(items)

@app.route('/api/my-recent-watchlist')
@login_required
def my_recent_watchlist():
    """Logged-in user's latest 4 items."""
    with get_db() as conn:
        items = [dict(row) for row in conn.execute(
            'SELECT title, category, status FROM watchlist WHERE user_id=? ORDER BY created_at DESC LIMIT 4',
            (session['user_id'],)
        ).fetchall()]
    return jsonify(items)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
