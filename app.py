from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from random import choice, randint
import asyncio
import random
import string
import os
import uuid
from typing import List, Dict
from temporalio.exceptions import FailureError
from temporalio.client import WorkflowFailureError
from client import get_client
from workflow import TriviaWorkflowInput, PlayerWorkflowInput, StartGameSignal, AnswerSignal

import re

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
async def home(): 
    client = await get_client()
    async for wf in client.list_workflows("WorkflowType = 'TriviaGameWorkflow'"):
        handle = client.get_workflow_handle(wf.id, run_id=wf.run_id)

        desc = await handle.describe()

        if (desc.status == 1):
            regex = re.search(r'(?<=trivia-game-)\d+$', wf.id)

            if regex:
                game_id = regex.group()
                #games[game_id] = "ready"
                trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
                players = await trivia_workflow.query("getPlayers")
                player_names = []
                if game_id not in games:
                    games[game_id]["users"] = {}
                for player in players:
                    print("PLAYER NAME")
                    print(player)
                    player_names.append(player)          
                games[game_id]["users"] = player_names
                #update_players(game_id)
    return render_template('index.html', games=games)

async def update_players(game_id):
    client = await get_client()

    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    players = await trivia_workflow.query("getPlayers")
    player_names = []
    if game_id not in games:
        games[game_id]["users"] = {}
    for player in players:
        print("PLAYER NAME")
        print(player)
        player_names.append(player)          
    games[game_id]["users"] = player_names

@app.route('/create_game')
async def create_game():
    game_id = str(uuid.uuid4().int)[:6] 
    games[game_id] = {"users": [], "current_question": None, "answers": []}
    games[game_id]["started"] = False

    trivia_game_input = TriviaWorkflowInput(
        NumberOfPlayers=2,
        NumberOfQuestions=2,
        AnswerTimeLimit=30,
    )  

    # Start booking workflow
    client = await get_client()

    await client.start_workflow(
        "TriviaGameWorkflow",
        trivia_game_input,
        id=f'trivia-game-{game_id}',
        task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
    )

    return redirect(url_for('join', game_id=game_id, create=True))

@app.route('/<game_id>/start')
async def start(game_id):
    games[game_id]["started"] = True
    games[game_id]["current_question"] = choice(questions)
    games[game_id]["status"] = "ready"

    # Start player workflow
    client = await get_client()

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
        username = request.form['username']

        player_input = PlayerWorkflowInput(
            GameWorkflowId=f'trivia-game-{game_id}',
            Player=username,
        )  

        # Start player workflow
        client = await get_client()

        await client.execute_workflow(
            "AddPlayerWorkflow",
            player_input,
            id=f'player-{username}-{game_id}',
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE"),
        )

        trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
        players = await trivia_workflow.query("getPlayers")
        player_names = []
        if game_id not in games:
            games[game_id]["users"] = {}
        for player in players:
            print("PLAYER NAME2")
            print(player)
            player_names.append(player)          
        games[game_id]["users"] = player_names
        print("HERE USERS")
        print(username)

        print(games)
        #if username not in games[game_id]["users"]:        
        #    games[game_id]["users"][username] = 0
        session['username'] = username
        session['game_id'] = game_id
 

        if len(games[game_id]["users"]) >= 2:
            return redirect(url_for('start', game_id=game_id, player=username))
        else:
            return redirect(url_for('lobby', game_id=game_id, player=username))
    else:
        return render_template('join.html', game_id=game_id)

@app.route('/<game_id>/lobby')
def lobby(game_id):
    return render_template('lobby.html', users=games[game_id]["users"], game_id=game_id)

@app.route('/<string:game_id>/get_player_count', methods=['GET'])
def get_player_count(game_id):
    game = games[game_id]
    print("PLAYER COUNT")
    print(game)
    return jsonify({'count': len(game["users"]), 'users': game["users"]})

