from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import uuid
from client import get_client
from temporalio.client import WorkflowFailureError
from workflow import TriviaWorkflowInput, GamesWorkflowInput, PlayerWorkflowInput, StartGameSignal, AnswerSignal
import qrcode
import qrcode.image.svg
import re
from typing import List, Dict
import dns.resolver
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'SA_R0ck5!'

games = {}

@app.route('/')
async def home(): 
    return render_template('login.html')

@app.route('/game')
async def game():

    print(games)
    client = await get_client()
    try:
        trivia_workflow = client.get_workflow_handle(workflow_id="trivia-game")
        desc = await trivia_workflow.describe()
        if (desc.status != 1):
            print("Trivia game state workflow does is not running, starting...")
            
            await client.start_workflow(
                "TriviaGamesWorkflow",
                id=f'trivia-game',
                task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )                
    except:
        print("Trivia game state workflow does not exist, starting...")
        
        await client.start_workflow(
            "TriviaGamesWorkflow",
            id=f'trivia-game',
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
        )        
    
    game_status = await trivia_workflow.query("getGames") 
    print(game_status)
    for game_id in game_status:
        print("here")
        game_id = None
    
        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

        # Try to get players, if we aren't successful skip workflow as something is likely wrong with it.
        players: List[Dict] = []
        for _ in range(3):
            try:
                players = await trivia_workflow.query("getPlayers")
                if players:
                    break
            except:
                pass
        else:
            continue

        player_names = []
        if game_id not in games:
            games[game_id] = {}
            games[game_id]["users"] = {}
        for p in players:
            player_names.append(p)   
        
        progress: List[Dict] = []
        while not progress:
            try:
                progress = await trivia_workflow.query("getProgress")             
            except:
                pass

        if progress["stage"] != "start":
            games[game_id]["started"] = True                 

        games[game_id]["users"] = player_names               

    # cleanup games where workflow was deleted due to storage tiering
    for game_id in list(games.keys()):
        if game_id not in game_status:
            del games[game_id]

    return render_template('index.html', games=games)

def create_qr_code(game_id):
    img = qrcode.make(f'https://trivia.tmprl-demo.cloud/{game_id}/join')
    with open(f'static/qr/qr-{game_id}.gif', 'wb') as qr:
        img.save(qr)

@app.route('/create_game', methods=['GET', 'POST'])
async def create_game():
    if request.method == 'POST':
        player = request.form['player']
        if not re.match('^[a-zA-Z0-9]+$', player):
            return render_template('create.html', error='Player can only contain letters and numbers without spaces.')        

        mode = request.form.get('mode')
        number_questions = int(request.form.get('questions'))
        number_players = int(request.form.get('players'))

        category_dropdown = request.form.get('category')
        category_custom = request.form.get('customCategory')

        answer_limit=300
        if mode == 'challenge':
            answer_limit=15

        if category_dropdown == 'custom':
            category = category_custom
        else:
            category = category_dropdown

        if category == 'random':
            category = ""    

        game_id = str(uuid.uuid4().int)[:6] 
        games[game_id] = {"users": [], "answers": []}
        games[game_id]["number_players"] = number_players
        games[game_id]["started"] = False
        games[game_id]["answer_limit"] = answer_limit
        
        client = await get_client()

        # Start game state workflow if not started
        try:
            # Attempt to describe the workflow
            handle = client.get_workflow_handle(workflow_id="trivia-game")
            desc = await handle.describe()

            if desc.status.name in ["COMPLETED", "FAILED", "CANCELED", "TIMED_OUT", "TERMINATED"]:
                print("Trivia game state workflow does is not running, starting...")
                
                await client.start_workflow(
                    "TriviaGamesWorkflow",
                    id=f'trivia-game',
                    task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
                )

        except Exception as e:
            print("Trivia game state workflow does not exist, starting...")
            
            await client.start_workflow(
                "TriviaGamesWorkflow",
                id=f'trivia-game',
                task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )                       

        trivia_game_input = TriviaWorkflowInput(
            GameId=game_id,
            Category=category,
            NumberOfPlayers=number_players,
            NumberOfQuestions=number_questions,
            AnswerTimeLimit=answer_limit,
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
            NumberOfPlayers=number_players,
        )  

        try:
            await client.execute_workflow(
                "AddPlayerWorkflow",
                player_input,
                id=f'player-{player}-{game_id}',
                task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )
        except WorkflowFailureError as e:
            return render_template('create.html', error=e.cause)
            

        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        players: List[Dict] = []
        while not players:
            try:
                players = await trivia_workflow.query("getPlayers")
            except:
                pass

        player_names = []
        if game_id not in games:
            games[game_id]["users"] = {}
        for p in players:
            player_names.append(p)          
        games[game_id]["users"] = player_names

        session['username'] = player

        if len(games[game_id]["users"]) >= games[game_id]["number_players"]:
            return redirect(url_for('start', game_id=game_id))
        else:
            return redirect(url_for('lobby', game_id=game_id, number_players=games[game_id]["number_players"]))
    else:
        return render_template('create.html')        

