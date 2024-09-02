from flask import Flask, make_response, request,jsonify, url_for,send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_restful import Api, Resource, reqparse
from models import db, User, Service, ProviderService, County, Photo, Video, Message,Blocked,Assigned, Payment
from flask_bcrypt import Bcrypt
import re
from flask_cors import CORS
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import timedelta
import os
from sqlalchemy import func
from geopy.distance import geodesic
from moviepy.editor import VideoFileClip
from google.cloud import storage
import io
import tempfile
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask.views import MethodView
import logging
import stripe

app = Flask(__name__)
api = Api(app)
bcrypt = Bcrypt(app)
CORS(app)
stripe.api_key = os.environ.get('stripe_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('database_url')
# app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://kazi_konnect_user:eOyqCLr1bAqThselFhTURgMnQUOKL5fL@dpg-cqj4tpeehbks73c5vc80-a/kazi_konnect'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('secret_key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['GCS_BUCKET_NAME'] = os.environ.get('GCS_BUCKET_NAME')   
app.config['GOOGLE_APPLICATION_CREDENTIALS'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')

db.init_app(app)
MAX_VIDEO_DURATION = 300
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov','avi','wmv','flv','mkv','webm','mpeg','mpg'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024

def allowed_file(filename, allowed_extensions, max_content_length=None):
    if '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        if max_content_length is None or request.content_length <= max_content_length:
            return True
    return False
password_pattern = re.compile(r'(?=.*[a-z])(?=.*\d)[a-z\d]{6,}')
email_pattern = re.compile(r'[\w-]+(\.[w-]+)*@([\w-]+\.)+[a-zA-Z]{2,}')
migrate = Migrate(app, db)
jwt = JWTManager(app)
jwt.init_app(app)

def upload_to_gcs(file, bucket_name, destination_blob_name):
    """Uploads a file to the GCS bucket."""
    storage_client = storage.Client.from_service_account_json(app.config['GOOGLE_APPLICATION_CREDENTIALS'])
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_file(file)
    return blob.public_url

def delete_from_gcs(bucket_name, blob_name):
    """Deletes a file from the GCS bucket."""
    storage_client = storage.Client.from_service_account_json(app.config['GOOGLE_APPLICATION_CREDENTIALS'])
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.delete()

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

update_parser = reqparse.RequestParser()
update_parser.add_argument('first_name', type=str)
update_parser.add_argument('middle_name', type=str)
update_parser.add_argument('last_name',type=str)
update_parser.add_argument('national_id', type=str)
update_parser.add_argument('phone_number',type=str)
update_parser.add_argument('password',type=str)

class Update(Resource):
    @jwt_required()
    def put (self):
        args = update_parser.parse_args()
        user = get_jwt_identity()
        first_name = args['first_name']
        middle_name = args['middle_name']
        last_name = args['last_name']
        national_id = args['national_id']
        phone_number = args['phone_number']
        password = args['password']
        if not password:
            return {'error':'Either the current password or the new password is required'}, 400
        if not password_pattern.match(password):
            return {'error':'Password must meet the required criteria'}, 400

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        existing_user = User.query.filter_by(email = user).first()
        if existing_user:
            if first_name is not None:
                existing_user.first_name = first_name
            if middle_name is not None:
                existing_user.middle_name = middle_name
            if last_name is not None:
                existing_user.last_name = last_name
            if national_id is not None:
                existing_user.national_id = national_id
            if phone_number is not None:
                existing_user.phone_number = phone_number
            if password:
                existing_user.password = hashed_password
            db.session.commit()
            return {'message': 'Update Successful'}, 200
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USERNAME = 'shadrack.bett.92@gmail.com'
SMTP_PASSWORD = 'sfcg cqqu pqkx nrqt'

def send_email(to_address, subject, body):
    msg = MIMEMultipart()
    msg['From'] = SMTP_USERNAME
    msg['To'] = to_address
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

class Needy(Resource):
    @jwt_required()
    def post(self):
        bank_code = request.json.get('bank_code')
        bank_account = request.json.get('bank_account')
        amount = request.json.get('amount')
        name = request.json.get('name')
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        
        if user and user.role_id == 4:
            if not user.stripe_account_id:
                try:
                    account = stripe.Account.create(
                        type="express",
                        country="KE",
                        email=email,
                        capabilities={
                            "transfers": {"requested": True},
                        },
                        business_type="individual",
                        external_account={
                            "object": "bank_account",
                            "country": "KE",
                            "currency": "kes",
                            "account_number": bank_account,
                            "account_holder_name": name,
                            "account_holder_type": "individual",
                            "bank_code": bank_code,
                        }
                    )
                    user.stripe_account_id = account.id
                except stripe.error.StripeError as e:
                    return make_response({'error': f'Stripe error: {e.user_message}'}, 500)
            user.bank_code = bank_code
            user.bank_account = bank_account
            user.amount = amount
            
            db.session.commit()
            response = make_response({'message': 'Details added and Stripe account created successfully'}, 200)
            return response
        else:
            response = make_response({'error': 'No user found or unauthorized access'}, 404)
            return response

class Fetch_Needy(Resource):
    def get(self):
        users = User.query.filter_by(role_id=4).all()
        if users:
            user_data = [
                {'bank_code': user.bank_code, 'bank_account': user.bank_account, 'amount': user.amount, 'stripe_id': user.stripe_account_id, 'id':user.id  }
                for user in users
            ]
            response = make_response({'message': 'Users fetched successfully', 'users': user_data}, 200)
            return response
        else:
            response = make_response({'error': 'No users found'}, 404)
            return response

block_parser = reqparse.RequestParser()
block_parser.add_argument('first_name', type=str, required=True, help='First name cannot be blank!')
block_parser.add_argument('last_name', type=str, required=True, help='Last name cannot be blank!')
block_parser.add_argument('email', type=str, required=True, help='Email cannot be blank!')
block_parser.add_argument('reason', type=str, required=True, help='State a reason for blocking the user!')
block_parser.add_argument('user_id', type=int, required=True, help='User ID cannot be blank!')

class BlockUser(Resource):
    def post(self):
        data = block_parser.parse_args()

        first_name = data['first_name']
        last_name = data['last_name']
        email = data['email']
        user_id = data['user_id']
        reason = data['reason']

        existing_user = Blocked.query.filter_by(user_id=user_id).first()
        if existing_user:
            response = make_response(jsonify({'error': 'User already blocked'}), 404)
            return response

        new_blocked_user = Blocked(
            first_name=first_name,
            last_name=last_name,
            email=email,
            user_id=user_id,
            reason=reason
        )
        db.session.add(new_blocked_user)
        db.session.commit()

        return make_response(jsonify({'message': 'User successfully blocked'}), 201)

class UnblockUser(Resource):
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('user_id', type=int, required=True, help='User ID cannot be blank!')
        data = parser.parse_args()

        blocked_user = Blocked.query.filter_by(user_id=data['user_id']).first()

        if not blocked_user:
            return make_response(jsonify({'error': 'User is not blocked'}), 404)
        
        user = User.query.filter_by(id=data['user_id']).first()
        if not user:
            return make_response(jsonify({'error': 'User not found'}), 404)

        db.session.delete(blocked_user)
        db.session.commit()

        subject = "Your Account Has Been Unblocked"
        body = f"Hello {user.first_name},\n\nYour account has been unblocked. You can now access the site.\n\nBest regards,\nKazi-Qonnect Team"
        send_email(user.email, subject, body)

        return make_response(jsonify({'message': 'User successfully unblocked and notified'}), 200)


class Fetch_blocked(Resource):
    def get(self):
        users = Blocked.query.all()
        if users:
            user_details = ({
                'first_name':user.first_name,'last_name': user.last_name, 'email':user.email,'id':user.user_id,'reason':user.reason,'id':user.id
            } for user in users)
            response = make_response({'User successfully fetched',user_details},200)
            return response
        response = make_response('No blocked users available',404)

class DeleteUser(Resource):
    @jwt_required()
    def delete (self):
        user = get_jwt_identity()
        existing_user = User.query.filter_by(email = user).first()
        if existing_user:
            db.session.delete(existing_user)
            db.session.commit()
            return {'message':'Account deleted successfully'}, 200
        return {'error':'user not found'},404

signup_parser = reqparse.RequestParser()
signup_parser.add_argument('first_name', type=str, required=False, help='First name is required')
signup_parser.add_argument('last_name', type=str, required=False, help='Last name is required')
signup_parser.add_argument('email', type=str, required=False, help='Email is required')
signup_parser.add_argument('password', type=str, required=False, help='Password is required')
signup_parser.add_argument('selectedRole', type=int, required=False, help='Role is required')
signup_parser.add_argument('service_name', type=str, required=False, help='service name is required')
signup_parser.add_argument('uuid', type=str, required=False, help='uuid is required')

class Signup(Resource):
    def post(self):
        args = signup_parser.parse_args()
        email = args['email']
        password = args['password']
        first_name = args['first_name']
        last_name = args['last_name']
        role_id = args['selectedRole']
        service_name = args.get('service_name')
        uuid = args['uuid']

        if email == "":
            return {'error': 'Email is required'}, 400
        if password == "":
            return {'error': 'Password is required'}, 400
        if first_name == "":
            return {'error': 'First name is reuired'}, 400
        if last_name == "":
            return {'error': "Last name is required"}, 400
        if role_id == "":
            return {'error': "Role id is required"}, 400
        if uuid == "":
            return {'error': "Uuid is required"}, 400

        if not password_pattern.match(password):
            return {'error': 'Password must meet the required criteria'}, 400
        if not email_pattern.match(email):
            return {'error': 'Invalid email format'}, 400

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return {'error': 'Email already exists'}, 400
        db.session.commit()
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=hashed_password,
            role_id=role_id,
            uuid = uuid,
        )
        db.session.add(new_user)
        db.session.commit()
        if role_id == 2 and service_name:
            service = Service.query.filter(func.lower(Service.service_name) == func.lower(service_name)).first()
            if service:
                provider_service = ProviderService(
                    provider_id=new_user.id,
                    service_id=service.id
                )
                db.session.add(provider_service)

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return {'error': str(e)}, 500
        

        access_token = create_access_token(identity=email)
        response = make_response({'message': 'Sign up successful', 'token': access_token, 'id': new_user.id,'role_id':new_user.role_id,'first_name':new_user.first_name,'last_name':new_user.last_name,'email':new_user.email,'password':new_user.password}, 201)
        return response

class Signup2(Resource):
    def post(self):
        try:
            middle_name = request.form.get('middle_name')
            national_id = request.form.get('national_id')
            phone_number = request.form.get('phone_number')
            uids = request.form.get('uids')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            county_name = request.form.get('county')

            if not middle_name or not national_id or not phone_number or not uids or not county_name:
                return {'error': 'Missing required fields'}, 400


            if len(str(national_id)) != 8:
                return {'error':'Enter a valid national id'}, 400

            if len(str(phone_number)) != 10:
                return {'error':'Enter a valid phone number'}, 400

            existing_user = User.query.filter_by(uuid=uids).first()
            if existing_user:
                existing_user.middle_name = middle_name
                existing_user.national_id = national_id
                existing_user.phone_number = phone_number
                existing_user.uids = uids
                existing_user.latitude = float(latitude)
                existing_user.longitude = float(longitude)
                existing_user.county = county_name

                db.session.commit()
                return {'message': 'User details updated successfully'}
            else:
                return {'error': 'User not found'}, 404
        except Exception as e:
            app.logger.error(f"An error occurred: {e}")
            return {'error': 'An error occurred while processing the request'}, 500

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json
    sender_id = data.get('sender_id')
    receiver_id = data.get('receiver_id')
    content = data.get('content')

    new_message = Message(sender_id=sender_id, receiver_id=receiver_id, content=content)
    db.session.add(new_message)
    db.session.commit()

    return jsonify({'message': 'Message sent'}), 201

@app.route('/get_messages_between/<int:sender_id>/<int:receiver_id>', methods=['GET'])
def get_messages_between(sender_id, receiver_id):
    messages = Message.query.filter(
        ((Message.sender_id == sender_id) & (Message.receiver_id == receiver_id)) |
        ((Message.sender_id == receiver_id) & (Message.receiver_id == sender_id))
    ).order_by(Message.timestamp.asc()).all()
    return jsonify([{
        'id': msg.id,
        'sender_id': msg.sender_id,
        'receiver_id': msg.receiver_id,
        'content': msg.content,
        'timestamp': msg.timestamp.isoformat()
    } for msg in messages]), 200

@app.route('/get_messages_for_receiver/<int:receiver_id>', methods=['GET'])
def get_messages_for_receiver(receiver_id):
    messages = Message.query.filter(
        (Message.sender_id == receiver_id) | (Message.receiver_id == receiver_id)
    ).order_by(Message.timestamp.asc()).all()

    return jsonify([{
        'id': msg.id,
        'sender_id': msg.sender_id,
        'receiver_id': msg.receiver_id,
        'content': msg.content,
        'timestamp': msg.timestamp.isoformat()
    } for msg in messages]), 200

class Upload(Resource):
    @jwt_required()
    def post(self):
        try:
            user_email = get_jwt_identity()
            image = request.files.get('image')
            image_files = request.files.getlist('photos')
            video_files = request.files.getlist('videos')

            app.logger.info(f"User email: {user_email}")
            app.logger.info(f"Image file: {image}")
            app.logger.info(f"Image files: {image_files}")
            app.logger.info(f"Video files: {video_files}")

            user = User.query.filter_by(email=user_email).first()
            if not user:
                return {'error': 'User not found'}, 404

            total_images = len(image_files) + len(user.photos)
            total_videos = len(video_files) + len(user.videos)

            if total_images > 4:
                return {'error': 'Total photos should not exceed four'}, 400
            if total_videos > 2:
                return {'error': 'Total videos should not exceed two'}, 400

            if not image_files and not video_files and not image:
                return {'error': 'No selected file'}, 400

            photos_urls = []
            video_urls = []

            if image and allowed_file(image.filename, ALLOWED_IMAGE_EXTENSIONS, MAX_CONTENT_LENGTH):
                image_filename = secure_filename(image.filename)
                image_url = upload_to_gcs(image, app.config['GCS_BUCKET_NAME'], image_filename)
                user.image = image_url

            for image_file in image_files:
                app.logger.info(f"Processing image file: {image_file.filename}")
                if image_file and allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS, MAX_CONTENT_LENGTH):
                    image_filename = secure_filename(image_file.filename)
                    image_url = upload_to_gcs(image_file, app.config['GCS_BUCKET_NAME'], image_filename)
                    new_photo = Photo(filename=image_filename, url=image_url, user_id=user.id)
                    db.session.add(new_photo)
                    photos_urls.append(image_url)
                else:
                    return {'error': 'Invalid image file type or size larger than 16mbs'}, 400

            for video_file in video_files:
                video_filename = secure_filename(video_file.filename)
                app.logger.info(f"Processing video file: {video_filename}")
                if video_file and allowed_file(video_filename, ALLOWED_VIDEO_EXTENSIONS):
                    video_stream = io.BytesIO(video_file.read())
                    with tempfile.NamedTemporaryFile(delete=False) as temp_video_file:
                        temp_video_file.write(video_stream.getvalue())
                        temp_video_file_path = temp_video_file.name
                    try:
                        video = VideoFileClip(temp_video_file_path)
                        duration = video.duration
                        if duration > MAX_VIDEO_DURATION:
                            os.remove(temp_video_file_path)
                            return {'error': 'Video must not exceed 5 minutes'}, 400
                    except Exception as e:
                        os.remove(temp_video_file_path)
                        app.logger.error(f"Video processing error: {e}")
                        return {'error': str(e)}, 500
                    video_stream.seek(0) 
                    video_url = upload_to_gcs(video_stream, app.config['GCS_BUCKET_NAME'], video_filename)
                    new_video = Video(filename=video_filename, url=video_url, user_id=user.id)
                    db.session.add(new_video)
                    video_urls.append(video_url)
                else:
                    return {'error': 'Invalid video file type'}, 400

            db.session.commit()
            return {'message': 'Upload successful', 'photos': photos_urls, 'image': user.image, 'videos': video_urls}, 200
        except Exception as e:
            app.logger.error(f"An error occurred: {e}")
            return {'error': 'An error occurred while processing the request'}, 500

