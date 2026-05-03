import os
import uuid
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import json
import random
from datetime import datetime
import io

# --- IMPORT TWILIO AND DOTENV ---
from twilio.rest import Client
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'exam_db.sqlite3')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 1. Load environment variables first
load_dotenv()

# 2. CREATE THE APP FIRST
app = Flask(__name__)

# 3. NOW CONFIGURE IT
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'exam_db.sqlite3')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'secret_key_needed_for_session' 

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- TWILIO CONFIGURATION ---
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')  # Your +12692289777 number

# Initialize Twilio Client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


# --- MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False) # <-- NEW COLUMN
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)


class Program(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))

class Block(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    floors = db.relationship('Floor', backref='block', cascade="all, delete-orphan")
    
    @property
    def total_rooms(self):
        return sum(len(floor.rooms) for floor in self.floors)

    @property
    def total_capacity(self):
        total_seats = 0
        for floor in self.floors:
            for room in floor.rooms:
                try:
                    layout = json.loads(room.layout_data)
                    bench_count = sum(1 for item in layout if item.get('type') == 'bench')
                    total_seats += bench_count * 2
                except:
                    continue
        return total_seats

class Floor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    floor_num = db.Column(db.Integer)
    block_id = db.Column(db.Integer, db.ForeignKey('block.id'))
    rooms = db.relationship('Room', backref='floor', cascade="all, delete-orphan")

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    floor_id = db.Column(db.Integer, db.ForeignKey('floor.id'))
    layout_data = db.Column(db.Text, default='[]')
    rows = db.Column(db.Integer, default=10)
    cols = db.Column(db.Integer, default=10)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    roll_no = db.Column(db.String(50))
    reg_no = db.Column(db.String(50))
    exam_uid = db.Column(db.String(20), unique=True)
    academic_year = db.Column(db.String(20))
    program_id = db.Column(db.Integer, db.ForeignKey('program.id'))
    semester = db.Column(db.Integer, default=1)
    section = db.Column(db.String(10), default='A')

class PublishedTimetable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    allocation_data = db.Column(db.Text, nullable=False) 
    total_students = db.Column(db.Integer)

# --- NEW MODEL: ATTENDANCE ---
class ExamAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'))
    exam_uid = db.Column(db.String(20)) 
    
    # Exam Details
    subject_name = db.Column(db.String(100))
    subject_code = db.Column(db.String(20))
    exam_date = db.Column(db.String(20))
    exam_time = db.Column(db.String(20))
    block = db.Column(db.String(50))
    room_no = db.Column(db.String(20))
    
    # Answer Sheet
    answer_sheet_no = db.Column(db.String(50))
    
    # Meta
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Present')

    student = db.relationship('Student', backref='attendance_records')


# --- GATEKEEPER ---
@app.before_request
def require_login():
    allowed_routes = ['login', 'signup', 'static', 'logout', 'index', 'page_not_found', 'api_send_otp', 'login_with_phone'] 
    if request.endpoint and request.endpoint not in allowed_routes and 'user' not in session:
        return redirect(url_for('login'))


# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(email=email).first()
        if user and user.password == password:
            session['user'] = user.name 
            return redirect(url_for('campus')) 
        else:
            flash('Invalid Email or Password', 'error')
    return render_template('auth.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name') 
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        if User.query.filter_by(email=email).first():
            flash('Account already exists!', 'error')
        else:
            new_user = User(name=name, email=email, password=password)
            db.session.add(new_user)
            db.session.commit()
            flash('Account created!', 'success')
            return redirect(url_for('login'))
    return render_template('auth.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
def index(): return render_template('landing.html')

@app.route('/docs')
def docs(): return render_template('docs.html')

@app.route('/campus')
def campus():
    blocks = Block.query.all()
    return render_template('campus.html', blocks=blocks)

@app.route('/support')
def support(): return render_template('support.html')

# --- INVIGILATOR / ATTENDANCE ROUTES ---

@app.route('/invigilator/setup')
def invigilator_setup():
    today_str = datetime.now().strftime('%Y-%m-%d')
    programs = Program.query.all()
    
    # DEBUG 1: Check what date Python is looking for
    print(f"--- DEBUG: Looking for exams on date: {today_str} ---")
    
    raw_sessions = db.session.query(
        ExamAttendance.subject_name,
        ExamAttendance.subject_code,
        ExamAttendance.exam_date,
        ExamAttendance.exam_time,
        ExamAttendance.block,
        ExamAttendance.room_no,
        Program.name.label('program_name'),
        Program.id.label('program_id'),
        Student.academic_year
    ).join(Student, ExamAttendance.student_id == Student.id)\
     .join(Program, Student.program_id == Program.id)\
     .filter(ExamAttendance.exam_date == today_str)\
     .group_by(ExamAttendance.subject_code, ExamAttendance.room_no, Program.id)\
     .all()
     
    # DEBUG 2: Check if the database found anything
    print(f"--- DEBUG: Found {len(raw_sessions)} raw sessions ---")
    
    active_sessions = []
    for session in raw_sessions:
        time_str = session.exam_time if session.exam_time else ""
        time_parts = time_str.split(' - ')
        
        active_sessions.append({
            'subject_name': session.subject_name,
            'subject_code': session.subject_code,
            'exam_date': session.exam_date,
            'start_time': time_parts[0] if len(time_parts) > 0 else time_str,
            'end_time': time_parts[1] if len(time_parts) > 1 else "",
            'block': session.block,
            'room_no': session.room_no,
            'program_name': session.program_name,
            'program_id': session.program_id,
            'academic_year': session.academic_year
        })
    
    return render_template('invigilator_setup.html', active_sessions=active_sessions, programs=programs)

@app.route('/invigilator/scanner', methods=['POST'])
def invigilator_scanner():
    # 1. Grab the full time string from the dropdown (e.g. "11:00 PM - 01:00 AM")
    exam_time = request.form.get('time', '')
    
    # 2. Split it safely just in case the scanner page needs them separated
    time_parts = exam_time.split(' - ')
    start = time_parts[0] if len(time_parts) > 0 else ''
    end = time_parts[1] if len(time_parts) > 1 else ''

    # 3. Pass everything cleanly to the scanner template
    details = {
        'subject_name': request.form.get('subject_name'),
        'subject_code': request.form.get('subject_code'),
        'date': request.form.get('date'),
        'start_time': start,
        'end_time': end,
        'time': exam_time,  # This matches what your database expects to save!
        'block': request.form.get('block'),
        'room': request.form.get('room'),
        'program_id': request.form.get('program_id')
    }
    
    return render_template('invigilator_scanner.html', details=details)

@app.route('/api/mark_attendance', methods=['POST'])
def mark_attendance():
    data = request.json
    uid = data.get('uid')
    sheet_no = data.get('sheet_no')
    session_program_id = data.get('program_id') 
    
    if '/scan/' in uid:
        uid = uid.split('/scan/')[-1]

    student = Student.query.filter_by(exam_uid=uid).first()
    if not student:
        return jsonify({'status': 'error', 'message': 'Invalid Student QR'})

    if session_program_id:
        if str(student.program_id) != str(session_program_id):
            student_prog = Program.query.get(student.program_id).name
            session_prog = Program.query.get(session_program_id).name
            return jsonify({
                'status': 'error', 
                'message': f"WRONG PROGRAM ALERT!\n\nThis student belongs to {student_prog}.\nThis exam session is for {session_prog}."
            })

    duplicate_entry = ExamAttendance.query.filter_by(
        answer_sheet_no=sheet_no,
        exam_date=data.get('date'),
        subject_code=data.get('subject_code')
    ).first()

    if duplicate_entry and duplicate_entry.student_id != student.id:
        return jsonify({
            'status': 'error', 
            'message': f'Sheet No "{sheet_no}" is already assigned to {duplicate_entry.student.name}!'
        })

    existing = ExamAttendance.query.filter_by(
        student_id=student.id, 
        exam_date=data.get('date'), 
        subject_code=data.get('subject_code')
    ).first()

    if existing:
        existing.answer_sheet_no = sheet_no
        db.session.commit()
        msg = "Attendance Updated"
    else:
        new_record = ExamAttendance(
            student_id=student.id,
            exam_uid=student.exam_uid,
            subject_name=data.get('subject_name'),
            subject_code=data.get('subject_code'),
            exam_date=data.get('date'),
            exam_time=data.get('time'),
            block=data.get('block'),
            room_no=data.get('room'),
            answer_sheet_no=sheet_no,
            status='Present'
        )
        db.session.add(new_record)
        db.session.commit()
        msg = "Attendance Marked"

    return jsonify({
        'status': 'success', 
        'message': msg,
        'student': {
            'name': student.name,
            'roll': student.roll_no,
            'program': Program.query.get(student.program_id).name if student.program_id else 'N/A'
        }
    })
    
@app.route('/api/get_student_details', methods=['POST'])
def get_student_details():
    data = request.json
    uid = data.get('uid')
    
    # Clean the UID just like you do in your attendance route
    if uid and '/scan/' in uid:
        uid = uid.split('/scan/')[-1]

    # Look up the student
    student = Student.query.filter_by(exam_uid=uid).first()
    
    if student:
        return jsonify({
            'status': 'success',
            'name': student.name,
            'roll': student.roll_no
        })
    else:
        return jsonify({
            'status': 'error', 
            'message': 'Student not found in database.'
        })
    
# --- ATTENDANCE HIERARCHY ROUTES ---

@app.route('/attendance/dashboard')
def attendance_dashboard():
    programs = Program.query.all()
    prog_stats = []
    for p in programs:
        count = ExamAttendance.query.join(Student).filter(Student.program_id == p.id).count()
        prog_stats.append({
            'id': p.id,
            'name': p.name,
            'count': count,
            'color': random.choice(['from-blue-500 to-cyan-400', 'from-purple-500 to-pink-500', 'from-emerald-500 to-teal-400', 'from-orange-500 to-red-500'])
        })
    return render_template('attendance_dashboard.html', programs=prog_stats)

@app.route('/attendance/program/<int:program_id>')
def attendance_program_view(program_id):
    program = Program.query.get_or_404(program_id)
    records = db.session.query(
        ExamAttendance.subject_name,
        ExamAttendance.subject_code,
        ExamAttendance.exam_date,
        ExamAttendance.exam_time,
        db.func.count(ExamAttendance.id).label('present_count')
    ).join(Student).filter(Student.program_id == program_id)\
    .group_by(ExamAttendance.subject_code, ExamAttendance.exam_date)\
    .all()
    return render_template('attendance_program.html', program=program, exams=records)

@app.route('/attendance/exam/<int:program_id>/<code>/<date>')
def attendance_exam_list(program_id, code, date):
    program = Program.query.get_or_404(program_id)
    all_students = Student.query.filter_by(program_id=program_id).order_by(Student.roll_no).all()
    attendance_records = ExamAttendance.query.join(Student).filter(
        Student.program_id == program_id,
        ExamAttendance.subject_code == code,
        ExamAttendance.exam_date == date
    ).all()
    attendance_map = {r.student_id: r for r in attendance_records}
    final_list = []
    subject_name = "Unknown Subject"
    for student in all_students:
        record = attendance_map.get(student.id)
        if record:
            subject_name = record.subject_name
            final_list.append({
                'name': student.name,
                'roll': student.roll_no,
                'reg': student.reg_no,
                'sheet_no': record.answer_sheet_no,
                'time': record.exam_time,
                'status': 'Present',
                'row_color': 'hover:bg-gray-800/50'
            })
        else:
            final_list.append({
                'name': student.name,
                'roll': student.roll_no,
                'reg': student.reg_no,
                'sheet_no': '-',
                'time': '-',
                'status': 'Absent',
                'row_color': 'bg-red-900/10 hover:bg-red-900/20'
            })
    exam_info = {
        'subject': subject_name if attendance_records else 'Pending Scan',
        'code': code,
        'date': date
    }
    return render_template('attendance_exam_list.html', program=program, students=final_list, info=exam_info)

@app.route('/attendance/download_exam_pdf/<int:program_id>/<code>/<date>')
def download_exam_pdf(program_id, code, date):
    program = Program.query.get_or_404(program_id)
    all_students = Student.query.filter_by(program_id=program_id).order_by(Student.roll_no).all()
    attendance_records = ExamAttendance.query.join(Student).filter(
        Student.program_id == program_id,
        ExamAttendance.subject_code == code,
        ExamAttendance.exam_date == date
    ).all()
    attendance_map = {r.student_id: r for r in attendance_records}
    final_records = []
    subject_name = ""
    for student in all_students:
        record = attendance_map.get(student.id)
        if record:
            subject_name = record.subject_name
            final_records.append({
                'name': student.name,
                'reg_no': student.reg_no,
                'roll_no': student.roll_no,
                'sheet_no': record.answer_sheet_no,
                'status': 'Present'
            })
        else:
            final_records.append({
                'name': student.name,
                'reg_no': student.reg_no,
                'roll_no': student.roll_no,
                'sheet_no': '-',
                'status': 'Absent'
            })
    if not subject_name: subject_name = "Exam Report"
    return render_template('attendance_pdf_template.html', 
                           program=program, 
                           records=final_records, 
                           date=date, 
                           code=code, 
                           subject=subject_name)
    
@app.route('/attendance/download_excel')
def download_attendance_excel():
    records = ExamAttendance.query.all()
    data = []
    for r in records:
        prog = Program.query.get(r.student.program_id).name if r.student and r.student.program_id else 'N/A'
        data.append({
            'Date': r.exam_date,
            'Time': r.exam_time,
            'Subject': f"{r.subject_name} ({r.subject_code})",
            'Room': f"{r.block} - {r.room_no}",
            'Student Name': r.student.name if r.student else 'Unknown',
            'Roll No': r.student.roll_no if r.student else 'N/A',
            'Program': prog,
            'Answer Sheet No': r.answer_sheet_no,
            'Status': r.status,
            'Scan Time': r.timestamp.strftime('%H:%M:%S')
        })
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Attendance')
    output.seek(0)
    return send_file(output, download_name="Exam_Attendance_Report.xlsx", as_attachment=True)

@app.route('/reset_attendance', methods=['POST'])
def reset_attendance():
    try:
        num_rows_deleted = db.session.query(ExamAttendance).delete()
        db.session.commit()
        return jsonify({'status': 'success', 'message': f'Database Reset: Removed {num_rows_deleted} records.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

# --- CAMPUS & STUDENT MANAGEMENT ---

@app.route('/add_block', methods=['POST'])
def add_block():
    db.session.add(Block(name=request.form.get('name')))
    db.session.commit()
    return redirect(url_for('campus'))

@app.route('/block/<int:block_id>')
def view_block(block_id):
    block = Block.query.get_or_404(block_id)
    return render_template('view_block.html', block=block)

@app.route('/add_floor', methods=['POST'])
def add_floor():
    db.session.add(Floor(block_id=request.form.get('block_id'), floor_num=request.form.get('floor_num')))
    db.session.commit()
    return redirect(url_for('view_block', block_id=request.form.get('block_id')))

@app.route('/delete_floor/<int:floor_id>', methods=['POST'])
def delete_floor(floor_id):
    floor = Floor.query.get_or_404(floor_id)
    block_id = floor.block_id
    db.session.delete(floor)
    db.session.commit()
    return redirect(url_for('view_block', block_id=block_id))

@app.route('/add_room', methods=['POST'])
def add_room():
    db.session.add(Room(floor_id=request.form.get('floor_id'), name=request.form.get('name')))
    db.session.commit()
    return redirect(url_for('view_block', block_id=request.form.get('block_id')))

@app.route('/delete_room/<int:room_id>', methods=['POST'])
def delete_room(room_id):
    room = Room.query.get_or_404(room_id)
    block_id = room.floor.block.id
    db.session.delete(room)
    db.session.commit()
    return redirect(url_for('view_block', block_id=block_id))

@app.route('/update_room_name', methods=['POST'])
def update_room_name():
    try:
        data = request.json
        room = Room.query.get(data['room_id'])
        if room:
            room.name = data['new_name']
            db.session.commit()
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': 'Room not found'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/editor/<int:room_id>')
def room_editor(room_id):
    room = Room.query.get_or_404(room_id)
    return render_template('room_editor.html', room=room)

@app.route('/save_layout', methods=['POST'])
def save_layout():
    data = request.json
    room = Room.query.get(data['room_id'])
    room.layout_data = json.dumps(data['layout'])
    room.rows = data['rows']
    room.cols = data['cols']
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/programs', methods=['GET', 'POST'])
def programs():
    if request.method == 'POST':
        db.session.add(Program(name=request.form.get('name')))
        db.session.commit()
        return redirect(url_for('programs'))
    programs = Program.query.all()
    return render_template('programs.html', programs=programs)

@app.route('/edit_program/<int:id>', methods=['POST'])
def edit_program(id):
    program = Program.query.get_or_404(id)
    new_name = request.form.get('name')
    if new_name:
        program.name = new_name
        db.session.commit()
    return redirect(url_for('programs'))

@app.route('/delete_program/<int:id>', methods=['POST'])
def delete_program(id):
    program = Program.query.get_or_404(id)
    db.session.delete(program)
    db.session.commit()
    return redirect(url_for('programs'))

@app.route('/students')
def students():
    programs = Program.query.all()
    return render_template('students.html', programs=programs)

@app.route('/api/students/<int:program_id>')
def get_students_by_program(program_id):
    students = Student.query.filter_by(program_id=program_id).all()
    return jsonify([{
        'id': s.id, 'name': s.name, 'roll_no': s.roll_no, 'reg_no': s.reg_no,
        'exam_uid': s.exam_uid, 'year': s.academic_year, 'semester': s.semester, 'section': s.section
    } for s in students])

@app.route('/add_student', methods=['POST'])
def add_student():
    uid = "EX-" + uuid.uuid4().hex[:6].upper()
    db.session.add(Student(
        name=request.form.get('name'), roll_no=request.form.get('roll_no'),
        reg_no=request.form.get('reg_no'), program_id=request.form.get('program_id'),
        academic_year=request.form.get('year'), semester=request.form.get('semester'),
        section=request.form.get('section'), exam_uid=uid
    ))
    db.session.commit()
    return redirect(url_for('students'))

@app.route('/upload_students', methods=['POST'])
def upload_students():
    file = request.files['file']
    program_id = request.form.get('program_id')
    academic_year = request.form.get('year') 
    default_sem = request.form.get('semester', 1)
    default_sec = request.form.get('section', 'A')
    
    if not file: return "No file", 400
    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    try:
        df = pd.read_csv(path) if filename.endswith('.csv') else pd.read_excel(path)
        df.columns = [c.lower().strip() for c in df.columns]
        for _, row in df.iterrows():
            uid = "EX-" + uuid.uuid4().hex[:6].upper()
            name = row.get('name') or row.get('student name')
            roll = row.get('roll') or row.get('roll no')
            reg = row.get('reg') or row.get('reg no')
            sec = row.get('section') or default_sec
            sem = row.get('semester') or default_sem

            if name and roll:
                db.session.add(Student(
                    name=str(name).strip(), roll_no=str(roll).strip(), 
                    reg_no=str(reg).strip() if reg else "N/A", program_id=program_id, 
                    academic_year=str(academic_year).strip(), exam_uid=uid, semester=int(sem), section=str(sec)
                ))
        db.session.commit()
        return redirect(url_for('students'))
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/delete_all_students/<int:program_id>', methods=['POST'])
def delete_all_students(program_id):
    Student.query.filter_by(program_id=program_id).delete()
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/batch_transfer', methods=['GET', 'POST'])
def batch_transfer():
    if request.method == 'POST':
        student_ids = request.json.get('student_ids', [])
        target_sem = int(request.json.get('target_sem'))
        Student.query.filter(Student.id.in_(student_ids)).update({Student.semester: target_sem}, synchronize_session=False)
        db.session.commit()
        return jsonify({'status': 'success'})
    programs = Program.query.all()
    return render_template('batch_transfer.html', programs=programs)

@app.route('/api/get_batch_students')
def get_batch_students():
    program_id = request.args.get('program_id')
    semester = request.args.get('semester')
    
    students = Student.query.filter_by(program_id=program_id, semester=semester).all()
    
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'roll': s.roll_no,
        'section': s.section  # <--- Make sure this line exists
    } for s in students])
    
