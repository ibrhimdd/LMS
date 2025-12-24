import os
from flask import Flask, render_template, request, redirect, url_for, session
from flask_mysqldb import MySQL
import MySQLdb.cursors
import pdfplumber
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_private_secret_key'

# إعدادات قاعدة البيانات
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''  # ضع كلمة مرورك هنا
app.config['MYSQL_DB'] = 'learning_platform'

# إعدادات الرفع
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'pdf', 'mp4', 'mov', 'avi'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

mysql = MySQL(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# 1. مسار تسجيل الدخول
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s AND password = %s', (username, password))
        user = cursor.fetchone()
        if user:
            session['loggedin'] = True
            session['id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('teacher_dashboard' if user['role'] == 'teacher' else 'student_dashboard'))
        msg = 'بيانات غير صحيحة!'
    return render_template('login.html', msg=msg)

# 2. لوحة تحكم المعلم (رفع محتوى + منشورات)
@app.route('/teacher/dashboard', methods=['GET', 'POST'])
def teacher_dashboard():
    if 'role' in session and session['role'] == 'teacher':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        if request.method == 'POST':
            if 'announcement' in request.form:
                content = request.form['announcement']
                cursor.execute('INSERT INTO announcements (teacher_id, content) VALUES (%s, %s)', (session['id'], content))
            elif 'title' in request.form:
                title = request.form['title']
                file = request.files['file']
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    f_type = 'pdf' if filename.endswith('.pdf') else 'video'
                    cursor.execute('INSERT INTO lessons (course_id, title, file_path, file_type) VALUES (%s, %s, %s, %s)', (1, title, filename, f_type))
            mysql.connection.commit()
        return render_template('teacher_dash.html')
    return redirect(url_for('login'))

# 3. استخراج الطلاب من PDF
@app.route('/teacher/add_students', methods=['GET', 'POST'])
def add_students():
    if 'role' in session and session['role'] == 'teacher':
        if request.method == 'POST':
            file = request.files['pdf_file']
            if file:
                path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(path)
                with pdfplumber.open(path) as pdf:
                    cursor = mysql.connection.cursor()
                    for page in pdf.pages:
                        text = page.extract_text()
                        for line in text.split('\n'):
                            data = line.split()
                            if len(data) >= 2:
                                cursor.execute('INSERT IGNORE INTO users (username, password, role) VALUES (%s, %s, %s)', (data[0], data[1], 'student'))
                    mysql.connection.commit()
                return "تمت إضافة الطلاب بنجاح!"
        return render_template('add_students.html')
    return redirect(url_for('login'))

# 4. لوحة تحكم الطالب (عرض المحتوى والمنشورات)
@app.route('/student/dashboard')
def student_dashboard():
    if 'role' in session and session['role'] == 'student':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM announcements ORDER BY created_at DESC')
        announcements = cursor.fetchall()
        # الربط مع جدول الاختبارات لإظهار الزرار
        cursor.execute('''SELECT l.*, q.id AS quiz_id FROM lessons l 
                          LEFT JOIN quizzes q ON l.id = q.lesson_id''')
        lessons = cursor.fetchall()
        return render_template('student_dash.html', announcements=announcements, lessons=lessons)
    return redirect(url_for('login'))

# 5. منتدى النقاش
@app.route('/lesson/<int:lesson_id>/forum', methods=['GET', 'POST'])
def lesson_forum(lesson_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    if request.method == 'POST':
        cursor.execute('INSERT INTO forum_posts (lesson_id, user_id, message) VALUES (%s, %s, %s)', (lesson_id, session['id'], request.form['message']))
        mysql.connection.commit()
    cursor.execute('SELECT f.*, u.username, u.role FROM forum_posts f JOIN users u ON f.user_id = u.id WHERE lesson_id = %s ORDER BY created_at ASC', (lesson_id,))
    posts = cursor.fetchall()
    cursor.execute('SELECT title FROM lessons WHERE id = %s', (lesson_id,))
    lesson = cursor.fetchone()
    return render_template('forum.html', posts=posts, lesson=lesson, lesson_id=lesson_id)


# مسار إنشاء اختبار جديد (عام)
@app.route('/teacher/create_quiz', methods=['GET', 'POST'])
def create_quiz():
    if 'role' in session and session['role'] == 'teacher':
        if request.method == 'POST':
            cursor = mysql.connection.cursor()
            # إدخال الاختبار بدون lesson_id
            cursor.execute('INSERT INTO quizzes (title) VALUES (%s)', (request.form['quiz_title'],))
            quiz_id = cursor.lastrowid

            # جلب الأسئلة من الفورم
            q_texts = request.form.getlist('q_text[]')
            opt_as = request.form.getlist('opt_a[]')
            opt_bs = request.form.getlist('opt_b[]')
            opt_cs = request.form.getlist('opt_c[]')
            opt_ds = request.form.getlist('opt_d[]')
            corrects = request.form.getlist('correct[]')

            for i in range(len(q_texts)):
                cursor.execute('''INSERT INTO questions 
                    (quiz_id, question_text, option_a, option_b, option_c, option_d, correct_option) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                               (quiz_id, q_texts[i], opt_as[i], opt_bs[i], opt_cs[i], opt_ds[i], corrects[i]))

            mysql.connection.commit()
            return redirect(url_for('teacher_dashboard'))
        return render_template('create_quiz.html')
    return redirect(url_for('login'))


# مسار يعرض كل الاختبارات المتاحة للطالب
@app.route('/student/quizzes')
def available_quizzes():
    if 'role' in session and session['role'] == 'student':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM quizzes ORDER BY created_at DESC')
        quizzes = cursor.fetchall()
        return render_template('available_quizzes.html', quizzes=quizzes)
    return redirect(url_for('login'))


@app.route('/quiz/<int:quiz_id>', methods=['GET', 'POST'])
def take_quiz(quiz_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. جلب بيانات الاختبار (عشان العنوان)
    cursor.execute('SELECT * FROM quizzes WHERE id = %s', (quiz_id,))
    quiz = cursor.fetchone()

    if request.method == 'POST':
        # (كود التصحيح وحفظ الدرجة يظل كما هو...)
        cursor.execute('SELECT id, correct_option FROM questions WHERE quiz_id = %s', (quiz_id,))
        corrects = cursor.fetchall()
        score = sum(1 for q in corrects if request.form.get(f'question_{q["id"]}') == q['correct_option'])
        cursor.execute('INSERT INTO scores (user_id, quiz_id, score, total_questions) VALUES (%s, %s, %s, %s)',
                       (session['id'], quiz_id, score, len(corrects)))
        mysql.connection.commit()
        return f"<h1>انتهى الاختبار! درجتك هي: {score} من {len(corrects)}</h1><a href='/student/dashboard'>العودة للرئيسية</a>"

    # 2. جلب الأسئلة
    cursor.execute('SELECT * FROM questions WHERE quiz_id = %s', (quiz_id,))
    questions = cursor.fetchall()

    # 3. إرسال المتغيرات (تأكد من إرسال quiz هنا)
    return render_template('take_quiz.html', questions=questions, quiz=quiz, quiz_id=quiz_id)
@app.route('/teacher/results')
def view_results():
    if 'role' in session and session['role'] == 'teacher':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # جلب النتائج مع اسم الطالب واسم الاختبار
        cursor.execute('''
            SELECT scores.*, users.username, quizzes.title AS quiz_title 
            FROM scores 
            JOIN users ON scores.user_id = users.id 
            JOIN quizzes ON scores.quiz_id = quizzes.id
            ORDER BY scores.id DESC
        ''')
        results = cursor.fetchall()
        return render_template('view_results.html', results=results)
    return redirect(url_for('login'))


@app.route('/teacher/view_students')
def view_students():
    if 'role' in session and session['role'] == 'teacher':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        # جلب المستخدمين اللي رتبتهم طالب فقط
        cursor.execute("SELECT id, username, password FROM users WHERE role = 'student'")
        students = cursor.fetchall()
        return render_template('view_students.html', students=students)
    return redirect(url_for('login'))


@app.route('/teacher/manage_content')
def manage_content():
    if 'role' in session and session['role'] == 'teacher':
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # جلب الدروس مع عدد التعليقات في منتدى النقاش لكل درس
        query = """
            SELECT l.id, l.title, l.file_type, l.file_path, l.created_at,
            (SELECT COUNT(*) FROM forum_posts WHERE lesson_id = l.id) as discussion_count
            FROM lessons l
            ORDER BY l.created_at DESC
        """
        cursor.execute(query)
        my_lessons = cursor.fetchall()

        return render_template('manage_content.html', lessons=my_lessons)
    return redirect(url_for('login'))
# 7. تسجيل الخروج
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
if __name__ == '__main__':
    # host='0.0.0.0' بتسمح للسيرفر يستقبل طلبات من أي IP في الشبكة
    app.run(host='0.0.0.0', port=5000, debug=True)