class AssignedResource(Resource):
    def get(self, senderId):
        user = User.query.filter_by(id=senderId).first()
        if user:
            associated_records = Assigned.query.filter_by(provider_id=senderId).order_by(Assigned.id.desc()).all()
            if associated_records:
                associated_ids = [record.client_id for record in associated_records]
                response = make_response(jsonify({'provider_ids': associated_ids}))
                return response
            else:
                return make_response(jsonify({'error': 'No records found'})), 404
        return make_response(jsonify({'error': 'User not found'})), 404
class Details (Resource):
    def get(self, senderId):
        user = User.query.filter_by(id=senderId).first()
        if user:
            image_url = user.image if user.image else None
            response = make_response(
                jsonify({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'image': image_url
                })
            )
            return response
        else:
            response = make_response(jsonify({'error': 'Error fetching user details'}), 404)
            return response
class RecentClients(Resource):
    def get(self, senderIds):
        if isinstance(senderIds,int):
            senderIds = str(senderIds)
        elif isinstance(senderIds,list):
            senderIds=",".join(map(str,senderIds))
        try:
            sender_ids = [int(id.strip()) for id in senderIds.split(',')]
        except ValueError:
            return make_response(jsonify({'error': 'Invalid ID format'}), 400)

        users = User.query.filter(User.id.in_(sender_ids)).all()

        if users:
            user_details = []
            for user in users:
                user_detail = {
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'id':user.id
                }
                user_details.append(user_detail)

            return make_response(jsonify(user_details), 200)
        else:
            return make_response(jsonify({'error': 'No users found with the provided IDs'})), 404
        
