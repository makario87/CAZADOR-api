from flask import Flask, request

app = Flask(__name__)

ultima_senal = "NINGUNA"

@app.route("/")
def home():

    return f"""
    <h1>CAZADOR API ONLINE</h1>
    <h2>ULTIMA SEÑAL: {ultima_senal}</h2>
    """

@app.route("/webhook", methods=["POST"])
def webhook():

    global ultima_senal

    data = request.json

    ultima_senal = data["action"]

    print(data)

    return f"SEÑAL RECIBIDA: {ultima_senal}"

@app.route("/estado")
def estado():

    return f"ULTIMA SEÑAL: {ultima_senal}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
