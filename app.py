from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import uuid
from client import get_client
from temporalio.client import WorkflowFailureError
from workflow import TriviaWorkflowInput, PlayerWorkflowInput, StartGameSignal, AnswerSignal
import qrcode
import qrcode.image.svg
import re

app = Flask(__name__)
app.secret_key = 'SA_R0ck5!'

games = {}

@app.route('/')
async def home(): 
    client = await get_client()
    async for wf in client.list_workflows("WorkflowType = 'TriviaGameWorkflow'"):
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)

        desc = await handle.describe()
        regex = re.search(r'(?<=trivia-game-)\d+$', wf.id)

        game_id = None
        if regex:
            game_id = regex.group() 
        if (desc.status == 1):               
                trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
                players = await trivia_workflow.query("getPlayers")
                player_names = []

                if game_id not in games:
                    games[game_id] = {}
                    games[game_id]["users"] = {}
                for player in players:
                    player_names.append(player)   

                progress = await trivia_workflow.query("getProgress")
                if progress["stage"] != "start":
                    games[game_id]["started"] = True

                games[game_id]["users"] = player_names
        else:
            if game_id is not None and game_id in games:
                del games[game_id]
                
                qr_file = f'static/qr/qr-{game_id}.gif'
                if os.path.isfile(qr_file):
                    os.remove(qr_file)      

    return render_template('index.html', games=games)

def create_qr_code(game_id):
    img = qrcode.make(f'https://triviav2.tmprl-demo.cloud/{game_id}/join')
    with open(f'static/qr/qr-{game_id}.gif', 'wb') as qr:
        img.save(qr)

@app.route('/create_game', methods=['GET', 'POST'])
async def create_game():
    if request.method == 'POST':
        player = request.form['player']
        if not re.match('^[a-zA-Z0-9]+$', player):
            return render_template('create.html', error='Player can only contain letters and numbers without spaces.')        

        number_questions = int(request.form.get('questions'))
        number_players = int(request.form.get('players'))

        category_dropdown = request.form.get('category')
        category_custom = request.form.get('customCategory')

        if category_dropdown == 'custom':
            category = category_custom
        else:
            category = category_dropdown

        if category == 'random':
            category = ""    

        game_id = str(uuid.uuid4().int)[:6] 
        games[game_id] = {"users": [], "answers": []}
        games[game_id]["number_players"] = number_players

        client = await get_client()

        trivia_game_input = TriviaWorkflowInput(
            Category=category,
            NumberOfPlayers=number_players,
            NumberOfQuestions=number_questions,
            AnswerTimeLimit=60,
            StartTimeLimit=300,
            ResultTimeLimit=10,
        )               

        await client.start_workflow(
            "TriviaGameWorkflow",
            trivia_game_input,
            id=f'trivia-game-{game_id}',
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
        )

        create_qr_code(game_id)

        player_input = PlayerWorkflowInput(
            GameWorkflowId=f'trivia-game-{game_id}',
            Player=player,
        )  

        try:
            await client.execute_workflow(
                "AddPlayerWorkflow",
                player_input,
                id=f'player-{player}-{game_id}',
                task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )
        except:
            return render_template('create.html', error='Player name failed moderation')
            

        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        players = await trivia_workflow.query("getPlayers")
        player_names = []
        if game_id not in games:
            games[game_id]["users"] = {}
        for player in players:
            player_names.append(player)          
        games[game_id]["users"] = player_names

        session['username'] = player
        session['game_id'] = game_id

        if len(games[game_id]["users"]) >= games[game_id]["number_players"]:
            return redirect(url_for('start', game_id=game_id, player=player))
        else:
            return redirect(url_for('lobby', game_id=game_id, player=player, number_players=games[game_id]["number_players"]))
    else:
        return render_template('create.html')        

@app.route('/<game_id>/start')
async def start(game_id):
    client = await get_client()

    games[game_id]["started"] = True

    StartGameSignalInput = StartGameSignal(
        action="StartGame"
    )    

    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    await trivia_workflow.signal("start-game-signal", StartGameSignalInput)
    progress = await trivia_workflow.query("getProgress")
    games[game_id]["number_questions"] = int(progress["numberOfQuestions"])
    games[game_id]["question_number"] = "1"

    return render_template('start.html', game_id=game_id)