@app.route('/clean-images', methods=['POST'])
def clean_images():
    try:
        users = User.query.all()
        for user in users:
            user.image = None 
        db.session.commit()
        return "Image column cleaned for all users.", 200
    except Exception as e:
        db.session.rollback()
        return str(e), 500

class DeleteUpload(Resource):
    @jwt_required()
    def delete(self, file_type, filename):
        try:
            user_email = get_jwt_identity()
            user = User.query.filter_by(email=user_email).first()
            if not user:
                return {'error': 'User not found'}, 404

            if file_type == 'photo':
                photo = Photo.query.filter_by(filename=filename, user_id=user.id).first()
                if photo:
                    db.session.delete(photo)
                    delete_from_gcs(app.config['GCS_BUCKET_NAME'], filename)
                else:
                    return {'error': 'Photo not found'}, 404

            elif file_type == 'video':
                video = Video.query.filter_by(filename=filename, user_id=user.id).first()
                if video:
                    db.session.delete(video)
                    delete_from_gcs(app.config['GCS_BUCKET_NAME'], filename)
                else:
                    return {'error': 'Video not found'}, 404

            db.session.commit()
            return {'message': 'File deleted successfully'}, 200

        except Exception as e:
            app.logger.error(f"An error occurred: {e}")
            return {'error': 'An error occurred while processing the request'}, 500
