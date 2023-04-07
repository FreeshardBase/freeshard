from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from starlette import status

from portal_core.model.profile import Profile

app = FastAPI()


@app.get('/')
def root(request: Request):
	base_url = request.base_url
	return {
		'profile': f'{base_url}profile'
	}


@app.get('/profile')
def get_profile():
	return Profile(
		vm_id='mock_vm_id',
		owner='Mock Owner',
		owner_email='mock_owner@getportal.org',
		time_created=datetime.now() - timedelta(days=2),
		time_assigned=datetime.now() - timedelta(minutes=5),
		delete_after=datetime.now() + timedelta(days=4),
		portal_size='xs',
		max_portal_size='m',
	)


@app.post('/resize')
def resize():
	return status.HTTP_204_NO_CONTENT


@app.post('/app_usage')
def app_usage():
	return status.HTTP_201_CREATED
