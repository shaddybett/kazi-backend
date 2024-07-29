from flask import Flask, make_response, request,jsonify, url_for,send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_restful import Api, Resource, reqparse
from models import db, User, Service, ProviderService, County, Photo, Video
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

app = Flask(__name__)
api = Api(app)
bcrypt = Bcrypt(app)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('database_url')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('secret_key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
app.config['GCS_BUCKET_NAME'] = os.environ.get('GCS_BUCKET_NAME')
app.config['GOOGLE_APPLICATION_CREDENTIALS'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = app.config['GOOGLE_APPLICATION_CREDENTIALS']

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
                    video_stream.seek(0)  # Reset stream pointer after reading for duration check
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
                    'image': image_url
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
        if all_users:
            user_list = [{
                'first_name': user.first_name,
                'last_name': user.last_name,
                'id': user.national_id,
                
            }]
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
def assign_job(user_id):
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

if __name__=='__main__':
    app.run(port=4000)