@app.route('/allocation')
def allocation():
    programs = Program.query.all()
    blocks = Block.query.all()
    return render_template('allocation.html', programs=programs, blocks=blocks)

@app.route('/run_allocation', methods=['POST'])
def run_allocation():
    data = request.json
    selected_program_ids = [int(id) for id in data.get('program_ids', [])]
    exam_type = data.get('exam_type') 
    
    if not selected_program_ids: return jsonify({'status': 'error', 'message': 'No programs selected'})

    all_fetched_students = []
    for pid in selected_program_ids:
        sem_filter = (Student.semester % 2 != 0) if exam_type == 'odd' else (Student.semester % 2 == 0)
        students = Student.query.filter(Student.program_id == pid, sem_filter).order_by(Student.roll_no).all()
        serialized = [{'id': s.id, 'name': s.name, 'roll': s.roll_no, 'reg_no': s.reg_no, 'exam_uid': s.exam_uid, 'prog_id': s.program_id} for s in students]
        if serialized: all_fetched_students.append(serialized)

    if not all_fetched_students: return jsonify({'status': 'error', 'message': 'No students found'})

    strategy = 'single' if len(all_fetched_students) == 1 else 'multi'
    student_queue = []
    
    if strategy == 'single':
        student_queue = all_fetched_students[0]
    else:
        max_len = max(len(l) for l in all_fetched_students)
        for i in range(max_len):
            for s_list in all_fetched_students:
                if i < len(s_list): student_queue.append(s_list[i])

    total_students = len(student_queue)
    allocations = []
    allocated_count = 0
    idx_a = 0
    idx_b = 0
    
    team_a = []
    team_b = []
    if strategy == 'multi':
        for idx, s_list in enumerate(all_fetched_students):
            if idx % 2 == 0: team_a.extend(s_list)
            else: team_b.extend(s_list)
        len_a = len(team_a)
        len_b = len(team_b)

    rooms = Room.query.all()

    for room in rooms:
        if strategy == 'single' and not student_queue: break
        if strategy == 'multi' and idx_a >= len_a and idx_b >= len_b: break
        
        try: layout = json.loads(room.layout_data)
        except: continue
            
        benches = [item for item in layout if item.get('type') == 'bench']
        benches.sort(key=lambda b: (b.get('c', 0), b.get('r', 0)))
        
        sorted_benches_with_id = []
        for i, b in enumerate(benches):
            sorted_benches_with_id.append({'data': b, 'alloc_id': i + 1})

        if strategy == 'single':
            for b in sorted_benches_with_id:
                if not student_queue: break
                s = student_queue.pop(0)
                allocations.append({'room': f"{room.floor.block.name} - {room.name}", 'room_cols': room.cols, 'bench': b['alloc_id'], 'seat': 'L', 'name': s['name'], 'roll': s['roll'], 'reg_no': s['reg_no'], 'exam_uid': s['exam_uid'], 'color': 'blue'})
                allocated_count += 1
            for b in sorted_benches_with_id:
                if not student_queue: break
                s = student_queue.pop(0)
                allocations.append({'room': f"{room.floor.block.name} - {room.name}", 'room_cols': room.cols, 'bench': b['alloc_id'], 'seat': 'R', 'name': s['name'], 'roll': s['roll'], 'reg_no': s['reg_no'], 'exam_uid': s['exam_uid'], 'color': 'blue'})
                allocated_count += 1
        else:
            for b in sorted_benches_with_id:
                if idx_a >= len_a and idx_b >= len_b: break
                if idx_a < len_a:
                    s = team_a[idx_a]
                    allocations.append({'room': f"{room.floor.block.name} - {room.name}", 'room_cols': room.cols, 'bench': b['alloc_id'], 'seat': 'L', 'name': s['name'], 'roll': s['roll'], 'reg_no': s['reg_no'], 'exam_uid': s['exam_uid'], 'color': 'blue'})
                    idx_a += 1; allocated_count += 1
                if idx_b < len_b:
                    s = team_b[idx_b]
                    allocations.append({'room': f"{room.floor.block.name} - {room.name}", 'room_cols': room.cols, 'bench': b['alloc_id'], 'seat': 'R', 'name': s['name'], 'roll': s['roll'], 'reg_no': s['reg_no'], 'exam_uid': s['exam_uid'], 'color': 'purple'})
                    idx_b += 1; allocated_count += 1

    return jsonify({'status': 'success', 'allocated': allocated_count, 'total': total_students, 'details': allocations})

