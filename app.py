import json
import os
from functools import wraps
from typing import Any, Dict, List

from flask import Flask, flash, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "replace-this-with-a-strong-secret")
app.config["UPLOAD_FOLDER"] = os.path.join(app.static_folder, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

DATA_FILE = "site_data.json"
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return default_site_data()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return default_site_data()
    return data


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def default_site_data() -> Dict[str, Any]:
    return {
        "site_name": "Initiative for Legal Aid",
        "tagline": "Empowering Access To Justice In South Sudan",
        "hero_image": "/static/uploads/hero.jpg",
        "cta_text": "Get Legal Aid",
        "about_title": "About Us",
        "about_story": "The Initiative for Legal Aid was established to ensure that justice is accessible to all South Sudanese citizens, aligning legal aid with the empowerment of communities.",
        "mission": "We work to protect rights, promote legal awareness, and support vulnerable people through justice-focused advocacy and practical legal assistance.",
        "values": [
            {"title": "Justice And Equality", "text": "We believe in equal rights and opportunities for all."},
            {"title": "Integrity", "text": "We act with honesty, transparency, and accountability."},
            {"title": "Service", "text": "We stand with vulnerable communities and respond with dignity."}
        ],
        "services": [
            {"title": "Access To Justice", "text": "We provide free and subsidized legal assistance, ensuring vulnerable populations have the support they need to assert their rights and seek justice."},
            {"title": "Human Rights Protection", "text": "Our program focuses on monitoring, documenting, and advocating for victims of human rights violations while promoting respect for civil liberties."},
            {"title": "Women And Children\'s Rights", "text": "We champion gender equality and protection for women and children, offering legal support and advocacy against gender-based violence and discrimination."},
            {"title": "Peacebuilding", "text": "Our peacebuilding initiatives foster social cohesion, conflict resolution, and peaceful coexistence among communities affected by violence and displacement."}
        ],
        "projects": [
            {"title": "Legal Empowerment Workshops", "text": "These workshops equip individuals with essential legal knowledge to advocate effectively for their rights."},
            {"title": "Community Dialogues", "text": "Facilitated discussions that aim to resolve conflicts peacefully and strengthen community bonds."},
            {"title": "Advocacy Campaigns", "text": "Targeted campaigns raising awareness about human rights issues affecting local communities."}
        ],
        "testimonials": [
            {"quote": "The support from ILA has changed my life. I finally received the help I needed to claim my rights.", "name": "Amina L.", "role": "Beneficiary"},
            {"quote": "ILA's advocacy work creates real change. We are grateful for their dedication to protecting our rights.", "name": "John D.", "role": "Human Rights Advocate"},
            {"quote": "Through ILA, we learned our rights as women. This knowledge empowers us to stand up and make a difference in our community.", "name": "Sarah M.", "role": "Community Leader"}
        ],
        "contact_address": "Customs Business Area, Along Main Highway, Opp Dr. John Garang Mausoleum, Juba, Central Equatoria State, Republic of South Sudan",
        "contact_phone": "+211 922 460 564 / +211 920 800 802",
        "contact_email": "contact@domain.com",
        "gallery": [
            "/static/uploads/gallery-1.jpg",
            "/static/uploads/gallery-2.jpg",
            "/static/uploads/gallery-3.jpg"
        ]
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            flash("You need to log in to manage the site.")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def handle_upload(file, fallback_name: str) -> str:
    if not file or file.filename == "":
        return fallback_name

    filename = file.filename
    safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in ("-", "_", "."))
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
    file.save(file_path)
    return f"/static/uploads/{safe_name}"


@app.route("/")
def index():
    site = load_data()
    return render_template("index.html", site=site)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            flash("Login successful.")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.")
    return render_template("admin_login.html", site=load_data())


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    site = load_data()
    return render_template("admin_dashboard.html", site=site)


@app.route("/admin/update", methods=["POST"])
@login_required
def update_site():
    data = load_data()
    form = request.form

    data["site_name"] = form.get("site_name", data.get("site_name"))
    data["tagline"] = form.get("tagline", data.get("tagline"))
    data["cta_text"] = form.get("cta_text", data.get("cta_text"))
    data["about_title"] = form.get("about_title", data.get("about_title"))
    data["about_story"] = form.get("about_story", data.get("about_story"))
    data["mission"] = form.get("mission", data.get("mission"))
    data["contact_address"] = form.get("contact_address", data.get("contact_address"))
    data["contact_phone"] = form.get("contact_phone", data.get("contact_phone"))
    data["contact_email"] = form.get("contact_email", data.get("contact_email"))

    # Parse services entries from text area: 'Title | Description'
    services_text = form.get("services_text", "")
    if services_text.strip():
        data["services"] = []
        for line in services_text.splitlines():
            if "|" in line:
                title, description = [part.strip() for part in line.split("|", 1)]
                if title and description:
                    data["services"].append({"title": title, "text": description})

    projects_text = form.get("projects_text", "")
    if projects_text.strip():
        data["projects"] = []
        for line in projects_text.splitlines():
            if "|" in line:
                title, description = [part.strip() for part in line.split("|", 1)]
                if title and description:
                    data["projects"].append({"title": title, "text": description})

    testimonials_text = form.get("testimonials_text", "")
    if testimonials_text.strip():
        data["testimonials"] = []
        for line in testimonials_text.splitlines():
            if "|" in line:
                quote, author = [part.strip() for part in line.split("|", 1)]
                if quote and author:
                    name_part = author.split("-")
                    role = name_part[-1].strip() if len(name_part) > 1 else "Beneficiary"
                    name = author.replace("-" + role, "").strip()
                    data["testimonials"].append({"quote": quote, "name": name, "role": role})

    hero_image = request.files.get("hero_image")
    if hero_image and hero_image.filename:
        data["hero_image"] = handle_upload(hero_image, data.get("hero_image", "/static/uploads/hero.jpg"))

    gallery_images = request.files.getlist("gallery_images")
    if gallery_images:
        for gallery_file in gallery_images:
            if gallery_file and gallery_file.filename:
                image_path = handle_upload(gallery_file, "")
                if image_path:
                    data.setdefault("gallery", [])
                    data["gallery"].append(image_path)

    save_data(data)
    flash("The website content has been updated successfully.")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=True, host="0.0.0.0", port=port)
