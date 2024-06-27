from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=False)
    national_id = db.Column(db.BigInteger, nullable=True, unique=True)
    phone_number = db.Column(db.BigInteger, nullable=True, unique=True)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    image = db.Column(db.String, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    role = db.relationship('Role', backref=db.backref('users', lazy=True))
    uuid = db.Column(db.String(36),nullable=True,default='default_uuid_value')
    uids = db.Column(db.String(36),nullable=True,default='default_uuid_value')
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    county = db.Column(db.String,nullable=True)
    services = db.relationship('Service', secondary='provider_services', backref=db.backref('providers', lazy=True, cascade="all, delete"))

class Service(db.Model):
    __tablename__ = 'services'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    service_name = db.Column(db.String(100), nullable=False)

class ProviderService(db.Model):
    __tablename__ = 'provider_services'
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    county_id = db.Column(db.Integer, db.ForeignKey('counties.id'))

class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    role_name = db.Column(db.String(100), nullable=False)

class County(db.Model):
    __tablename__ = 'counties'
    id = db.Column(db.Integer, primary_key=True)
    county_name = db.Column(db.String(100), nullable=False)
