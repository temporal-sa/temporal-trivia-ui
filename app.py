from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from random import choice, randint

app = Flask(__name__)
app.secret_key = 'some secret key'  # replace with a real secret key

games = {}

questions = [
    {
        "question": "Which language is used for web apps?",
        "choices": ["PHP", "Python", "JavaScript", "All"],
        "answer": "All"
    },
    # add more questions if desired
]

@app.route('/')
def home():
    return render_template('index.html', games=games)

@app.route('/create_game')
def create_game():
    game_id = f"{randint(0, 9)}{randint(0, 9)}{randint(0, 9)}{randint(0, 9)}"
    games[game_id] = {"users": {}, "current_question": None, "answers": []}
    games[game_id]["started"] = False
    return redirect(url_for('join', game_id=game_id))

@app.route('/<game_id>/start')
def start(game_id):
    games[game_id]["started"] = True
    games[game_id]["current_question"] = choice(questions)
    games[game_id]["status"] = "ready"
    return render_template('start.html', game_id=game_id)

@app.route('/<game_id>/join', methods=['GET', 'POST'])
def join(game_id):
    if request.method == 'POST':
        username = request.form['username']
        if username not in games[game_id]["users"]:
            games[game_id]["users"][username] = 0
        session['username'] = username
        session['game_id'] = game_id
        if len(games[game_id]["users"]) >= 2:
            return redirect(url_for('start', game_id=game_id))
        else:
            return redirect(url_for('lobby', game_id=game_id))
    else:
        return render_template('join.html', game_id=game_id)

@app.route('/<game_id>/lobby')
def lobby(game_id):
     return render_template('lobby.html', users=games[game_id]["users"], game_id=game_id)

@app.route('/<string:game_id>/get_player_count', methods=['GET'])
def get_player_count(game_id):
    game = games[game_id]
    return jsonify({'count': len(games[game_id]["users"]), 'users': games[game_id]["users"]})

@app.route('/<game_id>/check_ready', methods=['GET'])
def check_ready(game_id):
    if games[game_id]['status'] == 'ready':
        return jsonify({'ready': True})
    else:
        return jsonify({'ready': False})

@app.route('/<game_id>/play', methods=['GET', 'POST'])
def play(game_id):
    if request.method == 'GET':
        question = games[game_id]["current_question"]['question']
        choices = games[game_id]["current_question"]['choices']
        return render_template('play.html', question=question, choices=choices, game_id=game_id)
    else:
        choice = request.form['choice']
        if games[game_id]["current_question"]['answer'] == choice:
            games[game_id]["users"][session['username']] += 1

        # Check if this user has already submitted an answer
        user_answer = next((answer for answer in games[game_id]["answers"] if answer['username'] == session['username']), None)

        if user_answer:
            # Update the existing answer
            user_answer['choice'] = choice
            user_answer['correct'] = games[game_id]["current_question"]['answer']
        else:
            # Append a new answer
            games[game_id]["answers"].append({
                'username': session['username'],
                'choice': choice,
                'correct': games[game_id]["current_question"]['answer']
            })

        return redirect(url_for('results', game_id=game_id))

@app.route('/<game_id>/results')
def results(game_id):
    return render_template('results.html', results=games[game_id]["answers"], question=games[game_id]["current_question"], game_id=game_id)

@app.route('/<game_id>/end')
def end(game_id):
    return render_template('end.html', users=games[game_id]["users"], game_id=game_id)

if __name__ == '__main__':
    app.run(debug=True)

