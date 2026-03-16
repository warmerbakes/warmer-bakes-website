from flask import Flask, render_template, request, redirect, url_for, flash, session
from pymongo import MongoClient
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
from bson.errors import InvalidId
import os
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from datetime import datetime
from flask import jsonify

load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bakzy_super_secret_key")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

# ── MongoDB ─────────────────────────────────────────────────
try:
    client = MongoClient(os.environ.get("MONGO_URI"))  # FIX: was missing MongoClient()
    db = client["bakzy"]
    collection = db["items"]
    collection_gallery = db['gallery']
    collection_categories = db['category']
    collection_contact=db['contact_us']
    print("[DB] Connected to MongoDB successfully.")
except Exception as e:
    print(f"[DB ERROR] Could not connect to MongoDB: {e}")
    collection = None
    collection_gallery = None
    collection_categories = None

# ── Cloudinary ──────────────────────────────────────────────
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)


# ── Helpers ─────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def safe_save_image(file):
    """Upload to Cloudinary, return secure URL or None."""
    try:
        if file and file.filename and allowed_file(file.filename):
            result = cloudinary.uploader.upload(
                file,
                folder="bakzy",
                overwrite=True,
                resource_type="image",
                transformation=[
                    {"fetch_format": "auto", "quality": "auto"}
                ]
            )
            return result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY UPLOAD ERROR] {e}")
    return None

def safe_delete_image(image_url):
    """Delete from Cloudinary by extracting public_id from URL."""
    try:
        if image_url and "cloudinary.com" in image_url:
            parts = image_url.split("/")
            filename_with_ext = parts[-1]
            folder = parts[-2]
            public_id = f"{folder}/{filename_with_ext.rsplit('.', 1)[0]}"
            cloudinary.uploader.destroy(public_id)
    except Exception as e:
        print(f"[CLOUDINARY DELETE ERROR] {e}")

def safe_object_id(id_str):
    try:
        return ObjectId(id_str)
    except (InvalidId, Exception):
        return None


# ── Public routes ───────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    try:
        gallery = list(collection_gallery.find())
        categories = list(collection_categories.find())
        reviews = list(collection_reviews.find().sort("date", -1))

        if request.method == 'POST':
            form_type = request.form.get("form_type")

            # ── Contact form ──
            if form_type == "contact":
                name = request.form.get("name", "").strip()
                email = request.form.get("email", "").strip()
                phone = request.form.get("phone", "").strip()
                message = request.form.get("message", "").strip()

                if name and phone and message:
                    collection_contact.insert_one({
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "message": message,
                        "date": datetime.now()
                    })
                    flash("Message sent! We will get back to you soon.", "success")
                else:
                    flash("Please fill all required fields.", "error")

            # ── Review form ──
            elif form_type == "review":
                rv_name = request.form.get("rv_name", "").strip()
                rv_message = request.form.get("rv_message", "").strip()
                rv_rating = int(request.form.get("rv_rating", 0))

                if rv_name and rv_message and rv_rating > 0:
                    collection_reviews.insert_one({
                        "name": rv_name,
                        "message": rv_message,
                        "rating": rv_rating,
                        "date": datetime.now().strftime("%B %Y")
                    })
                    flash("Thank you for your review!", "review_success")
                else:
                    flash("Please fill all fields and select a star rating.", "review_error")

    except Exception as e:
        print(f"[INDEX ERROR] {e}")
        gallery = []
        categories = []
        reviews = []

    return render_template("home.html", gallery=gallery, categories=categories, reviews=reviews)


@app.route("/submit_review", methods=["POST"])
def submit_review():
    try:
        data = request.get_json()
        rv_name = data.get("name", "").strip()
        rv_message = data.get("message", "").strip()
        rv_rating = int(data.get("rating", 0))

        if rv_name and rv_message and rv_rating > 0:
            date_str = datetime.now().strftime("%B %Y")
            result = collection_reviews.insert_one({
                "name": rv_name,
                "message": rv_message,
                "rating": rv_rating,
                "date": date_str
            })
            return jsonify({"success": True, "date": date_str, "id": str(result.inserted_id)})
        else:
            return jsonify({"success": False})
    except Exception as e:
        print(f"[REVIEW ERROR] {e}")
        return jsonify({"success": False})

@app.route("/delete_review/<review_id>", methods=["POST"])
def delete_review(review_id):
    try:
        oid = safe_object_id(review_id)
        if not oid:
            return jsonify({"success": False})
        collection_reviews.delete_one({"_id": oid})
        return jsonify({"success": True})
    except Exception as e:
        print(f"[DELETE REVIEW ERROR] {e}")
        return jsonify({"success": False})


