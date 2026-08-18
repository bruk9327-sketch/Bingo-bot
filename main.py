from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import time
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bkbingo_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# የውሸት ዳታቤዝ (Memory Storage)
user_balances = {}       # {user_id: balance}
taken_cards_global = []  # በወቅቱ የተያዙ ካርቴላዎች
game_timer = 15          # የሰዓት ቆጣሪ (ሰከንድ)
game_active = False      # ጨዋታው እየተካሄደ መሆኑን ማረጋገጫ
sold_cards_in_round = [] # በዚህ ዙር የተሸጡ ካርቴላዎች
drawn_balls = []         # የወጡ ኳሶች
current_draw_thread = None

# ተጠቃሚ ሲገባ 10 ብር ቦነስ የሚሰጥበት እና ባላንስ የሚያነብበት
@socketio.on('get_user_balance')
def handle_get_balance(data):
    user_id = data.get('user_id')
    if not user_id:
        return
    
    # ተጠቃሚው ሰርቨር ላይ ከሌለ 10 ብር ቦነስ እንሰጠዋለን
    if user_id not in user_balances:
        user_balances[user_id] = 10.00
    
    emit('balance_update', {'user_id': user_id, 'balance': user_balances[user_id]})
    emit('update_selected_cards', {'taken_cards': taken_cards_global})

# ካርቴላ መምረጫ
@socketio.on('select_card')
def handle_select_card(data):
    global game_active
    if game_active:
        emit('error_msg', {'msg': 'ጨዋታው ተጀምሯል! እባክዎ የሚቀጥለውን ዙር ይጠብቁ።'})
        return

    user_id = data.get('user_id')
    card_id = int(data.get('card_id'))
    card_price = 10.00

    if user_id not in user_balances:
        user_balances[user_id] = 10.00

    # የተጠቃሚውን ብር ማረጋገጥ
    if user_balances[user_id] < card_price:
        emit('error_msg', {'msg': 'በቂ ባላንስ የለም። እባክዎ አካውንትዎ ላይ ብር ይጫኑ!'})
        return

    if card_id in taken_cards_global:
        emit('error_msg', {'msg': 'ይህ ካርቴላ ተይዟል!'})
        return

    # ብር መቀነስ እና ካርቴላውን መያዝ
    user_balances[user_id] -= card_price
    taken_cards_global.append(card_id)
    sold_cards_in_round.append({'user_id': user_id, 'card_id': card_id})

    # የካርቴላ ማትሪክስ (5x5) ማመንጨት
    matrix = generate_bingo_matrix(card_id)

    emit('balance_update', {'user_id': user_id, 'balance': user_balances[user_id]})
    emit('card_confirmed', {'card_id': card_id, 'matrix': matrix, 'new_balance': user_balances[user_id]}, broadcast=True)
    socketio.emit('update_selected_cards', {'taken_cards': taken_cards_global})

def generate_bingo_matrix(seed_val):
    import random
    random.seed(seed_val)
    b = random.sample(range(1, 16), 5)
    i = random.sample(range(16, 31), 5)
    n = random.sample(range(31, 46), 4)
    n.insert(2, 'FREE')
    g = random.sample(range(46, 61), 5)
    o = random.sample(range(61, 76), 5)
    
    matrix = []
    for row in range(5):
        matrix.append([b[row], i[row], n[row], g[row], o[row]])
    return matrix

# የሰዓት ቆጣሪ እና የጨዋታ ሉፕ (Background Thread)
def game_timer_loop():
    global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls
    while True:
        if not game_active:
            if game_timer > 0:
                time.sleep(1)
                game_timer -= 1
                socketio.emit('timer_update', {
                    'time_left': game_timer,
                    'sold_count': len(sold_cards_in_round)
                })
            else:
                # ሰዓቱ ሲያልቅ ካርቴላዎች ከተሸጡ ጨዋታው ይጀምራል
                if len(sold_cards_in_round) > 0:
                    game_active = True
                    derash = len(sold_cards_in_round) * 10.00 * 0.8  # 20% የቤት ድርሻ ሲቀነስ
                    socketio.emit('game_started', {'derash': derash})
                    run_game_draw()
                else:
                    # ካርቴላ ካልተገዛ ጨዋታውን ላለማቆም ሰዓቱን ራሱ ወደ 15 ሰከንድ ይመልሰዋል
                    game_timer = 15
        else:
            time.sleep(1)

def run_game_draw():
    global game_active, drawn_balls, taken_cards_global, sold_cards_in_round, game_timer
    import random
    available_balls = list(range(1, 76))
    random.shuffle(available_balls)
    drawn_balls = []

    for ball in available_balls:
        if not game_active:
            break
        drawn_balls.append(ball)
        
        # የፊደል አጠራር (B, I, N, G, O) ማስተካከያ
        prefix = 'B' if ball <= 15 else ('I' if ball <= 30 else ('N' if ball <= 45 else ('G' if ball <= 60 else 'O')))
        display_str = f"{prefix}-{ball}"
        
        socketio.emit('new_number', {'ball': ball, 'display': display_str})
        time.sleep(3) # እያንዳንዱ ቁጥር የሚጠራበት ሰዓት ክፍተት (3 ሰከንድ)

# አሸናፊ ማረጋገጫ (Claim Bingo)
@socketio.on('claim_bingo')
def handle_claim_bingo(data):
    global game_active
    user_id = data.get('user_id')
    card_id = data.get('card_id')
    board = data.get('board') # 5x5 boolean matrix ከፍሮንትኤንድ የሚመጣ

    # የቢንጎ መስመር መሟላቱን በሰርቨር ማረጋገጥ
    if check_bingo_win(board):
        game_active = False
        prize = len(sold_cards_in_round) * 10.00 * 0.8
        user_balances[user_id] = user_balances.get(user_id, 0) + prize
        
        matrix = generate_bingo_matrix(card_id)
        socketio.emit('winner_announced', {
            'winner_name': f"ተጫዋች {user_id}",
            'winner_ids': [user_id],
            'prize': prize,
            'card_id': card_id,
            'card_matrix': matrix
        })
        
        # ጨዋታውን ከ 6 ሰከንድ በኋላ ለሚቀጥለው ዙር ማቀናበር (Reset)
        threading.Thread(target=reset_game_state_delayed).start()
        emit('bingo_response', {'status': 'success', 'message': 'እንኳን ደስ አለዎት! አሸናፊ ሆነዋል! 🎉'})
    else:
        emit('bingo_response', {'status': 'fail', 'message': '❌ ቢንጎ አልተሟላም! እባክዎ በትክክል ይጫኑ።'})

def check_bingo_win(board):
    # ረድፎች (Rows)
    for r in range(5):
        if all(board[r][c] for c in range(5)): return True
    # አምዶች (Columns)
    for c in range(5):
        if all(board[r][c] for r in range(5)): return True
    # ሰያፍ (Diagonals)
    if all(board[i][i] for i in range(5)): return True
    if all(board[i][4-i] for i in range(5)): return True
    return False

def reset_game_state_delayed():
    global game_timer, game_active, taken_cards_global, sold_cards_in_round, drawn_balls
    time.sleep(6)
    taken_cards_global = []
    sold_cards_in_round = []
    drawn_balls = []
    game_timer = 15
    game_active = False
    socketio.emit('reset_game', {})

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # የሰዓት ቆጣሪውን በጀርባ (Background) ማስጀመር
    threading.Thread(target=game_timer_loop, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
