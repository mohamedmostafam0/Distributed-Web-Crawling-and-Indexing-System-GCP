from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        url = request.form.get("url")
        print(f"User submitted URL: {url}")  # You can do more with the URL here
        return render_template("index.html", url=url)
    return render_template("index.html", url=None)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
