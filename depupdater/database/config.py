"""all constants of database"""
import os
from depupdater.paths import PROJECT_ROOT

# path to sqlite file(it locates in the root dir of this project)
SQLITE_PATH = os.path.join(PROJECT_ROOT, 'reusable_data.sqlite')
# port to connect to the mongodb
MONGO_PORT = 27017
# host name of the mongodb
MONGO_HOST = 'localhost'
