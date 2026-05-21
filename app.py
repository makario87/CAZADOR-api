from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "CAZADOR API ONLINE"

@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.json

    print(data)

    return "SEÑAL RECIBIDA"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
    