@app.route("/menu")
def menu():
    try:
        items = list(collection.find())
        categories = list(collection_categories.find())
    except Exception:
        items = []
        categories = []
    return render_template("menu.html", items=items, categories=categories)
@app.route("/contact_messages")
def contact_messages():
    messages = list(collection_contact.find().sort("date", -1))
    return render_template("contact_messages.html",messages=messages)

# ── Admin dashboard ─────────────────────────────────────────

@app.route("/admin", methods=['GET', 'POST'])
def admin():
    if 'logged_in' not in session:
        return redirect(url_for('admin_login'))

    try:
        total_items = collection_gallery.count_documents({})
    except Exception:
        total_items = 0

    if request.method == 'POST':
        try:
            image_name = request.form.get('image_name', '').strip()
            if not image_name:
                flash("Please provide a photo name.", "error")
                return redirect(url_for("admin"))
            image_url = safe_save_image(request.files.get('image'))
            if not image_url:
                flash("Invalid or missing image file.", "error")
                return redirect(url_for("admin"))
            collection_gallery.insert_one({"name": image_name, "image": image_url})
            flash("Image added to gallery successfully!", "success")
        except Exception as e:
            print(f"[ADMIN POST ERROR] {e}")
            flash("Something went wrong while adding the photo.", "error")
        return redirect(url_for("admin"))

    try:
        gallery = list(collection_gallery.find())
    except Exception:
        gallery = []
    return render_template("admin.html", gallery=gallery, total_items=total_items)


# ── Gallery routes ──────────────────────────────────────────

@app.route("/admin/delete_gallery/<item_id>", methods=["POST"])
def delete_gallery(item_id):
    oid = safe_object_id(item_id)
    if not oid:
        flash("Invalid photo ID.", "error")
        return redirect(url_for('admin'))
    try:
        item = collection_gallery.find_one({'_id': oid})
        if item:
            safe_delete_image(item.get('image'))
        collection_gallery.delete_one({'_id': oid})
        flash("Photo deleted successfully!", "success")
    except Exception as e:
        print(f"[DELETE GALLERY ERROR] {e}")
        flash("Could not delete photo.", "error")
    return redirect(url_for('admin'))


@app.route("/admin/edit_gallery/<item_id>", methods=["POST"])
def edit_gallery(item_id):
    oid = safe_object_id(item_id)
    if not oid:
        flash("Invalid photo ID.", "error")
        return redirect(url_for('admin'))
    try:
        image_name = request.form.get('image_name', '').strip()
        update = {"name": image_name}
        new_url = safe_save_image(request.files.get('image'))
        if new_url:
            item = collection_gallery.find_one({'_id': oid})
            if item:
                safe_delete_image(item.get('image'))
            update["image"] = new_url
        collection_gallery.update_one({'_id': oid}, {'$set': update})
        flash("Photo updated successfully!", "success")
    except Exception as e:
        print(f"[EDIT GALLERY ERROR] {e}")
        flash("Could not update photo.", "error")
    return redirect(url_for('admin'))


# ── Menu item routes ────────────────────────────────────────

@app.route("/admin_add_item", methods=["GET", "POST"])
def admin_add_item():
    if 'logged_in' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        try:
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "").strip()

            if not name:
                flash("Item name is required.", "error")
                return render_template("admin_add_item.html")

            sizes = request.form.getlist("size[]")
            prices = request.form.getlist("price[]")
            size_data = []
            for s, p in zip(sizes, prices):
                s, p = s.strip(), p.strip()
                if p:
                    size_data.append({"size": s, "price": p})

            image_url = safe_save_image(request.files.get("image"))
            if not image_url:
                flash("Invalid or missing image file.", "error")
                return render_template("admin_add_item.html")

            collection.insert_one({
                "name": name,
                "category": category,
                "image": image_url,
                "sizes": size_data
            })
            flash("Item added successfully!", "success")
        except Exception as e:
            print(f"[ADD ITEM ERROR] {e}")
            flash("Something went wrong while adding the item.", "error")
    categories = list(collection_categories.find())
    categories = sorted(categories, key=lambda x: x['name'])
    return render_template("admin_add_item.html", categories=categories)


@app.route("/view_items")
def view_items():
    if 'logged_in' not in session:
        return redirect(url_for('admin_login'))
    try:
        items = list(collection.find())
    except Exception:
        items = []
    return render_template("view_items.html", items=items)