@app.route('/publish_timetable', methods=['POST'])
def publish_timetable():
    data = request.json
    new_publish = PublishedTimetable(title=data.get('title'), allocation_data=json.dumps(data.get('details')), total_students=data.get('total'))
    db.session.add(new_publish)
    db.session.commit()
    return jsonify({'status': 'success', 'redirect_url': url_for('view_published', id=new_publish.id)})

@app.route('/exam_timetable')
def exam_timetable_index():
    published = PublishedTimetable.query.order_by(PublishedTimetable.created_at.desc()).all()
    return render_template('exam_timetable.html', published_list=published)

@app.route('/view_timetable/<int:id>')
def view_published(id):
    timetable = PublishedTimetable.query.get_or_404(id)
    programs = Program.query.all()
    alloc_data = json.loads(timetable.allocation_data)
    return render_template('view_published.html', timetable=timetable, alloc_data=alloc_data, programs=programs)

@app.route('/delete_timetable/<int:id>', methods=['POST'])
def delete_timetable(id):
    try:
        timetable = PublishedTimetable.query.get_or_404(id)
        db.session.delete(timetable)
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/print_stickers/<int:timetable_id>')
def print_stickers(timetable_id):
    program_id = request.args.get('program_id')
    timetable = PublishedTimetable.query.get_or_404(timetable_id)
    full_data = json.loads(timetable.allocation_data)
    
    if program_id and program_id != 'all':
        prog_rolls = [s.roll_no for s in Student.query.filter_by(program_id=int(program_id)).all()]
        filtered_data = [item for item in full_data if item['roll'] in prog_rolls]
    else:
        filtered_data = full_data

    return render_template('sticker_layout.html', timetable=timetable, seats=filtered_data)

