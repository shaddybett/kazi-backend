from flask import Flask, make_response, abort, request,jsonify,session,send_from_directory, url_for
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_restful import Api, Resource, reqparse
from models import db, User, Service, ProviderService, County
from flask_bcrypt import Bcrypt
import re
from flask_cors import CORS
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import timedelta
import os
from sqlalchemy import func
from geopy.distance import geodesic

app = Flask(__name__)
api = Api(app)
bcrypt = Bcrypt(app)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://myuser:shady42635509@localhost:5432/kazikazi'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('secret_key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=1)
db.init_app(app)

password_pattern = re.compile(r'(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*[$%@!*.!?])[A-Za-z\d$%@!*.!?]{8,}')
email_pattern = re.compile(r'[\w-]+(\.[w-]+)*@([\w-]+\.)+[a-zA-Z]{2,}')

migrate = Migrate(app, db)
jwt = JWTManager(app)
jwt.init_app(app)

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

        if not all([email, password, first_name, last_name, role_id,uuid]):
            return {'error': 'Fill in all forms'}, 400

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
        # Add provider service if role_id is 2 and service_name is provided
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

UPLOAD_FOLDER = '/files'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/files/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp' }
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
class signup2(Resource):
    def post(self):
        try:
            middle_name = request.form.get('middle_name')
            national_id = request.form.get('national_id')
            phone_number = request.form.get('phone_number')
            uids = request.form.get('uids')
            image_file = request.files.get('image')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            county_name = request.form.get('county')
            
            if not middle_name or not national_id or not phone_number or not uids or not image_file or not county_name:
                return {'error': 'Missing required fields'}, 400

            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER)

            if not allowed_file(image_file.filename):
                return {'error': 'Invalid file type'}, 400

            image_filename = secure_filename(image_file.filename)
            image_path = os.path.join(UPLOAD_FOLDER, image_filename)
            image_file.save(image_path)
            
            image_url = url_for('uploaded_file', filename=image_filename, _external=True)
            
            if len(str(national_id)) != 8:
                return {'error':'Enter a valid national id'}, 400

            if len(str(phone_number)) != 10:
                return {'error':'Enter a valid phone number'}, 400

            existing_user = User.query.filter_by(uuid = uids).first()
            if existing_user:
                existing_user.middle_name = middle_name
                existing_user.national_id = national_id
                existing_user.phone_number = phone_number
                existing_user.image = image_url
                existing_user.uids = uids
                existing_user.latitude = float(latitude)
                existing_user.longitude = float(longitude)
                existing_user.county = county_name

                db.session.commit()
                return {'message': 'User details updated successfully'}
            else:
                return {'error': 'User not found'}, 404
        except Exception as e:
            return {'error': 'An error occurred while processing the request'}, 500

class UpdateImage(Resource):
    @jwt_required()
    def post(self):
        try:
            user = get_jwt_identity()
            existing_user = User.query.filter_by(email=user).first()
            image_file = request.files.get('image')
            if image_file is not None:
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)

                if not allowed_file(image_file.filename):
                    return {'error': 'Invalid file type'}, 400
                image_filename = secure_filename(image_file.filename)
                image_path = os.path.join(UPLOAD_FOLDER, image_filename)
                image_file.save(image_path)
                image_url = url_for('uploaded_file', filename=image_filename, _external=True)
                existing_user = User.query.filter_by(email=user).first()
                if existing_user:
                    existing_user.image = image_url
                    db.session.commit()
                    return {'message':'user details updated successfully'}
                else:
                    return {'error':'Update failed'}
        except Exception as e:
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


class Dashboard(Resource):
    @jwt_required()
    def get(self):
        current_user = get_jwt_identity()
        user = User.query.filter_by(email=current_user).first()
        if user:
            response = make_response(
                {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
                 'role_id': user.role_id, 'phone_number': user.phone_number,'middle_name':user.middle_name,'national_id':user.national_id, 'image':user.image})
            return response
        else:
            response = make_response({'error': 'Error fetching user details'}, 404)
            return response      

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
                # Check if this service is already registered by this provider
                provider_existing_service = ProviderService.query.filter_by(provider_id=user.id, service_id=existing_service.id).first()
                if provider_existing_service:
                    return {'error': f'Service "{new_service_name}" is already registered by you'}, 401
                else:
                    # If the service exists but not registered by this provider, register it now
                    provider_service = ProviderService(
                        provider_id=user.id,
                        service_id=existing_service.id,
                        county_id=county_id
                    )
                    db.session.add(provider_service)
                    service_ids.append(existing_service.id)
            else:
                # Create a new service and associate it with the provider
                new_service = Service(service_name=new_service_name)
                db.session.add(new_service)
                db.session.flush()  # Ensure new_service.id is available

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

            # Check if at least one service is provided
            if not existing_services and not new_service_name:
                return {'error': 'At least one service must be provided'}, 400

            # Initialize a list to hold service IDs
            service_ids = []

            # Handle existing services selected from the dropdown
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

            # Handle new service entered manually
            if new_service_name:
                existing_service = Service.query.filter(func.lower(Service.service_name) == func.lower(new_service_name)).first()
                if existing_service:
                    return {'error': f'Service "{new_service_name}" already exists, kindly check the list provided'}, 401

                new_service = Service(
                    service_name=new_service_name
                    # provider_id=user.id
                )
                db.session.add(new_service)
                db.session.flush()
                provider_service = ProviderService(
                    provider_id=user.id,
                    service_id=new_service.id
                )
                db.session.add(provider_service)
                service_ids.append(new_service.id)

            # Commit all changes to the database
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

from flask import request, jsonify
from flask_restful import Resource
from flask_jwt_extended import jwt_required
from geopy.distance import geodesic
from models import User
from app import db

class ProviderList(Resource):
    @jwt_required()
    def get(self):
        provider_ids = request.args.get('provider_ids')
        client_lat = request.args.get('client_lat')
        client_lon = request.args.get('client_lon')

        if provider_ids is None:
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

        if provider_ids is None or county_id is None:
            return {'error': 'provider_ids and countyId are required parameters'}, 400

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

        # Query services provided in the selected county
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

class UserDetails(Resource):
    def get(self):
        email = request.args.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            response = make_response(
                    {'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email,
                    'role_id': user.role_id, 'phone_number': user.phone_number, 'middle_name': user.middle_name,
                    'national_id': user.national_id, 'image': user.image})
            return response
        else:
            response = make_response({'error': 'Error fetching user details'}, 404)
            return response
api.add_resource(ProviderList, '/provider-details')
api.add_resource(ProviderIds,'/provider-ids/<int:service_id>')
api.add_resource(ServiceProvider,'/service-provider')
api.add_resource(Signup, '/signup')
api.add_resource(Login, '/login')
api.add_resource(Dashboard, '/dashboard')
api.add_resource(signup2, '/signup2')
api.add_resource(Update, '/update')
api.add_resource(DeleteUser, '/delete')
api.add_resource(Offers,'/offers')
api.add_resource(AddService, '/add-service')
api.add_resource(DeleteService, '/delete-service/<int:service_id>')
api.add_resource(UpdateImage, '/update-image')
api.add_resource(UserDetails, '/user-details')
api.add_resource(Counties, '/county')
api.add_resource(ProviderDetails2, '/provider-delta')

if __name__ == '__main__':
    app.run(debug=True, port=4000)