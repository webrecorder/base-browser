import random
import ssl
import websockets
import asyncio
import os
import sys
import json
import argparse
import re
import itertools

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
gi.require_version('GstWebRTC', '1.0')
from gi.repository import GstWebRTC
gi.require_version('GstSdp', '1.0')
from gi.repository import GstSdp


LOCAL_HOST = os.environ.get('LOCAL_HOST', '127.0.0.1')

RTP_PORT = 10235


AUDIO_VIDEO_PIPELINE = '''
 webrtcbin name=sendrecv bundle-policy=max-bundle min-rtp-port={0} max-rtp-port={0} min-rtcp-port={1} max-rtcp-port={1}
 ximagesrc ! video/x-raw ! videoconvert ! queue ! vp8enc deadline=1 buffer-size=100 keyframe-max-dist=30 cpu-used=5 ! rtpvp8pay !
 queue ! application/x-rtp,media=video,encoding-name=VP8,payload=97 ! sendrecv.
 pulsesrc buffer-time=128000 latency-time=32000  ! audioconvert ! queue ! opusenc frame-size=2.5 ! rtpopuspay !
 queue ! application/x-rtp,media=audio,encoding-name=OPUS,payload=96 ! sendrecv.
'''.format(RTP_PORT, RTP_PORT + 3)


AUDIO_PIPELINE = '''
 webrtcbin name=sendrecv bundle-policy=max-bundle min-rtp-port={0} max-rtp-port={0} min-rtcp-port={1} max-rtcp-port={1}
 pulsesrc buffer-time=128000 latency-time=32000  ! audioconvert ! queue ! opusenc frame-size=2.5 ! rtpopuspay !
 queue ! application/x-rtp,media=audio,encoding-name=OPUS,payload=97 ! sendrecv.
'''.format(RTP_PORT, RTP_PORT + 3)


if os.environ.get('WEBRTC_VIDEO'):
    PIPELINE = AUDIO_VIDEO_PIPELINE
else:
    PIPELINE = AUDIO_PIPELINE



class WebRTCClient:
    def __init__(self, id_, peer_id, server):
        self.id_ = id_
        self.conn = None
        self.pipe = None
        self.webrtc = None
        self.peer_id = str(peer_id)
        self.server = server
        self.cand_count = 1
        self.tcp_port = None
        self.udp_port = None

    async def connect(self):
        #sslctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        self.conn = await websockets.connect(self.server)
        await self.conn.send('HELLO %d' % our_id)

    async def setup_call(self):
        await self.conn.send('SESSION {}'.format(self.peer_id))

    def send_sdp_offer(self, offer):
        text = offer.sdp.as_text()
        print ('Sending offer:\n%s' % text)
        msg = json.dumps({'sdp': {'type': 'offer', 'sdp': text}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(msg))

    def on_offer_created(self, promise, _, __):
        promise.wait()
        reply = promise.get_reply()
        offer = reply.get_value('offer')

        promise = Gst.Promise.new()
        self.webrtc.emit('set-local-description', offer, promise)
        promise.interrupt()
        self.send_sdp_offer(offer)

    def on_negotiation_needed(self, element):
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, element, None)
        element.emit('create-offer', None, promise)

    def send_ice_candidate_message(self, _, mlineindex, candidate):
        if 'typ host' not in candidate:
            return

        if ' 9 ' in candidate:
            return

        parts = candidate.split(' ')

        if parts[1] == '2':
            return

        parts[0] = 'candidate:' + str(self.cand_count)

        if RTP_PORT in candidate:
            orig_host = parts[4]
            orig_port = parts[5]
            parts.extend(itertools.repeat('', 12 - len(parts)))
            parts[4] = LOCAL_HOST
            parts[5] = self.tcp_port if parts[2] == 'TCP' else self.udp_port
            parts[6] = 'typ'
            parts[7] = 'srflx'
            parts[8] = 'raddr'
            parts[9] = orig_host
            parts[10] = 'rport'
            parts[11] = orig_port

        candidate = ' '.join(parts)

        self.cand_count += 1

        icemsg = json.dumps({'ice': {'candidate': candidate, 'sdpMLineIndex': mlineindex}})
        loop = asyncio.new_event_loop()
        loop.run_until_complete(self.conn.send(icemsg))

    def start_pipeline(self):
        self.pipe = Gst.parse_launch(PIPELINE)
        self.webrtc = self.pipe.get_by_name('sendrecv')
        self.webrtc.connect('on-negotiation-needed', self.on_negotiation_needed)
        self.webrtc.connect('on-ice-candidate', self.send_ice_candidate_message)
        self.pipe.set_state(Gst.State.PLAYING)

    async def handle_sdp(self, message):
        assert (self.webrtc)
        msg = json.loads(message)
        if 'sdp' in msg:
            sdp = msg['sdp']
            assert(sdp['type'] == 'answer')
            sdp = sdp['sdp']
            print ('Received answer:\n%s' % sdp)
            res, sdpmsg = GstSdp.SDPMessage.new()
            GstSdp.sdp_message_parse_buffer(bytes(sdp.encode()), sdpmsg)
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
            promise = Gst.Promise.new()
            self.webrtc.emit('set-remote-description', answer, promise)
            promise.interrupt()
        elif 'ice' in msg:
            ice = msg['ice']
            candidate = ice['candidate']
            sdpmlineindex = ice['sdpMLineIndex']
            self.webrtc.emit('add-ice-candidate', sdpmlineindex, candidate)

    async def loop(self):
        assert self.conn
        async for message in self.conn:
            if message == 'HELLO':
                await self.setup_call()
            elif message == 'SESSION_OK':
                self.start_pipeline()
            elif message.startswith('ERROR'):
                print (message)
                return 1
            elif message.startswith('PORT'):
                print(message)
                _, self.tcp_port, self.udp_port = message.split(' ')
            else:
                await self.handle_sdp(message)
        return 0


def check_plugins():
    needed = ["opus", "vpx", "nice", "webrtc", "dtls", "srtp", "rtp",
              "rtpmanager"]

    missing = list(filter(lambda p: Gst.Registry.get().find_plugin(p) is None, needed))
    if len(missing):
        print('Missing gstreamer plugins:', missing)
        return False
    return True


if __name__=='__main__':
    Gst.init(None)
    if not check_plugins():
        sys.exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument('--peer-id', help='String ID of the peer to connect to')
    parser.add_argument('--server', help='Signalling server to connect to, eg "wss://127.0.0.1:8443"')
    args = parser.parse_args()
    our_id = random.randrange(10, 10000)
    c = WebRTCClient(our_id, args.peer_id, args.server)
    asyncio.get_event_loop().run_until_complete(c.connect())
    res = asyncio.get_event_loop().run_until_complete(c.loop())
    sys.exit(res)