@app.route('/admin/delete/<item_id>', methods=['POST'])
def admin_delete_item(item_id):
    oid = safe_object_id(item_id)
    if not oid:
        flash("Invalid item ID.", "error")
        return redirect(url_for('view_items'))
    try:
        item = collection.find_one({'_id': oid})
        if item:
            safe_delete_image(item.get('image'))
        collection.delete_one({'_id': oid})
        flash("Item deleted successfully!", "success")
    except Exception as e:
        print(f"[DELETE ITEM ERROR] {e}")
        flash("Could not delete item.", "error")
    return redirect(url_for('view_items'))


@app.route('/admin/edit/<item_id>', methods=['GET', 'POST'])
def admin_edit_item(item_id):
    oid = safe_object_id(item_id)
    if not oid:
        flash("Invalid item ID.", "error")
        return redirect(url_for('view_items'))

    try:
        item = collection.find_one({'_id': oid})
    except Exception:
        item = None

    if not item:
        flash("Item not found.", "error")
        return redirect(url_for('view_items'))

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()

            sizes = []
            for s, p in zip(request.form.getlist('size[]'), request.form.getlist('price[]')):
                s, p = s.strip(), p.strip()
                if p:
                    sizes.append({'size': s, 'price': p})

            update = {'name': name, 'category': category, 'sizes': sizes}
            new_url = safe_save_image(request.files.get('image'))
            if new_url:
                safe_delete_image(item.get('image'))
                update['image'] = new_url

            collection.update_one({'_id': oid}, {'$set': update})
            flash("Item updated successfully!", "success")
            return redirect(url_for('view_items'))
        except Exception as e:
            print(f"[EDIT ITEM ERROR] {e}")
            flash("Could not update item.", "error")

    return render_template('admin_edit_item.html', item=item)


# ── Category routes ─────────────────────────────────────────

@app.route("/add_new_category", methods=["GET", "POST"])
def add_new_category():
    if 'logged_in' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        try:
            category_name = request.form.get('name', '').strip()
            if not category_name:
                flash("Category name is required.", "error")
                return redirect(url_for('add_new_category'))
            image_url = safe_save_image(request.files.get('image'))
            if not image_url:
                flash("Category image is required.", "error")
                return redirect(url_for('add_new_category'))
            category_doc = {"name": category_name, "image": image_url}
            collection_categories.insert_one(category_doc)
            flash("Category added successfully!", "success")
        except Exception as e:
            print(f"[ADD CATEGORY ERROR] {e}")
            flash("Something went wrong while adding the category.", "error")
        return redirect(url_for('add_new_category'))

    try:
        categories = list(collection_categories.find())
    except Exception:
        categories = []
    return render_template("add_new_category.html", categories=categories)


@app.route("/admin/edit_category/<cat_id>", methods=["POST"])
def edit_category(cat_id):
    oid = safe_object_id(cat_id)
    if not oid:
        flash("Invalid category ID.", "error")
        return redirect(url_for('add_new_category'))
    try:
        name = request.form.get('name', '').strip()
        update = {"name": name}
        new_url = safe_save_image(request.files.get('image'))
        if new_url:
            cat = collection_categories.find_one({'_id': oid})
            if cat:
                safe_delete_image(cat.get('image'))
            update["image"] = new_url
        collection_categories.update_one({'_id': oid}, {'$set': update})
        flash("Category updated successfully!", "success")
    except Exception as e:
        print(f"[EDIT CATEGORY ERROR] {e}")
        flash("Could not update category.", "error")
    return redirect(url_for('add_new_category'))


@app.route("/admin/delete_category/<cat_id>", methods=["POST"])
def delete_category(cat_id):
    oid = safe_object_id(cat_id)
    if not oid:
        flash("Invalid category ID.", "error")
        return redirect(url_for('add_new_category'))
    try:
        cat = collection_categories.find_one({'_id': oid})
        if cat:
            safe_delete_image(cat.get('image'))
        collection_categories.delete_one({'_id': oid})
        flash("Category deleted successfully!", "success")
    except Exception as e:
        print(f"[DELETE CATEGORY ERROR] {e}")
        flash("Could not delete category.", "error")
    return redirect(url_for('add_new_category'))


# ── Auth ────────────────────────────────────────────────────

@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        try:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if username == "admin" and password == "admin":
                session['username'] = username
                session['logged_in'] = True
                flash("Logged in successfully!", "success")
                return redirect(url_for("admin"))
            else:
                flash("Invalid credentials.", "error")
        except Exception as e:
            print(f"[LOGIN ERROR] {e}")
            flash("Login failed.", "error")
    return render_template("admin_login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.errorhandler(404)
def not_found(e):
    return render_template("admin_login.html"), 404

@app.errorhandler(500)
def server_error(e):
    import traceback
    return f"<pre>{traceback.format_exc()}</pre>", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