@app.route('/<game_id>/check_ready', methods=['GET'])
async def check_ready(game_id):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    questions = await trivia_workflow.query("getQuestions")
    if not questions:
        return jsonify({'ready': False})
    else:
        print(questions)
        games[game_id]["questions"] = questions
        return jsonify({'ready': True})

    #if games[game_id]['status'] == 'ready':
    #    return jsonify({'ready': True})
    #else:
    #    return jsonify({'ready': False})


@app.route('/<game_id>/<question>/check_progress', methods=['GET'])
async def check_progress(game_id, question):

    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    progress = await trivia_workflow.query("getProgress")

    question = int(question)
    if question == progress["numberOfQuestions"] and progress["stage"] == "scores":
        print("END END END")
        return jsonify({'ready': True, 'show_score' : True})
    elif question != progress["currentQuestion"] and progress["stage"] == "answers":
            print("NEXT NEXT NEXT")
            return jsonify({'ready': True, 'show_score' : False})
    else:
        print("STAY STAY STAY")
        return jsonify({'ready': False, 'show_score' : False})


@app.route('/<game_id>/play', methods=['GET', 'POST'])
async def play(game_id):

    client = await get_client()
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')
    questions = games[game_id]["questions"]
    print("HERE QUESTIONS")
    print(games[game_id]["number_questions"])

    #for i in questions:
    progress = await trivia_workflow.query("getProgress")
    print(progress["currentQuestion"])
    i=str(progress["currentQuestion"])
    question = questions[i]["question"]
    answer = questions[i]["answer"]
    choices = questions[i]["multipleChoiceAnswers"]

    if request.method == 'GET':
        #question = games[game_id]["current_question"]['question']
        #choices = games[game_id]["current_question"]['choices']

        return render_template('play.html', question=question, choices=choices, game_id=game_id)
    else:
        choice = request.form['choice']
        print("here")
        print(choice)
        print(questions[i]['answer'])

        AnswerSignalInput = AnswerSignal(
            action="Answer",
            player=session['username'],
            question=int(i),
            answer=choice
        )    

        #await trivia_workflow.signal("answer-signal", AnswerSignalInput)            
        #if questions[i]['answer'] == choice:
        #if games[game_id]["current_question"]['answer'] == choice:
        #    games[game_id]["users"][session['username']] += 1

        # Check if this user has already submitted an answer
        user_answer = next((answer for answer in games[game_id]["answers"] if answer['username'] == session['username']), None)
        await trivia_workflow.signal("answer-signal", AnswerSignalInput) 
        if user_answer:
            # Update the existing answer
            user_answer['choice'] = choice
            #user_answer['correct'] = games[game_id]["current_question"]['answer']
            user_answer['correct'] = questions[i]['answer']
        else:
            # Append a new answer
            games[game_id]["answers"].append({
                'username': session['username'],
                'choice': choice,
                #'correct': games[game_id]["current_question"]['answer']
                'correct': questions[i]['answer']
            })              

        print("here123455")
        print(games[game_id])
        #next_question = int(games[game_id]["question_number"] +1)
        #games[game_id]["question_number"] = str(next_question)
        #player = games[game_id]["answers"]["username"]
        #selection = games[game_id]["answers"]["choice"]
        #return render_template('results.html', player=player,selection=selection, question=question, choices=choices, answer=answer, game_id=game_id)
        #return redirect(url_for('results', game_id=game_id))
        return render_template('results.html', results=games[game_id]["answers"], question_number=i, question=question, choices=choices, answer=answer, game_id=game_id)

@app.route('/<game_id>/results')
def results(game_id):
    return render_template('results.html', results=games[game_id]["answers"], question=games[game_id]["current_question"], game_id=game_id)

@app.route('/<game_id>/end')
async def end(game_id):
    client = await get_client()
   
    trivia_workflow = client.get_workflow_handle(f'trivia-game-{game_id}')

    players = await trivia_workflow.query("getPlayers")    
    return render_template('end.html', players=players, game_id=game_id)

if __name__ == '__main__':
    app.run(debug=True)