class UpdateImage(Resource):
    @jwt_required()
    def post(self):
        try:
            user_email = get_jwt_identity()
            image_file = request.files.get('image')

            if image_file is None:
                return {'error': 'No image file provided'}, 400

            if not allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                return {'error': 'Invalid file type'}, 400

            existing_user = User.query.filter_by(email=user_email).first()
            if not existing_user:
                return {'error': 'User not found'}, 404

            image_filename = secure_filename(image_file.filename)
            image_url = upload_to_gcs(image_file, app.config['GCS_BUCKET_NAME'], image_filename)

            if existing_user.image:
                old_image_filename = existing_user.image.split('/').pop()
                delete_from_gcs(app.config['GCS_BUCKET_NAME'], old_image_filename)

            existing_user.image = image_url
            db.session.commit()

            return {'message': 'User details updated successfully', 'image': image_url}, 200

        except Exception as e:
            app.logger.error(f"An error occurred: {e}")
            return {'error': 'An error occurred while processing the request'}, 500

login_parse = reqparse.RequestParser()
login_parse.add_argument('email', type=str, required=True, help='email is required'),
login_parse.add_argument('password', type=str, required=True, help='Password is required')

class Login(Resource):
    def post(self):
        args = login_parse.parse_args()
        email = args['email']
        password = args['password']
        if email == '' or password == '':
            response = make_response({'error': 'Fill in all forms'}, 401)
            return response
        blocked_user = Blocked.query.filter_by(email=email).first()
        if blocked_user:
            return make_response(jsonify({
                'error': 'You have been blocked from accessing this site!',
                'first_name': blocked_user.first_name,
                'last_name': blocked_user.last_name,
                'reason': blocked_user.reason,
                'user_id': blocked_user.user_id
            }), 403)

        existing_user = User.query.filter_by(email=email).first()
        if not existing_user:
            response = make_response({'error': 'Invalid email or password'}, 401)
            return response
        hashed_password = existing_user.password
        if existing_user and bcrypt.check_password_hash(hashed_password, password):
            access_token = create_access_token(identity=email)
            role_id = existing_user.role_id
            id = existing_user.id
            response = make_response(
                {'message': 'Login successful', 'access_token': access_token, 'role_id': role_id, 'id': id}, 200)
            return response
        response = make_response({'error': 'Invalid email or password'}, 401)
        return response 

