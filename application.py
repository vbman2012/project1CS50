import os, json

from flask import Flask, session, redirect, render_template, request, jsonify, flash
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import datetime 

from werkzeug.security import check_password_hash, generate_password_hash

import requests

from helpers import login_required


app = Flask(__name__)


# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
@login_required
def index():
    """search"""
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """ Login """
    # Forget any user_id
    session.clear()
    username = request.form.get("username")
    # User reached route via POST.
    if request.method == "POST":
        if not request.form.get("username"):
            return render_template("error.html", message="must provide username")
        # Ensure password was submitted
        elif not request.form.get("password"):
            return render_template("error.html", message="must provide password")

        rows = db.execute("SELECT * FROM users_account WHERE username = :username",
                            {"username": username})
        result = rows.fetchone()

        # Ensure username exists and password is correct
        if result == None or not check_password_hash(result[2], request.form.get("password")):
            return render_template("error.html", message="invalid username and/or password")

        # Remember which user has logged in
        session["user_id"] = result[0]
        session["user_name"] = result[1]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET.
    else:
        return render_template("login.html")

@app.route("/logout")
def logout():
    """ Logout """
    session.clear()
    return redirect("/")

@app.route("/register", methods=["GET", "POST"])
def register():
    """ Registeration"""
    session.clear()
    # User reached route via POST.
    if request.method == "POST":
        if not request.form.get("username"):
            return render_template("error.html", message="must provide username")
        # Query database for username
        userCheck = db.execute("SELECT * FROM users_account WHERE username = :username",
                          {"username":request.form.get("username")}).fetchone()
        if userCheck:
            return render_template("error.html", message="username already exist")
        elif not request.form.get("password"):
            return render_template("error.html", message="must provide password")

        # Ensure confirmation wass submitted 
        elif not request.form.get("confirmation"):
            return render_template("error.html", message="must confirm password")

        # Check passwords are equal
        elif not request.form.get("password") == request.form.get("confirmation"):
            return render_template("error.html", message="passwords didn't match")
        
        # user password store in DB
        hashedPassword = generate_password_hash(request.form.get("password"), method='pbkdf2:sha256', salt_length=8)
        
        # Insert register into DB
        db.execute("INSERT INTO users_account (username, password) VALUES (:username, :password)",
                            {"username":request.form.get("username"), 
                             "password":hashedPassword})
        db.commit()
        flash('Account created', 'info')

        # Redirect user to login page
        return redirect("/login")

    # User reached route via GET.
    else:
        return render_template("register.html")


@app.route("/search", methods=["GET"])
@login_required
def search():
    """Get books"""
    # Check book id
    if not request.args.get("book"):
        return render_template("error.html", message="you must provide a book.")

    query = "%" + request.args.get("book") + "%"
    query = query.title()
    rows = db.execute("SELECT isbn, title, author, year FROM books WHERE \
                        isbn LIKE :query OR \
                        title LIKE :query OR \
                        author LIKE :query LIMIT 15",
                        {"query": query})
    #Book not found
    if rows.rowcount == 0:
        return render_template("error.html", message="we can't find books with that description.")
    
    # Fetchall the results
    books = rows.fetchall()
    return render_template("results.html", books=books)


@app.route("/book/<isbn>", methods=['GET','POST'])
@login_required
def book(isbn):
    """ Save user review and load again"""

    if request.method == "POST":
        # Save current user info
        currentUser = session["user_id"]
        # Fetch data
        rating = request.form.get("rating")
        comment = request.form.get("comment")
        
        # Search book_id by ISBN
        row = db.execute("SELECT id FROM books WHERE isbn = :isbn",
                        {"isbn": isbn})
        # Save id into variable
        bookId = row.fetchone()
        bookId = bookId[0]

        # Check for user submission.
        row2 = db.execute("SELECT * FROM reviews WHERE user_id = :user_id AND book_id = :book_id",
                    {"user_id": currentUser,
                     "book_id": bookId})

        # A review already exists
        if row2.rowcount == 1:
            flash('You already submitted a review for this book', 'warning')
            return redirect("/book/" + isbn)

        # Convert to save into DB
        rating = int(rating)

        db.execute("INSERT INTO reviews (user_id, book_id, comment, rating, time) VALUES \
                    (:user_id, :book_id, :comment, :rating, :time)",
                    {"user_id": currentUser, 
                    "book_id": bookId, 
                    "comment": comment, 
                    "rating": rating,
                    "time": datetime.datetime.today()})

        db.commit()
        flash('Review submitted!', 'info')
        return redirect("/book/" + isbn)

    #Take the book ISBN and redirect to page
    else:
        row = db.execute("SELECT isbn, title, author, year FROM books WHERE \
                        isbn = :isbn",
                        {"isbn": isbn})

        bookInfo = row.fetchall()
        key = os.getenv("GOODREADS_KEY")
        # Query the api with key and isbn
        query = requests.get("https://www.goodreads.com/book/review_counts.json",
                params={"key": key, "isbns": isbn})

        # Convert to JSON
        response = query.json()

        # "Clean" the JSON before passing it 
        response = response['books'][0]
        bookInfo.append(response)

         # Search book_id by ISBN
        row = db.execute("SELECT id FROM books WHERE isbn = :isbn",
                        {"isbn": isbn})

        # Save id into variable
        book = row.fetchone()
        book = book[0]
        results = db.execute("SELECT users_account.username, comment, rating, \
                            to_char(time, 'DD Mon YY - HH24:MI:SS') as time \
                            FROM users_account \
                            INNER JOIN reviews \
                            ON users_account.id = reviews.user_id \
                            WHERE book_id = :book \
                            ORDER BY time",
                            {"book": book})

        reviews = results.fetchall()
        return render_template("book.html", bookInfo=bookInfo, reviews=reviews)


@app.route("/api/<isbn>", methods=['GET'])
@login_required
def api_call(isbn):
    row = db.execute("SELECT title, author, year, isbn, \
                    COUNT(reviews.id) as review_count, \
                    AVG(reviews.rating) as average_score \
                    FROM books \
                    INNER JOIN reviews \
                    ON books.id = reviews.book_id \
                    WHERE isbn = :isbn \
                    GROUP BY title, author, year, isbn",
                    {"isbn": isbn})

    if row.rowcount != 1:
        return jsonify({"Error": "Invalid book ISBN"}), 422

    tmp = row.fetchone()
    result = dict(tmp.items())
    result['average_score'] = float('%.2f'%(result['average_score']))
    return jsonify(result)