@app.route('/<game_id>/join', methods=['GET', 'POST'])
async def join(game_id):
    if request.method == 'POST':
        player = request.form['player']
        if not re.match('^[a-zA-Z0-9]+$', player):
            return render_template('join.html', game_id=game_id, error='Player can only contain letters and numbers without spaces.')        

        player_input = PlayerWorkflowInput(
            GameWorkflowId=f'trivia-game-{game_id}',
            Player=player,
        )  

        client = await get_client()

        try:
            await client.execute_workflow(
            "AddPlayerWorkflow",
            player_input,
            id=f'player-{player}-{game_id}',
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )
        except WorkflowFailureError:
            return render_template('join.html', game_id=game_id, error='Player name failed moderation')
        
        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        players = await trivia_workflow.query("getPlayers")
        player_names = []
        if game_id not in games:
            games[game_id]["users"] = {}
        for player in players:
            player_names.append(player)          
        games[game_id]["users"] = player_names

        session['username'] = player
        session['game_id'] = game_id
 
        if len(games[game_id]["users"]) >= games[game_id]["number_players"]:
            return redirect(url_for('start', game_id=game_id, player=player))
        else:
            return redirect(url_for('lobby', game_id=game_id, player=player, number_players=games[game_id]["number_players"]))
    else:
        return render_template('join.html', game_id=game_id)

@app.route('/<game_id>/lobby')
def lobby(game_id):    
    return render_template('lobby.html', users=games[game_id]["users"], game_id=game_id, number_players=games[game_id]["number_players"])

@app.route('/<string:game_id>/get_player_count', methods=['GET'])
def get_player_count(game_id):
    game = games[game_id]

    return jsonify({'count': len(game["users"]), 'users': game["users"], 'number_players': games[game_id]["number_players"]})

@app.route('/<game_id>/check_results')
async def get_results_ready(game_id):
    client = await get_client()  

    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    progress = await trivia_workflow.query("getProgress")  
    
    if progress["stage"] == "result":
        return jsonify({'ready': True})
    else:
        return jsonify({'ready': False})

@app.route('/<game_id>/check_ready', methods=['GET'])
async def check_ready(game_id):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    questions = await trivia_workflow.query("getQuestions")
    if not questions:
        return jsonify({'ready': False})
    else:
        games[game_id]["questions"] = questions
        return jsonify({'ready': True})

@app.route('/<game_id>/<question>/check_progress', methods=['GET'])
async def check_progress(game_id, question):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    progress = await trivia_workflow.query("getProgress")

    question = int(question)
    if question == progress["numberOfQuestions"] and progress["stage"] == "scores":
        return jsonify({'ready': True, 'show_score' : True})
    elif question != progress["currentQuestion"] and progress["stage"] == "answers":
            return jsonify({'ready': True, 'show_score' : False})
    else:
        return jsonify({'ready': False, 'show_score' : False})


@app.route('/<game_id>/play', methods=['GET', 'POST'])
async def play(game_id):

    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    questions = games[game_id]["questions"]

    progress = await trivia_workflow.query("getProgress")
    i=str(progress["currentQuestion"])
    question = questions[i]["question"]
    choices = questions[i]["multipleChoiceAnswers"]

    if request.method == 'GET':
        return render_template('play.html', question=question, choices=choices, game_id=game_id)
    else:
        choice = request.form['choice']
        choice_lower = choice.lower()

        AnswerSignalInput = AnswerSignal(
            action="Answer",
            player=session['username'],
            question=int(i),
            answer=choice_lower
        )   

        if "answers" not in games[game_id]:
            games[game_id]["answers"] = {}

        index = int(i)
        while len(games[game_id]["answers"]) <= index:
            games[game_id]["answers"].append({})
        games[game_id]["answers"][index][session['username']] = {
            'choice': choice,
            'correct': questions[i]['answer']
        }          

        await trivia_workflow.signal("answer-signal", AnswerSignalInput)         

        return jsonify({'status': 'success'})

@app.route('/<game_id>/<choice>/results')
async def results(game_id,choice):
    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    questions = games[game_id]["questions"]

    progress = await trivia_workflow.query("getProgress")
    i=str(progress["currentQuestion"])
    question = questions[i]["question"]
    answer = questions[i]["answer"]
    choices = questions[i]["multipleChoiceAnswers"]

    index = int(i)

    return render_template('results.html', results=games[game_id]["answers"][index], question_number=i, question=question, choices=choices, answer=answer, game_id=game_id, stage=progress["stage"])

@app.route('/<game_id>/view')
async def view(game_id):  
    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    players = await trivia_workflow.query("getPlayers")

    return render_template('end.html', players=players, game_id=game_id)

@app.route('/<game_id>/end')
async def end(game_id):  
    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    players = await trivia_workflow.query("getPlayers")
    progress = await trivia_workflow.query("getProgress")

    if progress["stage"] == "scores":
        if game_id in games:
            del games[game_id]   

    qr_file = f'static/qr/qr-{game_id}.gif'
    if os.path.isfile(qr_file):
        os.remove(qr_file)

    return render_template('end.html', players=players, game_id=game_id)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True) 