class UserDetails(Resource):
    def get(self):
        email = request.args.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            image_url = user.image if user.image else None
            photos_urls = [photo.url for photo in user.photos] if user.photos else []
            videos_urls = [video.url for video in user.videos] if user.videos else []
            response = make_response(
                jsonify({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'likes': user.likes,
                    'jobs': user.jobs,
                    'photos': photos_urls,
                    'videos': videos_urls,
                    'role_id': user.role_id,
                    'phone_number': user.phone_number,
                    'middle_name': user.middle_name,
                    'national_id': user.national_id,
                    'image': image_url,
                    'id':user.id
                })
            )
            return response
        else:
            response = make_response(jsonify({'error': 'Error fetching user details'}), 404)
            return response
class Dashboard(Resource):
    @jwt_required()
    def get(self):
        current_user = get_jwt_identity()
        user = User.query.filter_by(email=current_user).first()
        if user:
            image_url = user.image if user.image else None
            photos_urls = [photo.url for photo in user.photos] if user.photos else []
            videos_urls = [video.url for video in user.videos] if user.videos else []

            response = make_response(
                jsonify({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'likes': user.likes,
                    'jobs': user.jobs,
                    'photos': photos_urls,
                    'videos': videos_urls,
                    'role_id': user.role_id,
                    'phone_number': user.phone_number,
                    'middle_name': user.middle_name,
                    'national_id': user.national_id,
                    'image': image_url,
                    'id':user.id,
                })
            )
            return response
        else:
            response = make_response(jsonify({'error': 'Error fetching user details'}), 404)
            return response

class AllUsers(Resource):
    @jwt_required()
    def get(self):
        all_users = User.query.all()
        blocked_users = Blocked.query.all()

        blocked_user_ids = {blocked.user_id for blocked in blocked_users}

        user_list = [{
            'first_name': user.first_name,
            'last_name': user.last_name,
            'national_id': user.national_id,
            'id': user.id,
            'email': user.email,
            'role_id': user.role_id,
            'is_blocked': user.id in blocked_user_ids,
            'block_reason': next((blocked.reason for blocked in blocked_users if blocked.user_id == user.id), None)
        } for user in all_users]

        return make_response(jsonify(user_list), 200)

