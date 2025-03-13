import os
import json
import random
import secrets
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database handling
DB_FILE = 'database.json'

def load_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f:
            json.dump({"users": {}, "game_stats": {}}, f)
    
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, 'w') as f:
        json.dump(db, f, indent=2)

# User Model
class User(UserMixin):
    def __init__(self, id, username, email, balance=1000):
        self.id = id
        self.username = username
        self.email = email
        self.balance = balance

@login_manager.user_loader
def load_user(user_id):
    db = load_db()
    if user_id in db['users']:
        user_data = db['users'][user_id]
        return User(
            user_id, 
            user_data['username'],
            user_data['email'],
            user_data['balance']
        )
    return None

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        db = load_db()
        
        # Check if username or email already exists
        for user_id, user_data in db['users'].items():
            if user_data['username'] == username:
                flash('Username already exists')
                return redirect(url_for('register'))
            if user_data['email'] == email:
                flash('Email already exists')
                return redirect(url_for('register'))
        
        # Create new user
        user_id = str(secrets.randbits(32))
        db['users'][user_id] = {
            'username': username,
            'email': email,
            'password': generate_password_hash(password),
            'balance': 1000,  # Initial balance
            'created_at': datetime.now().isoformat()
        }
        
        save_db(db)
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = load_db()
        
        user_id = None
        user_data = None
        
        # Find user by username
        for uid, data in db['users'].items():
            if data['username'] == username:
                user_id = uid
                user_data = data
                break
        
        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_id, user_data['username'], user_data['email'], user_data['balance'])
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/mines')
@login_required
def mines_game():
    return render_template('mines.html')

@app.route('/api/balance')
@login_required
def get_balance():
    db = load_db()
    balance = db['users'][current_user.id]['balance']
    return jsonify({'balance': balance})

@app.route('/api/update_balance', methods=['POST'])
@login_required
def update_balance():
    amount = int(request.json.get('amount', 0))
    
    db = load_db()
    db['users'][current_user.id]['balance'] += amount
    save_db(db)
    
    return jsonify({'success': True, 'balance': db['users'][current_user.id]['balance']})

@app.route('/api/mines/start', methods=['POST'])
@login_required
def start_mines_game():
    bet_amount = int(request.json.get('bet_amount', 0))
    mines_count = int(request.json.get('mines_count', 5))
    
    if mines_count < 1 or mines_count > 24:
        return jsonify({'error': 'Invalid mines count'}), 400
    
    db = load_db()
    user_balance = db['users'][current_user.id]['balance']
    
    if bet_amount <= 0:
        return jsonify({'error': 'Invalid bet amount'}), 400
    
    if user_balance < bet_amount:
        return jsonify({'error': 'Insufficient balance'}), 400
    
    # Deduct bet amount
    db['users'][current_user.id]['balance'] -= bet_amount
    save_db(db)
    
    # Generate game state
    grid_size = 25  # 5x5 grid
    mines_positions = random.sample(range(grid_size), mines_count)
    
    # Save game state in session
    session['game_state'] = {
        'mines_positions': mines_positions,
        'bet_amount': bet_amount,
        'mines_count': mines_count,
        'revealed_positions': [],
        'active': True,
        'won': False,
        'multiplier': 1.0
    }
    
    return jsonify({
        'success': True,
        'balance': db['users'][current_user.id]['balance'],
        'game_started': True
    })

@app.route('/api/mines/reveal', methods=['POST'])
@login_required
def reveal_tile():
    position = int(request.json.get('position', -1))
    
    if position < 0 or position >= 25:
        return jsonify({'error': 'Invalid position'}), 400
    
    if 'game_state' not in session or not session['game_state']['active']:
        return jsonify({'error': 'No active game'}), 400
    
    game_state = session['game_state']
    
    if position in game_state['revealed_positions']:
        return jsonify({'error': 'Tile already revealed'}), 400
    
    # Check if mine hit
    if position in game_state['mines_positions']:
        # Game over - player lost
        game_state['active'] = False
        game_state['won'] = False
        session['game_state'] = game_state
        
        return jsonify({
            'success': True,
            'is_mine': True,
            'game_over': True,
            'won': False,
            'mines_positions': game_state['mines_positions']
        })
    
    # Reveal safe tile
    game_state['revealed_positions'].append(position)
    
    # Calculate new multiplier based on revealed tiles
    safe_tiles = 25 - game_state['mines_count']
    revealed_count = len(game_state['revealed_positions'])
    
    # Simple multiplier calculation - increases as more safe tiles are revealed
    # This is a basic formula, could be adjusted for better game economics
    multiplier = 1 + (revealed_count / safe_tiles) * game_state['mines_count']
    game_state['multiplier'] = multiplier
    
    # Check if all safe tiles revealed (game won)
    if revealed_count == safe_tiles:
        game_state['active'] = False
        game_state['won'] = True
        
        # Award winnings
        winnings = int(game_state['bet_amount'] * multiplier)
        db = load_db()
        db['users'][current_user.id]['balance'] += winnings
        save_db(db)
        
        session['game_state'] = game_state
        
        return jsonify({
            'success': True,
            'is_mine': False,
            'game_over': True,
            'won': True,
            'multiplier': multiplier,
            'winnings': winnings,
            'balance': db['users'][current_user.id]['balance'],
            'mines_positions': game_state['mines_positions']
        })
    
    session['game_state'] = game_state
    
    return jsonify({
        'success': True,
        'is_mine': False,
        'game_over': False,
        'revealed_positions': game_state['revealed_positions'],
        'multiplier': multiplier,
        'potential_win': int(game_state['bet_amount'] * multiplier)
    })

@app.route('/api/mines/cashout', methods=['POST'])
@login_required
def cashout():
    if 'game_state' not in session or not session['game_state']['active']:
        return jsonify({'error': 'No active game'}), 400
    
    game_state = session['game_state']
    
    # Calculate winnings
    winnings = int(game_state['bet_amount'] * game_state['multiplier'])
    
    # Update balance
    db = load_db()
    db['users'][current_user.id]['balance'] += winnings
    save_db(db)
    
    # End game
    game_state['active'] = False
    game_state['won'] = True
    session['game_state'] = game_state
    
    return jsonify({
        'success': True,
        'winnings': winnings,
        'balance': db['users'][current_user.id]['balance'],
        'mines_positions': game_state['mines_positions']
    })

if __name__ == '__main__':
    app.run(debug=True)