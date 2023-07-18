import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from portal_core.service.websocket import ws_worker

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/ws',
)


@router.websocket('/updates')
async def updates(websocket: WebSocket):
	await ws_worker.connect(websocket)
	try:
		while True:
			await websocket.receive_json()
			log.warning('Received data over websocket. This is unsupported and will be ignored.')
	except WebSocketDisconnect:
		ws_worker.disconnect(websocket)