class AddService(Resource):
    @jwt_required()
    def post(self):
        current_user = get_jwt_identity()
        user = User.query.filter_by(email=current_user).first()
        if not user:
            return {'error': 'User not found'}, 404
        
        reg_county = user.county
        exist_county = County.query.filter_by(county_name=reg_county).first()
        if not exist_county:
            return {'error': 'County not found'}, 404
        county_id = exist_county.id

        args = request.json
        existing_services = args.get('existing_services', [])
        new_service_name = args.get('service_name')

        if not existing_services and not new_service_name:
            return {'error': 'At least one service must be provided'}, 400

        service_ids = []

        for service_id in existing_services:
            provider_service = ProviderService.query.filter_by(provider_id=user.id, service_id=service_id).first()
            if not provider_service:
                provider_service = ProviderService(
                    provider_id=user.id,
                    service_id=service_id,
                    county_id=county_id
                )
                db.session.add(provider_service)
                service_ids.append(service_id)

        if new_service_name:
            existing_service = Service.query.filter(func.lower(Service.service_name) == func.lower(new_service_name)).first()
            if existing_service:
                provider_existing_service = ProviderService.query.filter_by(provider_id=user.id, service_id=existing_service.id).first()
                if provider_existing_service:
                    return {'error': f'Service "{new_service_name}" is already registered by you'}, 401
                else:
                    provider_service = ProviderService(
                        provider_id=user.id,
                        service_id=existing_service.id,
                        county_id=county_id
                    )
                    db.session.add(provider_service)
                    service_ids.append(existing_service.id)
            else:
                new_service = Service(service_name=new_service_name)
                db.session.add(new_service)
                db.session.flush()  

                provider_service = ProviderService(
                    provider_id=user.id,
                    service_id=new_service.id,
                    county_id=county_id
                )
                db.session.add(provider_service)
                service_ids.append(new_service.id)

        db.session.commit()
        return {'message': f'Services created and associated with {user.first_name} {user.last_name}', 'service_ids': service_ids}, 201

class DeleteService(Resource):
    @jwt_required()
    def delete(self,service_id):
        current_user = get_jwt_identity()
        user = User.query.filter_by(email=current_user).first()
        if not user:
            return {'error': 'User not found'}, 404
        provider_service = ProviderService.query.filter_by(provider_id=user.id, service_id=service_id).first()
        if not provider_service:
            return {'error': 'Service not associated with the user'}
        
        db.session.delete(provider_service)
        db.session.commit()

        return {'message': 'Service deleted successfully'}, 200

class Offers(Resource):
    @jwt_required()
    def post(self):
        email = get_jwt_identity()
        user = User.query.filter_by(email=email).first()
        if user:
            provider_services = ProviderService.query.filter_by(provider_id=user.id).all()
            if provider_services:
                service_ids = [ps.service_id for ps in provider_services]
                services = Service.query.filter(Service.id.in_(service_ids)).all()
                service_list = [{'id': service.id, 'name': service.service_name} for service in services]
                return {'services': service_list}, 200
        return {'error': ''}, 404

class Counties(Resource):
    def get(self):
        all_counties = County.query.all()
        all_counties_data = [{'id': county.id, 'name': county.county_name} for county in all_counties ]

        return {'all_counties': all_counties_data },200

@app.route('/service', methods=['GET', 'POST'])
@jwt_required()
def handle_service_request():
    if request.method == 'GET':
        try:
            all_services = Service.query.all()
            all_services_data = [{'id': service.id, 'name': service.service_name} for service in all_services]
            return {'all_services': all_services_data}, 200

        except Exception as e:
            return {'error': 'An error occurred while processing the request'}, 500

    elif request.method == 'POST':
        
        try:
            current_user = get_jwt_identity()
            user = User.query.filter_by(email=current_user).first()
            args = request.json
            existing_services = args.get('existing_services', [])
            new_service_name = args.get('service_name')
            idd = user.id
            county_name = user.county
            county = County.query.filter_by(county_name=county_name).first()
            if county:
                county_id = county.id

            if not existing_services and not new_service_name:
                return {'error': 'At least one service must be provided'}, 400

            service_ids = []

            for service_id in existing_services:
                service = Service.query.get(service_id)
                if service:
                    provider_service = ProviderService(
                        provider_id=user.id,
                        service_id=service_id,
                        county_id = county_id
                    )
                    db.session.add(provider_service)
                    service_ids.append(service_id)

            if new_service_name:
                existing_service = Service.query.filter(func.lower(Service.service_name) == func.lower(new_service_name)).first()
                if existing_service:
                    return {'error': f'Service "{new_service_name}" already exists, kindly check the list provided'}, 401

                new_service = Service(
                    service_name=new_service_name
                )
                db.session.add(new_service)
                db.session.flush()
                provider_service = ProviderService(
                    provider_id=user.id,
                    service_id=new_service.id
                )
                db.session.add(provider_service)
                service_ids.append(new_service.id)

            db.session.commit()

            return {'message': f'Services created and associated with {user.first_name} {user.last_name}', 'service_ids': service_ids}, 201

        except Exception as e:
            return {'error': 'An error occurred while processing the request'}, 500



provider_parser = reqparse.RequestParser()
provider_parser.add_argument('service_id', type=int, required=True, help='Service Id required')