@app.route('/scan/<string:uid>')
def scan_student(uid):
    student = Student.query.filter_by(exam_uid=uid).first_or_404()
    program = Program.query.get(student.program_id)
    return render_template('student_scan.html', student=student, program=program)

@app.route('/delete_block/<int:block_id>', methods=['POST'])
def delete_block(block_id):
    try:
        block = Block.query.get_or_404(block_id)
        db.session.delete(block)
        db.session.commit()
        return redirect(url_for('campus'))
    except Exception as e:
        return f"Error deleting block: {str(e)}", 500

@app.errorhandler(404)
def page_not_found(e): return render_template('404.html'), 404

# ==========================================
# CUSTOM OTP: SEND SMS API
# ==========================================
@app.route('/api/send_otp', methods=['POST'])
def api_send_otp():
    try:
        data = request.get_json(silent=True) or {}
        phone = data.get('phone')
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        
        if not phone:
            return jsonify({'status': 'error', 'message': 'No phone number received.'})

        # --- 1. COLLECT ALL DUPLICATE ERRORS ---
        duplicate_errors = []

        if username and User.query.filter(User.username.ilike(username)).first():
            duplicate_errors.append(f'Username "{username}"')
            
        if email and User.query.filter(User.email.ilike(email)).first():
            duplicate_errors.append('Email')
            
        if phone and User.query.filter_by(phone=phone).first():
            duplicate_errors.append('Phone number')

        # --- 2. FORMAT THE COMBINED MESSAGE PERFECTLY ---
        if duplicate_errors:
            if len(duplicate_errors) == 1:
                # 1 Error: "Username is taken"
                error_string = duplicate_errors[0]
                is_are = "is"
            elif len(duplicate_errors) == 2:
                # 2 Errors: "Username and Email are taken"
                error_string = f"{duplicate_errors[0]} and {duplicate_errors[1]}"
                is_are = "are"
            else:
                # 3 Errors: "Username, Email, and Phone number are taken"
                error_string = f"{duplicate_errors[0]}, {duplicate_errors[1]}, and {duplicate_errors[2]}"
                is_are = "are"
            
            final_message = f"{error_string} {is_are} already registered/taken. Please use different details."
            return jsonify({'status': 'error', 'message': final_message})

        # --- 3. NO DUPLICATES FOUND, PROCEED WITH OTP ---
        import random
        otp_code = str(random.randint(100000, 999999))
        
        # Save it in the Flask session temporarily
        session['sent_otp'] = otp_code
        session['otp_phone'] = phone

        # Send it using Twilio
        message = twilio_client.messages.create(
            to=phone,
            from_=TWILIO_PHONE_NUMBER,
            body=f"Your ExamCell verification code is: {otp_code}"
        )
        
        return jsonify({'status': 'success', 'message': 'OTP sent successfully!'})
        
    except Exception as e:
        print(f"--- SMS ERROR --- : {str(e)}") 
        return jsonify({'status': 'error', 'message': str(e)})
