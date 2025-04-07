from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def home():
    submitted_data = None
    if request.method == "POST":
        seed_urls_raw = request.form.get("seed_urls")
        depth_limit = request.form.get("depth_limit")
        domain_restriction = request.form.get("domain_restriction")

        seed_urls = [url.strip() for url in seed_urls_raw.splitlines() if url.strip()]

        print(f"User submitted Seed URLs: {seed_urls}")
        if depth_limit:
            print(f"User submitted Depth Limit: {depth_limit}")
        if domain_restriction:
            print(f"User submitted Domain Restriction: {domain_restriction}")

        submitted_data = {
            "seed_urls": seed_urls,
            "depth_limit": depth_limit,
            "domain_restriction": domain_restriction,
        }
        return render_template("index.html", submitted_data=submitted_data)
    return render_template("index.html", submitted_data=None)

if __name__ == "__main__":
    app.run(debug=True, port=5000)