class ServiceProvider(Resource):
    @jwt_required()
    def get(self):
        args = provider_parser.parse_args() 
        service_id = args['service_id']
        provider_ids = ProviderService.query.filter_by(service_id=service_id).all()
        
        if provider_ids:
            provider_ids = [provider.provider_id for provider in provider_ids]
            response = make_response({'provider_ids': provider_ids})
            return response
        else:
            response = make_response({'error': 'No Service providers found for this service'}, 404)
            return response
class ProviderList(Resource):
    @jwt_required()
    def get(self):
        provider_ids = request.args.get('provider_ids')
        client_lat = request.args.get('client_lat')
        client_lon = request.args.get('client_lon')

        if provider_ids is None and client_lat is None and client_lon is None:
            return {'error': 'No provider IDs provided'}, 400

        provider_ids_list = provider_ids.split(',')
        try:
            provider_ids_list = [int(provider_id) for provider_id in provider_ids_list]
        except ValueError:
            return {'error': 'Invalid provider IDs'}, 400

        users = User.query.filter(User.id.in_(provider_ids_list)).all()
        if not users:
            return {'error': 'No users found for the given provider IDs'}, 404

        user_details = []
        if client_lat and client_lon:
            try:
                client_lat = float(client_lat)
                client_lon = float(client_lon)
            except (ValueError, TypeError):
                return {'error': 'Invalid latitude or longitude values'}, 400

            for user in users:
                distance = geodesic((client_lat, client_lon), (user.latitude, user.longitude)).miles if user.latitude and user.longitude else None
                user_details.append({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'image': user.image,
                    'latitude': user.latitude,
                    'longitude': user.longitude,
                    'distance': distance,
                    'county': user.county
                })

            user_details.sort(key=lambda x: x['distance'] if x['distance'] is not None else float('inf'))
        else:
            for user in users:
                user_details.append({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'image': user.image,
                    'latitude': user.latitude,
                    'longitude': user.longitude,
                    'distance': None,
                    'county': user.county
                })

        response = {
            'providers': user_details,
            'message': 'Enable location services to see the closest providers' if not client_lat or not client_lon else None
        }

        return jsonify(response)

class ProviderDetails2(Resource):
    @jwt_required()
    def get(self):
        provider_ids = request.args.get('provider_ids')
        county_id = request.args.get('countyId')
        client_lat = request.args.get('client_lat')
        client_lon = request.args.get('client_lon')

        if provider_ids is None:
            return {'error': 'provider_ids are required parameters'}, 400
        if county_id is None:
            return {'error': 'countyId is a required parameter'}, 400

        county = County.query.filter_by(id=county_id).first()
        if not county:
            return {'error': 'County not found'}, 404

        cnt_name = county.county_name

        provider_ids_list = provider_ids.split(',')
        try:
            provider_ids_list = [int(provider_id) for provider_id in provider_ids_list]
        except ValueError:
            return {'error': 'Invalid provider IDs'}, 400

        users = User.query.filter(User.id.in_(provider_ids_list)).all()
        if not users:
            return {'error': 'No users found for the given provider IDs'}, 404

        user_details = []
        for user in users:
            if user.county == cnt_name:
                distance = None
                if client_lat and client_lon:
                    try:
                        client_lat = float(client_lat)
                        client_lon = float(client_lon)
                        if user.latitude and user.longitude:
                            distance = geodesic((client_lat, client_lon), (user.latitude, user.longitude)).miles
                    except (ValueError, TypeError):
                        return {'error': 'Invalid latitude or longitude values'}, 400
                
                user_details.append({
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'email': user.email,
                    'image': user.image,
                    'latitude': user.latitude,
                    'longitude': user.longitude,
                    'distance': distance,
                    'county': user.county
                })

        user_details.sort(key=lambda x: x['distance'] if x['distance'] is not None else float('inf'))
        return jsonify(user_details)

class ProviderIds(Resource):
    def get(self, service_id):
        provider_ids = ProviderService.query.filter_by(service_id=service_id).all()
        if provider_ids:
            ids = [provider.provider_id for provider in provider_ids]
            response = make_response({'provider_ids': ids})
            return response
        else:
            response = make_response({'error': 'No service providers available for this service'}, 404)
            return response

@app.route('/services-by-county/<county_name>', methods=['GET'])
@jwt_required()
def get_services_by_county(county_name):
    try:
        county = County.query.filter_by(county_name=county_name).first()
        if not county:
            return jsonify({'error': 'County not found'}), 404
        county_id = county.id

        services = db.session.query(Service).join(ProviderService).join(User).filter(
            ProviderService.county_id == county.id,
            User.county == county_name
        ).all()

        if services:
            service_names = [{'id': service.id, 'name': service.service_name} for service in services]
            return jsonify({'services': service_names,'county_id':county_id}), 200
        else:
            return jsonify({'error': 'Sorry, no registered services for the selected county'}), 404

    except Exception as e:
        return jsonify({'error': 'An error occurred while processing the request'}), 500