# ==========================================
# CUSTOM OTP: VERIFY & REGISTER API
# ==========================================

@app.route('/login_with_phone', methods=['POST'])
def login_with_phone():
    try:
        data = request.get_json(silent=True) or {}
        phone = data.get('phone')
        code = data.get('code')
        name = data.get('name')
        
        # Safely grab and lower-case to prevent "Arhan" vs "arhan" bypass
        email = data.get('email', '').strip().lower()
        username = data.get('username', '').strip().lower()
        password = data.get('password', 'twilio_user')

        if not phone or not code:
            return jsonify({'status': 'error', 'message': 'Phone or Code missing.'})

        # 1. Validate against session
        saved_otp = session.get('sent_otp')
        saved_phone = session.get('otp_phone')

        if saved_otp and str(code) == str(saved_otp) and phone == saved_phone:
            # 2. Clear OTP so it can't be reused
            session.pop('sent_otp', None)
            session.pop('otp_phone', None)

            # 3. STRICT REGISTRATION CHECKS
            if not username or not email or not name:
                return jsonify({'status': 'error', 'message': 'All fields are required.'})
            
            if not username.isalnum():
                return jsonify({'status': 'error', 'message': 'Username must contain only letters and numbers.'})

            # Check for ANY duplicates
            if User.query.filter_by(username=username).first():
                return jsonify({'status': 'error', 'message': f'Username "{username}" is already taken.'})
            
            if User.query.filter_by(email=email).first():
                return jsonify({'status': 'error', 'message': 'This email is already registered.'})
            
            if User.query.filter_by(phone=phone).first():
                return jsonify({'status': 'error', 'message': 'This phone number is already registered.'})

            # 4. If all checks pass, create the new user!
            new_user = User(username=username, name=name, email=email, phone=phone, password=password)
            db.session.add(new_user)
            db.session.commit()
            
            # Set the session using the unique username
            session['user'] = new_user.username 
            return jsonify({'status': 'success', 'redirect_url': url_for('campus')})
        else:
            return jsonify({'status': 'error', 'message': 'Invalid or Expired OTP.'})
            
    except Exception as e:
        print(f"--- VERIFY ERROR --- : {str(e)}") 
        return jsonify({'status': 'error', 'message': str(e)})
        
    
if __name__ == '__main__':
    with app.app_context(): 
        db.create_all()
        if not User.query.filter_by(email="admin@sbu.ac.in").first():
            print("Creating Admin User...")
            # Added username="admin" to the Admin creation
            admin = User(username="admin", name="Arhan Akhtar", email="admin@sbu.ac.in", password="password123")
            db.session.add(admin)
            db.session.commit()
            print("Admin User Created: Username: admin | Email: admin@sbu.ac.in | Password: password123")
app.run()