@app.route('/<game_id>/start')
async def start(game_id):
    client = await get_client()

    if not games[game_id]["started"] == True:
        StartGameSignalInput = StartGameSignal(
            action="StartGame"
        )    

        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        await trivia_workflow.signal("start-game-signal", StartGameSignalInput)
        progress: List[Dict] = []
        while not progress:
            try:
                progress = await trivia_workflow.query("getProgress")
            except:
                pass


        games[game_id]["number_questions"] = int(progress["numberOfQuestions"])
        games[game_id]["question_number"] = "1"
        games[game_id]["started"] = True

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
            NumberOfPlayers=games[game_id]["number_players"],
        )  

        client = await get_client()

        player_result = ""
        try:
            player_result = await client.execute_workflow(
            "AddPlayerWorkflow",
            player_input,
            id=f'player-{player}-{game_id}',
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
            )
            print(player_result)
        except WorkflowFailureError as e:
            return render_template('join.html', game_id=game_id, error=e.cause)
        
        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        players: List[Dict] = []
        while not players:
            try:
                players = await trivia_workflow.query("getPlayers")
            except:
                pass

        player_names = []
        if game_id not in games:
            games[game_id]["users"] = {}
        for p in players:
            player_names.append(p)          
        games[game_id]["users"] = player_names

        session['username'] = player
 
        if len(games[game_id]["users"]) >= games[game_id]["number_players"]:
            return redirect(url_for('start', game_id=game_id))
        else:
            return redirect(url_for('lobby', game_id=game_id, number_players=games[game_id]["number_players"]))
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
    progress: List[Dict] = []
    while not progress:
        try:
            progress = await trivia_workflow.query("getProgress")
        except:
            pass

    if progress["stage"] == "result":
        return jsonify({'ready': True})
    else:
        return jsonify({'ready': False})

@app.route('/<game_id>/check_ready', methods=['GET'])
async def check_ready(game_id):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    questions: List[Dict] = []
    while not questions:
        try:
            questions = await trivia_workflow.query("getQuestions")            
        except:
            pass

    if not questions:
        return jsonify({'ready': False})
    else:
        if game_id in games:
            games[game_id]["questions"] = questions
        return jsonify({'ready': True})

@app.route('/<game_id>/<question>/check_progress', methods=['GET'])
async def check_progress(game_id, question):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    progress: List[Dict] = []
    while not progress:
        try:
            progress = await trivia_workflow.query("getProgress")
        except:
            pass

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

    progress: List[Dict] = []
    while not progress:
        try:
            progress = await trivia_workflow.query("getProgress")
        except:
            pass

    i=str(progress["currentQuestion"])
    question = questions[i]["question"]
    choices = questions[i]["multipleChoiceAnswers"]

    if request.method == 'GET':
        return render_template('play.html', question=question, choices=choices, game_id=game_id, answer_limit=games[game_id]["answer_limit"])
    else:
        progress: List[Dict] = []
        while not progress:
            try:
                progress = await trivia_workflow.query("getProgress")
            except:
                return jsonify({'status': 'error'})

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

    progress: List[Dict] = []
    while not progress:
        try:
            progress = await trivia_workflow.query("getProgress")
        except:
            pass

    i=str(progress["currentQuestion"])
    question = questions[i]["question"]
    answer = questions[i]["answer"]
    choices = questions[i]["multipleChoiceAnswers"]

    index = int(i)
    while len(games[game_id]["answers"]) <= index:
        games[game_id]["answers"].append({})

    return render_template('results.html', results=games[game_id]["answers"][index], question_number=i, question=question, choices=choices, answer=answer, game_id=game_id, stage=progress["stage"])

@app.route('/<game_id>/view')
async def view(game_id):  
    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    players: List[Dict] = []
    while not players:
        try:
            players = await trivia_workflow.query("getPlayers")
        except:
            pass

    return render_template('end.html', players=players, game_id=game_id)

@app.route('/<game_id>/end')
async def end(game_id):  
    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    players: List[Dict] = []
    while not players:
        try:
            players = await trivia_workflow.query("getPlayers")
        except:
            pass

    progress: List[Dict] = []
    while not progress:
        try:
            progress = await trivia_workflow.query("getProgress")
        except:
            pass

    if progress["stage"] == "scores":
        if game_id in games:
            del games[game_id]   

    qr_file = f'static/qr/qr-{game_id}.gif'
    if os.path.isfile(qr_file):
        os.remove(qr_file)

    return render_template('end.html', players=players, game_id=game_id)

@app.route('/get_cname')
async def get_cname():

    cname = None
    parsed_url = urlparse('//' + os.getenv("TEMPORAL_HOST_URL")) 
    hostname = parsed_url.hostname
    try:
        result = dns.resolver.resolve(hostname, 'CNAME')
        for rdata in result:
            cname=str(rdata.target)
    except dns.resolver.NoAnswer:
        print('No CNAME record found for', hostname)
    except dns.resolver.NXDOMAIN:
        print('No such domain', hostname)
    except dns.resolver.Timeout:
        print('Timeout while querying', hostname)
    except Exception as e:
        print('Error occurred: ', e)
    return jsonify(cname=cname)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True) 

