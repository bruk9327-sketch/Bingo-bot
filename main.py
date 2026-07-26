from flask import jsonify, request

@app.route('/api/sync-balance', methods=['POST'])
def sync_balance():
    data = request.json
    user_id = data.get('user_id')
    new_balance = data.get('balance')
    
    if user_id and new_balance is not None:
        user_balances[user_id] = float(new_balance)
        return jsonify({"status": "success", "balance": user_balances[user_id]})
    return jsonify({"status": "error"}), 400
