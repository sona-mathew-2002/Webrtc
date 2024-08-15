

from flask import Flask, request, jsonify, Response
from langchain_community.llms import Ollama
import base64
import asyncio
import concurrent.futures
import json
from langchain_community.llms import Ollama

app = Flask(__name__)
ollama_model = Ollama(model="phi3")


data = {}

@app.route('/test')
def test():
    return Response('{"status":"ok"}', status=200, mimetype='application/json')

@app.route('/offer', methods=['POST'])
def offer():
    if request.form.get("type") == "offer":
        data["offer"] = {"id" : request.form['id'], "type" : request.form['type'], "sdp" : request.form['sdp']}
        return Response(status=200)
    else:
        return Response(status=400)

@app.route('/answer', methods=['POST'])
def answer():
    if request.form.get("type") == "answer":
        data["answer"] = {"id" : request.form['id'], "type" : request.form['type'], "sdp" : request.form['sdp']}
        return Response(status=200)
    else:
        return Response(status=400)



@app.route('/get_offer', methods=['GET'])
def get_offer():
    if "offer" in data:
        j = json.dumps(data["offer"])
        del data["offer"]
        return Response(j, status=200, mimetype='application/json')
    else:
        return Response(status=503)

@app.route('/get_answer', methods=['GET'])
def get_answer():
    if "answer" in data:
        j = json.dumps(data["answer"])
        del data["answer"]
        return Response(j, status=200, mimetype='application/json')
    else:
        return Response(status=503)

async def summarize_text(text):
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        summary = await loop.run_in_executor(pool, ollama_model.invoke, "Give the best option from the given. Casual shoes for a men of size 8" + text)
    return summary

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.json
    input_text = data['text']
    summary = asyncio.run(summarize_text(input_text))
    return jsonify({'summary': summary})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=9090, debug=True)