@app.route('/assign_job/<int:user_id>', methods=['POST'])
@jwt_required()
def assign_job(user_id):
    email = get_jwt_identity()
    client = User.query.filter_by(email=email).first()
    if client:
        new_assignee = Assigned(
            client_id=client.id,
            provider_id=user_id
        )
        db.session.add(new_assignee)
        db.session.commit()

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        user.jobs = (user.jobs or 0) + 1
        db.session.commit()
        return jsonify({'message': 'Job assigned successfully', 'jobs_done': user.jobs}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
@app.route('/like_job/<int:idd>', methods=['POST'])
def like_job(idd):
    user = User.query.get(idd)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        user.likes = (user.likes or 0) + 1
        db.session.commit()
        return jsonify({'message': 'Like added '}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
@app.route('/unlike_job/<int:idd>', methods=['POST'])
def unlike_job(idd):
    user = User.query.get(idd)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        user.unlikes = (user.unlikes or 0) + 1
        db.session.commit()
        return jsonify({'message': 'UnLike added'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

def process_payment(amount, bank_code, account_number, recipient_account_id):
    amount = float(amount)
    fee_percentage = 0.05
    fee = amount * fee_percentage
    net_amount = amount - fee

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100), 
            currency="kes", 
            payment_method_types=["card"],
            description=f"Payment from sponsor to student",
            transfer_data={
                "amount": int(net_amount * 100),  
                "destination": recipient_account_id,
            },
            metadata={
                "bank_code": bank_code,
                "account_number": account_number,
                "fee_bank_code": "247247", 
                "fee_account_number": "1980185542243",
            }
        )
        payment_status = "pending"
        client_secret = intent['client_secret']

    except stripe.error.StripeError as e:
        client_secret = None
        payment_status = "failed"
        print(f"Stripe error occurred: {e.user_message}")
        raise
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        raise

    payment = Payment(
        amount=amount,
        fee=fee,
        net_amount=net_amount,
        status=payment_status,
        fee_account="1980185542243"
    )
    db.session.add(payment)
    db.session.commit()

    return payment, client_secret

@app.route('/pay', methods=['POST'])
@jwt_required()
def pay():
    data = request.get_json()
    amount = data.get('amount')
    bank_code = data.get('bank_code')
    recipient_account_id = data.get('stripe_id')
    account_number = data.get('account_number')

    if not amount or not bank_code or not account_number or not recipient_account_id :
        logging.error("Missing required fields in payment request")
        return jsonify({"error": "Amount, bank code,account number and recipient_account_id are required"}), 400

    try:
        payment, client_secret = process_payment(
            amount=amount, 
            bank_code=bank_code, 
            account_number=account_number,
            recipient_account_id=recipient_account_id
        )
        return jsonify({
            "success": True,
            "payment_id": payment.id,
            "client_secret": client_secret,
            "status": payment.status
        }), 200
    except Exception as e:
        logging.error(f"Payment processing failed: {str(e)}")
        return jsonify({"error": str(e)}), 500

api.add_resource(ProviderList, '/provider-details')
api.add_resource(ProviderIds,'/provider-ids/<int:service_id>')
api.add_resource(ServiceProvider,'/service-provider')
api.add_resource(Signup, '/signup')
api.add_resource(Login, '/login')
api.add_resource(Dashboard, '/dashboard')
api.add_resource(Signup2, '/signup2')
api.add_resource(Update, '/update')
api.add_resource(DeleteUser, '/delete')
api.add_resource(Offers,'/offers')
api.add_resource(AddService, '/add-service')
api.add_resource(DeleteService, '/delete-service/<int:service_id>')
api.add_resource(UpdateImage, '/update-image')
api.add_resource(UserDetails, '/user-details')
api.add_resource(Counties, '/county')
api.add_resource(ProviderDetails2, '/provider-delta')
api.add_resource(Upload, '/upload')
api.add_resource(DeleteUpload, '/delete-upload/<string:file_type>/<string:filename>')
api.add_resource(AllUsers, '/all_users')
api.add_resource(Details, '/details/<int:senderId>')
api.add_resource(BlockUser, '/block_user')
api.add_resource(RecentClients, '/recent_clients/<int:senderIds>')
api.add_resource(AssignedResource,'/assigned_resource/<int:senderId>')
api.add_resource(UnblockUser, '/unblock_user')
api.add_resource(Needy, '/needy')
api.add_resource(Fetch_Needy, '/fetch_needy')
api.add_resource(Fetch_blocked, '/fetch_blocked')

if __name__=='__main__':
    app.run(port=4000)
# bash predeploy.sh && gunicorn app:app
# database_url postgresql://kazi_user:eeJf5YH36L7V8CdHtdaf4mN0NLgmiQAm@dpg-cr7lq6rv2p9s73a6e7eg-a/kazi
# GCS_BUCKET_NAME kipkorirbett
# GOOGLE_APPLICATION_CREDENTIALS cosmic-descent-429616-s4-f89510dd5dd0.json
# secret_key    betkipkorir 
# stripe_secret_key=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